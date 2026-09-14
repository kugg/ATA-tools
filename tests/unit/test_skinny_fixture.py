"""Offline protocol checks for the local SCCP/ATA186 fixture."""

import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "ata_skinny_fixture_test_module", ROOT / "telephony/skinny_fixture.py"
)
assert SPEC is not None and SPEC.loader is not None
FIXTURE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = FIXTURE
SPEC.loader.exec_module(FIXTURE)


class SkinnyFixtureTests(unittest.TestCase):
    def decode_one(self, wire):
        frames = FIXTURE.FrameDecoder().feed(wire)
        self.assertEqual(len(frames), 1)
        return frames[0]

    def test_wire_header_is_little_endian_and_length_includes_message_id(self):
        wire = FIXTURE.encode_frame(FIXTURE.Frame(0x81, b"abc"))
        self.assertEqual(wire[:4], b"\x07\x00\x00\x00")
        self.assertEqual(self.decode_one(wire), FIXTURE.Frame(0x81, b"abc"))

    def test_fragmented_and_coalesced_register_and_keepalive(self):
        endpoint = FIXTURE.FixtureEndpoint()
        register = FIXTURE.encode_frame(
            FIXTURE.Frame(FIXTURE.REGISTER_MESSAGE, FIXTURE.build_register_body("ATA186-TEST"))
        )
        self.assertEqual(endpoint.receive(register[:7]), b"")
        reply = endpoint.receive(register[7:])
        registration_ack = self.decode_one(reply)
        self.assertEqual(registration_ack.message_id, FIXTURE.REGISTER_ACK_MESSAGE)
        self.assertTrue(endpoint.session.registered)

        keepalive = FIXTURE.encode_frame(FIXTURE.Frame(FIXTURE.KEEP_ALIVE_MESSAGE))
        replies = FIXTURE.FrameDecoder().feed(endpoint.receive(keepalive + keepalive))
        self.assertEqual(
            [frame.message_id for frame in replies],
            [FIXTURE.KEEP_ALIVE_ACK_MESSAGE, FIXTURE.KEEP_ALIVE_ACK_MESSAGE],
        )

    def test_ringer_is_available_only_after_a_valid_ata186_registration(self):
        endpoint = FIXTURE.FixtureEndpoint()
        with self.assertRaisesRegex(FIXTURE.ProtocolError, "unregistered"):
            endpoint.ringer(FIXTURE.RINGER_INSIDE)
        self.assertTrue(endpoint.failed)
        endpoint.reset()

        endpoint.receive(
            FIXTURE.encode_frame(
                FIXTURE.Frame(FIXTURE.REGISTER_MESSAGE, FIXTURE.build_register_body("ATA186-TEST"))
            )
        )
        ringer = self.decode_one(endpoint.ringer(FIXTURE.RINGER_INSIDE))
        self.assertEqual(ringer.message_id, FIXTURE.SET_RINGER_MESSAGE)
        self.assertEqual(ringer.body[:4], b"\x02\x00\x00\x00")

    def test_wrong_identity_or_device_type_fails_without_registering(self):
        for body in (
            FIXTURE.build_register_body("OTHER-ATA"),
            FIXTURE.build_register_body("ATA186-TEST", device_type=99),
        ):
            with self.subTest(body=body):
                endpoint = FIXTURE.FixtureEndpoint()
                with self.assertRaisesRegex(FIXTURE.ProtocolError, "unexpected SCCP"):
                    endpoint.receive(
                        FIXTURE.encode_frame(FIXTURE.Frame(FIXTURE.REGISTER_MESSAGE, body))
                    )
                self.assertFalse(endpoint.session.registered)

    def test_malformed_lengths_and_input_floods_fail_before_unbounded_buffering(self):
        decoder = FIXTURE.FrameDecoder()
        oversized = (FIXTURE.MAX_BODY_BYTES + 5).to_bytes(4, "little") + b"\0" * 4
        with self.assertRaisesRegex(FIXTURE.ProtocolError, "frame length"):
            decoder.feed(oversized)
        self.assertTrue(decoder.failed)
        self.assertEqual(decoder.buffered_bytes, 0)
        with self.assertRaisesRegex(FIXTURE.ProtocolError, "reset required"):
            decoder.feed(b"")
        with self.assertRaisesRegex(FIXTURE.ProtocolError, "buffer limit"):
            FIXTURE.FrameDecoder().feed(b"x" * (FIXTURE.MAX_BUFFER_BYTES + 1))

    def test_error_locks_endpoint_until_explicit_reset(self):
        endpoint = FIXTURE.FixtureEndpoint()
        malformed = (FIXTURE.MAX_BODY_BYTES + 5).to_bytes(4, "little") + b"\0" * 4
        with self.assertRaisesRegex(FIXTURE.ProtocolError, "frame length"):
            endpoint.receive(malformed)
        self.assertTrue(endpoint.failed)
        with self.assertRaisesRegex(FIXTURE.ProtocolError, "reset required"):
            endpoint.receive(
                FIXTURE.encode_frame(
                    FIXTURE.Frame(FIXTURE.REGISTER_MESSAGE, FIXTURE.build_register_body("ATA186-TEST"))
                )
            )
        endpoint.reset()
        self.assertFalse(endpoint.failed)
        self.assertTrue(
            endpoint.receive(
                FIXTURE.encode_frame(
                    FIXTURE.Frame(FIXTURE.REGISTER_MESSAGE, FIXTURE.build_register_body("ATA186-TEST"))
                )
            )
        )

    def test_complete_seventeenth_frame_and_end_of_stream_truncation_fail_closed(self):
        keepalive = FIXTURE.encode_frame(FIXTURE.Frame(FIXTURE.KEEP_ALIVE_MESSAGE))
        decoder = FIXTURE.FrameDecoder()
        with self.assertRaisesRegex(FIXTURE.ProtocolError, "too many"):
            decoder.feed(keepalive * (FIXTURE.MAX_FRAMES_PER_FEED + 1))
        self.assertTrue(decoder.failed)

        decoder = FIXTURE.FrameDecoder()
        decoder.feed(keepalive[:7])
        with self.assertRaisesRegex(FIXTURE.ProtocolError, "truncated"):
            decoder.finish()
        self.assertTrue(decoder.failed)
        self.assertEqual(decoder.buffered_bytes, 0)

        decoder = FIXTURE.FrameDecoder()
        self.assertEqual(len(decoder.feed(keepalive * 15 + keepalive[:7])), 15)
        with self.assertRaisesRegex(FIXTURE.ProtocolError, "truncated"):
            decoder.finish()

    def test_wire_length_boundaries_fail_before_parsing_or_allocation(self):
        for length in (0, FIXTURE.MAX_BODY_BYTES + 5, 0xFFFFFFFF):
            with self.subTest(length=length):
                decoder = FIXTURE.FrameDecoder()
                with self.assertRaisesRegex(FIXTURE.ProtocolError, "frame length"):
                    decoder.feed(length.to_bytes(4, "little") + b"\0" * 4)
                self.assertTrue(decoder.failed)

    def test_maximum_body_size_is_accepted(self):
        frame = FIXTURE.Frame(FIXTURE.REGISTER_MESSAGE, b"x" * FIXTURE.MAX_BODY_BYTES)
        self.assertEqual(self.decode_one(FIXTURE.encode_frame(frame)), frame)

    def test_register_fields_have_fixed_safe_bounds(self):
        with self.assertRaisesRegex(FIXTURE.ProtocolError, "device name"):
            FIXTURE.build_register_body("A" * 17)
        with self.assertRaisesRegex(FIXTURE.ProtocolError, "device name"):
            FIXTURE.build_register_body("ATA\n186")
        with self.assertRaisesRegex(FIXTURE.ProtocolError, "device name"):
            FIXTURE.build_register_body("ATA 186")
        with self.assertRaisesRegex(FIXTURE.ProtocolError, "device name"):
            FIXTURE.build_register_body("ATA186-\u00dc")
        with self.assertRaisesRegex(FIXTURE.ProtocolError, "protocol version"):
            FIXTURE.build_register_body("ATA186-TEST", protocol_version=256)
        with self.assertRaisesRegex(FIXTURE.ProtocolError, "device type"):
            FIXTURE.build_register_body("ATA186-TEST", device_type="12")
        with self.assertRaisesRegex(FIXTURE.ProtocolError, "device name"):
            FIXTURE.FixtureSession(expected_device_name="")

    def test_binary_identity_padding_is_rejected_before_registration(self):
        body = bytearray(FIXTURE.build_register_body("ATA186-TEST"))
        body[12:16] = b"\0BAD"
        endpoint = FIXTURE.FixtureEndpoint()
        with self.assertRaisesRegex(FIXTURE.ProtocolError, "register identity"):
            endpoint.receive(FIXTURE.encode_frame(FIXTURE.Frame(FIXTURE.REGISTER_MESSAGE, bytes(body))))
        self.assertFalse(endpoint.session.registered)
        self.assertTrue(endpoint.failed)
        with self.assertRaisesRegex(FIXTURE.ProtocolError, "reset required"):
            endpoint.ringer(FIXTURE.RINGER_INSIDE)

    def test_non_ascii_wire_identity_is_rejected_before_registration(self):
        body = bytearray(FIXTURE.build_register_body("ATA186-TEST"))
        body[:16] = b"ATA186-\xff".ljust(16, b"\0")
        endpoint = FIXTURE.FixtureEndpoint()
        with self.assertRaisesRegex(FIXTURE.ProtocolError, "register identity"):
            endpoint.receive(FIXTURE.encode_frame(FIXTURE.Frame(FIXTURE.REGISTER_MESSAGE, bytes(body))))
        self.assertFalse(endpoint.session.registered)
        self.assertTrue(endpoint.failed)

    def test_coalesced_error_locks_without_applying_prior_or_later_frames(self):
        endpoint = FIXTURE.FixtureEndpoint()
        register = FIXTURE.encode_frame(
            FIXTURE.Frame(FIXTURE.REGISTER_MESSAGE, FIXTURE.build_register_body("ATA186-TEST"))
        )
        malformed = (FIXTURE.MAX_BODY_BYTES + 5).to_bytes(4, "little") + b"\0" * 4
        keepalive = FIXTURE.encode_frame(FIXTURE.Frame(FIXTURE.KEEP_ALIVE_MESSAGE))
        with self.assertRaisesRegex(FIXTURE.ProtocolError, "frame length"):
            endpoint.receive(register + malformed + keepalive)
        self.assertFalse(endpoint.session.registered)
        self.assertTrue(endpoint.session.failed)
        self.assertTrue(endpoint.decoder.failed)
        self.assertEqual(endpoint.decoder.buffered_bytes, 0)

    def test_error_state_is_isolated_to_its_own_endpoint(self):
        failed = FIXTURE.FixtureEndpoint()
        healthy = FIXTURE.FixtureEndpoint()
        malformed = (FIXTURE.MAX_BODY_BYTES + 5).to_bytes(4, "little") + b"\0" * 4
        with self.assertRaises(FIXTURE.ProtocolError):
            failed.receive(malformed)
        reply = healthy.receive(
            FIXTURE.encode_frame(
                FIXTURE.Frame(FIXTURE.REGISTER_MESSAGE, FIXTURE.build_register_body("ATA186-TEST"))
            )
        )
        self.assertTrue(failed.failed)
        self.assertTrue(healthy.session.registered)
        self.assertEqual(self.decode_one(reply).message_id, FIXTURE.REGISTER_ACK_MESSAGE)

    def test_exact_expected_identity_can_register_and_enable_actions(self):
        endpoint = FIXTURE.FixtureEndpoint(FIXTURE.FixtureSession(expected_device_name="TEST1234"))
        reply = endpoint.receive(
            FIXTURE.encode_frame(
                FIXTURE.Frame(FIXTURE.REGISTER_MESSAGE, FIXTURE.build_register_body("TEST1234"))
            )
        )
        self.assertEqual(self.decode_one(reply).message_id, FIXTURE.REGISTER_ACK_MESSAGE)
        self.assertEqual(
            self.decode_one(endpoint.ringer(FIXTURE.RINGER_OFF)).message_id,
            FIXTURE.SET_RINGER_MESSAGE,
        )

    def test_direct_api_paths_preserve_input_bounds(self):
        with self.assertRaisesRegex(FIXTURE.ProtocolError, "invalid frame body"):
            FIXTURE.FixtureSession().receive(
                FIXTURE.Frame(FIXTURE.REGISTER_MESSAGE, b"x" * (FIXTURE.MAX_BODY_BYTES + 1))
            )
        with self.assertRaisesRegex(FIXTURE.ProtocolError, "register message length"):
            FIXTURE.parse_register_body(b"x" * (FIXTURE.MAX_BODY_BYTES + 1))
        with self.assertRaisesRegex(FIXTURE.ProtocolError, "ringer mode"):
            FIXTURE.build_ringer_body(True)


if __name__ == "__main__":
    unittest.main()
