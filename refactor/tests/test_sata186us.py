"""Offline and loopback-only tests for ATA image and protocol helpers."""

import contextlib
import hashlib
import io
import os
from pathlib import Path
import socket
import struct
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from refactor import sata186us


ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_DIR = Path(
    os.environ.get("ATA186_TEST_ARTIFACT_DIR", ROOT / "vendor")).resolve()
ATA_ZUP = ARTIFACT_DIR / "ATA030100SIP040211A.zup"
TRANS_ZUP = ARTIFACT_DIR / "transition.zup"
ATA_SHA256 = "b8597657928905aea66924118889f0883bd38c0804ddf880e3be2c33ccf62eb5"


class CommandTest(unittest.TestCase):
    def test_default_command_is_offline(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(sata186us.main(["sata186us"]), 0)
        self.assertIn("DRY RUN", out.getvalue())

    def test_invalid_argument_does_not_echo_its_value(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit):
            sata186us.parse_options([
                "hostile\nprogram", "--password=SensitivePayloadData123"])
        self.assertIn("invalid arguments", err.getvalue())
        self.assertIn("usage: sata186us.py", err.getvalue())
        self.assertNotIn("hostile", err.getvalue())
        self.assertNotIn("SensitivePayloadData123", err.getvalue())

    @unittest.skipUnless(ATA_ZUP.exists(), "needs ATA .zup")
    def test_inspect_is_offline_and_reports_verified_metadata(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(sata186us.main(["sata186us", "--inspect", str(ATA_ZUP)]), 0)
        self.assertIn(f"sha256={ATA_SHA256}", out.getvalue())
        self.assertIn("platform=0x00000301", out.getvalue())
        self.assertIn("version=0x0301", out.getvalue())


class ImageTest(unittest.TestCase):
    @unittest.skipUnless(ATA_ZUP.exists(), "needs ATA .zup")
    def test_known_sip_image_header_and_hash(self):
        raw = ATA_ZUP.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), ATA_SHA256)
        info = sata186us.parse_image_header(raw)
        self.assertEqual((info.base_type, info.name, info.platform, info.proto, info.version),
                         (0, "00000000", 0x301, 0x400, 0x301))
        store = sata186us.make_block_store(raw, info)
        self.assertEqual(store.total, 319135)
        self.assertEqual(len(store.sums), 312)
        self.assertEqual(sata186us.build_hello(store).hex(), "000001850004de9f00000400")
        self.assertEqual(sata186us.build_block(store, 0)[:4].hex(), "00021f8f")

    @unittest.skipUnless(ATA_ZUP.exists(), "needs ATA .zup")
    def test_pinned_target_requires_exact_hash_metadata_size_and_blocks(self):
        digest, info, store = sata186us.inspect_pinned_target(str(ATA_ZUP))
        self.assertEqual(digest, sata186us.PINNED_TARGET_SHA256)
        self.assertEqual((info.platform, info.proto, info.version),
                         (0x301, 0x400, 0x301))
        self.assertEqual((store.total, len(store.sums)), (319135, 312))

    def test_image_inspection_rejects_symlinks_and_non_regular_files(self):
        with tempfile.TemporaryDirectory() as directory:
            regular = Path(directory) / "regular.zup"
            regular.write_bytes(b"not-firmware")
            symlink = Path(directory) / "symlink.zup"
            symlink.symlink_to(regular)
            with self.assertRaisesRegex(ValueError, "cannot open"):
                sata186us.inspect_image(str(symlink))
            with self.assertRaisesRegex(ValueError, "bounded regular file"):
                sata186us.inspect_image(directory)
            fifo = Path(directory) / "firmware.fifo"
            os.mkfifo(fifo, 0o600)
            with self.assertRaisesRegex(ValueError, "bounded regular file"):
                sata186us.inspect_image(str(fifo))

    def test_bad_envelope_is_rejected(self):
        with self.assertRaises(ValueError):
            sata186us.check_image(b"+kxz\x00\x00\x00\x01" + b"\x00" * 12)

    def test_empty_image_name_is_rejected(self):
        with self.assertRaises(ValueError):
            sata186us.parse_image_header(b"kup1" + b"\x00" * 20)

    @unittest.skipUnless(TRANS_ZUP.exists(), "needs transition.zup")
    def test_transition_header_is_v2(self):
        info = sata186us.parse_image_header(TRANS_ZUP.read_bytes())
        self.assertEqual(sata186us.version_str(info.platform, info.proto, info.version),
                         "ata186.itsp2.v2.0")


