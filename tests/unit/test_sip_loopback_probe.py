"""Offline tests for the bounded loopback SIP UAC probe."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from telephony import sip_loopback_probe as probe  # noqa: E402


def register_message():
    return probe.parse_request(
        probe.build_request(
            "REGISTER", "sip:127.0.0.1:5060", ["Expires: 60"],
            "127.0.0.1", 15060, "cid-1", "1 REGISTER",
        )
    )


class ParseTest(unittest.TestCase):
    def test_parse_response(self):
        wire = b"SIP/2.0 200 OK\r\nCall-ID: c\r\nContent-Length: 0\r\n\r\n"
        status, headers, body = probe.parse_response(wire)
        self.assertEqual(status, "SIP/2.0 200 OK")
        self.assertEqual(headers["call-id"], "c")
        self.assertEqual(body, "")

    def test_parse_response_garbage(self):
        with self.assertRaises(probe.ProtocolError):
            probe.parse_response(b"BOGUS")

    def test_parse_request(self):
        method, uri, headers, body = register_message()
        self.assertEqual(method, "REGISTER")
        self.assertEqual(headers["call-id"], "cid-1")
        self.assertEqual(headers["cseq"], "1 REGISTER")
        self.assertEqual(body, "")

    def test_parse_request_bad(self):
        with self.assertRaises(probe.ProtocolError):
            probe.parse_request(b"no space")


class RequestBuildTest(unittest.TestCase):
    def test_register_well_formed(self):
        wire = probe.build_request(
            "REGISTER", "sip:127.0.0.1:5060", ["Expires: 60"],
            "127.0.0.1", 15060, "cid-1", "1 REGISTER",
        )
        text = wire.decode("utf-8")
        self.assertIn("Expires: 60", text)
        self.assertIn("Max-Forwards: 70", text)

    def test_invite_has_sdp(self):
        wire = probe.build_request(
            "INVITE", "sip:100@127.0.0.1:5060",
            ["Content-Type: application/sdp"],
            "127.0.0.1", 15060, "cid-1", "2 INVITE",
            body=probe.build_sdp("127.0.0.1", 16384),
        )
        method, uri, headers, body = probe.parse_request(wire)
        self.assertEqual(method, "INVITE")
        self.assertEqual(uri, "sip:100@127.0.0.1:5060")
        self.assertEqual(probe.parse_sdp_target(body), ("127.0.0.1", 16384))
        self.assertEqual(headers["content-type"], "application/sdp")


class SdpTest(unittest.TestCase):
    def test_sdp_target(self):
        body = probe.build_sdp("127.0.0.1", 5004)
        self.assertEqual(probe.parse_sdp_target(body), ("127.0.0.1", 5004))

    def test_sdp_missing_audio(self):
        with self.assertRaises(probe.ProtocolError):
            probe.parse_sdp_target("v=0\r\nc=IN IP4 1.2.3.4\r\nm=video 9 ...\r\n")


class DtmfTest(unittest.TestCase):
    def test_rfc2833_packet_shape(self):
        import struct
        wire = probe.build_rfc2833_dtmf(1, 0x10, 0x200, 0x0A7A2,
                                        duration_ms=160)
        self.assertEqual(len(wire), 12 + 4)
        first, second, seq, ts, ssrc = struct.unpack_from("!BBHII", wire)
        event, flags, duration = struct.unpack_from(
            "!BBH", wire[probe.RTP_HEADER_BYTES:])
        self.assertEqual(event, 1)
        self.assertEqual(duration, 1280)
        self.assertTrue(flags & 0x80)          # E-bit set
        self.assertTrue(second & 0x80)         # marker
        self.assertEqual((second & 0x7F), 101) # telephone-event payload
        self.assertEqual(ssrc, 0x0A7A2)
        self.assertEqual(seq, 0x10)


if __name__ == "__main__":
    unittest.main()