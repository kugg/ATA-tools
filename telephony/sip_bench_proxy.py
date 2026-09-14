"""Bounded SIP registrar and UAS for validating a bench ATA186 call path.

Answers only one fixed peer: REGISTER with 200 OK, and INVITE to a fixed
extension with PCMU (RTP/AVP 0) plus a short generated PCMU tone streamed to
the peer. Inbound RTP is counted, never stored. One dialog at a time, bounded
call time and bounded run time. Dry run by default; --apply binds UDP sockets.

No registration dial tone is played unless a call is answered; nothing is
recorded, replayed or auto-redialled.
"""

import argparse
import math
import os
import select
import socket
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telephony import g711
from telephony.iax2_fixture import PCMU_PACKET_BYTES
from telephony.rtp_external_media import RtpPacket, encode_rtp_packet

DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
SAMPLE_RATE = 8000
TONE_AMPLITUDE = 0.35
DIALOG_FRAME_SECONDS = PCMU_PACKET_BYTES / SAMPLE_RATE
SIP_OK = "SIP/2.0 200 OK\r\n"
SIP_TRYING = "SIP/2.0 100 Trying\r\n"
SIP_RINGING = "SIP/2.0 180 Ringing\r\n"
SIP_BUSY = "SIP/2.0 486 Busy Here\r\n"


class ProtocolError(ValueError):
    """A SIP datagram is outside the bounded bench profile."""


def _now():
    return time.strftime(DATETIME_FORMAT, time.gmtime())


class Log:
    def __init__(self, stream=sys.stderr):
        self.stream = stream

    def info(self, message):
        print("%s sip %s" % (_now(), message), file=self.stream, flush=True)


def parse_message(wire):
    """Parse a SIP datagram into (method, request_uri, headers, body)."""
    if not isinstance(wire, bytes) or not wire:
        raise ProtocolError("empty SIP datagram")
    text = wire.decode("utf-8", errors="replace")
    head, sep, body = text.partition("\r\n\r\n")
    if not sep:
        head, body = text, ""
        if "\r\n" in head:
            head, body = head.split("\r\n", 1)
    lines = head.split("\r\n")
    if not lines or " " not in lines[0]:
        raise ProtocolError("missing SIP start line")
    request_line = lines[0]
    parts = request_line.split(" ", 2)
    if len(parts) != 3 or not parts[2].startswith("SIP/2.0"):
        raise ProtocolError("malformed SIP start line")
    method = parts[0].upper()
    headers = {}
    for line in lines[1:]:
        if ":" not in line:
            continue
        name, _, value = line.partition(":")
        headers[name.strip().lower()] = value.strip()
    if not headers.get("call-id") or not headers.get("cseq"):
        raise ProtocolError("SIP datagram missing Call-ID or CSeq")
    return method, parts[1], headers, body or ""


def _sip_response(status_line, extra_headers, body, original):
    """Build a response for a parsed request, echoing its Via/From/To etc."""
    orig_headers = original[2]
    via = orig_headers.get("via") or "SIP/2.0/UDP unknown:0"
    frm = orig_headers.get("from") or "bench"
    to = orig_headers.get("to") or "bench"
    call_id = orig_headers.get("call-id") or "bench"
    cseq = orig_headers.get("cseq") or "1 REGISTER"
    if "tag=" not in to:
        to = to + ";tag=bench"
    head_lines = [
        status_line.rstrip("\r\n"),
        "Via: %s" % via,
        "From: %s" % frm,
        "To: %s" % to,
        "Call-ID: %s" % call_id,
        "CSeq: %s" % cseq,
        "User-Agent: Bench-ATA-UAS/1.0",
    ] + list(extra_headers) + ["Content-Length: %d" % len(body)]
    return "\r\n".join(head_lines) + "\r\n\r\n" + body


def register_ok(parsed):
    headers = ["Expires: 60"]
    if parsed[3]:
        headers.append("Contact: %s" % parsed[3])
    return _sip_response(SIP_OK, headers, "", parsed)


def build_sdp(address, rtp_port):
    return "\r\n".join([
        "v=0",
        "o=- 0 0 IN IP4 %s" % address,
        "s=bench-ata-call",
        "c=IN IP4 %s" % address,
        "t=0 0",
        "m=audio %d RTP/AVP 0" % rtp_port,
        "a=rtpmap:0 PCMU/8000",
        "",
    ])


def invite_ok(parsed, address, rtp_port):
    body = build_sdp(address, rtp_port)
    return _sip_response(SIP_OK, {}, body, parsed)


