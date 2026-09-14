"""Offline tests for the bounded bench SIP registrar/UAS."""

import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from telephony import sip_bench_proxy as sip  # noqa: E402
from telephony import g711  # noqa: E402
from telephony.rtp_external_media import (  # noqa: E402
    PCMU_PAYLOAD_TYPE,
    decode_rtp_packet,
)


def register_request(call_id="abc123", cseq="1 REGISTER"):
    return (
        b"REGISTER sip:192.168.2.2 SIP/2.0\r\n"
        b"Via: SIP/2.0/UDP 192.168.2.10:5060\r\n"
        b"From: <sip:100@192.168.2.2>\r\n"
        b"To: <sip:100@192.168.2.2>\r\n"
        b"Call-ID: " + call_id.encode() + b"\r\n"
        b"CSeq: " + cseq.encode() + b"\r\n"
        b"Contact: <sip:100@192.168.2.10:5060>\r\n"
        b"Content-Length: 0\r\n"
        b"\r\n")


def invite_request(call_id="call-1", cseq="1 INVITE"):
    return register_request(call_id, cseq).replace(
        b"REGISTER sip:", b"INVITE sip:").replace(
        b"CSeq: ", b"CSeq: ") + (
        b"v=0\r\n"
        b"o=- 0 0 IN IP4 192.168.2.10\r\n"
        b"c=IN IP4 192.168.2.10\r\n"
        b"t=0 0\r\n"
        b"m=audio 16384 RTP/AVP 0\r\n"
        b"a=rtpmap:0 PCMU/8000\r\n"
        b"\r\n")


class ParseMessageTest(unittest.TestCase):
    def test_parse_register(self):
        method, uri, headers, body = sip.parse_message(register_request())
        self.assertEqual(method, "REGISTER")
        self.assertIn("192.168.2.2", uri)
        self.assertEqual(headers["call-id"], "abc123")
        self.assertEqual(headers["cseq"], "1 REGISTER")
        self.assertEqual(body, "")

    def test_parse_invite_with_sdp(self):
        method, _uri, headers, body = sip.parse_message(invite_request())
        self.assertEqual(method, "INVITE")
        self.assertIn("m=audio 16384 RTP/AVP 0", body)
        self.assertIn("sip:100@192.168.2.10:5060", headers["contact"])

    def test_rejects_garbage(self):
        with self.assertRaises(sip.ProtocolError):
            sip.parse_message(b"")
        with self.assertRaises(sip.ProtocolError):
            sip.parse_message(b"BOGUS\r\n\r\n")

    def test_missing_call_id(self):
        with self.assertRaises(sip.ProtocolError):
            sip.parse_message(b"INVITE sip:a SIP/2.0\r\nCSeq: 1 INVITE\r\n\r\n")


class SdpParseTest(unittest.TestCase):
    def test_audio_target(self):
        _m, _u, _h, body = sip.parse_message(invite_request())
        self.assertEqual(sip.parse_sdp_target(body), ("192.168.2.10", 16384))

    def test_missing_audio_line(self):
        with self.assertRaises(sip.ProtocolError):
            sip.parse_sdp_target("v=0\r\nc=IN IP4 1.2.3.4\r\nm=video 9 RTP/AVP 96\r\n")


class ResponseTest(unittest.TestCase):
    def test_register_ok(self):
        resp = sip.register_ok(sip.parse_message(register_request()))
        lines = resp.splitlines()
        self.assertEqual(lines[0], "SIP/2.0 200 OK")
        self.assertIn("CSeq: 1 REGISTER", lines)
        self.assertIn("Expires: 60", lines)

    def test_invite_ok_sdp(self):
        parsed = sip.parse_message(invite_request())
        resp = sip.invite_ok(parsed, "192.168.2.2", 5004)
        self.assertIn("SIP/2.0 200 OK", resp.splitlines()[0])
        self.assertIn("m=audio 5004 RTP/AVP 0", resp)
        self.assertIn("c=IN IP4 192.168.2.2", resp)
        length = [l for l in resp.splitlines() if l.startswith("Content-Length:")]
        body = resp.split("\r\n\r\n", 1)[1]
        self.assertEqual(int(length[0].split(":")[1]), len(body))


