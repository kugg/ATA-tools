"""Offline validation for the bounded RTP/PCMU external-media profile."""

import unittest

from telephony import rtp_external_media as rtp
from telephony.iax2_fixture import PCMU_SILENCE


class RtpExternalMediaTests(unittest.TestCase):
    def test_round_trip_uses_rtp_v2_pcmu_header(self):
        packet = rtp.RtpPacket(100, 0, 0x11111111, PCMU_SILENCE)
        wire = rtp.encode_rtp_packet(packet)
        self.assertEqual(wire[:2], b"\x80\x00")
        self.assertEqual(rtp.decode_rtp_packet(wire), packet)

    def test_rejects_extensions_payload_types_and_wrong_sized_packets(self):
        with self.assertRaisesRegex(rtp.ProtocolError, "version"):
            rtp.decode_rtp_packet(b"\x40\x00" + b"\0" * 170)
        with self.assertRaisesRegex(rtp.ProtocolError, "extensions"):
            rtp.decode_rtp_packet(b"\x90\x00" + b"\0" * 170)
        with self.assertRaisesRegex(rtp.ProtocolError, "payload type"):
            rtp.decode_rtp_packet(b"\x80\x08" + b"\0" * 170)
        with self.assertRaisesRegex(rtp.ProtocolError, "length"):
            rtp.decode_rtp_packet(b"\0" * 12)
        for length in (100, 250):
            with self.subTest(length=length):
                with self.assertRaisesRegex(rtp.ProtocolError, "length"):
                    rtp.decode_rtp_packet(b"\0" * length)

    def test_session_requires_ssrc_sequence_and_timestamp_then_locks_on_error(self):
        session = rtp.PcmuMediaSession(0x11111111, 0x22222222)
        first = rtp.encode_rtp_packet(rtp.RtpPacket(100, 0, 0x11111111, PCMU_SILENCE))
        self.assertEqual(session.receive(first).sequence, 100)
        self.assertEqual(session.build_outbound().sequence, 500)
        self.assertEqual(session.build_outbound().timestamp, 160)

        with self.assertRaisesRegex(rtp.ProtocolError, "sequence"):
            session.receive(rtp.encode_rtp_packet(rtp.RtpPacket(102, 160, 0x11111111, PCMU_SILENCE)))
        self.assertTrue(session.failed)
        with self.assertRaisesRegex(rtp.ProtocolError, "reset required"):
            session.build_outbound()
        session.reset()
        self.assertEqual(session.receive(first).timestamp, 0)

    def test_timestamp_regression_locks_the_session_until_explicit_reset(self):
        session = rtp.PcmuMediaSession(0x11111111, 0x22222222)
        first = rtp.encode_rtp_packet(rtp.RtpPacket(100, 0, 0x11111111, PCMU_SILENCE))
        session.receive(first)
        with self.assertRaisesRegex(rtp.ProtocolError, "timestamp"):
            session.receive(rtp.encode_rtp_packet(rtp.RtpPacket(101, 0, 0x11111111, PCMU_SILENCE)))
        self.assertTrue(session.failed)
        with self.assertRaisesRegex(rtp.ProtocolError, "reset required"):
            session.receive(first)
        session.reset()
        self.assertEqual(session.receive(first).timestamp, 0)

    def test_sequence_and_timestamp_wrap_without_accepting_a_wrong_ssrc(self):
        session = rtp.PcmuMediaSession(
            0x11111111,
            0x22222222,
            initial_inbound_sequence=0xFFFF,
            initial_outbound_sequence=0xFFFF,
            initial_timestamp=0xFFFFFF60,
        )
        session.receive(
            rtp.encode_rtp_packet(rtp.RtpPacket(0xFFFF, 0xFFFFFF60, 0x11111111, PCMU_SILENCE))
        )
        self.assertEqual(session.build_outbound().sequence, 0xFFFF)
        self.assertEqual(session.build_outbound().sequence, 0)
        with self.assertRaisesRegex(rtp.ProtocolError, "SSRC"):
            session.receive(rtp.encode_rtp_packet(rtp.RtpPacket(0, 0, 0x33333333, PCMU_SILENCE)))


if __name__ == "__main__":
    unittest.main()