def parse_sdp_target(body):
    """Return (ip, port) of the peer's first audio m-line from SDP."""
    remote = None
    for line in (body or "").splitlines():
        line = line.strip()
        if line.startswith("m=audio "):
            port = int(line.split()[1])
            remote = (remote[0], port) if remote else (None, port)
        elif line.startswith("c=IN IP4 "):
            ip = line.split()[2]
            remote = (ip, remote[1]) if remote else (ip, None)
    if remote is None or None in remote:
        raise ProtocolError("SDP lacks audio m-line or c-line")
    return remote


def pcmu_sine_frame(frequency_hz, start_phase):
    """One 20ms PCMU frame of a sine tone (bounded, no capture)."""
    samples = []
    phase = start_phase
    for index in range(PCMU_PACKET_BYTES):
        phase_value = 2.0 * math.pi * frequency_hz * index / SAMPLE_RATE + phase
        sample = int(32767 * TONE_AMPLITUDE * math.sin(phase_value))
        samples.append(sample)
    pcm = struct.pack("<%dh" % PCMU_PACKET_BYTES, *samples)
    return g711.pcm16le_to_pcmu(pcm)


def tone_pattern(frames_of_tone=15, frames_of_silence=60):
    """Bounded repeating tone pattern: 300ms tone then silence (~75 frames)."""
    if frames_of_tone < 1 or frames_of_silence < 1:
        raise ValueError("tone pattern frames must be positive")
    phase = 0.0
    frames = []
    for _ in range(frames_of_tone):
        frames.append(pcmu_sine_frame(440.0, phase))
        phase += 2.0 * math.pi * 440.0 * PCMU_PACKET_BYTES / SAMPLE_RATE
    frames.extend([None] * frames_of_silence)
    return tuple(frames)


