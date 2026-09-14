"""Offline tests for the bounded TFTP profile server."""

import io
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from telephony import tftp_profile as tftp  # noqa: E402


class SplitRrqTest(unittest.TestCase):
    def test_valid_octet_rrq(self):
        self.assertEqual(
            tftp.split_rrq(b"\x00\x01ATA0000000EXAMPLE.cnf.xml\x00octet\x00"),
            ("ATA0000000EXAMPLE.cnf.xml", "octet"))

    def test_rejects_path_traversal(self):
        with self.assertRaises(tftp.ProtocolError):
            tftp.split_rrq(b"\x00\x01../etc/passwd\x00octet\x00")

    def test_rejects_absolute_path(self):
        with self.assertRaises(tftp.ProtocolError):
            tftp.split_rrq(b"\x00\x01/abs/x\x00octet\x00")

    def test_rejects_netascii(self):
        with self.assertRaises(tftp.ProtocolError):
            tftp.split_rrq(b"\x00\x01file\x00netascii\x00")

    def test_rejects_truncated(self):
        with self.assertRaises(tftp.ProtocolError):
            tftp.split_rrq(b"\x00\x01")
        with self.assertRaises(tftp.ProtocolError):
            tftp.split_rrq(b"\x00\x01file")


class BlockizeTest(unittest.TestCase):
    def test_empty_file(self):
        self.assertEqual(tftp.blockize(b""), [b""])

    def test_small_payload(self):
        self.assertEqual(tftp.blockize(b"abc"), [b"abc"])

    def test_exact_multiple(self):
        payload = b"x" * 1024
        self.assertEqual([len(b) for b in tftp.blockize(payload)], [512, 512])

    def test_requires_bytes(self):
        with self.assertRaises(TypeError):
            tftp.blockize("abc")


class WireEncodingTest(unittest.TestCase):
    def test_data_frame(self):
        wire = tftp.encode_data(1, b"abc")
        self.assertEqual(wire[:4], b"\x00\x03\x00\x01")
        self.assertEqual(wire[4:], b"abc")

    def test_ack_frame(self):
        self.assertEqual(tftp.encode_ack(0), b"\x00\x04\x00\x00")


class _FakeSock:
    """Records sendto((peer, packet)) pairs; never touches the network."""

    def __init__(self):
        self.sent = []

    def sendto(self, packet, peer):
        self.sent.append((peer, packet))


class _PayloadLog:
    def __init__(self):
        self.lines = []

    def info(self, message):
        self.lines.append(message)