class ToneTest(unittest.TestCase):
    def test_pattern_shape(self):
        pattern = sip.tone_pattern()
        self.assertEqual(len(pattern), 75)
        tones = [f for f in pattern if f is not None]
        self.assertEqual(len(tones), 15)
        self.assertTrue(all(len(f) == 160 for f in tones))

    def test_tone_is_audible(self):
        frame = sip.pcmu_sine_frame(440.0, 0.0)
        pcm = g711.pcmu_to_pcm16le(frame)
        samples = struct.unpack("<%dh" % (len(pcm) // 2), pcm)
        self.assertTrue(any(abs(s) > 100 for s in samples),
                        "tone frame should contain audible samples")

    def test_pattern_rejects_nonpositive(self):
        with self.assertRaises(ValueError):
            sip.tone_pattern(frames_of_silence=0)


class _FakeSock:
    def __init__(self):
        self.sent = []

    def sendto(self, packet, peer):
        self.sent.append((peer, packet))


class _DrainingSock:
    """Non-blocking socket: yields queued peer packets, then empty-buffer."""

    def __init__(self, packets, peer=("192.168.2.10", 5004)):
        self.packets = list(packets)
        self.peer = peer
        self.sent = []

    def recvfrom(self, _size):
        if self.packets:
            return self.packets.pop(0), self.peer
        raise BlockingIOError("no data")

    def sendto(self, packet, peer):
        self.sent.append((peer, packet))


class _PayloadLog:
    def __init__(self):
        self.lines = []

    def info(self, message):
        self.lines.append(message)


class ProxyFlowTest(unittest.TestCase):
    def _make_proxy(self, peer=("192.168.2.10", 5060)):
        proxy = sip.SipBenchProxy(
            "192.168.2.2", 5060, 5004, peer[0], "100",
            run_seconds=60, call_seconds=10,
            pattern=sip.tone_pattern(frames_of_tone=2, frames_of_silence=2),
            log=_PayloadLog())
        proxy.sip_sock = _FakeSock()
        proxy.rtp_sock = _FakeSock()
        return proxy

    def test_register_answered(self):
        proxy = self._make_proxy()
        method = proxy.handle_datagram(("192.168.2.10", 5060), register_request())
        self.assertEqual(method, "REGISTER")
        self.assertTrue(any("SIP/2.0 200 OK" in d.decode() for _, d in proxy.sip_sock.sent))

    def test_drops_unexpected_peer(self):
        proxy = self._make_proxy()
        proxy.handle_datagram(("192.168.2.99", 5060), register_request())
        self.assertEqual(proxy.sip_sock.sent, [])

    def test_invite_to_ack_streams_rtp(self):
        proxy = self._make_proxy()
        parsed = sip.parse_message(invite_request())
        proxy.handle_datagram(("192.168.2.10", 5060), invite_request())
        self.assertIsNotNone(proxy.call)
        proxy.handle_datagram(("192.168.2.10", 5060),
                              register_request("call-1", "1 ACK").replace(
                                  b"REGISTER sip:", b"ACK sip:"))
        proxy._rtp_tick()
        rtp_sent = proxy.rtp_sock.sent
        self.assertTrue(rtp_sent, "expected RTP frames after ACK")
        wire = rtp_sent[0][1]
        packet = decode_rtp_packet(wire)
        self.assertEqual(packet.payload_type, PCMU_PAYLOAD_TYPE)
        self.assertEqual(packet.ssrc, 0x0A7A1)
        proxy._end_call("test")

    def test_second_invite_is_busy(self):
        proxy = self._make_proxy()
        proxy.handle_datagram(("192.168.2.10", 5060), invite_request())
        proxy.handle_datagram(("192.168.2.10", 5060),
                              invite_request(call_id="call-2"))
        self.assertTrue(any("486 Busy" in (d.decode() if isinstance(d, bytes) else "")
                            for _, d in proxy.sip_sock.sent))

    def test_invite_bad_sdp_rejected(self):
        proxy = self._make_proxy()
        bad = invite_request().replace(b"m=audio 16384 RTP/AVP 0",
                                       b"m=video 16384 RTP/AVP 96")
        proxy.handle_datagram(("192.168.2.10", 5060), bad)
        self.assertIsNone(proxy.call)

    def test_rtp_drain_returns_when_buffer_empties(self):
        proxy = self._make_proxy()
        proxy.rtp_sock = _DrainingSock([b"pad"] * 40)
        proxy.handle_datagram(("192.168.2.10", 5060), invite_request())
        proxy.call["ackd"] = True
        proxy._rtp_receive()
        self.assertEqual(proxy.call["rtp_rx"], 40)
        proxy._rtp_tick()
        self.assertTrue(proxy.rtp_sock.sent,
                        "tone tick must still run after a drain")
        proxy._end_call("test")


if __name__ == "__main__":
    unittest.main()