class SipBenchProxy:
    """Fixed-peer SIP registrar/UAS with a bounded streamed PCMU tone."""

    def __init__(self, address, port, rtp_port, expected_peer, extension,
                 run_seconds, call_seconds, pattern=None, log=None):
        self.address = address
        self.port = port
        self.rtp_port = rtp_port
        self.expected_peer = expected_peer
        self.extension = extension
        self.run_seconds = run_seconds
        self.call_seconds = call_seconds
        self.pattern = tone_pattern() if pattern is None else pattern
        self.log = log or Log()
        self.sip_sock = None
        self.rtp_sock = None
        self.call = None

    def _send_sip(self, peer, message):
        self.sip_sock.sendto(message.encode("utf-8"), peer)

    def handle_datagram(self, peer, data):
        if peer[0] != self.expected_peer:
            self.log.info("drop peer=%s not-expected" % peer[0])
            return None
        try:
            method, _uri, headers, body = parse_message(data)
        except ProtocolError as exc:
            self.log.info("malformed peer=%s error=%s" % (peer[0], exc))
            return None
        if method == "REGISTER":
            self._handle_register(peer, headers, body)
        elif method == "INVITE":
            self._handle_invite(peer, headers, body)
        elif method == "ACK":
            self._handle_ack(peer, headers)
        elif method == "BYE":
            self._handle_bye(peer, headers)
        elif method == "CANCEL":
            self._send_sip(peer, "SIP/2.0 200 OK\r\nContent-Length: 0\r\n\r\n")
        return method

    def _handle_register(self, peer, headers, body):
        call_id = headers.get("call-id") or "unknown"
        self.log.info("register peer=%s call-id=%s" % (peer[0], call_id))
        self._send_sip(peer, register_ok((None, None, headers, body)))

    def _handle_invite(self, peer, headers, body):
        call_id = headers.get("call-id") or "unknown"
        self.log.info("invite peer=%s call-id=%s" % (peer[0], call_id))
        if self.call is not None:
            self._send_sip(peer, _sip_response(SIP_BUSY, [], "", (None, None, headers, body)))
            return
        try:
            remote = parse_sdp_target(body)
        except ProtocolError as exc:
            self.log.info("invite-bad-sdp peer=%s error=%s" % (peer[0], exc))
            self._send_sip(peer, _sip_response("SIP/2.0 400 Bad Request", [], "",
                                               (None, None, headers, body)))
            return
        self.call = {
            "peer": peer,
            "headers": headers,
            "remote": remote,
            "start": time.monotonic(),
            "last_rtp_tx": time.monotonic(),
            "last_rtp_rx": time.monotonic(),
            "rtp_rx": 0,
            "rtp_tx": 0,
            "seq": 0,
            "ts": 0,
            "pattern_index": 0,
            "ackd": False,
            "done": False,
        }
        self._send_sip(peer, _sip_response(SIP_TRYING, {}, "", (None, None, headers, body)))
        self._send_sip(peer, _sip_response(SIP_RINGING, {}, "", (None, None, headers, body)))
        self._send_sip(peer, invite_ok((None, None, headers, body), self.address, self.rtp_port))

    def _handle_ack(self, peer, headers):
        if self.call is None:
            return
        self.call["ackd"] = True
        self.log.info("ack peer=%s call-id=%s" % (peer[0], headers.get("call-id") or "?"))

    def _handle_bye(self, peer, headers):
        self._send_sip(peer, "SIP/2.0 200 OK\r\nContent-Length: 0\r\n\r\n")
        if self.call is not None and self.call["peer"] == peer:
            self._end_call("bye")
        else:
            self.log.info("bye peer=%s no-active-call" % peer[0])

    def _end_call(self, reason):
        call, self.call = self.call, None
        self.log.info("end reason=%s peer=%s rtp_tx=%d rtp_rx=%d"
                      % (reason, call["peer"][0], call["rtp_tx"], call["rtp_rx"]))

    def _next_tone_frame(self):
        index = self.call["pattern_index"]
        frame = self.pattern[index % len(self.pattern)]
        self.call["pattern_index"] += 1
        return frame

    def _rtp_tick(self):
        if self.call is None or not self.call["ackd"]:
            return
        frame = self._next_tone_frame()
        if frame is not None:
            packet = RtpPacket(self.call["seq"], self.call["ts"], 0x0A7A1, frame)
            wire = encode_rtp_packet(packet)
            self.rtp_sock.sendto(wire, self.call["remote"])
            self.call["seq"] = (self.call["seq"] + 1) & 0xFFFF
            self.call["ts"] = (self.call["ts"] + PCMU_PACKET_BYTES) & 0xFFFFFFFF
            self.call["rtp_tx"] += 1
        self.call["last_rtp_tx"] = time.monotonic()

    def _rtp_receive(self):
        while True:
            try:
                data, peer = self.rtp_sock.recvfrom(2048)
            except OSError:
                break
            if self.call is None or peer[0] != self.expected_peer:
                continue
            self.call["rtp_rx"] += 1
            self.call["last_rtp_rx"] = time.monotonic()

    def run(self):
        deadline = time.monotonic() + self.run_seconds
        self.log.info("start address=%s sip-port=%d rtp-port=%d peer=%s "
                      "extension=%s run-seconds=%d"
                      % (self.address, self.port, self.rtp_port,
                         self.expected_peer, self.extension, self.run_seconds))
        next_tick = time.monotonic()
        while True:
            now = time.monotonic()
            if now >= deadline:
                break
            if self.call is not None:
                if now - self.call["start"] > self.call_seconds:
                    self._end_call("call-timeout")
                elif now >= self.call["last_rtp_tx"] + DIALOG_FRAME_SECONDS:
                    self._rtp_tick()
            wait = min(DIALOG_FRAME_SECONDS, deadline - now)
            try:
                readable, _, _ = select.select([self.sip_sock, self.rtp_sock], [], [], wait)
            except (OSError, select.error):
                break
            for sock in readable:
                if sock is self.sip_sock:
                    try:
                        data, peer = self.sip_sock.recvfrom(4096)
                    except OSError:
                        continue
                    self.handle_datagram(peer, data)
                else:
                    self._rtp_receive()
        if self.call is not None:
            self._end_call("shutdown")
        self.log.info("stop")
        return "stopped"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true",
                        help="bind UDP sockets and serve; default is a dry run")
    parser.add_argument("--address", default="192.168.2.2")
    parser.add_argument("--port", type=int, default=5060)
    parser.add_argument("--rtp-port", type=int, default=5004)
    parser.add_argument("--expected-peer", default="192.168.2.10")
    parser.add_argument("--extension", default="100")
    parser.add_argument("--run-seconds", type=int, default=180)
    parser.add_argument("--call-seconds", type=int, default=45)
    return parser.parse_args(argv)


def main(argv=None):
    os.umask(0o077)
    args = parse_args(argv)
    proxy = SipBenchProxy(args.address, args.port, args.rtp_port,
                          args.expected_peer, args.extension,
                          args.run_seconds, args.call_seconds)
    if not args.apply:
        print("DRY RUN: would bind %s:%d (SIP) and :%d (RTP), serve %s "
              "from expected peer %s"
              % (args.address, args.port, args.rtp_port, args.extension,
                 args.expected_peer))
        print("DRY RUN: start with --apply to actually serve")
        return 0
    sip_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rtp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sip_sock.bind((args.address, args.port))
        rtp_sock.bind((args.address, args.rtp_port))
    except OSError as exc:
        print("ERROR: bind failed: %s" % exc, file=sys.stderr)
        return 1
    sip_sock.settimeout(1.0)
    rtp_sock.setblocking(False)
    proxy.sip_sock = sip_sock
    proxy.rtp_sock = rtp_sock
    try:
        proxy.run()
    finally:
        sip_sock.close()
        rtp_sock.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())