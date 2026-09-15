"""Bounded loopback SIP UAC for validating the local Asterisk engine path.

Registers with the engine, places a call to a fixed extension, receives RTP
(PCMU) audio, sends RFC2833 DTMF, then hangs up.  Bounded run/call windows;
dry run by default; --apply binds UDP sockets on loopback.

No registration dial tone is played; nothing is recorded, replayed or
auto-redialled.  The probe is an offline harness: it exercises the Asterisk
chan_sip + res_rtp_asterisk stack on loopback, never a hardware ATA.
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

from telephony import g711  # noqa: E402
from telephony.sip_bench_proxy import pcmu_sine_frame  # noqa: E402
from telephony.rtp_external_media import (  # noqa: E402
    RTP_HEADER_BYTES,
    RTP_TIMESTAMP_STEP,
    encode_rtp_packet,
)
from telephony.rtp_external_media import RtpPacket  # noqa: E402
from telephony.iax2_fixture import PCMU_PACKET_BYTES  # noqa: E402

DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
SAMPLE_RATE = 8000
DIALOG_FRAME_SECONDS = PCMU_PACKET_BYTES / SAMPLE_RATE

# Phase-2 IVR profile: prompt playback window before the digit, the digit the
# dialplan accepts, and the minimum post-DTMF RTP that proves Read() consumed
# it (the confirmation prompt only plays on a matched digit).
DTMF_DELAY_SECONDS = 2.6
DTMF_DIGIT = 5
POST_DTMF_RTP_MIN = 20


def _now():
    return time.strftime(DATETIME_FORMAT, time.gmtime())


class Log:
    def __init__(self, stream=sys.stderr):
        self.stream = stream

    def info(self, message):
        print("%s probe %s" % (_now(), message), file=self.stream, flush=True)


class ProtocolError(ValueError):
    """A SIP datagram is outside the bounded bench profile."""


def parse_response(wire):
    """Parse a SIP response into (status_line, headers, body)."""
    if not isinstance(wire, bytes) or not wire:
        raise ProtocolError("empty SIP datagram")
    text = wire.decode("utf-8", errors="replace")
    head, sep, body = text.partition("\r\n\r\n")
    if not sep:
        head, body = text, ""
    lines = head.split("\r\n")
    if not lines or not lines[0].startswith("SIP/2.0"):
        raise ProtocolError("missing SIP status line")
    status_line = lines[0]
    headers = {}
    for line in lines[1:]:
        if ":" not in line:
            continue
        name, _, value = line.partition(":")
        headers[name.strip().lower()] = value.strip()
    return status_line, headers, body or ""


def parse_request(wire):
    """Parse a SIP request into (method, uri, headers, body)."""
    if not isinstance(wire, bytes) or not wire:
        raise ProtocolError("empty SIP datagram")
    text = wire.decode("utf-8", errors="replace")
    head, sep, body = text.partition("\r\n\r\n")
    if not sep:
        head, body = text, ""
    lines = head.split("\r\n")
    if not lines or " " not in lines[0]:
        raise ProtocolError("missing SIP start line")
    parts = lines[0].split(" ", 2)
    if len(parts) != 3:
        raise ProtocolError("malformed SIP start line")
    headers = {}
    for line in lines[1:]:
        if ":" not in line:
            continue
        name, _, value = line.partition(":")
        headers[name.strip().lower()] = value.strip()
    return parts[0].upper(), parts[1], headers, body or ""


def parse_sdp_target(body):
    """Return (ip, port) of the first audio m-line from SDP."""
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


def build_request(method, uri, extra_headers, address, port, call_id, cseq,
                  contact_addr=None, body="", from_tag=""):
    """Build a SIP request with a From tag (pedantic checking requires one)."""
    if contact_addr is None:
        contact_addr = "%s:%d" % (address, port)
    tag = ";tag=%s" % from_tag if from_tag else ""
    head_lines = [
        "%s %s SIP/2.0" % (method, uri),
        "Via: SIP/2.0/UDP %s:%d" % (address, port),
        "From: <sip:100@%s:%d>%s" % (address, port, tag),
        "To: <sip:100@%s:%d>" % (address, port),
        "Call-ID: %s" % call_id,
        "CSeq: %s" % cseq,
        "Contact: <sip:100@%s>" % contact_addr,
        "Max-Forwards: 70",
    ] + list(extra_headers) + [
        "Content-Length: %d" % len(body),
        "",
        body,
    ]
    return "\r\n".join(head_lines).encode("utf-8")


def build_sdp(address, rtp_port):
    """Build an SDP offer supporting PCMU plus RFC2833 telephone-event."""
    lines = [
        "v=0",
        "o=- 0 0 IN IP4 %s" % address,
        "s=bench-loopback",
        "c=IN IP4 %s" % address,
        "t=0 0",
        "m=audio %d RTP/AVP 0 101" % rtp_port,
        "a=rtpmap:0 PCMU/8000",
        "a=rtpmap:101 telephone-event/8000",
        "a=fmtp:101 0-16",
        "",
    ]
    return "\r\n".join(lines)


def build_rfc2833_dtmf(event_code, sequence, timestamp, ssrc,
                       duration_ms=160):
    """Build one RFC2833 DTMF packet (20 ms payload, E-bit set)."""
    payload = struct.pack(
        "!BBH",
        event_code,
        0x81,  # E-bit set (end), volume=0
        duration_ms * SAMPLE_RATE // 1000,
    )
    first = (2 << 6)
    second = 0x80 | 101  # marker, payload type 101 = telephone-event
    return struct.pack("!BBHII", first, second, sequence, timestamp, ssrc) + payload


class SipLoopbackProbe:
    """Bounded SIP UAC probing REGISTER, INVITE, RFC2833 DTMF, and RTP on
    the local engine."""

    def __init__(self, address, port, target_host, target_port, extension,
                 run_seconds, call_seconds, log=None):
        self.address = address
        self.port = port
        self.target_host = target_host
        self.target_port = target_port
        self.extension = extension
        self.run_seconds = run_seconds
        self.call_seconds = call_seconds
        self.log = log or Log()
        self.sip_sock = None
        self.rtp_sock = None
        self.rtp_port = None
        self.engine_rtp_port = None
        self.call_id = "loopback-probe-%d" % os.getpid()
        self.cseq = 1
        self.rtp_rx = 0
        self.rtp_tx = 0
        self.dtmf_sent = False
        self.pre_dtmf_rx = 0
        self.from_tag = "%s-a" % self.call_id[-12:]
        self.seq = 0x100
        self.ts = 0x1000

    def _next_cseq(self):
        self.cseq += 1
        return self.cseq

    def _send_sip(self, message):
        self.sip_sock.sendto(message, (self.target_host, self.target_port))

    def _build_register(self):
        cseq_line = "%d REGISTER" % self._next_cseq()
        return build_request(
            "REGISTER",
            "sip:%s:%d" % (self.target_host, self.target_port),
            ["Expires: 60"],
            self.address,
            self.port,
            self.call_id,
            cseq_line,
            from_tag=self.from_tag,
        )

    def _build_invite(self):
        cseq_line = "%d INVITE" % self._next_cseq()
        body = build_sdp(self.address, self.rtp_port)
        return build_request(
            "INVITE",
            "sip:%s@%s:%d" % (self.extension, self.target_host, self.target_port),
            ["Content-Type: application/sdp"],
            self.address,
            self.port,
            self.call_id,
            cseq_line,
            body=body,
            from_tag=self.from_tag,
        )

    def _build_ack(self, to_hdr, call_id, cseq):
        lines = [
            "ACK sip:%s:%d SIP/2.0" % (self.target_host, self.target_port),
            "Via: SIP/2.0/UDP %s:%d" % (self.address, self.port),
            "From: <sip:100@%s:%d>;tag=%s" % (self.address, self.port, self.from_tag),
            "To: %s" % to_hdr,
            "Call-ID: %s" % call_id,
            "CSeq: %s ACK" % cseq,
            "Max-Forwards: 70",
            "Content-Length: 0",
            "",
            "",
        ]
        return "\r\n".join(lines).encode("utf-8")

    def _build_bye(self, to_hdr, call_id, cseq):
        lines = [
            "BYE sip:%s:%d SIP/2.0" % (self.target_host, self.target_port),
            "Via: SIP/2.0/UDP %s:%d" % (self.address, self.port),
            "From: <sip:100@%s:%d>;tag=%s" % (self.address, self.port, self.from_tag),
            "To: %s" % to_hdr,
            "Call-ID: %s" % call_id,
            "CSeq: %d BYE" % cseq,
            "Max-Forwards: 70",
            "Content-Length: 0",
            "",
            "",
        ]
        return "\r\n".join(lines).encode("utf-8")

    def _rtp_receive(self, deadline):
        while True:
            try:
                data, peer = self.rtp_sock.recvfrom(2048)
            except BlockingIOError:
                break
            except OSError:
                break
            if peer[0] != self.target_host:
                continue
            if len(data) >= RTP_HEADER_BYTES:
                self.rtp_rx += 1
            now = time.monotonic()
            if now >= deadline:
                break

    def _rtp_tick(self):
        if self.rtp_sock is None or self.engine_rtp_port is None:
            return
        frame = pcmu_sine_frame(440.0, 0.0)
        packet = RtpPacket(self.seq, self.ts, 0x0A7A2, frame)
        wire = encode_rtp_packet(packet)
        self.rtp_sock.sendto(wire, (self.target_host, self.engine_rtp_port))
        self.seq = (self.seq + 1) & 0xFFFF
        self.ts = (self.ts + RTP_TIMESTAMP_STEP) & 0xFFFFFFFF
        self.rtp_tx += 1

    def run(self):
        deadline = time.monotonic() + self.run_seconds
        self.log.info("start target=%s:%d rtp-port=%s extension=%s run-seconds=%d"
                      % (self.target_host, self.target_port, self.rtp_port,
                         self.extension, self.run_seconds))

        # REGISTER
        self._send_sip(self._build_register())
        status_line = self._wait_sip_response(deadline)
        self.log.info("register status=%s" % status_line)
        if not status_line or "200 OK" not in status_line:
            self.log.info("FAIL register")
            return "fail-register"

        # INVITE
        self._send_sip(self._build_invite())
        to_hdr = None
        status_line = None
        while True:
            resp_line, headers, body = self._wait_sip_response_full(deadline)
            if resp_line is None:
                self.log.info("FAIL invite timeout")
                return "fail-invite"
            code = int(resp_line.split()[1]) if " " in resp_line else 0
            self.log.info("invite status=%s" % resp_line)
            to_hdr = headers.get("to", to_hdr)
            if code >= 200:
                status_line = resp_line
                break
        if "200 OK" not in status_line:
            self.log.info("FAIL invite %s" % status_line)
            return "fail-invite"
        if body:
            _ip, engine_rtp = parse_sdp_target(body)
            self.engine_rtp_port = engine_rtp

        # ACK
        ack_wire = self._build_ack(to_hdr, self.call_id, self.cseq)
        self._send_sip(ack_wire)
        self.log.info("ack sent")

        # Receive the prompt RTP, then send one RFC2833 DTMF digit, then
        # require fresh RTP afterwards (the IVR echoes a confirmation prompt
        # only when Read() actually consumed the digit).
        dtmf_at = time.monotonic() + DTMF_DELAY_SECONDS
        tick_deadline = time.monotonic() + self.call_seconds
        last_tick = time.monotonic()
        post_dtmf_rx = 0
        while time.monotonic() < tick_deadline:
            wait = min(DIALOG_FRAME_SECONDS, tick_deadline - time.monotonic())
            if wait <= 0:
                break
            readable, _, _ = select.select([self.sip_sock, self.rtp_sock], [], [],
                                           wait)
            for sock in readable:
                if sock is self.rtp_sock:
                    self._rtp_receive(tick_deadline)
                elif sock is self.sip_sock:
                    # SIP in-dialog messages (e.g. keepalive or BYE retransmit)
                    try:
                        self.sip_sock.recvfrom(4096)
                    except OSError:
                        pass
            now = time.monotonic()
            if now >= last_tick + DIALOG_FRAME_SECONDS:
                self._rtp_tick()
                last_tick = now
                if not self.dtmf_sent and now >= dtmf_at:
                    dtmf_wire = build_rfc2833_dtmf(
                        DTMF_DIGIT, self.seq, self.ts, 0x0A7A2, duration_ms=160)
                    self.pre_dtmf_rx = self.rtp_rx
                    self.rtp_sock.sendto(
                        dtmf_wire, (self.target_host, self.engine_rtp_port))
                    self.seq = (self.seq + 1) & 0xFFFF
                    self.ts = (self.ts + RTP_TIMESTAMP_STEP) & 0xFFFFFFFF
                    self.dtmf_sent = True
                    self.rtp_tx += 1
                    self.log.info("dtmf-sent event=%d rtp-tx=%d"
                                  % (DTMF_DIGIT, self.rtp_tx))
            if self.dtmf_sent:
                post_dtmf_rx = self.rtp_rx - self.pre_dtmf_rx
                if post_dtmf_rx >= POST_DTMF_RTP_MIN:
                    break

        # BYE
        bye_wire = self._build_bye(to_hdr, self.call_id,
                                   self._next_cseq())
        self._send_sip(bye_wire)
        bye_resp, _, _ = self._wait_sip_response_full(deadline)
        self.log.info("bye status=%s" % (bye_resp or "timeout"))

        self.log.info("stop rtp-rx=%d rtp-tx=%d post-dtmf-rx=%d"
                      % (self.rtp_rx, self.rtp_tx, post_dtmf_rx))
        if self.rtp_rx < 1:
            self.log.info("FAIL no RTP received")
            return "fail-rtp"
        if not self.dtmf_sent or post_dtmf_rx < POST_DTMF_RTP_MIN:
            self.log.info("FAIL no confirmation audio after DTMF (ivr)")
            return "fail-ivr"
        return "pass"

    def _wait_sip_response(self, deadline):
        status_line, _, _ = self._wait_sip_response_full(deadline)
        return status_line

    def _wait_sip_response_full(self, deadline):
        while time.monotonic() < deadline:
            wait = deadline - time.monotonic()
            if wait <= 0:
                break
            try:
                readable, _, _ = select.select([self.sip_sock], [], [], wait)
            except (OSError, select.error):
                break
            if not readable:
                continue
            try:
                data, peer = self.sip_sock.recvfrom(4096)
            except OSError:
                continue
            if peer[0] != self.target_host:
                continue
            try:
                status_line, headers, body = parse_response(data)
                return status_line, headers, body
            except ProtocolError:
                continue
        return None, {}, ""


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true",
                        help="bind UDP sockets and run; default is a dry run")
    parser.add_argument("--address", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=15060)
    parser.add_argument("--rtp-port", type=int, default=16384)
    parser.add_argument("--target-host", default="127.0.0.1")
    parser.add_argument("--target-port", type=int, default=5060)
    parser.add_argument("--extension", default="100")
    parser.add_argument("--run-seconds", type=int, default=30)
    parser.add_argument("--call-seconds", type=int, default=10)
    return parser.parse_args(argv)


def main(argv=None):
    os.umask(0o077)
    args = parse_args(argv)
    probe = SipLoopbackProbe(
        args.address, args.port, args.target_host, args.target_port,
        args.extension, args.run_seconds, args.call_seconds,
    )
    if not args.apply:
        print("DRY RUN: would bind %s:%d (SIP) and %s:%d (RTP), call ext %s"
              " at %s:%d"
              % (args.address, args.port, args.address, args.rtp_port,
                 args.extension, args.target_host, args.target_port))
        print("DRY RUN: start with --apply to actually run")
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
    probe.sip_sock = sip_sock
    probe.rtp_sock = rtp_sock
    probe.rtp_port = args.rtp_port
    try:
        result = probe.run()
    finally:
        sip_sock.close()
        rtp_sock.close()
    print("RESULT: %s" % result)
    return 0 if result == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
