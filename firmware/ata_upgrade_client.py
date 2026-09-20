#!/usr/bin/env python3
"""Loopback ATA firmware client simulator for Python firmware servers."""

from __future__ import annotations

import argparse
import hashlib
import socket
import struct
import sys
import time

try:
    from . import sata186us
except ImportError:
    import sata186us  # type: ignore


LOOPBACK = "127.0.0.1"
DEFAULT_COMMAND_PORT = 8000
DEFAULT_DATA_PORT = 8500
MAX_TIMEOUT_SECONDS = 10
MAX_SESSION_SECONDS = 60


class ClientError(ValueError):
    pass


class ClientResult:
    __slots__ = ("blocks", "payload_bytes", "payload_sha256",
                 "selection_normalized_sha256", "data_wire_sha256")

    def __init__(self, blocks: int, payload_bytes: int, payload_sha256: str,
                 selection_normalized_sha256: str, data_wire_sha256: str):
        self.blocks = blocks
        self.payload_bytes = payload_bytes
        self.payload_sha256 = payload_sha256
        self.selection_normalized_sha256 = selection_normalized_sha256
        self.data_wire_sha256 = data_wire_sha256


def build_selection_request() -> bytes:
    return sata186us.build_kbox_request(
        0x301, 0x400, 0x304, 0, "00000000", (0, 0, 0))


def validate_selection_response(packet: bytes, expected_url: str) -> None:
    if len(packet) != 0x90 or packet[:4] != sata186us.KBOX_MAGIC:
        raise ClientError("invalid KBOX response framing")
    if struct.unpack(">I", packet[4:8])[0] != sata186us.KBOX_RESPONSE_CODE:
        raise ClientError("invalid KBOX response code")
    area = packet[16:0x90]
    expected = expected_url.encode("ascii")
    expected += b"\x00" * (0x80 - len(expected))
    if area != expected or struct.unpack(">I", packet[12:16])[0] != sata186us.cksum(area):
        raise ClientError("invalid KBOX response URL or checksum")


def _request(sock: socket.socket, packet: bytes, endpoint: tuple[str, int],
             maximum: int, deadline: float) -> bytes:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ClientError("firmware simulator session timed out")
    sock.settimeout(min(sock.gettimeout() or remaining, remaining))
    sock.sendto(packet, endpoint)
    try:
        response, source = sock.recvfrom(maximum + 1)
    except socket.timeout as error:
        raise ClientError("firmware simulator request timed out") from error
    if source != endpoint:
        raise ClientError("firmware simulator received a response from the wrong relay")
    return response


def run_client(image_path: str, command_port: int = DEFAULT_COMMAND_PORT,
               data_port: int = DEFAULT_DATA_PORT, timeout_seconds: int = 5,
               expected_url: str = "udp: 10.0.2.15 8500 123") -> ClientResult:
    if not 1 <= command_port <= 65535 or not 1 <= data_port <= 65535:
        raise ClientError("simulator port is invalid")
    if not 1 <= timeout_seconds <= MAX_TIMEOUT_SECONDS:
        raise ClientError("simulator timeout is invalid")
    _digest, _info, store = sata186us.inspect_image(image_path)
    command_endpoint = (LOOPBACK, command_port)
    data_endpoint = (LOOPBACK, data_port)
    deadline = time.monotonic() + MAX_SESSION_SECONDS
    data_wire = hashlib.sha256()
    payload = hashlib.sha256()

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as command, \
            socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as data:
        command.bind((LOOPBACK, 0))
        data.bind((LOOPBACK, 0))
        command.settimeout(timeout_seconds)
        data.settimeout(timeout_seconds)

        selection = build_selection_request()
        response = _request(command, selection, command_endpoint, 0x90, deadline)
        validate_selection_response(response, expected_url)
        normalized_selection = response[:8] + b"\x00" * 4 + response[12:]
        selection_normalized_sha256 = hashlib.sha256(normalized_selection).hexdigest()

        hello_body = struct.pack(">IHH", 0, 0, 0)
        hello = struct.pack(">I", sata186us.cksum(hello_body)) + hello_body
        response = _request(data, hello, data_endpoint, 12, deadline)
        if response != sata186us.build_hello(store):
            raise ClientError("firmware hello does not match the selected image")
        data_wire.update(response)

        for index in range(len(store.sums)):
            body = struct.pack(">IHH", 0, index, sata186us.BLOCK_SIZE)
            request = struct.pack(">I", sata186us.cksum(body)) + body
            response = _request(
                data, request, data_endpoint, 8 + sata186us.BLOCK_SIZE, deadline)
            if response != sata186us.build_block(store, index):
                raise ClientError("firmware block does not match the selected image")
            data_wire.update(response)
            start = index * sata186us.BLOCK_SIZE
            payload.update(response[8:8 + min(sata186us.BLOCK_SIZE,
                                               store.total - start)])

    result = ClientResult(
        len(store.sums), store.total, payload.hexdigest(),
        selection_normalized_sha256, data_wire.hexdigest())
    print(f"ATA_SIM_COMPLETE blocks={result.blocks} bytes={result.payload_bytes} "
          f"payload_sha256={result.payload_sha256} "
          f"data_wire_sha256={result.data_wire_sha256} "
          f"selection_normalized_sha256={result.selection_normalized_sha256}")
    return result


def parse_options(argv: list[str]) -> argparse.Namespace:
    parser = sata186us.SafeArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--image")
    parser.add_argument("--command-port", type=int, default=DEFAULT_COMMAND_PORT)
    parser.add_argument("--data-port", type=int, default=DEFAULT_DATA_PORT)
    parser.add_argument("--timeout-seconds", type=int, default=5)
    return parser.parse_args(argv[1:])


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv
    args = parse_options(argv)
    if not args.run:
        print("DRY RUN: no simulator sockets or firmware files opened.")
        return 0
    if not args.image:
        print("error: --run requires --image", file=sys.stderr)
        return 1
    try:
        run_client(args.image, args.command_port, args.data_port,
                   args.timeout_seconds)
        return 0
    except Exception:
        print("error: ATA firmware client simulation failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