class ServerFlowTest(unittest.TestCase):
    PROFILE = b"profile-data-\x00\x01-with-binary" * 40

    def _make_server(self, expected="192.168.2.10"):
        sock = _FakeSock()
        log = _PayloadLog()
        server = tftp.TftpServer(
            "192.168.2.2", expected,
            {"ATA.cnf.xml": self.PROFILE, "atadefault.cfg": self.PROFILE},
            run_seconds=60, timeout_seconds=1, log=log)
        server.sock = sock
        return server, sock, log

    def _drive_client(self, server, sock, peer=("192.168.2.10", 2000)):
        server.handle_datagram(peer, b"\x00\x01ATA.cnf.xml\x00octet\x00")
        received = []
        seen = set()
        guard = 0
        while server.transfer is not None:
            self.assertLess(guard, 1000)
            guard += 1
            data_packets = [(p, d) for (p, d) in sock.sent
                            if p == peer and d[:2] == b"\x00\x03"
                            and d[2:4] not in seen]
            self.assertTrue(data_packets, "expected a DATA block sent")
            _, data = data_packets[0]
            block = int.from_bytes(data[2:4], "big")
            seen.add(data[2:4])
            received.append(data[4:])
            server.handle_datagram(peer, tftp.encode_ack(block))
        return received

    def test_full_transfer(self):
        server, sock, log = self._make_server()
        received = self._drive_client(server, sock)
        self.assertEqual(b"".join(received), self.PROFILE)
        self.assertEqual(server.transfer, None)
        self.assertGreaterEqual(server.requests, 1)
        self.assertEqual(server.errors, 0)
        self.assertEqual(server.byte_count, len(self.PROFILE))

    def test_short_tail_ends_with_empty_block(self):
        server, sock, log = self._make_server()
        peer = ("192.168.2.10", 2000)
        server.handle_datagram(peer, b"\x00\x01ATA.cnf.xml\x00octet\x00")
        sent = []
        seen = set()
        guard = 0
        while server.transfer is not None:
            self.assertLess(guard, 1000)
            guard += 1
            blocks = [(p, d) for (p, d) in sock.sent
                      if p == peer and d[:2] == b"\x00\x03"
                      and d[2:4] not in seen]
            self.assertTrue(blocks, "expected a DATA block")
            _, data = blocks[0]
            seen.add(data[2:4])
            sent.append(data)
            server.handle_datagram(
                peer, tftp.encode_ack(int.from_bytes(data[2:4], "big")))
        expected_blocks = len(tftp.blockize(self.PROFILE)) + 1
        self.assertEqual(len(sent), expected_blocks)
        self.assertEqual(sent[-1][4:], b"")
        self.assertEqual(server.errors, 0)

    def test_rejects_unknown_filename(self):
        server, sock, log = self._make_server()
        peer = ("192.168.2.10", 2000)
        server.handle_datagram(peer, b"\x00\x01other.txt\x00octet\x00")
        self.assertTrue(any(p == peer and d[:2] == b"\x00\x05"
                            and d[2:4] == b"\x00\x01" for p, d in sock.sent))
        self.assertEqual(server.errors, 1)

    def test_rejects_unexpected_client(self):
        server, sock, log = self._make_server()
        peer = ("192.168.2.99", 2000)
        server.handle_datagram(peer, b"\x00\x01ATA.cnf.xml\x00octet\x00")
        self.assertTrue(any(p == peer and d[:2] == b"\x00\x05"
                            for p, d in sock.sent))
        self.assertEqual(server.transfer, None)

    def test_rejects_write_request(self):
        server, sock, log = self._make_server()
        peer = ("192.168.2.10", 2000)
        server.handle_datagram(peer, b"\x00\x02ATA.cnf.xml\x00octet\x00")
        self.assertTrue(any(p == peer and d[:2] == b"\x00\x05"
                            and d[2:4] == b"\x00\x04" for p, d in sock.sent))

    def test_takeover_replaces_same_client_request(self):
        server, sock, log = self._make_server()
        peer = ("192.168.2.10", 2000)
        server.handle_datagram(peer, b"\x00\x01ATA.cnf.xml\x00octet\x00")
        requests_before = server.requests
        server.handle_datagram(peer, b"\x00\x01atadefault.cfg\x00octet\x00")
        self.assertGreaterEqual(server.requests, requests_before + 1)
        self.assertIsNotNone(server.transfer)
        self.assertEqual(server.transfer["file"], "atadefault.cfg")
        self.assertTrue(any(line.startswith("abandon peer=")
                            for line in log.lines))

    def test_takeover_ignores_client_source_port(self):
        server, sock, log = self._make_server()
        peer = ("192.168.2.10", 2000)
        other = ("192.168.2.10", 2001)
        server.handle_datagram(peer, b"\x00\x01ATA.cnf.xml\x00octet\x00")
        requests_before = server.requests
        server.handle_datagram(other, b"\x00\x01atadefault.cfg\x00octet\x00")
        self.assertGreaterEqual(server.requests, requests_before + 1)
        self.assertIsNotNone(server.transfer)
        self.assertEqual(server.transfer["file"], "atadefault.cfg")
        self.assertTrue(any(line.startswith("abandon peer=")
                            for line in log.lines))

    def test_unknown_network_rejected_before_takeover(self):
        server, sock, log = self._make_server()
        peer = ("192.168.2.10", 2000)
        server.handle_datagram(peer, b"\x00\x01ATA.cnf.xml\x00octet\x00")
        other = ("192.168.2.99", 2000)
        server.handle_datagram(other, b"\x00\x01ATA.cnf.xml\x00octet\x00")
        self.assertTrue(any(p == other and d[:2] == b"\x00\x05"
                            for p, d in sock.sent))
        self.assertIsNotNone(server.transfer)
        self.assertEqual(server.transfer["file"], "ATA.cnf.xml")
        self.assertTrue(any("access violation" in line for line in log.lines))

    def test_dry_run_does_not_send(self):
        server, sock, log = self._make_server()
        self.assertEqual(sock.sent, [])
        self.assertEqual(server.transfer, None)


if __name__ == "__main__":
    unittest.main()