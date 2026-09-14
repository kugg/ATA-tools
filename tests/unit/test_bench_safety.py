"""Offline checks for legacy diagnostics; no packets, privilege or models."""
import importlib.util
import os
from pathlib import Path
import signal
import subprocess
import struct
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("ring_once", ROOT / "ring_once.py")
assert spec is not None and spec.loader is not None
ring = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ring)
dhcp_spec = importlib.util.spec_from_file_location("dhcp", ROOT / "dhcp.py")
assert dhcp_spec is not None and dhcp_spec.loader is not None
dhcp = importlib.util.module_from_spec(dhcp_spec)
dhcp_spec.loader.exec_module(dhcp)


class BenchSafety(unittest.TestCase):
    CLIENT_MAC = bytes.fromhex("020000000001")
    OTHER_MAC = bytes.fromhex("020000000002")

    def setUp(self):
        self.dhcp_config = dhcp.DhcpConfig(
            "test0", "192.168.2.2", "192.168.2.10", "255.255.255.0")

    def _dhcp_frame(self, message_type=1, mac=None, xid=0x10203040,
                    options=None, end=True):
        if mac is None:
            mac = self.CLIENT_MAC
        bootp = bytearray(236)
        bootp[:4] = b"\x01\x01\x06\0"
        bootp[4:8] = xid.to_bytes(4, "big")
        bootp[28:34] = mac
        if options is None:
            options = bytes((53, 1, message_type))
            if message_type == 3:
                options += bytes((54, 4)) + self.dhcp_config.server_bytes
                options += bytes((50, 4)) + self.dhcp_config.client_bytes
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

    def test_default_commands_are_offline_without_scapy(self):
        for filename in ("dhcp.py", "ring_once.py"):
            with self.subTest(filename=filename):
                result = subprocess.run([sys.executable, "-I", "-S", "-B", str(ROOT / filename)],
                                        capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("DRY RUN", result.stdout)
        direct_dhcp = subprocess.run(
            [sys.executable, "-I", "-S", "-B", str(ROOT / "dhcp.py"),
             "--apply"], capture_output=True, text=True, timeout=5)
        self.assertEqual(direct_dhcp.returncode, 2)
        self.assertIn("usage: dhcp.py", direct_dhcp.stderr)

    def test_dhcp_probe_is_deadline_bounded_and_nonpersistent(self):
        source = (ROOT / "dhcp.py").read_text()
        self.assertEqual(dhcp.DEFAULT_TIMEOUT_SECONDS, 600)
        self.assertEqual(dhcp.MAX_PACKET_BYTES, 1024)
        self.assertEqual(dhcp.MAX_DHCP_OPTION_BYTES, 512)
        self.assertIn("stop_filter=", source)
        self.assertIn("interface_changed", source)
        self.assertNotIn("MAX_PACKETS", source)
        self.assertNotIn("EXPECTED_CLIENT_MAC", source)
        self.assertNotIn("write_text(", source)
        self.assertNotIn('"mac": mac.hex', source)

    def test_dhcp_parser_accepts_bounded_self_consistent_client_requests(self):
        for message_type in (1, 3):
            with self.subTest(message_type=message_type):
                parsed = dhcp.parse_request(
                    self._dhcp_frame(message_type), self.dhcp_config)
                self.assertEqual(parsed, (message_type, 0x10203040,
                                          self.CLIENT_MAC + b"\0" * 10))
        valid = self._dhcp_frame()
        self.assertIsNone(dhcp.parse_request(valid[:-1], self.dhcp_config))
        self.assertIsNone(dhcp.parse_request(
            valid + b"x" * dhcp.MAX_PACKET_BYTES, self.dhcp_config))
        self.assertIsNone(dhcp.parse_request(
            self._dhcp_frame(mac=b"\0" * 6), self.dhcp_config))
        malformed = self._dhcp_frame(options=bytes((53, 2, 1)), end=True)
        self.assertIsNone(dhcp.parse_request(malformed, self.dhcp_config))
        self.assertIsNone(dhcp.parse_request(
            self._dhcp_frame(end=False), self.dhcp_config))
        bad_cookie = bytearray(valid)
        bad_cookie[278] ^= 1
        self.assertIsNone(dhcp.parse_request(bytes(bad_cookie), self.dhcp_config))
        unknown_option = bytes((99, 2, 1, 2, 53, 1, 1))
        self.assertIsNotNone(dhcp.parse_request(
            self._dhcp_frame(options=unknown_option), self.dhcp_config))
        large_options = bytes((99, 255)) + b"x" * 255
        large_options *= 2
        large_options += bytes((53, 1, 1))
        self.assertIsNone(dhcp.parse_request(
            self._dhcp_frame(options=large_options), self.dhcp_config))

        expected = dhcp.DhcpConfig(
            "test0", "192.168.2.2", "192.168.2.10", "255.255.255.0",
            self.CLIENT_MAC)
        self.assertIsNone(dhcp.parse_request(
            self._dhcp_frame(mac=self.OTHER_MAC), expected))
        self.assertIsNotNone(dhcp.parse_request(
            self._dhcp_frame(mac=self.OTHER_MAC), self.dhcp_config))

    def test_dhcp_locks_first_valid_client_through_ack(self):
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
                return "02:00:00:00:00:02"

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

        scapy = FakeScapy((
            self._dhcp_frame(3, self.CLIENT_MAC),
            self._dhcp_frame(1, self.CLIENT_MAC),
            self._dhcp_frame(3, self.OTHER_MAC),
            self._dhcp_frame(3, self.CLIENT_MAC, xid=0x55667788),
            self._dhcp_frame(3, self.CLIENT_MAC),
        ))
        logs = []
        address_checks = 0

        def address_check():
            nonlocal address_checks
            address_checks += 1
            return True

        lease = dhcp.run_dhcp(
            self.dhcp_config, scapy_module=scapy,
            address_check=address_check, logger=logs.append)
        self.assertEqual(lease.client_mac, self.CLIENT_MAC)
        self.assertEqual(lease.client_address, "192.168.2.10")
        self.assertEqual(len(scapy.sent), 2)
        self.assertTrue(all(item["promisc"] is False
                            for item in scapy.send_kwargs))
        self.assertIs(scapy.sniff_kwargs["promisc"], False)
        self.assertEqual(address_checks, 3)
        self.assertTrue(any('"response":"ACK"' in line for line in logs))

    def test_http_response_limit_and_cleanup(self):
        with patch.object(ring.http.client, "HTTPConnection") as connection:
            connection.return_value.getresponse.return_value.read.return_value = b"x" * 65537
            with self.assertRaisesRegex(RuntimeError, "exceeds"):
                ring.web("dev")
            connection.return_value.close.assert_called_once()

    def test_sccp_logs_do_not_include_payload(self):
        from unittest.mock import Mock
        with patch("builtins.print") as log:
            ring.send(Mock(), 1, b"private-payload")
        self.assertNotIn("private", str(log.call_args_list))
        self.assertNotIn(b"private-payload".hex(), str(log.call_args_list))

    def test_total_deadline_interrupts_blocking_response_and_restores_handler(self):
        previous = ring.signal.getsignal(ring.signal.SIGALRM)
        with patch.object(ring.http.client, "HTTPConnection") as connection, \
             patch.object(ring, "HTTP_TIMEOUT", 0.03):
            connection.return_value.getresponse.side_effect = lambda: time.sleep(1)
            started = time.monotonic()
            with self.assertRaisesRegex(TimeoutError, "total deadline"):
                ring.web("dev")
            self.assertLess(time.monotonic() - started, 0.5)
            connection.return_value.close.assert_called_once()
        self.assertEqual(ring.signal.getsignal(ring.signal.SIGALRM), previous)
        self.assertEqual(ring.signal.getitimer(ring.signal.ITIMER_REAL), (0.0, 0.0))

    def test_existing_process_timer_is_not_overwritten(self):
        with patch.object(ring.signal, "getitimer", return_value=(1.0, 0.0)), \
             patch.object(ring.http.client, "HTTPConnection") as connection:
            with self.assertRaisesRegex(RuntimeError, "existing process timer"):
                ring.web("dev")
            connection.assert_not_called()

    def test_backup_is_private_at_creation(self):
        # Socket failure ends the test before any configuration POST.
        with tempfile.TemporaryDirectory() as directory:
            backup = Path(directory) / "ata-config-test.json"
            form = '<input name="CallManager0" value="0"><input name="UseTFTP" value="1">'
            previous = os.umask(0)
            try:
                with patch.object(ring, "web", return_value=form), \
                     patch.object(ring, "Path") as path, \
                     patch.object(ring.socket, "socket", side_effect=RuntimeError("offline stop")):
                    path.return_value.with_name.return_value = backup
                    with self.assertRaisesRegex(RuntimeError, "offline stop"):
                        ring.main()
                self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
            finally:
                os.umask(previous)

    def test_qemu_tool_harness_uses_array_and_bounded_private_evidence(self):
        script = ROOT / "tests" / "qemu" / "run-qemu-tools.sh"
        source = script.read_text()
        syntax = subprocess.run(
            ["/bin/bash", "-n", str(script)], capture_output=True, text=True,
            timeout=5)
        self.assertEqual(syntax.returncode, 0, syntax.stderr)
        self.assertIn('qemu-system-x86_64 "${QEMU_ARGS[@]}"', source)
        self.assertNotIn("qemu-system-x86_64 $QEMU_ARGS", source)
        self.assertIn('"$RUNDIR/console.log"', source)
        self.assertIn('"$BOUNDED_COMMAND"', source)
        self.assertNotIn("ulimit -f", source)
        self.assertIn("is_safe_qemu_path", source)
        self.assertNotIn("--allow-subnet-overlap", source)
        self.assertIn('"$NETWORK_STATE" check-overlap', source)
        self.assertIn('"$NETWORK_STATE" compare', source)
        self.assertIn('trap cleanup EXIT', source)
        self.assertIn("trap 'handle_signal 129' HUP", source)
        self.assertIn('"$RUNDIR/prelaunch-route4.txt"', source)
        self.assertIn('child_pid="$!"', source)
        self.assertNotIn("trap '' HUP INT TERM\n\"$PYTHON_BIN\"", source)

    def test_qemu_network_helper_handles_netmasks_and_stable_state(self):
        helper = ROOT / "tests" / "qemu" / "network_state.py"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            overlap = root / "overlap.txt"
            overlap.write_text(
                "Routing tables\nInternet:\nDestination Gateway Flags Netif\n"
                "10.0/255.255.0.0 utun7 USc utun7\n")
            overlap.chmod(0o600)
            result = subprocess.run([
                sys.executable, "-B", str(helper), "check-overlap",
                str(overlap), "10.0.2.0/24",
            ], capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 1, result.stderr)

            route4_before = root / "route4-before.txt"
            route4_after = root / "route4-after.txt"
            route4_before.write_text(
                "Routing tables\nInternet:\nDestination Gateway Flags Netif Expire\n"
                "default 192.0.2.1 UGSc en0\n"
                "192.0.2  link#1 UCS en0\n"
                "192.0.2.2 aa:bb:cc:dd:ee:ff UHLWI en0 20\n")
            route4_after.write_text(route4_before.read_text().replace(
                "aa:bb:cc:dd:ee:ff UHLWI en0 20",
                "00:00:00:00:00:00 UHLWI en0 1"))
            route6_before = root / "route6-before.txt"
            route6_after = root / "route6-after.txt"
            route6_before.write_text(
                "Routing tables\nInternet6:\nDestination Gateway Flags Netif\n"
                "fd00:47:11:0::/64 utun7 USc utun7\n")
            route6_after.write_text(route6_before.read_text().replace(
                "fd00:47:11:0::/64", "fd00:47:11::/64"))
            nwi_before = root / "nwi-before.txt"
            nwi_after = root / "nwi-after.txt"
            nwi_before.write_text(
                "Network information\nIPv4 network interface information\n"
                "IPv6 network interface information\nREACH : flags 0x2\n"
                "Network interfaces: en0\n")
            nwi_after.write_text(nwi_before.read_text().replace("0x2", "0x7"))
            for snapshot in (overlap, route4_before, route4_after,
                             route6_before, route6_after, nwi_before, nwi_after):
                snapshot.chmod(0o600)
            compare = [
                sys.executable, "-B", str(helper), "compare",
                str(route4_before), str(route4_after),
                str(route6_before), str(route6_after),
                str(nwi_before), str(nwi_after),
            ]
            changed = subprocess.run(
                compare, capture_output=True, text=True, timeout=5)
            self.assertEqual(changed.returncode, 1, changed.stderr)
            nwi_after.write_text(nwi_before.read_text())
            unchanged = subprocess.run(
                compare, capture_output=True, text=True, timeout=5)
            self.assertEqual(unchanged.returncode, 0, unchanged.stderr)
            route6_after.write_text(route4_after.read_text())
            wrong_family = subprocess.run(
                compare, capture_output=True, text=True, timeout=5)
            self.assertEqual(wrong_family.returncode, 2)

    def test_bounded_command_caps_burst_output_and_rejects_existing_paths(self):
        helper = ROOT / "tests" / "qemu" / "bounded_command.py"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "console.log"
            command = [
                sys.executable, "-c",
                "import sys; sys.stdout.buffer.write(b'x' * (5 * 1024 * 1024 // 2))",
            ]
            result = subprocess.run(
                [sys.executable, "-B", str(helper), str(output), "10", *command],
                capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 125, result.stderr)
            self.assertEqual(output.stat().st_size, 2 * 1024 * 1024)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            existing = subprocess.run(
                [sys.executable, "-B", str(helper), str(output), "10", *command],
                capture_output=True, text=True, timeout=5)
            self.assertEqual(existing.returncode, 126)
            target = Path(directory) / "target"
            target.write_text("unchanged")
            link = Path(directory) / "link"
            link.symlink_to(target)
            linked = subprocess.run(
                [sys.executable, "-B", str(helper), str(link), "10", *command],
                capture_output=True, text=True, timeout=5)
            self.assertEqual(linked.returncode, 126)
            self.assertEqual(target.read_text(), "unchanged")

    def test_bounded_command_stops_a_timed_out_process_group(self):
        helper = ROOT / "tests" / "qemu" / "bounded_command.py"
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "late-marker"
            output = Path(directory) / "timeout.log"
            child = (
                "import pathlib,time; time.sleep(2); "
                f"pathlib.Path({str(marker)!r}).write_text('late')"
            )
            command = [
                sys.executable, "-c",
                ("import subprocess,sys,time; "
                 f"subprocess.Popen([sys.executable, '-c', {child!r}]); "
                 "time.sleep(30)"),
            ]
            started = time.monotonic()
            result = subprocess.run(
                [sys.executable, "-B", str(helper), str(output), "1", *command],
                capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 124, result.stderr)
            self.assertLess(time.monotonic() - started, 7)
            time.sleep(2)
            self.assertFalse(marker.exists())

    def test_bounded_command_enforces_deadline_after_eof_and_reserves_timeout_status(self):
        helper = ROOT / "tests" / "qemu" / "bounded_command.py"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            eof_result = subprocess.run([
                sys.executable, "-B", str(helper), str(root / "eof.log"), "1",
                sys.executable, "-c",
                "import os,time; os.close(1); os.close(2); time.sleep(2)",
            ], capture_output=True, text=True, timeout=5)
            self.assertEqual(eof_result.returncode, 124, eof_result.stderr)
            reserved = subprocess.run([
                sys.executable, "-B", str(helper), str(root / "reserved.log"), "5",
                sys.executable, "-c", "raise SystemExit(124)",
            ], capture_output=True, text=True, timeout=5)
            self.assertEqual(reserved.returncode, 126)
            self.assertIn("reserved timeout status", reserved.stderr)

    def test_bounded_command_stops_its_group_on_sighup(self):
        helper = ROOT / "tests" / "qemu" / "bounded_command.py"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "sighup-marker"
            child = (
                "import pathlib,time; time.sleep(2); "
                f"pathlib.Path({str(marker)!r}).write_text('late')"
            )
            command = (
                "import subprocess,sys,time; "
                f"subprocess.Popen([sys.executable, '-c', {child!r}]); "
                "time.sleep(30)"
            )
            process = subprocess.Popen([
                sys.executable, "-B", str(helper), str(root / "sighup.log"), "30",
                sys.executable, "-c", command,
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            time.sleep(0.5)
            process.send_signal(signal.SIGHUP)
            _stdout, stderr = process.communicate(timeout=8)
            self.assertEqual(process.returncode, 128 + signal.SIGHUP, stderr)
            time.sleep(2)
            self.assertFalse(marker.exists())

    def test_bounded_command_rejects_and_stops_a_lingering_descendant(self):
        helper = ROOT / "tests" / "qemu" / "bounded_command.py"
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "orphan-marker"
            output = Path(directory) / "orphan.log"
            child = (
                "import pathlib,time; time.sleep(2); "
                f"pathlib.Path({str(marker)!r}).write_text('orphaned')"
            )
            parent = (
                "import os,subprocess,sys; "
                f"subprocess.Popen([sys.executable, '-c', {child!r}], "
                "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, "
                "stderr=subprocess.DEVNULL)"
            )
            result = subprocess.run([
                sys.executable, "-B", str(helper), str(output), "10",
                sys.executable, "-c", parent,
            ], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 126, result.stderr)
            time.sleep(2)
            self.assertFalse(marker.exists())

    def test_qemu_harness_preserves_safe_metacharacter_paths_as_arguments(self):
        script = ROOT / "tests" / "qemu" / "run-qemu-tools.sh"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            argv_output = root / "argv.bin"
            qemu = fake_bin / "qemu-system-x86_64"
            qemu.write_text(
                "#!/usr/bin/env python3\n"
                "import os, sys\n"
                "with open(os.environ['FAKE_QEMU_ARGV'], 'wb') as output:\n"
                "    output.write(b'\\0'.join(os.fsencode(v) for v in sys.argv[1:]))\n"
                "print('fake qemu only')\n")
            qemu.chmod(0o700)
            for name, body in (
                    ("netstat", "printf 'Routing tables\\nInternet:\\nDestination Gateway Flags Netif\\ndefault 192.0.2.1 UGSc en0\\n'\n"),
                    ("scutil", "printf 'Network information\\nNetwork interfaces: en0\\n'\n"),
                    ("arp", ":\n"),
                    ("pgrep", "exit 1\n")):
                executable = fake_bin / name
                executable.write_text("#!/bin/sh\n" + body)
                executable.chmod(0o700)
            (fake_bin / "netstat").write_text(
                "#!/bin/sh\ncase \"$*\" in\n"
                "  *inet6*) printf 'Routing tables\\nInternet6:\\n"
                "Destination Gateway Flags Netif\\n"
                "default fe80::%%utun0 UGcIg utun0\\n' ;;\n"
                "  *) printf 'Routing tables\\nInternet:\\n"
                "Destination Gateway Flags Netif\\n"
                "default 192.0.2.1 UGSc en0\\n' ;;\n"
                "esac\n")
            (fake_bin / "scutil").write_text(
                "#!/bin/sh\nprintf 'Network information\\n"
                "IPv4 network interface information\\n"
                "IPv6 network interface information\\n"
                "Network interfaces: en0\\n'\n")
            strange = "a[$(touch${IFS}owned)]0;unicode-\u00e5"
            disk = root / "nbd:host:10809"
            disk.write_bytes(b"disk")
            ovmf = root / ("ovmf-" + strange)
            ovmf.write_bytes(b"ovmf")
            tools = root / ("tools-" + strange)
            tools.mkdir()
            for name in ("cfgfmt.py", "prserv.py", "sata186us.py"):
                (tools / name).write_text("")
            legacy = root / ("legacy-" + strange)
            legacy.mkdir()
            (legacy / "ptag.dat").write_text("")
            env = os.environ.copy()
            env["PATH"] = str(fake_bin) + os.pathsep + env["PATH"]
            env["FAKE_QEMU_ARGV"] = str(argv_output)
            env["TMPDIR"] = str(root)
            result = subprocess.run([
                "/bin/bash", str(script), "--disk", disk.name,
                "--ovmf", str(ovmf),
                "--tools", str(tools), "--legacy", str(legacy),
                "--timeout", "60", "--apply",
            ], cwd=root, env=env, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertFalse((root / "owned").exists())
            arguments = argv_output.read_bytes().split(b"\0")
            self.assertIn(os.fsencode(
                f"file={disk.resolve()},format=qcow2,if=virtio,snapshot=on"),
                arguments)
            self.assertIn(os.fsencode(
                f"if=pflash,format=raw,readonly=on,file={ovmf.resolve()}"), arguments)
            self.assertIn(os.fsencode(
                f"local,path={tools.resolve()},mount_tag=refactor,"
                "security_model=mapped-xattr,readonly=on"), arguments)
            rundir = next(root.glob("ata-qemu-tools.*"))
            for name in ("console.log", "pre-route4.txt", "pre-route6.txt",
                         "pre-nwi.txt", "prelaunch-route4.txt",
                         "prelaunch-route6.txt", "prelaunch-nwi.txt",
                         "post-route4.txt", "post-route6.txt", "post-nwi.txt"):
                evidence = rundir / name
                self.assertLessEqual(evidence.stat().st_size, 2 * 1024 * 1024)
                self.assertEqual(evidence.stat().st_mode & 0o777, 0o600)

    def test_qemu_harness_rejects_suboption_delimiters_and_missing_values(self):
        script = ROOT / "tests" / "qemu" / "run-qemu-tools.sh"
        for arguments in (("--disk", "bad,value"),
                          ("--disk", "bad\nvalue"),
                          ("--disk", "bad\tvalue"),
                          ("--disk",)):
            with self.subTest(arguments=arguments):
                result = subprocess.run(
                    ["/bin/bash", str(script), *arguments],
                    capture_output=True, text=True, timeout=5)
                self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
