"""Offline tests for the bounded ATA DHCP responder."""

import contextlib
import io
from pathlib import Path
import struct
import subprocess
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import dhcp


CLIENT_MAC = bytes.fromhex("020000000001")
OTHER_MAC = bytes.fromhex("020000000002")


def dhcp_frame(config, message_type=1, mac=CLIENT_MAC, xid=0x10203040,
               options=None, end=True):
    bootp = bytearray(236)
    bootp[:4] = b"\x01\x01\x06\0"
    bootp[4:8] = xid.to_bytes(4, "big")
    bootp[28:34] = mac
    if options is None:
        options = bytes((53, 1, message_type))
        if message_type == 3:
            options += bytes((54, 4)) + config.server_bytes
            options += bytes((50, 4)) + config.client_bytes
    if end:
        options += b"\xff"
    payload = bytes(bootp) + dhcp.DHCP_COOKIE + options
    udp = struct.pack("!HHHH", 68, 67, 8 + len(payload), 0) + payload
    ip = bytearray(20)
    ip[0] = 0x45
    ip[2:4] = (20 + len(udp)).to_bytes(2, "big")
    ip[8] = 64
    ip[9] = 17
    return b"\xff" * 6 + mac + b"\x08\0" + bytes(ip) + udp


class Layer:
    def __truediv__(self, _other):
        return self


class Packet:
    def __init__(self, raw):
        self.original = raw


class FakeScapy:
    BOOTP = staticmethod(lambda **_kwargs: Layer())
    DHCP = staticmethod(lambda **_kwargs: Layer())
    Ether = staticmethod(lambda **_kwargs: Layer())
    IP = staticmethod(lambda **_kwargs: Layer())
    UDP = staticmethod(lambda **_kwargs: Layer())

    def __init__(self, frames):
        self.frames = frames
        self.sent = []
        self.send_kwargs = []
        self.sniff_kwargs = None

    @staticmethod
    def get_if_hwaddr(_interface):
        return "02:00:00:00:00:03"

    def sendp(self, packet, **kwargs):
        self.sent.append(packet)
        self.send_kwargs.append(kwargs)

    def sniff(self, prn, stop_filter, **kwargs):
        self.sniff_kwargs = kwargs
        for frame in self.frames:
            packet = Packet(frame)
            prn(packet)
            if stop_filter(packet):
                break


