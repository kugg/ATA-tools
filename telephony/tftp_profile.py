"""Bounded TFTP octet server serving one bench ATA profile over UDP 69.

The server answers a fixed expected client only, serves an exact allow list of
profile file names (no path lookup whatsoever), never writes, and enforces a
bounded run time, transfer timeout and retransmission count. RFC1350 octet
mode with 512-byte blocks. Dry run by default; --apply binds the socket.

This is a reviewed bench tool for the operator workflow. It requires root to
bind UDP/69 on macOS; use dry run to validate first.
"""

import argparse
import os
import select
import socket
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TFTP_PORT = 69
BLOCK_SIZE = 512
TIMEOUT_SECONDS = 5
RETRANSMITS = 4
MAX_OPCODE_LEN = 600
DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class ProtocolError(ValueError):
    """A TFTP datagram is outside the bounded profile."""


def _now():
    return time.strftime(DATETIME_FORMAT, time.gmtime())


class Log:
    def __init__(self, stream=sys.stderr):
        self.stream = stream

    def info(self, message):
        print("%s tftp %s" % (_now(), message), file=self.stream, flush=True)


def blockize(payload):
    """Split payload into RFC1350 data blocks; final block may be short."""
    if not isinstance(payload, bytes):
        raise TypeError("payload must be bytes")
    if len(payload) == 0:
        return [b""]
    return [payload[i : i + BLOCK_SIZE] for i in range(0, len(payload), BLOCK_SIZE)]


def split_rrq(data):
    """Parse an RRQ datagram into (filename, mode)."""
    if not isinstance(data, bytes) or len(data) < 4 or len(data) > MAX_OPCODE_LEN:
        raise ProtocolError("malformed RRQ length")
    (opcode,) = struct.unpack("!H", data[:2])
    if opcode != 1:
        raise ProtocolError("expected RRQ")
    fields = data[2:].split(b"\x00")
    if len(fields) < 3 or not fields[0] or not fields[1]:
        raise ProtocolError("malformed RRQ fields")
    filename = fields[0].decode("ascii", errors="replace")
    mode = fields[1].decode("ascii", errors="replace")
    if any(part in filename for part in ("/", "\\", "..", "\x00")):
        raise ProtocolError("filename outside allow list")
    if mode != "octet":
        raise ProtocolError("only octet mode is served")
    return filename, mode


def encode_error(code, message):
    if not 0 <= code <= 5:
        raise ValueError("invalid TFTP error code")
    return struct.pack("!HH", 5, code) + message.encode("ascii")[:120] + b"\x00"


def encode_data(block_number, chunk):
    if not 1 <= block_number <= 0xFFFF:
        raise ValueError("invalid block number")
    if len(chunk) > BLOCK_SIZE:
        raise ValueError("chunk too large")
    return struct.pack("!HH", 3, block_number) + chunk


def encode_ack(block_number):
    if not 0 <= block_number <= 0xFFFF:
        raise ValueError("invalid block number")
    return struct.pack("!HH", 4, block_number)


