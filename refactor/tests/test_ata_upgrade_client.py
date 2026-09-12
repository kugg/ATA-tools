"""Loopback/offline tests for the ATA firmware client simulator."""

import contextlib
import io
import hashlib
import os
import struct
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from refactor import ata_upgrade_client
from refactor import sata186us


class ClientSimulatorTest(unittest.TestCase):
    def test_default_is_inert(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(ata_upgrade_client.main(["ata_upgrade_client"]), 0)
        self.assertIn("DRY RUN", output.getvalue())

    def test_invalid_argument_does_not_echo_its_value(self):
        error = io.StringIO()
        with contextlib.redirect_stderr(error), self.assertRaises(SystemExit):
            ata_upgrade_client.parse_options([
                "ata_upgrade_client", "--password=SensitivePayloadData123"])
        self.assertIn("invalid arguments", error.getvalue())
        self.assertNotIn("SensitivePayloadData123", error.getvalue())

    def test_selection_response_validates_url_and_checksum(self):
        url = "udp: 10.0.2.15 8500 123"
        response = sata186us.build_kbox_response(url)
        ata_upgrade_client.validate_selection_response(response, url)
        corrupt = bytearray(response)
        corrupt[-1] = 1
        with self.assertRaises(ata_upgrade_client.ClientError):
            ata_upgrade_client.validate_selection_response(bytes(corrupt), url)

    def test_selection_response_accepts_legacy_reserved_bytes(self):
        url = "udp: 10.0.2.15 8500 123"
        response = bytearray(sata186us.build_kbox_response(url))
        response[8:12] = struct.pack(">I", 0xA5A5A5A5)
        ata_upgrade_client.validate_selection_response(bytes(response), url)

    def test_client_result_retains_payload_free_stream_identities(self):
        result = ata_upgrade_client.ClientResult(
            312, 319135, "a" * 64, "b" * 64, "c" * 64)
        self.assertEqual((result.blocks, result.payload_bytes), (312, 319135))
        self.assertEqual(result.payload_sha256, "a" * 64)
        self.assertEqual(result.selection_normalized_sha256, "b" * 64)
        self.assertEqual(result.data_wire_sha256, "c" * 64)
        self.assertEqual(
            hashlib.sha256(sata186us.build_kbox_response(
                "udp: 10.0.2.15 8500 123")).hexdigest(),
            "6beddb21fc08c6518a8f1f3375030c3d5a56b3171c5ee7cb29e686a2fd9282f0")

    def test_run_requires_image(self):
        error = io.StringIO()
        with contextlib.redirect_stderr(error):
            self.assertEqual(
                ata_upgrade_client.main(["ata_upgrade_client", "--run"]), 1)
        self.assertIn("requires --image", error.getvalue())

    def test_main_suppresses_internal_exception_details(self):
        error = io.StringIO()
        with patch.object(
                ata_upgrade_client, "run_client",
                side_effect=RuntimeError("SensitivePayloadData123")), \
                contextlib.redirect_stderr(error):
            self.assertEqual(ata_upgrade_client.main([
                "ata_upgrade_client", "--run", "--image", "image.zup"]), 1)
        self.assertIn("simulation failed", error.getvalue())
        self.assertNotIn("SensitivePayloadData123", error.getvalue())

    def test_request_rejects_expired_session_without_sending(self):
        sock = Mock()
        with patch.object(ata_upgrade_client.time, "monotonic", return_value=2.0):
            with self.assertRaises(ata_upgrade_client.ClientError):
                ata_upgrade_client._request(sock, b"request", ("127.0.0.1", 8000),
                                            128, 1.0)
        sock.sendto.assert_not_called()

    def test_request_reads_one_extra_byte_to_expose_trailing_data(self):
        sock = Mock()
        sock.gettimeout.return_value = 1
        sock.recvfrom.return_value = (b"response", ("127.0.0.1", 8000))
        with patch.object(ata_upgrade_client.time, "monotonic", return_value=0.0):
            self.assertEqual(ata_upgrade_client._request(
                sock, b"request", ("127.0.0.1", 8000), 128, 1.0), b"response")
        sock.recvfrom.assert_called_once_with(129)


if __name__ == "__main__":
    unittest.main()