class DhcpTest(unittest.TestCase):
    def setUp(self):
        self.config = dhcp.DhcpConfig(
            "test0", "192.0.2.2", "192.0.2.10", "255.255.255.0")

    def test_default_command_is_inert_without_scapy(self):
        result = subprocess.run(
            [sys.executable, "-I", "-S", "-B", str(ROOT / "dhcp.py")],
            capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("DRY RUN", result.stdout)

    def test_main_apply_requires_interface(self):
        with self.assertRaises(SystemExit) as caught:
            dhcp.main(["dhcp.py", "--apply"])
        self.assertEqual(caught.exception.code, 2)

    def test_main_apply_interface_builds_default_config(self):
        class FakeAddressScapy:
            @staticmethod
            def get_if_addr(_interface):
                return "192.0.2.2"

        captured = {}

        def fake_run_dhcp(config, **kwargs):
            captured["config"] = config
            return dhcp.DhcpLease(
                config.client_address, bytes.fromhex("020000000001"))

        with patch("dhcp.import_module", return_value=FakeAddressScapy()), \
                patch("dhcp.run_dhcp", side_effect=fake_run_dhcp):
            result = dhcp.main(["dhcp.py", "--apply", "--interface", "test0",
                                "--lease-seconds", "300",
                                "--timeout-seconds", "60"])
        self.assertEqual(result, 0)
        config = captured["config"]
        self.assertEqual(config.interface, "test0")
        self.assertEqual(config.server_address, "192.0.2.2")
        self.assertEqual(config.client_address, "192.0.2.10")
        self.assertEqual(config.subnet_mask, "255.255.255.0")
        self.assertEqual(config.lease_seconds, 300)
        self.assertEqual(config.timeout_seconds, 60)

    def test_main_client_mac_and_address_override_defaults(self):
        class FakeAddressScapy:
            @staticmethod
            def get_if_addr(_interface):
                return "192.0.2.2"

        captured = {}

        def fake_run_dhcp(config, **kwargs):
            captured["config"] = config
            return dhcp.DhcpLease(config.client_address, CLIENT_MAC)

        with patch("dhcp.import_module", return_value=FakeAddressScapy()), \
                patch("dhcp.run_dhcp", side_effect=fake_run_dhcp):
            result = dhcp.main([
                "dhcp.py", "--apply", "--interface", "test0",
                "--client-address", "192.0.2.50",
                "--client-mac", "02:00:00:00:00:01"])
        self.assertEqual(result, 0)
        config = captured["config"]
        self.assertEqual(config.client_address, "192.0.2.50")
        self.assertEqual(config.expected_client_mac, CLIENT_MAC)

    def test_parser_accepts_only_bounded_coherent_requests(self):
        for message_type in (1, 3):
            with self.subTest(message_type=message_type):
                parsed = dhcp.parse_request(
                    dhcp_frame(self.config, message_type), self.config)
                self.assertEqual(parsed, (
                    message_type, 0x10203040, CLIENT_MAC + b"\0" * 10))

        valid = dhcp_frame(self.config)
        self.assertIsNone(dhcp.parse_request(valid[:-1], self.config))
        self.assertIsNone(dhcp.parse_request(
            valid + b"x" * dhcp.MAX_PACKET_BYTES, self.config))
        self.assertIsNone(dhcp.parse_request(
            dhcp_frame(self.config, mac=b"\0" * 6), self.config))
        self.assertIsNone(dhcp.parse_request(
            dhcp_frame(self.config, options=bytes((53, 2, 1))), self.config))
        self.assertIsNone(dhcp.parse_request(
            dhcp_frame(self.config, end=False), self.config))

        expected = dhcp.DhcpConfig(
            "test0", "192.0.2.2", "192.0.2.10", "255.255.255.0",
            CLIENT_MAC)
        self.assertIsNone(dhcp.parse_request(
            dhcp_frame(expected, mac=OTHER_MAC), expected))

    def test_first_discover_locks_client_and_transaction_through_ack(self):
        scapy = FakeScapy((
            dhcp_frame(self.config, 3, CLIENT_MAC),
            dhcp_frame(self.config, 1, CLIENT_MAC),
            dhcp_frame(self.config, 3, OTHER_MAC),
            dhcp_frame(self.config, 3, CLIENT_MAC, xid=0x55667788),
            dhcp_frame(self.config, 3, CLIENT_MAC),
        ))
        logs = []
        address_checks = 0

        def address_check():
            nonlocal address_checks
            address_checks += 1
            return True

        lease = dhcp.run_dhcp(
            self.config, scapy_module=scapy,
            address_check=address_check, logger=logs.append)
        self.assertEqual(lease.client_mac, CLIENT_MAC)
        self.assertEqual(lease.client_address, "192.0.2.10")
        self.assertEqual(len(scapy.sent), 2)
        self.assertEqual(address_checks, 3)
        self.assertTrue(all(item["promisc"] is False
                            for item in scapy.send_kwargs))
        self.assertIs(scapy.sniff_kwargs["promisc"], False)
        self.assertTrue(any('"response":"ACK"' in line for line in logs))

    def test_reply_advertises_tftp_server_options(self):
        class RecordingScapy(FakeScapy):
            dhcp_kwargs = []

            @staticmethod
            def DHCP(**kwargs):
                RecordingScapy.dhcp_kwargs.append(kwargs)
                return Layer()

        scapy = RecordingScapy((dhcp_frame(self.config, 1),
                                dhcp_frame(self.config, 3)))
        lease = dhcp.run_dhcp(
            self.config, scapy_module=scapy, address_check=lambda: True,
            logger=lambda _message: None)
        self.assertEqual(lease.client_mac, CLIENT_MAC)
        self.assertEqual(len(scapy.sent), 2)
        self.assertEqual(len(RecordingScapy.dhcp_kwargs), 2)
        options = RecordingScapy.dhcp_kwargs[0].get("options")
        self.assertIn(("tftp_server_name", self.config.server_address),
                      options)
        self.assertIn(("tftp_server_address", self.config.server_address),
                      options)

    def test_expected_client_can_request_directly(self):
        config = dhcp.DhcpConfig(
            "test0", "192.0.2.2", "192.0.2.10", "255.255.255.0",
            CLIENT_MAC)
        scapy = FakeScapy((dhcp_frame(config, 3, CLIENT_MAC),))
        lease = dhcp.run_dhcp(
            config, scapy_module=scapy, address_check=lambda: True,
            logger=lambda _message: None)
        self.assertEqual(lease.client_mac, CLIENT_MAC)
        self.assertEqual(len(scapy.sent), 1)

    def test_address_change_aborts_before_reply(self):
        scapy = FakeScapy((dhcp_frame(self.config, 1),))
        checks = iter((True, False))
        with contextlib.redirect_stdout(io.StringIO()), \
                self.assertRaisesRegex(dhcp.DhcpError, "address changed"):
            dhcp.run_dhcp(
                self.config, scapy_module=scapy,
                address_check=lambda: next(checks),
                logger=lambda _message: None)
        self.assertEqual(scapy.sent, [])


if __name__ == "__main__":
    unittest.main()