class TftpServer:
    """One at a time RFC1350 octet transfer to a fixed expected client."""

    def __init__(self, address, expected_client, payloads, run_seconds,
                 timeout_seconds=TIMEOUT_SECONDS, retransmits=RETRANSMITS,
                 log=None):
        self.address = address
        self.expected_client = expected_client
        self.payloads = payloads
        if not isinstance(payloads, dict) or not payloads:
            raise ValueError("payloads must be a non-empty mapping name->bytes")
        self.run_seconds = run_seconds
        self.timeout = timeout_seconds
        self.retransmits = retransmits
        self.log = log or Log()
        self.sock = None
        self.transfer = None
        self.requests = 0
        self.errors = 0
        self.byte_count = 0

    def _sendto(self, peer, packet):
        self.sock.sendto(packet, peer)

    def _reject(self, peer, code, message):
        self.errors += 1
        self.log.info("reject peer=%s code=%d message=%s" % (peer[0], code, message))
        try:
            self._sendto(peer, encode_error(code, message))
        except OSError:
            pass

    def handle_datagram(self, peer, data):
        """Process one datagram from an untrusted or fixed client."""
        if peer[0] != self.expected_client:
            self._reject(peer, 2, "access violation: client not expected")
            return
        if len(data) < 2:
            self._reject(peer, 4, "malformed datagram")
            return
        (opcode,) = struct.unpack("!H", data[:2])
        if opcode == 1:
            self._handle_rrq(peer, data)
            return
        if opcode == 4:
            self._handle_ack(peer, data)
            return
        if opcode == 2:
            self._reject(peer, 4, "writes are not accepted")
            return
        self._reject(peer, 4, "illegal operation")

    def _handle_rrq(self, peer, data):
        try:
            filename, _mode = split_rrq(data)
        except ProtocolError as exc:
            self._reject(peer, 4, "malformed RRQ: %s" % exc)
            return
        if self.transfer is not None:
            if self.transfer["peer"][0] != peer[0]:
                self.log.info("busy peer=%s file=%s" % (peer[0], filename))
                self._reject(peer, 4, "one transfer at a time")
                return
            transfer, self.transfer = self.transfer, None
            self.log.info("abandon peer=%s file=%s blocks=%d acked=%d"
                          % (transfer["peer"][0], transfer["file"],
                             len(transfer["blocks"]), transfer["acked"]))
        if filename not in self.payloads:
            self.log.info("rrq-unserved peer=%s file=%s" % (peer[0], filename))
            self._reject(peer, 1, "file not found")
            return
        self.requests += 1
        blocks = blockize(self.payloads[filename])
        if blocks and blocks[-1] != b"" and len(blocks[-1]) < BLOCK_SIZE:
            blocks = blocks + [b""]
        self.transfer = {
            "peer": peer,
            "file": filename,
            "blocks": blocks,
            "next": 1,
            "pending_ack": 0,
            "sent_at": time.monotonic(),
            "retries": 0,
            "acked": 0,
            "terminator": False,
        }
        self.log.info("rrq peer=%s file=%s blocks=%d" % (peer[0], filename, len(blocks)))
        self._send_next_block()

    def _handle_ack(self, peer, data):
        if self.transfer is None or self.transfer["peer"] != peer:
            return
        if len(data) != 4:
            self._reject(peer, 4, "malformed ACK")
            return
        (opcode, ack_number) = struct.unpack("!HH", data)
        if opcode != 4:
            self._reject(peer, 4, "expected ACK")
            return
        expected = self.transfer["pending_ack"]
        if ack_number != expected:
            self.log.info("ack-mismatch peer=%s got=%d expected=%d"
                          % (peer[0], ack_number, expected))
            self._send_next_block()
            return
        self.transfer["acked"] += 1
        self.transfer["retries"] = 0
        self.transfer["sent_at"] = time.monotonic()
        if self.transfer["terminator"]:
            self._finish_transfer("complete")
            return
        self.transfer["next"] += 1
        self._send_next_block()

    def _send_next_block(self):
        blocks = self.transfer["blocks"]
        next_number = self.transfer["next"]
        index = next_number - 1
        if index < len(blocks):
            chunk = blocks[index]
            self.transfer["terminator"] = (
                index == len(blocks) - 1 and len(chunk) < BLOCK_SIZE
            )
        else:
            chunk = b""
            self.transfer["terminator"] = True
        self.transfer["pending_ack"] = next_number
        self._sendto(self.transfer["peer"], encode_data(next_number, chunk))
        self.byte_count += len(chunk)

    def _finish_transfer(self, status):
        transfer, self.transfer = self.transfer, None
        self.log.info("done status=%s peer=%s file=%s blocks=%d acked=%d"
                      % (status, transfer["peer"][0], transfer["file"],
                         len(transfer["blocks"]), transfer["acked"]))

    def _expire_transfer(self):
        transfer, self.transfer = self.transfer, None
        self.errors += 1
        self.log.info("done status=timeout peer=%s file=%s"
                      % (transfer["peer"][0], transfer["file"]))

    def run(self):
        deadline = time.monotonic() + self.run_seconds
        self.log.info("start address=%s peer=%s names=%s profile-bytes=%d"
                      % (self.address, self.expected_client,
                         ", ".join(sorted(self.payloads)),
                         sum(len(p) for p in self.payloads.values())))
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            if self.transfer is not None:
                since = time.monotonic() - self.transfer["sent_at"]
                if since > self.timeout:
                    if self.transfer["retries"] >= self.retransmits:
                        self._expire_transfer()
                    else:
                        self.transfer["retries"] += 1
                        self._send_next_block()
            wait = min(self.timeout, remaining)
            try:
                readable, _, _ = select.select([self.sock], [], [], wait)
            except (OSError, select.error):
                break
            for sock in readable:
                try:
                    data, peer = sock.recvfrom(MAX_OPCODE_LEN)
                except OSError:
                    continue
                self.handle_datagram(peer, data)
        self.log.info("stop requests=%d errors=%d bytes=%d"
                      % (self.requests, self.errors, self.byte_count))
        return (self.requests, self.errors, self.byte_count)


def load_payloads(profile_paths, allow_names):
    payloads = {}
    primary = None
    for path in profile_paths:
        data = open(path, "rb").read()
        name = os.path.basename(path)
        payloads[name] = data
        if primary is None:
            primary = data
    if primary is None:
        raise ValueError("no profile files supplied")
    for name in allow_names:
        if "/" in name or "\\" in name or ".." in name or not name:
            raise ValueError("invalid allow name: %r" % name)
        payloads[name] = primary
    return payloads


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true",
                        help="bind UDP/69 and serve; default is a dry run")
    parser.add_argument("--address", default="192.168.2.2")
    parser.add_argument("--expected-client", default="192.168.2.10")
    parser.add_argument("--run-seconds", type=int, default=120)
    parser.add_argument("--timeout", type=int, default=TIMEOUT_SECONDS)
    parser.add_argument("--profile", action="append", default=[],
                        help="profile file to serve under its basename (repeatable)")
    parser.add_argument("--allow-name", action="append", default=[],
                        help="extra exact filename served with the profile (repeatable)")
    return parser.parse_args(argv)


def main(argv=None):
    os.umask(0o077)
    args = parse_args(argv)
    payloads = load_payloads(args.profile, args.allow_name)
    server = TftpServer(args.address, args.expected_client, payloads,
                        args.run_seconds, args.timeout)
    if not args.apply:
        print("DRY RUN: would bind %s:%d and serve "
              % (args.address, TFTP_PORT) + "+".join(sorted(payloads)))
        print("DRY RUN: start with --apply to actually serve")
        return 0
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind((args.address, TFTP_PORT))
    except PermissionError:
        print("ERROR: UDP/69 requires root; run with sudo", file=sys.stderr)
        return 1
    except OSError as exc:
        print("ERROR: bind failed: %s" % exc, file=sys.stderr)
        return 1
    sock.settimeout(args.timeout)
    server.sock = sock
    try:
        server.run()
    finally:
        sock.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())