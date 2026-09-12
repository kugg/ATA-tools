#!/usr/bin/env python3
"""Bounded ATA image tools, KBOX capture, and reusable firmware serving.

Bare invocation is inert. ``ata_flash.py`` owns the live DHCP and network
preflight; this module supplies the checked image and protocol implementation.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
import hashlib
import os
import select
import socket
import stat
import struct
import sys
import threading
import time
from typing import Any

VERSION = "3.1"
DEFAULT_PORT = 8000
DATA_PORT = 8500
BLOCK_SIZE = 0x400
KBOX_MAGIC = b"kbox"
KBOX_VERSION = 1
KBOX_RESPONSE_CODE = 0x102

MAX_IMAGE_BYTES = 512 * 1024
MAX_KBOX_DATA_BYTES = 256
MAX_KBOX_PACKET_BYTES = 16 + MAX_KBOX_DATA_BYTES
MAX_CAPTURE_SECONDS = 60
MAX_CAPTURE_PACKETS = 32
LOOPBACK_ADDRESS = "127.0.0.1"
MAX_SERVE_SECONDS = 24 * 60 * 60
MAX_SERVER_DATAGRAM_BYTES = 2048
PINNED_TARGET_SHA256 = "b8597657928905aea66924118889f0883bd38c0804ddf880e3be2c33ccf62eb5"
PINNED_TARGET_DATA_WIRE_SHA256 = (
    "158a9e2d5736f253cddcd1c4662b83792f996e0edd78b9eb5b6b1f34a279c7f2"
)
PINNED_SELECTION_NORMALIZED_SHA256 = (
    "6beddb21fc08c6518a8f1f3375030c3d5a56b3171c5ee7cb29e686a2fd9282f0"
)
PINNED_TARGET_PAYLOAD_BYTES = 319135
PINNED_TARGET_BLOCKS = 312


class SafeArgumentParser(argparse.ArgumentParser):
    """Keep parser diagnostics from echoing arbitrary command-line values."""

    def error(self, _message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, "error: invalid arguments\n")

    def fixed_error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, f"error: {message}\n")


def cksum(data: bytes | bytearray) -> int:
    """Byte sum (``cksum_n``)."""
    return sum(data) & 0xFFFFFFFF


def curtime(now: float | None = None) -> str:
    try:
        s = time.ctime(now)
    except Exception:
        return "<time unknown>"
    return s[:-1] if s.endswith("\n") else s


def ip_to_string(ip: bytes | bytearray) -> str:
    return ".".join(str(x) for x in bytes(ip[:4]))


# ---------------------------------------------------------------------------
# logging (logs/loga/openLog)

class Logger:
    """Emit fixed local status messages without creating persistent logs."""

    def __init__(self, out=None):
        self.out = sys.stdout if out is None else out

    def logs(self, fmt: str, *args) -> None:
        text = fmt % args if args else fmt
        self.out.write(text)
        self.out.flush()


# ---------------------------------------------------------------------------
# image database (newUpgradeInfo/setUpgradeInfo/whichUrl)

class UpgradeInfo:
    __slots__ = ("itype", "name", "platform", "proto", "version", "url")

    def __init__(self, itype: int, name: str, platform: int,
                 proto: int, version: int, url: str):
        self.itype = itype
        self.name = name
        self.platform = platform
        self.proto = proto
        self.version = version
        self.url = url


class UpgradeDB:
    """Ordered upgrade-info list with the original replacement rules."""

    def __init__(self):
        self.entries: list[UpgradeInfo | None] = []

    def set(self, itype: int, name: str, platform: int,
            proto: int, version: int, url: str) -> None:
        if len(url) >= 0x80 or len(name) >= 0x0B:
            return
        if not self.entries:
            self.entries.append(UpgradeInfo(itype, name, platform, proto, version, url))
            return
        new_is_default = (name == "00000000")
        free_slot: int | None = None
        last: UpgradeInfo | None = None
        for i, e in enumerate(self.entries):
            assert e is not None
            if not e.url:
                if free_slot is None:
                    free_slot = i
            elif (e.itype == itype and e.platform == platform
                    and e.name == name
                    and ((new_is_default and e.proto == proto) or not new_is_default)):
                e.platform = platform
                e.proto = proto
                e.version = version
                e.url = url
                return
            last = e
        if free_slot is None:
            self.entries.append(UpgradeInfo(itype, name, platform, proto, version, url))
        else:
            self.entries[free_slot] = UpgradeInfo(
                itype, name, platform, proto, version, url)

    def which(self, itype: int, name: str, platform: int,
              hw: int, sw: int) -> str:
        if itype == 0x105F09C6:
            return "testok"
        for e in self.entries:
            if e is None or not e.url:
                continue
            if e.itype == itype and e.platform == platform and e.name == name:
                if itype not in (0, 1):
                    return e.url
                if sw < e.version:
                    if hw <= e.proto:
                        return e.url
                elif sw == e.version and hw < e.proto:
                    return e.url
        for e in self.entries:
            if e is None or not e.url:
                continue
            if (e.itype == itype and e.platform == platform
                    and (e.proto == hw or e.proto == 0xFFFF)
                    and e.name == "00000000"):
                if itype not in (0, 1):
                    return e.url
                if sw < e.version:
                    return e.url
        return "none"


# ---------------------------------------------------------------------------
# human-readable version strings (versionStr/requestTypeStr)

def _proto_suffix_182(proto: int) -> str:
    return {0x1000: "h323.v", 0x2000: "nf.v", 0x3000: "sip.v",
            0x9000: "yap.v"}.get(proto, f"0x{proto:04x}." if proto != 0xFFFF else "anyv")


def _proto_suffix_186(proto: int) -> str:
    if proto == 0x400:
        return "itsp2.v"
    if proto == 0x100:
        return "h323.v"
    if proto == 0xFFFF:
        return "anyv"
    return f"0x{proto:04x}."


def version_str(platform: int, proto: int, version: int) -> str:
    needs_hint = False
    if platform == 0x201:
        s = "ata182." + _proto_suffix_182(proto)
        needs_hint = proto == 0xFFFF
    elif platform == 0x301:
        s = "ata186." + _proto_suffix_186(proto)
        needs_hint = proto == 0xFFFF
    elif platform == 0x401:
        s = "7902." + ("kn.v" if proto == 0x400 else
                       ("anyv" if proto == 0xFFFF else f"0x{proto:04x}."))
        needs_hint = proto == 0xFFFF
    elif platform == 0x501:
        s = "7905." + ("kn.v" if proto == 0x400 else
                       ("anyv" if proto == 0xFFFF else f"0x{proto:04x}."))
        needs_hint = proto == 0xFFFF
    elif platform == 0x601:
        s = "7912." + ("kn.v" if proto == 0x400 else
                       ("anyv" if proto == 0xFFFF else f"0x{proto:04x}."))
        needs_hint = proto == 0xFFFF
    elif platform == 0x40101:
        if proto == 2:
            s = "kf200.h323.v"
        elif proto == 0:
            s = "kf200.nf.v"
        elif proto == 1:
            s = "kf200.sip.v"
        elif proto == 9:
            s = "kf200.yap.v"
        elif proto == 0xFFFF:
            s = "kf200.anyv"
            needs_hint = True
        else:
            s = f"kf200.0x{proto:04x}."
    else:
        s = f"ata(0x{platform:04x},0x{proto:04x})"
    if version == 0xFFFF:
        s += "anyv"
        needs_hint = True
    else:
        s += f"{version >> 8}.{version & 0xFF}"
    if needs_hint:
        s += "\t(use 57123# for uploaded version)"
    return s


def request_type_str(code: int) -> str:
    if code == 100:
        return "code"
    return f"language {code - 0x32}"


def ivr_code(base_type: int) -> int:
    return base_type + 100 if base_type < 0x33 else base_type + 0x32


# ---------------------------------------------------------------------------
# image file parsing (CutHeader/readKUp1Info/checkKSum/makeSum)

def get_int(b: bytes | bytearray) -> int:
    return struct.unpack(">I", bytes(b[:4]))[0]


def check_image(payload: bytes) -> None:
    """Validate the complete supported envelope before it can be served."""
    if payload.startswith(b"+kxz") and len(payload) >= 12:
        expected = get_int(payload[4:8])
        actual = cksum(payload[12:])
    elif payload[:3] == b"+kb" and payload[3:4] in (b"z", b"x") and len(payload) >= 24:
        expected = get_int(payload[8:12])
        actual = cksum(payload[24:])
    else:
        raise ValueError("unsupported or truncated upgrade envelope")
    if expected != actual:
        raise ValueError("corrupted upgrade image")


class ImageInfo:
    __slots__ = ("base_type", "name", "platform", "proto", "version")

    def __init__(self, base_type: int, name: str, platform: int,
                 proto: int, version: int):
        self.base_type = base_type
        self.name = name
        self.platform = platform
        self.proto = proto
        self.version = version


def parse_image_header(raw: bytes) -> ImageInfo:
    """``readKUp1Info`` header parse: 24-byte ``kup1`` header.

    Returns validated raw on-disk metadata for offline inspection or policy
    comparison. Wildcard upgrade matching is intentionally unsupported.
    """
    if len(raw) < 24 or raw[:4] != b"kup1":
        raise ValueError("invalid upgrade image header")
    name_raw = raw[4:12].split(b"\x00", 1)[0]
    if not name_raw or any(byte < 0x20 or byte > 0x7E for byte in name_raw):
        raise ValueError("invalid upgrade image name")
    base_type = struct.unpack(">I", raw[12:16])[0]
    name = name_raw.decode("ascii")
    platform = struct.unpack(">I", raw[16:20])[0]
    proto = struct.unpack(">H", raw[20:22])[0]
    version = struct.unpack(">H", raw[22:24])[0]
    return ImageInfo(base_type, name, platform, proto, version)


class BlockStore:
    __slots__ = ("data", "total", "sums")

    def __init__(self, data: bytes, total: int, sums: list[int]):
        self.data = data          # zero-padded image payload
        self.total = total        # exact payload length
        self.sums = sums          # per-1024 block byte sums


def make_block_store(raw: bytes, info: ImageInfo) -> BlockStore:
    """``CutHeader`` tail + ``makeSum``: payload blocks with zero padding."""
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError("upgrade image exceeds the serving limit")
    payload = raw[24:]
    check_image(payload)
    if payload.startswith(b"+kxz"):
        try:
            from . import zup_bank
        except ImportError:
            import zup_bank  # type: ignore
        zup_bank.build_bank(raw)
    total = len(payload)
    if total == 0:
        raise ValueError("upgrade image has no payload")
    padded_len = (total + 0x3FF) & ~0x3FF
    data = payload + b"\x00" * (padded_len - total)
    sums = [cksum(data[i:i + BLOCK_SIZE]) for i in range(0, padded_len, BLOCK_SIZE)]
    if total % BLOCK_SIZE == 0 and total > 0:
        sums = sums[: total // BLOCK_SIZE]
    return BlockStore(data, total, sums)


def build_hello(store: BlockStore) -> bytes:
    body = struct.pack(">IHH", store.total, 0, BLOCK_SIZE)
    return struct.pack(">I", cksum(body)) + body


def build_block(store: BlockStore, index: int) -> bytes:
    body = (struct.pack(">HH", index & 0xFFFF, BLOCK_SIZE)
            + store.data[index * BLOCK_SIZE:(index + 1) * BLOCK_SIZE])
    body = body[:4 + BLOCK_SIZE]
    if len(body) < 4 + BLOCK_SIZE:
        body = body + b"\x00" * (4 + BLOCK_SIZE - len(body))
    return struct.pack(">I", cksum(body)) + body


# ---------------------------------------------------------------------------
# urlup.rc shared list (enterUpgradeInfo)

def _split_ws_tokens(s: str) -> list[str]:
    toks: list[str] = []
    cur: list[str] = []
    in_tok = False
    for ch in s:
        if ch in ", \t":
            if in_tok:
                toks.append("".join(cur))
                cur = []
                in_tok = False
        elif ch in "\r\n":
            break
        else:
            cur.append(ch)
            in_tok = True
    if in_tok:
        toks.append("".join(cur))
    return toks


def enter_upgrade_info(line: str, db: UpgradeDB) -> bool:
    """``enterUpgradeInfo``: ``name,int,0x..,0x..,0x..,url`` lines."""
    toks = _split_ws_tokens(line)
    if len(toks) != 6:
        return False
    try:
        name = toks[0]
        a = int(toks[1], 0)
        b = int(toks[2], 0)
        c = int(toks[3], 0)
        d = int(toks[4], 0)
        url = toks[5]
    except ValueError:
        return False
    db.set(a, name, b, c, d, url)
    return True


# ---------------------------------------------------------------------------
# Request metadata used by read-only capture

class HeaderSpec:
    __slots__ = ("name", "base_type", "platform", "proto", "version", "sha256")

    def __init__(self, name: str, base_type: int, platform: int, proto: int,
                 version: int, sha256: str | None = None):
        self.name = name
        self.base_type = base_type
        self.platform = platform
        self.proto = proto
        self.version = version
        self.sha256 = sha256

def inspect_image(path: str) -> tuple[str, ImageInfo, BlockStore]:
    """Return bounded image metadata after validating its internal envelope."""
    flags = (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
             | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0))
    try:
        fd = os.open(path, flags)
    except OSError as error:
        raise ValueError("cannot open firmware image") from error
    try:
        details = os.fstat(fd)
        if not stat.S_ISREG(details.st_mode) or details.st_size > MAX_IMAGE_BYTES:
            raise ValueError("firmware image is not a bounded regular file")
        with os.fdopen(fd, "rb") as file:
            fd = -1
            raw = file.read(MAX_IMAGE_BYTES + 1)
    except OSError as error:
        raise ValueError("cannot read firmware image") from error
    finally:
        if fd >= 0:
            os.close(fd)
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError("firmware image exceeds the serving limit")
    digest = hashlib.sha256(raw).hexdigest()
    info = parse_image_header(raw)
    store = make_block_store(raw, info)
    return digest, info, store


def build_kbox_request(platform: int, proto: int, version: int, itype: int,
                       name: str, extra: tuple[int, int, int]) -> bytes:
    data = (struct.pack(">III", platform, (proto << 16) | version, itype)
            + ("%s %d %d %d" % (name, *extra)).encode("latin-1"))
    return (KBOX_MAGIC + struct.pack(">I", KBOX_VERSION)
            + struct.pack(">H", len(data)) + b"\x00\x00"
            + struct.pack(">I", cksum(data)) + data)


def _parse_kbox_request_with_reason(pkt: bytes, allow_trailing: bool = False):
    if len(pkt) < 16 or pkt[:4] != KBOX_MAGIC:
        return None, "not_kbox"
    (ver,) = struct.unpack(">I", pkt[4:8])
    if ver != KBOX_VERSION:
        return None, "version"
    (ln,) = struct.unpack(">H", pkt[8:10])
    if ln > MAX_KBOX_DATA_BYTES or len(pkt) < 16 + ln \
            or not allow_trailing and len(pkt) != 16 + ln:
        return None, "framing"
    (want,) = struct.unpack(">I", pkt[12:16])
    data = pkt[16:16 + ln]
    if len(data) < ln or cksum(data) != want:
        return None, "checksum"
    if len(data) < 12:
        return None, "metadata"
    h, sv, t = struct.unpack(">III", data[:12])
    raw_name = data[12:].split(b"\x00", 1)[0]
    if any(byte < 0x20 or byte > 0x7E for byte in raw_name):
        return None, "metadata"
    rest = raw_name.decode("ascii")
    toks = rest.split()
    name = toks[0] if toks else ""
    nums: list[int] = []
    for tok in toks[1:4]:
        try:
            nums.append(int(tok, 0))
        except ValueError:
            return None, "metadata"
    while len(nums) < 3:
        nums.append(0)
    return (h, sv, t, name, nums[0], nums[1], nums[2]), None


def parse_kbox_request(pkt: bytes):
    parsed, _reason = _parse_kbox_request_with_reason(pkt)
    return parsed


def parse_legacy_kbox_request(pkt: bytes):
    """Parse the bounded declared KBOX payload and ignore legacy UDP padding."""
    parsed, _reason = _parse_kbox_request_with_reason(pkt, allow_trailing=True)
    return parsed


def capture_request_metadata(pkt: bytes) -> HeaderSpec | None:
    """Return only policy-safe request metadata; never retain the raw packet."""
    metadata, _reason = _capture_request_metadata_with_reason(pkt)
    return metadata


def _capture_request_metadata_with_reason(
        pkt: bytes) -> tuple[HeaderSpec | None, str | None]:
    parsed, reason = _parse_kbox_request_with_reason(pkt)
    if parsed is None:
        return None, reason
    platform, source_version, base_type, name, _a, _b, _c = parsed
    if not name or len(name) > 8:
        return None, "metadata"
    return (HeaderSpec(name, base_type, platform,
                       (source_version >> 16) & 0xFFFF,
                       source_version & 0xFFFF), None)


def capture_kbox_metadata(main_sock: Any, peer_address: str,
                           duration_seconds: int, logger: Logger) -> HeaderSpec | None:
    """Collect one exact-peer KBOX header without transmitting a response."""
    if not 1 <= duration_seconds <= MAX_CAPTURE_SECONDS:
        raise ValueError("capture duration exceeds the safe limit")
    deadline = time.monotonic() + duration_seconds
    packets_seen = 0
    expected_peer_packets = 0
    other_peer_packets = 0
    oversized_packets = 0
    invalid_packets = 0
    rejection_counts = {
        "not_kbox": 0,
        "version": 0,
        "framing": 0,
        "checksum": 0,
        "metadata": 0,
    }
    logger.logs("Read-only KBOX capture ready; no responses will be sent.\n")
    while time.monotonic() < deadline and packets_seen < MAX_CAPTURE_PACKETS:
        timeout = min(0.25, max(0.0, deadline - time.monotonic()))
        readable, _, _ = select.select((main_sock,), (), (), timeout)
        if not readable:
            continue
        packet, address = main_sock.recvfrom(MAX_KBOX_PACKET_BYTES + 1)
        packets_seen += 1
        if address[0] != peer_address:
            other_peer_packets += 1
            continue
        expected_peer_packets += 1
        if len(packet) > MAX_KBOX_PACKET_BYTES:
            oversized_packets += 1
            continue
        metadata, reason = _capture_request_metadata_with_reason(packet)
        if metadata is not None:
            logger.logs("Read-only KBOX metadata captured; no response was sent.\n")
            return metadata
        invalid_packets += 1
        assert reason is not None
        rejection_counts[reason] += 1
    logger.logs(
        "Read-only KBOX capture ended without valid metadata "
        "(datagrams=%d, expected_peer=%d, other_peer=%d, oversized=%d, "
        "invalid=%d, not_kbox=%d, version=%d, framing=%d, checksum=%d, "
        "metadata=%d, packet_limit_reached=%d).\n",
        packets_seen, expected_peer_packets, other_peer_packets, oversized_packets,
        invalid_packets, rejection_counts["not_kbox"], rejection_counts["version"],
        rejection_counts["framing"], rejection_counts["checksum"],
        rejection_counts["metadata"], int(packets_seen >= MAX_CAPTURE_PACKETS))
    return None


def build_kbox_response(url: str) -> bytes:
    area = url.encode("latin-1")
    if len(area) >= 0x80:
        raise ValueError("upgrade URL exceeds the protocol limit")
    area = area + b"\x00" * (0x80 - len(area))
    return (KBOX_MAGIC + struct.pack(">I", KBOX_RESPONSE_CODE)
            + b"\x00\x00\x00\x00" + struct.pack(">I", cksum(area)) + area)


def parse_data_request(packet: bytes) -> int | None:
    """Return a block index, or ``None`` for the legacy stream hello."""
    if len(packet) < 12 or len(packet) > MAX_SERVER_DATAGRAM_BYTES:
        raise ValueError("invalid firmware data request length")
    body = packet[4:12]
    if get_int(packet) != cksum(body):
        raise ValueError("invalid firmware data request checksum")
    _stream, index, size = struct.unpack(">IHH", body)
    if size == 0:
        return None
    if size != BLOCK_SIZE:
        raise ValueError("invalid firmware block size")
    return index


class ServerResult:
    __slots__ = (
        "command_requests", "command_responses", "command_request_bytes",
        "command_response_bytes", "data_requests", "data_responses",
        "data_request_bytes", "data_response_bytes", "invalid_requests",
        "rejected_requests", "unique_blocks", "total_blocks",
    )

    def __init__(self, total_blocks: int):
        self.command_requests = 0
        self.command_responses = 0
        self.command_request_bytes = 0
        self.command_response_bytes = 0
        self.data_requests = 0
        self.data_responses = 0
        self.data_request_bytes = 0
        self.data_response_bytes = 0
        self.invalid_requests = 0
        self.rejected_requests = 0
        self.unique_blocks: set[int] = set()
        self.total_blocks = total_blocks

    @property
    def complete(self) -> bool:
        return len(self.unique_blocks) == self.total_blocks


def _send_packet(sock: Any, packet: bytes, address: tuple[str, int]) -> None:
    if sock.sendto(packet, address) != len(packet):
        raise OSError("short UDP response")


def serve_firmware(command_sock: Any, data_sock: Any, info: ImageInfo,
                   store: BlockStore, advertised_address: str,
                   advertised_data_port: int, expected_peer_address: str,
                   duration_seconds: int, logger: Logger,
                   stop_event: threading.Event | None = None,
                   completion_grace_seconds: float | None = None,
                   safety_check: Callable[[], bool] | None = None) -> ServerResult:
    """Serve one bounded image reactively on two already-bound UDP sockets."""
    if not 1 <= duration_seconds <= MAX_SERVE_SECONDS:
        raise ValueError("firmware service duration exceeds the safe limit")
    if not 1 <= advertised_data_port <= 65535:
        raise ValueError("firmware data port is invalid")
    try:
        socket.inet_aton(advertised_address)
        socket.inet_aton(expected_peer_address)
    except OSError as error:
        raise ValueError("firmware service address is invalid") from error
    if completion_grace_seconds is not None \
            and not 0 <= completion_grace_seconds <= duration_seconds:
        raise ValueError("firmware completion grace exceeds the service duration")

    result = ServerResult(len(store.sums))
    selected = False
    deadline = time.monotonic() + duration_seconds
    completion_deadline: float | None = None
    completion_logged = False
    upgrade_url = f"udp: {advertised_address} {advertised_data_port} 123"

    while time.monotonic() < deadline:
        if stop_event is not None and stop_event.is_set():
            break
        if completion_deadline is not None and time.monotonic() >= completion_deadline:
            break
        timeout = min(0.1, max(0.0, deadline - time.monotonic()))
        readable, _, _ = select.select((command_sock, data_sock), (), (), timeout)
        for current in readable:
            packet, address = current.recvfrom(MAX_SERVER_DATAGRAM_BYTES + 1)
            rejected = (address[0] != expected_peer_address or not packet
                         or len(packet) > MAX_SERVER_DATAGRAM_BYTES)
            if rejected:
                result.rejected_requests += 1
                continue

            if current is command_sock:
                result.command_requests += 1
                result.command_request_bytes += len(packet)
            else:
                result.data_requests += 1
                result.data_request_bytes += len(packet)

            if current is command_sock:
                parsed = parse_legacy_kbox_request(packet)
                if parsed is None:
                    result.invalid_requests += 1
                    continue
                platform, _source_version, base_type, _name, _a, _b, _c = parsed
                selected = base_type == info.base_type and platform == info.platform
                response = build_kbox_response(upgrade_url if selected else "none")
                if safety_check is not None and not safety_check():
                    raise OSError("firmware service safety check failed")
                _send_packet(command_sock, response, address)
                result.command_responses += 1
                result.command_response_bytes += len(response)
                continue

            if not selected:
                result.invalid_requests += 1
                continue
            try:
                index = parse_data_request(packet)
            except ValueError:
                result.invalid_requests += 1
                continue
            if index is None:
                response = build_hello(store)
            elif index >= len(store.sums):
                result.invalid_requests += 1
                continue
            else:
                response = build_block(store, index)
            if safety_check is not None and not safety_check():
                raise OSError("firmware service safety check failed")
            _send_packet(data_sock, response, address)
            result.data_responses += 1
            result.data_response_bytes += len(response)
            if index is not None:
                first_block = not result.unique_blocks
                result.unique_blocks.add(index)
                if first_block and index == 0:
                    logger.logs("Python firmware transfer started.\n")
                if result.complete and not completion_logged:
                    logger.logs(
                        "Python firmware response stream complete "
                        "(blocks=%d, payload_bytes=%d).\n",
                        len(result.unique_blocks), store.total)
                    completion_logged = True
            if result.complete and completion_grace_seconds is not None:
                completion_deadline = time.monotonic() + completion_grace_seconds
    return result


def inspect_pinned_target(path: str) -> tuple[str, ImageInfo, BlockStore]:
    digest, info, store = inspect_image(path)
    identity = (
        digest, info.base_type, info.name, info.platform, info.proto,
        info.version, store.total, len(store.sums),
    )
    expected = (
        PINNED_TARGET_SHA256, 0, "00000000", 0x301, 0x400, 0x301,
        PINNED_TARGET_PAYLOAD_BYTES, PINNED_TARGET_BLOCKS,
    )
    if identity != expected:
        raise ValueError("firmware image is not the pinned SIP target")
    return digest, info, store


def run_loopback_qualification(image_path: str, logger: Logger) -> int:
    """Run the existing ATA simulator against this Python server only."""
    try:
        from . import ata_upgrade_client
    except ImportError:
        import ata_upgrade_client  # type: ignore

    _digest, info, store = inspect_pinned_target(image_path)
    stop_event = threading.Event()
    server_result: list[ServerResult] = []
    server_errors: list[BaseException] = []
    with bind_udp(LOOPBACK_ADDRESS, 0) as command_sock, \
            bind_udp(LOOPBACK_ADDRESS, 0) as data_sock:
        command_port = int(command_sock.getsockname()[1])
        data_port = int(data_sock.getsockname()[1])

        def run_server() -> None:
            try:
                server_result.append(serve_firmware(
                    command_sock, data_sock, info, store, "10.0.2.15", DATA_PORT,
                    LOOPBACK_ADDRESS, 30, logger, stop_event,
                    completion_grace_seconds=0))
            except BaseException as error:
                server_errors.append(error)

        thread = threading.Thread(target=run_server, name="ata-python-qualify")
        thread.start()
        try:
            client_result = ata_upgrade_client.run_client(
                image_path, command_port, data_port, 2,
                expected_url="udp: 10.0.2.15 8500 123")
        finally:
            stop_event.set()
            thread.join(timeout=2)
    if thread.is_alive():
        raise ValueError("Python firmware qualification server did not stop")
    if server_errors:
        raise ValueError("Python firmware qualification server failed") from server_errors[0]
    if len(server_result) != 1:
        raise ValueError("Python firmware qualification has no server result")
    result = server_result[0]
    expected_counts = (
        1, 1, 313, 313, 42, 144, 3756, 321996,
        0, 0, PINNED_TARGET_BLOCKS,
    )
    actual_counts = (
        result.command_requests, result.command_responses,
        result.data_requests, result.data_responses,
        result.command_request_bytes, result.command_response_bytes,
        result.data_request_bytes, result.data_response_bytes,
        result.invalid_requests, result.rejected_requests,
        len(result.unique_blocks),
    )
    if actual_counts != expected_counts or not result.complete:
        raise ValueError("Python firmware qualification totals do not match")
    if client_result.data_wire_sha256 != PINNED_TARGET_DATA_WIRE_SHA256:
        raise ValueError("Python firmware response stream differs from QEMU reference")
    if client_result.selection_normalized_sha256 \
            != PINNED_SELECTION_NORMALIZED_SHA256:
        raise ValueError("Python firmware selection differs from QEMU reference")
    print("PYTHON_SERVER_QUALIFIED command=1/1:42/144 "
          "data=313/313:3756/321996 blocks=312 payload_bytes=319135 "
          f"data_wire_sha256={client_result.data_wire_sha256}")
    return 0


def drain_udp(sock: Any, max_datagrams: int = 4096) -> int:
    """Discard a bounded pre-service receive queue or fail if it stays busy."""
    if max_datagrams < 1:
        raise ValueError("firmware queue drain limit is invalid")
    drained = 0
    while True:
        readable, _, _ = select.select((sock,), (), (), 0)
        if not readable:
            return drained
        if drained >= max_datagrams:
            raise ValueError("firmware socket queue did not quiesce")
        try:
            sock.recvfrom(MAX_SERVER_DATAGRAM_BYTES + 1)
        except BlockingIOError:
            return drained
        drained += 1


def bind_udp(address: str, port: int, interface: str | None = None) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        if interface is not None:
            interface_index = socket.if_nametoindex(interface)
            if sys.platform == "darwin":
                # Darwin's public IP_BOUND_IF value is not exported by Python.
                sock.setsockopt(socket.IPPROTO_IP, 25, interface_index)
            elif hasattr(socket, "SO_BINDTODEVICE"):
                sock.setsockopt(
                    socket.SOL_SOCKET, socket.SO_BINDTODEVICE,
                    interface.encode("ascii") + b"\x00")
        sock.bind((address, port))
        sock.setblocking(False)
    except BaseException:
        sock.close()
        raise
    return sock


def parse_options(argv: list[str]) -> argparse.Namespace:
    parser = SafeArgumentParser(prog="sata186us.py", description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--inspect", metavar="IMAGE",
                      help="validate and print local image metadata without sockets")
    mode.add_argument("--qualify", metavar="IMAGE",
                      help="serve the pinned image to the loopback ATA simulator")
    return parser.parse_args(argv[1:])


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv
    args = parse_options(argv)
    if args.inspect:
        try:
            digest, info, store = inspect_image(args.inspect)
        except Exception:
            print("error: firmware image refused by its safety checks", file=sys.stderr)
            return 1
        print(f"sha256={digest}")
        print(f"name={info.name}")
        print(f"base_type=0x{info.base_type:08x}")
        print(f"platform=0x{info.platform:08x}")
        print(f"proto=0x{info.proto:04x}")
        print(f"version=0x{info.version:04x}")
        print(f"payload_bytes={store.total}")
        return 0
    if args.qualify:
        try:
            return run_loopback_qualification(args.qualify, Logger())
        except Exception:
            print("error: Python firmware qualification failed closed", file=sys.stderr)
            return 1
    print("DRY RUN: no sockets or firmware files opened; use --inspect or "
          "--qualify. Use ata_flash.py for live service.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
