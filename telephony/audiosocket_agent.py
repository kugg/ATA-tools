"""Bounded AudioSocket agent for the bench external-media qualification.

Accepts exactly one TCP connection at a time on loopback, following the
AudioSocket protocol: a 3-byte header (kind, len-high, len-low) precedes every
message; kind 0x01 carries the 16-byte call UUID, kind 0x10 carries 20 ms
8 kHz signed-linear mono audio, kind 0x00 ends the session.

On each inbound audio frame the agent replies with the next frame of a fixed
660 Hz tone until the tone budget is exhausted, then terminates the session
(kind 0x00). Audio content is never stored or logged; only frame counts and
energy summaries are emitted. Dry run by default; --apply binds the socket.
"""

import argparse
import math
import os
import socket
import struct
import sys
import time

DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
SAMPLE_RATE = 8000
FRAME_BYTES = 320
FRAME_SECONDS = FRAME_BYTES / 2 / SAMPLE_RATE
TONE_HZ = 660.0
TONE_FRAMES = 100
MAX_SESSION_SECONDS = 120
MAX_AUDIO_BYTES = 16 * 1024 * 1024

HEADER_LEN = 3
KIND_TERMINATE = 0x00
KIND_UUID = 0x01
KIND_AUDIO = 0x10

# How long after the tone ends the agent keeps counting inbound audio before
# terminating the session (measured from tone start).
POST_TONE_WINDOW_SECONDS = 10.0


def _now():
    return time.strftime(DATETIME_FORMAT, time.gmtime())


def _log(message):
    print("%s agent %s" % (_now(), message), file=sys.stderr, flush=True)


def tone_frames(count=TONE_FRAMES, frequency_hz=TONE_HZ):
    """Fixed-tone outbound frames (signed-linear 16-bit mono).

    The tone is generated as one continuous buffer and sliced per frame; a
    naive per-frame sine would restart at phase zero and click at every
    20 ms boundary (audible as buzzy distortion).
    """
    total_samples = count * (FRAME_BYTES // 2)
    samples = bytearray()
    for offset in range(total_samples):
        samples += struct.pack("<h", int(32767 * 0.35 * math.sin(
            2.0 * math.pi * frequency_hz * offset / SAMPLE_RATE)))
    audio = bytes(samples)
    return [audio[base * FRAME_BYTES:(base + 1) * FRAME_BYTES]
            for base in range(count)]


def read_exact(sock, size):
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            return None
        data += chunk
    return data


def local_has_data(sock):
    """True when bytes are buffered (bounded-inburst read without blocking)."""
    import select
    return bool(select.select([sock], [], [], 0)[0])


def _drain_inbound(conn, log=_log):
    """Read all buffered messages without blocking. Returns audio frames seen."""
    drained = 0
    while local_has_data(conn):
        kind, payload = read_message(conn)
        if kind is None:
            break
        if kind != KIND_AUDIO or not payload:
            continue
        drained += 1
    return drained


def read_message(sock):
    """Return (kind, payload) or (None, None) on EOF."""
    header = read_exact(sock, HEADER_LEN)
    if header is None:
        return None, None
    kind = header[0]
    length = (header[1] << 8) | header[2]
    payload = b""
    if length:
        payload = read_exact(sock, length)
        if payload is None:
            return None, None
    return kind, payload


def frame_energy(payload):
    """Peak absolute sample of a signed-linear frame."""
    if len(payload) < 2:
        return 0
    samples = struct.unpack_from("<%dh" % (len(payload) // 2), payload)
    return max(abs(sample) for sample in samples)


def serve(conn, log=_log, tone=None):
    """Serve one AudioSocket session. Returns a summary dict."""
    tone = tone or tone_frames()
    kind, payload = read_message(conn)
    if kind != KIND_UUID or len(payload) != 16:
        log("reject reason=missing-uuid")
        return {"ok": False}
    uuid_hex = payload.hex()
    log("session uuid=%s tone-frames=%d" % (uuid_hex, len(tone)))
    # Emit the tone paced at the 20 ms media cadence, anchored to an absolute
    # clock so per-iteration overhead cannot stretch the cadence (a slow
    # clock turns the tone into discrete bops). Inbound audio is drained
    # concurrently and counted.
    audio_tx = 0
    audio_rx = 0
    voiced = 0
    peak = 0
    tonestart = time.time()
    base = time.monotonic()
    for index, frame in enumerate(tone):
        target = base + (index + 1) * FRAME_SECONDS
        delay = target - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        packet = bytes([KIND_AUDIO, len(frame) >> 8, len(frame) & 0xFF]) + frame
        conn.sendall(packet)
        audio_tx += 1
        audio_rx += _drain_inbound(conn, log)
    tone_deadline = time.time() + POST_TONE_WINDOW_SECONDS
    session_deadline = time.time() + MAX_SESSION_SECONDS
    while time.time() < session_deadline and time.time() < tone_deadline:
        if local_has_data(conn):
            kind, payload = read_message(conn)
        else:
            time.sleep(0.02)
            if time.time() >= tone_deadline:
                break
            continue
        if kind is None:
            log("session end reason=eof rx=%d" % audio_rx)
            break
        if kind == KIND_TERMINATE:
            log("session end reason=remote-terminate rx=%d" % audio_rx)
            break
        if kind != KIND_AUDIO or not payload:
            continue
        audio_rx += 1
        energy = frame_energy(payload)
        peak = max(peak, energy)
        if energy > 512:
            voiced += 1
    conn.sendall(bytes([KIND_TERMINATE, 0x00, 0x00]))
    log("session end reason=window rx=%d tx=%d voiced=%d peak=%d tone-sec=%.1f"
        % (audio_rx, audio_tx, voiced, peak, time.time() - tonestart))
    summary = {"ok": True, "uuid": uuid_hex, "audio_rx": audio_rx,
               "audio_tx": audio_tx, "voiced": voiced, "peak": peak}
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true",
                        help="bind the TCP socket; default is a dry run")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9100)
    parser.add_argument("--max-audio-bytes", type=int, default=MAX_AUDIO_BYTES)
    args = parser.parse_args(argv)
    if not args.apply:
        print("DRY RUN: would bind %s:%d and echo a %d-frame %d Hz tone"
              % (args.host, args.port, TONE_FRAMES, TONE_HZ))
        print("DRY RUN: start with --apply to actually serve")
        return 0
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        listener.bind((args.host, args.port))
        listener.listen(1)
    except OSError as exc:
        print("ERROR: bind failed: %s" % exc, file=sys.stderr)
        return 1
    listener.settimeout(5)
    _log("listening host=%s port=%d" % (args.host, args.port))
    served = 0
    try:
        while served < 8:
            try:
                conn, addr = listener.accept()
            except socket.timeout:
                continue
            if addr[0] != "127.0.0.1":
                _log("drop addr=%s not loopback" % addr[0])
                conn.close()
                continue
            served += 1
            conn.settimeout(MAX_SESSION_SECONDS)
            serve(conn)
            conn.close()
    finally:
        listener.close()
    _log("stop sessions=%d" % served)
    return 0


if __name__ == "__main__":
    sys.exit(main())