class WireTest(unittest.TestCase):
    class FakeSocket:
        def __init__(self, packets, on_send=None):
            self.packets = iter(packets)
            self.sent = []
            self.on_send = on_send

        def recvfrom(self, _size):
            return next(self.packets)

        def sendto(self, packet, address):
            self.sent.append((packet, address))
            if self.on_send is not None:
                self.on_send(self)
            return len(packet)

    @staticmethod
    def data_request(index, size=sata186us.BLOCK_SIZE):
        body = struct.pack(">IHH", 0, index, size)
        return struct.pack(">I", sata186us.cksum(body)) + body

    def test_capture_returns_safe_metadata_without_a_response_path(self):
        packet = sata186us.build_kbox_request(0x301, 0x400, 0x301, 0,
                                               "00000000", (123, 456, 789))

        class CaptureSocket:
            def recvfrom(self, _size):
                return packet, ("127.0.0.1", 8000)

        log = io.StringIO()
        capture_socket = CaptureSocket()
        with patch.object(sata186us.select, "select", return_value=((capture_socket,), (), ())):
            metadata = sata186us.capture_kbox_metadata(capture_socket, "127.0.0.1", 1,
                                                        sata186us.Logger(log))
        self.assertIsNotNone(metadata)
        assert metadata is not None
        self.assertEqual((metadata.name, metadata.base_type, metadata.platform,
                          metadata.proto, metadata.version),
                         ("00000000", 0, 0x301, 0x400, 0x301))
        self.assertNotIn("123", log.getvalue())
        self.assertNotIn("456", log.getvalue())
        self.assertNotIn("789", log.getvalue())

    def test_capture_refuses_unusable_request_name(self):
        packet = sata186us.build_kbox_request(0x301, 0x400, 0x301, 0,
                                               "name-is-too-long", (0, 0, 0))
        self.assertIsNone(sata186us.capture_request_metadata(packet))

    def test_parser_rejects_trailing_bytes(self):
        packet = sata186us.build_kbox_request(0x301, 0x400, 0x304, 0,
                                               "00000000", (0, 0, 0))
        padded = packet + b"legacy-padding"
        self.assertIsNone(sata186us.parse_kbox_request(padded))
        self.assertEqual(sata186us.parse_legacy_kbox_request(padded),
                         sata186us.parse_kbox_request(packet))

    def test_data_parser_matches_vintage_checksum_size_and_padding_rules(self):
        hello_body = struct.pack(">IHH", 0x12345678, 99, 0)
        hello = struct.pack(">I", sata186us.cksum(hello_body)) + hello_body
        self.assertIsNone(sata186us.parse_data_request(hello + b"legacy-padding"))

        block_body = struct.pack(">IHH", 0x12345678, 311, sata186us.BLOCK_SIZE)
        block = struct.pack(">I", sata186us.cksum(block_body)) + block_body
        self.assertEqual(sata186us.parse_data_request(block), 311)
        with self.assertRaisesRegex(ValueError, "checksum"):
            sata186us.parse_data_request(b"\0\0\0\0" + block_body)
        wrong_size_body = struct.pack(">IHH", 0, 0, 512)
        with self.assertRaisesRegex(ValueError, "block size"):
            sata186us.parse_data_request(
                struct.pack(">I", sata186us.cksum(wrong_size_body))
                + wrong_size_body)

    def test_server_accepts_legacy_padding_and_source_port_changes(self):
        stop = threading.Event()
        selection = sata186us.build_kbox_request(
            0x301, 0x9999, 0xffff, 0, "different-name", (0, 0, 0))
        command = self.FakeSocket(((selection + b"padding", ("127.0.0.1", 1000)),))
        hello = self.data_request(99, 0)
        block = self.data_request(0)

        def stop_after_complete(sock):
            if len(sock.sent) == 2:
                stop.set()

        data = self.FakeSocket((
            (hello + b"padding", ("127.0.0.1", 2000)),
            (block, ("127.0.0.1", 2001)),
            (block, ("127.0.0.1", 2000)),
        ), stop_after_complete)
        info = sata186us.ImageInfo(0, "00000000", 0x301, 0x400, 0x301)
        store = sata186us.BlockStore(b"x" * sata186us.BLOCK_SIZE, 1, [120])
        ready = iter((command, data, data, data))
        with patch.object(sata186us.select, "select",
                          side_effect=lambda *_args: ((next(ready),), (), ())):
            result = sata186us.serve_firmware(
                command, data, info, store, "10.0.2.15", 8500,
                "127.0.0.1", 1, sata186us.Logger(io.StringIO()), stop)
        self.assertTrue(result.complete)
        self.assertEqual((result.command_requests, result.command_responses), (1, 1))
        self.assertEqual((result.data_requests, result.data_responses), (2, 2))
        self.assertEqual(result.rejected_requests, 0)
        self.assertEqual(data.sent[0][0], sata186us.build_hello(store))
        self.assertEqual(data.sent[1][0], sata186us.build_block(store, 0))

    def test_wrong_source_is_ignored_until_the_expected_peer_requests(self):
        stop = threading.Event()
        selection = sata186us.build_kbox_request(
            0x301, 0x400, 0x304, 0, "00000000", (0, 0, 0))

        def stop_after_response(_sock):
            stop.set()

        command = self.FakeSocket((
            (selection, ("192.0.2.1", 1000)),
            (selection, ("127.0.0.1", 1000)),
        ), stop_after_response)
        data = self.FakeSocket(())
        info = sata186us.ImageInfo(0, "00000000", 0x301, 0x400, 0x301)
        store = sata186us.BlockStore(b"x" * sata186us.BLOCK_SIZE, 1, [120])
        ready = iter((command, command))
        with patch.object(sata186us.select, "select",
                          side_effect=lambda *_args: ((next(ready),), (), ())):
            result = sata186us.serve_firmware(
                command, data, info, store, "10.0.2.15", 8500,
                "127.0.0.1", 1, sata186us.Logger(io.StringIO()), stop)
        self.assertEqual((result.command_requests, result.command_responses), (1, 1))
        self.assertEqual(result.rejected_requests, 1)

    def test_empty_oversized_and_wrong_source_datagrams_are_rejected(self):
        stop = threading.Event()
        selection = sata186us.build_kbox_request(
            0x301, 0x400, 0x304, 0, "00000000", (0, 0, 0))

        def stop_after_response(_sock):
            stop.set()

        command = self.FakeSocket((
            (b"", ("127.0.0.1", 1000)),
            (b"x" * (sata186us.MAX_SERVER_DATAGRAM_BYTES + 1),
             ("127.0.0.1", 1000)),
            (selection, ("192.0.2.1", 1000)),
            (selection, ("127.0.0.1", 1000)),
        ), stop_after_response)
        data = self.FakeSocket(())
        info = sata186us.ImageInfo(0, "00000000", 0x301, 0x400, 0x301)
        store = sata186us.BlockStore(b"x" * sata186us.BLOCK_SIZE, 1, [120])
        with patch.object(sata186us.select, "select",
                          return_value=((command,), (), ())):
            result = sata186us.serve_firmware(
                command, data, info, store, "10.0.2.15", 8500,
                "127.0.0.1", 1, sata186us.Logger(io.StringIO()), stop)
        self.assertEqual(result.rejected_requests, 3)
        self.assertEqual((result.command_requests, result.command_responses), (1, 1))
        self.assertEqual(len(command.sent), 1)

    def test_invalid_requests_do_not_exhaust_a_fixed_request_budget(self):
        stop = threading.Event()
        selection = sata186us.build_kbox_request(
            0x301, 0x400, 0x304, 0, "00000000", (0, 0, 0))

        def stop_after_response(_sock):
            stop.set()

        packets = [(b"not-kbox", ("127.0.0.1", 1000)) for _ in range(1025)]
        packets.append((selection, ("127.0.0.1", 2000)))
        command = self.FakeSocket(packets, stop_after_response)
        data = self.FakeSocket(())
        info = sata186us.ImageInfo(0, "00000000", 0x301, 0x400, 0x301)
        store = sata186us.BlockStore(b"x" * sata186us.BLOCK_SIZE, 1, [120])
        with patch.object(sata186us.select, "select",
                          return_value=((command,), (), ())), \
                patch.object(sata186us.time, "monotonic", return_value=0.0):
            result = sata186us.serve_firmware(
                command, data, info, store, "10.0.2.15", 8500,
                "127.0.0.1", 1, sata186us.Logger(io.StringIO()), stop)
        self.assertEqual(result.command_requests, 1026)
        self.assertEqual(result.invalid_requests, 1025)
        self.assertEqual(result.command_responses, 1)

    def test_command_source_port_can_change_for_the_expected_peer(self):
        stop = threading.Event()
        selection = sata186us.build_kbox_request(
            0x301, 0x400, 0x304, 0, "00000000", (0, 0, 0))
        command = self.FakeSocket((
            (selection, ("127.0.0.1", 1000)),
            (selection, ("127.0.0.1", 1001)),
        ))

        def stop_after_data(_sock):
            stop.set()

        data = self.FakeSocket(
            ((self.data_request(0), ("127.0.0.1", 2000)),), stop_after_data)
        info = sata186us.ImageInfo(0, "00000000", 0x301, 0x400, 0x301)
        store = sata186us.BlockStore(b"x" * sata186us.BLOCK_SIZE, 1, [120])
        ready = iter((command, command, data))
        with patch.object(sata186us.select, "select",
                          side_effect=lambda *_args: ((next(ready),), (), ())):
            result = sata186us.serve_firmware(
                command, data, info, store, "10.0.2.15", 8500,
                "127.0.0.1", 1, sata186us.Logger(io.StringIO()), stop)
        self.assertEqual((result.command_requests, result.command_responses), (2, 2))
        self.assertEqual((result.data_requests, result.data_responses), (1, 1))
        self.assertEqual(result.rejected_requests, 0)

    def test_server_answers_retransmissions_after_all_blocks_were_served(self):
        stop = threading.Event()
        selection = sata186us.build_kbox_request(
            0x301, 0x400, 0x304, 0, "00000000", (0, 0, 0))
        command = self.FakeSocket(((selection, ("127.0.0.1", 1000)),))

        def stop_after_retransmission(sock):
            if len(sock.sent) == 2:
                stop.set()

        block = self.data_request(0)
        data = self.FakeSocket((
            (block, ("127.0.0.1", 2000)),
            (block, ("127.0.0.1", 2000)),
        ), stop_after_retransmission)
        info = sata186us.ImageInfo(0, "00000000", 0x301, 0x400, 0x301)
        store = sata186us.BlockStore(b"x" * sata186us.BLOCK_SIZE, 1, [120])
        ready = iter((command, data, data))
        with patch.object(sata186us.select, "select",
                          side_effect=lambda *_args: ((next(ready),), (), ())):
            result = sata186us.serve_firmware(
                command, data, info, store, "10.0.2.15", 8500,
                "127.0.0.1", 1, sata186us.Logger(io.StringIO()), stop)
        self.assertTrue(result.complete)
        self.assertEqual((result.data_requests, result.data_responses), (2, 2))
        self.assertEqual(len(result.unique_blocks), 1)

    def test_failed_final_send_is_not_reported_as_complete(self):
        selection = sata186us.build_kbox_request(
            0x301, 0x400, 0x304, 0, "00000000", (0, 0, 0))
        command = self.FakeSocket(((selection, ("127.0.0.1", 1000)),))
        data = self.FakeSocket(((self.data_request(0), ("127.0.0.1", 2000)),))
        original_send = data.sendto

        def fail_data_send(packet, address):
            original_send(packet, address)
            raise OSError("synthetic send failure")

        data.sendto = fail_data_send
        info = sata186us.ImageInfo(0, "00000000", 0x301, 0x400, 0x301)
        store = sata186us.BlockStore(b"x" * sata186us.BLOCK_SIZE, 1, [120])
        log = io.StringIO()
        ready = iter((command, data))
        with patch.object(sata186us.select, "select",
                          side_effect=lambda *_args: ((next(ready),), (), ())), \
                self.assertRaisesRegex(OSError, "synthetic send failure"):
            sata186us.serve_firmware(
                command, data, info, store, "10.0.2.15", 8500,
                "127.0.0.1", 1, sata186us.Logger(log))
        self.assertNotIn("complete", log.getvalue())

    def test_safety_check_fails_before_a_response(self):
        selection = sata186us.build_kbox_request(
            0x301, 0x400, 0x304, 0, "00000000", (0, 0, 0))
        command = self.FakeSocket(((selection, ("127.0.0.1", 1000)),))
        data = self.FakeSocket(())
        info = sata186us.ImageInfo(0, "00000000", 0x301, 0x400, 0x301)
        store = sata186us.BlockStore(b"x" * sata186us.BLOCK_SIZE, 1, [120])
        with patch.object(sata186us.select, "select",
                          return_value=((command,), (), ())), \
                self.assertRaisesRegex(OSError, "safety check"):
            sata186us.serve_firmware(
                command, data, info, store, "10.0.2.15", 8500,
                "127.0.0.1", 1, sata186us.Logger(io.StringIO()),
                safety_check=lambda: False)
        self.assertEqual(command.sent, [])

    def test_bound_socket_is_nonblocking_and_prequeue_is_drained(self):
        with sata186us.bind_udp("127.0.0.1", 0) as receiver, \
                socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            self.assertFalse(receiver.getblocking())
            sender.sendto(b"stale", receiver.getsockname())
            readable, _, _ = sata186us.select.select((receiver,), (), (), 1)
            self.assertEqual(readable, [receiver])
            self.assertEqual(sata186us.drain_udp(receiver), 1)
            self.assertEqual(sata186us.drain_udp(receiver), 0)

    @unittest.skipUnless(ATA_ZUP.exists(), "needs ATA .zup")
    def test_python_server_delivers_the_complete_qemu_reference_stream(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(sata186us.run_loopback_qualification(
                str(ATA_ZUP), sata186us.Logger(out)), 0)
        output = out.getvalue()
        self.assertIn("ATA_SIM_COMPLETE blocks=312 bytes=319135", output)
        self.assertIn(
            "PYTHON_SERVER_QUALIFIED command=1/1:42/144 "
            "data=313/313:3756/321996 blocks=312 payload_bytes=319135 "
            f"data_wire_sha256={sata186us.PINNED_TARGET_DATA_WIRE_SHA256}",
            output)

    def test_capture_reports_payload_free_rejection_counts(self):
        class CaptureSocket:
            def __init__(self):
                self.packets = iter((
                    (b"unrelated", ("192.0.2.1", 8000)),
                    (b"not-kbox", ("127.0.0.1", 8000)),
                    (b"kbox" + b"x" * sata186us.MAX_KBOX_PACKET_BYTES,
                     ("127.0.0.1", 8000)),
                ))

            def recvfrom(self, _size):
                return next(self.packets)

        capture_socket = CaptureSocket()
        log = io.StringIO()
        with patch.object(sata186us.select, "select",
                          return_value=((capture_socket,), (), ())), \
                patch.object(sata186us.time, "monotonic",
                             side_effect=(0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                                          0.0, 1.0)):
            self.assertIsNone(sata186us.capture_kbox_metadata(
                capture_socket, "127.0.0.1", 1, sata186us.Logger(log)))
        output = log.getvalue()
        self.assertIn("datagrams=3, expected_peer=2, other_peer=1, oversized=1, "
                      "invalid=1, not_kbox=1, version=0, framing=0, checksum=0, "
                      "metadata=0, packet_limit_reached=0", output)
        self.assertNotIn("unrelated", output)
        self.assertNotIn("not-kbox", output)

    def test_capture_reports_fixed_parser_stage_counts(self):
        valid = sata186us.build_kbox_request(0x301, 0x400, 0x301, 0,
                                              "00000000", (0, 0, 0))
        wrong_version = valid[:4] + struct.pack(">I", 2) + valid[8:]
        bad_framing = valid + b"\x00"
        bad_checksum = valid[:12] + b"\x00\x00\x00\x00" + valid[16:]
        bad_metadata = sata186us.build_kbox_request(
            0x301, 0x400, 0x301, 0, "name-is-too-long", (0, 0, 0))

        class CaptureSocket:
            def __init__(self):
                self.packets = iter((wrong_version, bad_framing, bad_checksum,
                                     bad_metadata))

            def recvfrom(self, _size):
                return next(self.packets), ("127.0.0.1", 8000)

        capture_socket = CaptureSocket()
        log = io.StringIO()
        with patch.object(sata186us.select, "select",
                          return_value=((capture_socket,), (), ())), \
                patch.object(sata186us.time, "monotonic",
                             side_effect=(0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                                          0.0, 0.0, 0.0, 1.0)):
            self.assertIsNone(sata186us.capture_kbox_metadata(
                capture_socket, "127.0.0.1", 1, sata186us.Logger(log)))
        self.assertIn("invalid=4, not_kbox=0, version=1, framing=1, checksum=1, "
                      "metadata=1, packet_limit_reached=0", log.getvalue())

if __name__ == "__main__":
    unittest.main()
