"""Offline tests for the combined ATA DHCP and firmware coordinator."""

import contextlib
import hashlib
import io
import ipaddress
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import call, patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import ata_flash


def synthetic_image() -> bytes:
    body = b"synthetic-firmware-payload"
    table_offset = 16 + len(body)
    table = struct.pack(">HHIII", 1, 0, 0, len(body), 2)
    inner = bytearray(
        b"+kxz" + b"\x00" * 4
        + struct.pack(">II", table_offset + len(table), table_offset)
        + body + table)
    struct.pack_into(">I", inner, 4, sum(inner[12:]) & 0xFFFFFFFF)
    outer = (b"kup1" + b"00000000"
             + struct.pack(">IIHH", 0, 0x301, 0x400, 0x301))
    return outer + bytes(inner)


def route(network: str, interface: str, gateway="0.0.0.0",
          output="192.0.2.2"):
    parsed = ipaddress.IPv4Network(network)
    return (int(parsed.network_address), int(parsed.netmask), gateway,
            interface, output, 1)


class FakeScapy:
    class Device:
        def __init__(self, addresses):
            self.name = "test0"
            self.network_name = "test0"
            self.description = "test0"
            self.ip = addresses[0] if addresses else None
            self.ips = {4: addresses}

    class Ifaces:
        def __init__(self, owner):
            self.owner = owner
            self.reloads = 0

        def reload(self):
            self.reloads += 1

        def dev_from_name(self, _interface):
            return FakeScapy.Device(self.owner.addresses)

    class Routes:
        def __init__(self, records):
            self.routes = records
            self.reloads = 0

        def resync(self):
            self.reloads += 1

    class Conf:
        def __init__(self, owner, records):
            self.ifaces = FakeScapy.Ifaces(owner)
            self.route = FakeScapy.Routes(records)

    def __init__(self, address="192.0.2.2", records=None, interfaces=None,
                 addresses=None):
        if records is None:
            records = (
                route("0.0.0.0/0", "uplink0", "203.0.113.1"),
                route("192.0.2.0/24", "test0"),
                route("192.0.2.2/32", "lo0"),
            )
        self.addresses = ([address] if addresses is None else list(addresses))
        self.interfaces = ["test0"] if interfaces is None else interfaces
        self.conf = self.Conf(self, records)

    def get_if_list(self):
        return self.interfaces

    def get_if_addr(self, _interface):
        return self.addresses[0] if self.addresses else "0.0.0.0"


