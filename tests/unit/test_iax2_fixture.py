"""Offline validation for the narrow IAX2 mini-frame media fixture."""

import unittest

from telephony import iax2_fixture as iax2


class Iax2MiniFixtureTests(unittest.TestCase):
    def test_round_trip_uses_the_rfc5456_four_octet_mini_header(self):
        frame = iax2.MiniFrame(101, 20, iax2.PCMU_SILENCE)
        wire = iax2.encode_mini_frame(frame)
        self.assertEqual(wire[:4], b"\x00e\x00\x14")
        self.assertEqual(iax2.decode_mini_frame(wire), frame)

    def test_rejects_full_meta_and_wrong_sized_frames(self):
        with self.assertRaisesRegex(iax2.ProtocolError, "full"):
            iax2.decode_mini_frame(b"\x80\x01\x00\x14" + iax2.PCMU_SILENCE)
        with self.assertRaisesRegex(iax2.ProtocolError, "source call"):
            iax2.decode_mini_frame(b"\x00\x00\x00\x14" + iax2.PCMU_SILENCE)
        with self.assertRaisesRegex(iax2.ProtocolError, "length"):
            iax2.decode_mini_frame(b"\x00" * 5)
        for length in (120, 200):
            with self.subTest(length=length):
                with self.assertRaisesRegex(iax2.ProtocolError, "length"):
                    iax2.decode_mini_frame(b"\x00" * length)
        with self.assertRaisesRegex(iax2.ProtocolError, "20ms"):
            iax2.encode_mini_frame(iax2.MiniFrame(1, 20, b"x"))

    def test_session_requires_call_and_timestamp_sequence_then_locks_on_error(self):
        session = iax2.MiniMediaSession(101, 202)
        first = iax2.encode_mini_frame(iax2.MiniFrame(101, 20, iax2.PCMU_SILENCE))
        self.assertEqual(session.receive(first).timestamp, 20)
        self.assertEqual(session.build_outbound().source_call_number, 202)
        self.assertEqual(session.build_outbound().timestamp, 40)

        with self.assertRaisesRegex(iax2.ProtocolError, "timestamp"):
            session.receive(iax2.encode_mini_frame(iax2.MiniFrame(101, 60, iax2.PCMU_SILENCE)))
        self.assertTrue(session.failed)
        with self.assertRaisesRegex(iax2.ProtocolError, "reset required"):
            session.build_outbound()
        session.reset()
        self.assertEqual(session.receive(first).timestamp, 20)

    def test_malformed_wire_locks_the_session_until_explicit_reset(self):
        session = iax2.MiniMediaSession(101, 202)
        valid = iax2.encode_mini_frame(iax2.MiniFrame(101, 20, iax2.PCMU_SILENCE))
        with self.assertRaisesRegex(iax2.ProtocolError, "length"):
            session.receive(valid[:-1])
        self.assertTrue(session.failed)
        with self.assertRaisesRegex(iax2.ProtocolError, "reset required"):
            session.receive(valid)
        session.reset()
        self.assertEqual(session.receive(valid).timestamp, 20)

    def test_session_requires_full_frame_resynchronization_before_timestamp_wrap(self):
        session = iax2.MiniMediaSession(101, 202, initial_timestamp=0x7FF8)
        last_mini = iax2.encode_mini_frame(iax2.MiniFrame(101, 0x7FF8, iax2.PCMU_SILENCE))
        session.receive(last_mini)
        with self.assertRaisesRegex(iax2.ProtocolError, "resynchronization"):
            session.receive(last_mini)
        self.assertTrue(session.failed)


if __name__ == "__main__":
    unittest.main()