class ChecksumTest(unittest.TestCase):
    def test_default_manifest_checks_only_the_exact_image_filename(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "firmware.zup"
            image.write_bytes(synthetic_image())
            digest = hashlib.sha256(image.read_bytes()).hexdigest()
            (root / "SHA256SUMS").write_text(
                "not a checksum for an unrelated file\n"
                + "0" * 64 + "  other.zup\n"
                + digest + "  firmware.zup\n")
            actual, info, store = ata_flash.prepare_image(str(image))
        self.assertEqual(actual, digest)
        self.assertEqual((info.platform, info.proto, info.version),
                         (0x301, 0x400, 0x301))
        self.assertGreater(store.total, 0)

    def test_manifest_rejects_mismatch_missing_and_duplicate_image_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "firmware.zup"
            image.write_bytes(synthetic_image())
            digest = hashlib.sha256(image.read_bytes()).hexdigest()
            manifest = root / "SHA256SUMS"
            cases = (
                ("0" * 64 + "  firmware.zup\n", "does not match"),
                (digest + "  directory/firmware.zup\n", "exactly one"),
                (digest + "  firmware.zup\n" + digest
                 + "  firmware.zup\n", "exactly one"),
            )
            for content, message in cases:
                with self.subTest(message=message):
                    manifest.write_text(content)
                    with self.assertRaisesRegex(ata_flash.FlashError, message):
                        ata_flash.verify_sha256sums(
                            str(image), digest, str(manifest))

    def test_manifest_must_be_a_bounded_non_symlink_regular_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "firmware.zup"
            image.write_bytes(synthetic_image())
            digest = hashlib.sha256(image.read_bytes()).hexdigest()
            real = root / "real-sums"
            real.write_text(digest + "  firmware.zup\n")
            linked = root / "SHA256SUMS"
            linked.symlink_to(real)
            with self.assertRaisesRegex(ata_flash.FlashError, "cannot open"):
                ata_flash.verify_sha256sums(str(image), digest, str(linked))

    def test_checksum_correct_but_map_invalid_image_is_rejected(self):
        body = b"not-a-map"
        inner = (b"+kxz" + struct.pack(">I", sum(body) & 0xFFFFFFFF)
                 + b"\x00" * 4 + body)
        image_bytes = (b"kup1" + b"00000000"
                       + struct.pack(">IIHH", 0, 0x301, 0x400, 0x301) + inner)
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "firmware.zup"
            image.write_bytes(image_bytes)
            digest = hashlib.sha256(image_bytes).hexdigest()
            (Path(directory) / "SHA256SUMS").write_text(
                digest + "  firmware.zup\n")
            with self.assertRaisesRegex(ata_flash.FlashError, "structural"):
                ata_flash.prepare_image(str(image))


class NetworkTest(unittest.TestCase):
    def test_current_address_and_own_routes_select_the_connected_subnet(self):
        scapy = FakeScapy()
        state = ata_flash.current_interface_state(scapy, "test0", None)
        self.assertEqual(str(state.address), "192.0.2.2")
        self.assertEqual(str(state.network), "192.0.2.0/24")
        self.assertEqual(scapy.conf.ifaces.reloads, 1)
        self.assertEqual(scapy.conf.route.reloads, 1)
        self.assertEqual(
            str(ata_flash.choose_client_address(None, state)), "192.0.2.10")
        ata_flash.validate_client_route(
            state, ipaddress.IPv4Address("192.0.2.10"))

    def test_optional_address_is_an_assertion_and_no_address_is_actionable(self):
        with self.assertRaisesRegex(ata_flash.FlashError, "--address assertion"):
            ata_flash.current_interface_state(
                FakeScapy(), "test0", ipaddress.IPv4Address("192.0.2.3"))
        with self.assertRaisesRegex(ata_flash.FlashError, "configure one"):
            ata_flash.current_interface_state(
                FakeScapy(address="0.0.0.0"), "test0", None)

    def test_multiple_addresses_require_and_honor_an_explicit_selection(self):
        addresses = ("198.51.100.2", "198.51.100.3")
        records = (
            route("0.0.0.0/0", "en0", "203.0.113.1"),
            route("198.51.100.0/24", "test0", output="198.51.100.2"),
        )
        scapy = FakeScapy(records=records, addresses=addresses)
        with self.assertRaisesRegex(ata_flash.FlashError, "multiple IPv4"):
            ata_flash.current_interface_state(scapy, "test0", None)
        selected = ata_flash.current_interface_state(
            scapy, "test0", ipaddress.IPv4Address("198.51.100.3"))
        self.assertEqual(str(selected.address), "198.51.100.3")
        self.assertEqual(str(selected.network), "198.51.100.0/24")
        with self.assertRaisesRegex(ata_flash.FlashError, "incompatible"):
            ata_flash.choose_client_address("198.51.100.2", selected)

    def test_numeric_route_overlap_on_another_interface_is_rejected(self):
        records = (
            route("0.0.0.0/0", "uplink0", "203.0.113.1"),
            route("192.0.2.0/24", "test0"),
            route("192.0.2.0/25", "tunnel0", "198.51.100.1"),
        )
        with self.assertRaisesRegex(ata_flash.FlashError, "192.0.2.0/25"):
            ata_flash.current_interface_state(
                FakeScapy(records=records), "test0", None)

    def test_default_uplink_and_same_interface_gateway_override_are_rejected(self):
        default_uplink = (
            route("0.0.0.0/0", "test0", "192.0.2.1"),
            route("192.0.2.0/24", "test0"),
        )
        with self.assertRaisesRegex(ata_flash.FlashError, "default route"):
            ata_flash.current_interface_state(
                FakeScapy(records=default_uplink), "test0", None)

        gateway_override = (
            route("0.0.0.0/0", "uplink0", "203.0.113.1"),
            route("192.0.2.0/24", "test0"),
            route("192.0.2.10/32", "test0", "192.0.2.1"),
        )
        with self.assertRaisesRegex(ata_flash.FlashError, "gateway route"):
            ata_flash.current_interface_state(
                FakeScapy(records=gateway_override), "test0", None)

        split_default = (
            route("0.0.0.0/1", "test0"),
            route("128.0.0.0/1", "test0"),
            route("192.0.2.0/24", "test0"),
        )
        with self.assertRaisesRegex(ata_flash.FlashError, "default-equivalent"):
            ata_flash.current_interface_state(
                FakeScapy(records=split_default), "test0", None)

    def test_explicit_client_must_be_a_distinct_host_in_the_selected_subnet(self):
        state = ata_flash.InterfaceState(
            "test0", ipaddress.IPv4Address("192.0.2.2"),
            ipaddress.IPv4Network("192.0.2.0/24"))
        self.assertEqual(
            str(ata_flash.choose_client_address("192.0.2.25", state)),
            "192.0.2.25")
        for value in ("192.0.2.2", "198.51.100.10", "192.0.2.255"):
            with self.subTest(value=value), self.assertRaises(ata_flash.FlashError):
                ata_flash.choose_client_address(value, state)


class RouteCaptureTest(unittest.TestCase):
    def test_clean_scapy_records_are_returned_as_is(self):
        records = (route("0.0.0.0/0", "uplink0", "203.0.113.1"),
                   route("192.0.2.0/24", "test0"))
        scapy = FakeScapy(records=records)
        captured = ata_flash._capture_route_records(scapy)
        self.assertEqual(captured, records)

    def test_corrupt_scapy_record_triggers_netstat_fallback(self):
        good_records = (
            (0xC0A80000, 0xffff0000, "0.0.0.0", "test0", "192.168.2.2", 1),
            (0xE0000000, 0xF0000000, "0.0.0.0", "test0", "192.168.2.2", 1),
        )
        corrupt_records = (
            (0xC0A80000, 0xffffffff, "0.0.0.0", "test0", "192.168.2.2", 1),
            (0xE0000000, 0xF0FFFF00, "0.0.0.0", "test0", "192.168.2.2", 1),
        )
        scapy = FakeScapy(records=corrupt_records)
        import types
        fake_unix = types.ModuleType("scapy.arch.unix")
        fake_unix.read_routes = lambda: list(good_records)
        modules = {"scapy.arch.unix": fake_unix}
        with patch.dict("sys.modules", modules):
            captured = ata_flash._capture_route_records(scapy)
        self.assertEqual(captured, good_records)

    def test_fallback_keeps_original_when_netstat_unavailable(self):
        corrupt_records = (
            (0xE0000000, 0xF0FFFF00, "0.0.0.0", "test0", "192.168.2.2", 1),
        )
        scapy = FakeScapy(records=corrupt_records)
        modules = {"scapy.arch.unix": types.ModuleType("scapy.arch.unix")}
        with patch.dict("sys.modules", modules):
            captured = ata_flash._capture_route_records(scapy)
        self.assertEqual(captured, corrupt_records)


class CoordinatorTest(unittest.TestCase):
    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, _kind, _value, _traceback):
            return False

    def test_default_command_is_inert_without_scapy(self):
        result = subprocess.run(
            [sys.executable, "-B", str(ROOT / "ata_flash.py")],
            capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("DRY RUN", result.stdout)

    def test_address_help_explicitly_says_optional_and_never_configures(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit):
            ata_flash.parse_options(["ata_flash", "--help"])
        self.assertIn("optional assertion", output.getvalue())
        self.assertIn("never configures it", output.getvalue())

    def test_parser_diagnostic_uses_a_fixed_program_name(self):
        error = io.StringIO()
        with contextlib.redirect_stderr(error), self.assertRaises(SystemExit):
            ata_flash.parse_options([
                "hostile\nprogram", "--unknown=SensitivePayloadData123"])
        self.assertIn("usage: ata_flash.py", error.getvalue())
        self.assertNotIn("hostile", error.getvalue())
        self.assertNotIn("SensitivePayloadData123", error.getvalue())

    def test_combined_flow_reserves_ports_runs_dhcp_then_serves_locked_ip(self):
        args = ata_flash.parse_options([
            "ata_flash", "--apply", "--interface", "test0",
            "--address", "192.0.2.2", "--duration-seconds", "60",
            "firmware.zup",
        ])
        state = ata_flash.InterfaceState(
            "test0", ipaddress.IPv4Address("192.0.2.2"),
            ipaddress.IPv4Network("192.0.2.0/24"),
            (route("192.0.2.0/24", "test0"),))
        info = ata_flash.sata186us.ImageInfo(
            0, "00000000", 0x301, 0x400, 0x301)
        store = ata_flash.sata186us.BlockStore(
            b"x" * ata_flash.sata186us.BLOCK_SIZE, 1, [120])
        result = ata_flash.sata186us.ServerResult(1)
        result.unique_blocks.add(0)
        command_socket = self.FakeSocket()
        data_socket = self.FakeSocket()
        log = io.StringIO()
        events = []

        def run_dhcp(config, **_kwargs):
            events.append("dhcp")
            self.assertEqual(config.interface, "test0")
            self.assertEqual(config.server_address, "192.0.2.2")
            self.assertEqual(config.client_address, "192.0.2.10")
            self.assertEqual(config.lease_seconds, 660)
            return ata_flash.dhcp.DhcpLease(
                "192.0.2.10", bytes.fromhex("020000000001"))

        def serve(*_args, **kwargs):
            events.append("serve")
            self.assertTrue(kwargs["safety_check"]())
            return result

        with patch.object(
                ata_flash, "prepare_image",
                return_value=("a" * 64, info, store)), \
                patch.object(
                    ata_flash, "current_interface_state",
                    side_effect=(state, state, state)), \
                patch.object(ata_flash.sata186us, "bind_udp",
                             side_effect=(command_socket, data_socket)) as bind, \
                patch.object(ata_flash.dhcp, "run_dhcp",
                             side_effect=run_dhcp), \
                patch.object(ata_flash.sata186us, "drain_udp",
                             side_effect=(0, 0)) as drain, \
                patch.object(ata_flash.sata186us, "serve_firmware",
                             side_effect=serve) as server:
            self.assertEqual(ata_flash.run_flash(
                args, scapy_module=object(),
                logger=ata_flash.sata186us.Logger(log)), 0)

        self.assertEqual(events, ["dhcp", "serve"])
        self.assertEqual(bind.call_args_list, [
            call("192.0.2.2", 8000, interface="test0"),
            call("192.0.2.2", 8500, interface="test0")])
        self.assertEqual(drain.call_count, 2)
        self.assertEqual(server.call_args.args[6], "192.0.2.10")
        self.assertEqual(server.call_args.kwargs["completion_grace_seconds"], 60)
        self.assertIn("safety_check", server.call_args.kwargs)
        self.assertIn("100#192*0*2*2*8000#", log.getvalue())
        self.assertIn("verify the ATA with 123#", log.getvalue())

    def test_pre_service_firmware_traffic_aborts_without_serving(self):
        args = ata_flash.parse_options([
            "ata_flash", "--apply", "--interface", "test0", "firmware.zup",
        ])
        state = ata_flash.InterfaceState(
            "test0", ipaddress.IPv4Address("192.0.2.2"),
            ipaddress.IPv4Network("192.0.2.0/24"),
            (route("192.0.2.0/24", "test0"),))
        info = ata_flash.sata186us.ImageInfo(
            0, "00000000", 0x301, 0x400, 0x301)
        store = ata_flash.sata186us.BlockStore(
            b"x" * ata_flash.sata186us.BLOCK_SIZE, 1, [120])
        with patch.object(
                ata_flash, "prepare_image",
                return_value=("a" * 64, info, store)), \
                patch.object(
                    ata_flash, "current_interface_state",
                    side_effect=(state, state)), \
                patch.object(
                    ata_flash.sata186us, "bind_udp",
                    side_effect=(self.FakeSocket(), self.FakeSocket())), \
                patch.object(
                    ata_flash.dhcp, "run_dhcp",
                    return_value=ata_flash.dhcp.DhcpLease(
                        "192.0.2.10", bytes.fromhex("020000000001"))), \
                patch.object(
                    ata_flash.sata186us, "drain_udp",
                    side_effect=(1, 0)), \
                patch.object(ata_flash.sata186us, "serve_firmware") as server, \
                self.assertRaisesRegex(ata_flash.FlashError, "restart manually"):
            ata_flash.run_flash(
                args, scapy_module=object(),
                logger=ata_flash.sata186us.Logger(io.StringIO()))
        server.assert_not_called()

    def test_incomplete_transfer_is_not_success(self):
        args = ata_flash.parse_options([
            "ata_flash", "--apply", "--interface", "test0", "firmware.zup",
        ])
        state = ata_flash.InterfaceState(
            "test0", ipaddress.IPv4Address("192.0.2.2"),
            ipaddress.IPv4Network("192.0.2.0/24"),
            (route("192.0.2.0/24", "test0"),))
        info = ata_flash.sata186us.ImageInfo(
            0, "00000000", 0x301, 0x400, 0x301)
        store = ata_flash.sata186us.BlockStore(
            b"x" * ata_flash.sata186us.BLOCK_SIZE * 2, 2, [120, 120])
        result = ata_flash.sata186us.ServerResult(2)
        result.unique_blocks.add(0)
        with patch.object(
                ata_flash, "prepare_image",
                return_value=("a" * 64, info, store)), \
                patch.object(
                    ata_flash, "current_interface_state",
                    side_effect=(state, state)), \
                patch.object(ata_flash.sata186us, "bind_udp",
                             side_effect=(self.FakeSocket(), self.FakeSocket())), \
                patch.object(
                    ata_flash.dhcp, "run_dhcp",
                    return_value=ata_flash.dhcp.DhcpLease(
                        "192.0.2.10", bytes.fromhex("020000000001"))), \
                patch.object(ata_flash.sata186us, "drain_udp",
                             side_effect=(0, 0)), \
                patch.object(ata_flash.sata186us, "serve_firmware",
                             return_value=result), \
                self.assertRaisesRegex(ata_flash.FlashError, "before all blocks"):
            ata_flash.run_flash(
                args, scapy_module=object(),
                logger=ata_flash.sata186us.Logger(io.StringIO()))


if __name__ == "__main__":
    unittest.main()
