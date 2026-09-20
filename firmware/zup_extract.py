#!/usr/bin/env python3
"""Decompose a legacy ATA ``+kxz`` package into an editable directory and back.

``extract`` writes one new private directory holding the exact 512 KiB bank,
a JSON manifest (map, launch headers/records, section checksum, payload
inventory with hashes), and the expanded type-8/nested payloads. ``compose``
rebuilds a bank from such a directory: edited launch records are validated
and written back, edited payloads are recompressed in place (raw DEFLATE plus
the legacy trailer) and spliced into their original spans, and anything that
no longer fits fails closed. Feed a composed bank to ``zup_rebuild.py`` with
the original template to obtain a new package, then re-extract it to verify.

Changed compressed output is encoded with the local zlib and is therefore
structural, not a byte-faithful reproduction of the historical streams;
unchanged regions stay byte-identical through ``zup_rebuild.py``. Modified
packages must stay off hardware until a separate authenticity, recovery, and
maintenance review approves them. Offline only: no sockets, no vendor
execution, no overwrite of existing paths.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import struct
import subprocess
import sys
import zlib

if __package__:
    from . import zup_bank
else:
    import zup_bank


MANIFEST_FORMAT = "ata-zup-extract/1"
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_PAYLOAD_FILES = 32
MAX_PAYLOAD_BYTES = zup_bank.BANK_BYTES
HEADER_CANDIDATES = (0x0, 0x40000, 0x40100, 0x70000)
SECTION_OFFSET = 0x40000
SECTION_MAGIC = 0x12340004
CHECKSUM_SEED = 0xDEADBEEF
COMPRESSION_LEVEL = 9
KNOWN_RECORD_TYPES = frozenset(
    (1, 2, 3, 4, 5, 6, 7, 8, 9, 0xA, 0xB, 0xC, 0xD))
DISASM_ARCH = "mipsx"
DISASM_BASEPC = zup_bank.RUNTIME_BANK_BASE


class SafeArgumentParser(argparse.ArgumentParser):
    """Keep parser diagnostics from echoing arbitrary command-line values."""

    def error(self, _message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, "error: invalid arguments\n")


def _find_unidasm() -> str | None:
    """Return the path to unidasm if found, else None."""
    path = shutil.which("unidasm")
    if path:
        return path
    for candidate in ("/usr/local/bin/unidasm", "/opt/homebrew/bin/unidasm"):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def _disasm_bank(bank_path: str, out_dir: str) -> str | None:
    """Run MAME unidasm on bank.bin; return output path or None if skipped."""
    unidasm = _find_unidasm()
    if not unidasm:
        return None
    bank_size = os.path.getsize(bank_path)
    if bank_size != zup_bank.BANK_BYTES:
        return None
    disasm_path = os.path.join(out_dir, "disasm.txt")
    try:
        result = subprocess.run(
            [unidasm, bank_path, "-arch", DISASM_ARCH,
             "-basepc", f"0x{DISASM_BASEPC:X}"],
            capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            return None
        _write_private(disasm_path, result.stdout.encode())
        return disasm_path
    except (subprocess.TimeoutExpired, OSError):
        return None


def _read_u32(bank: bytes, offset: int) -> int:
    if offset < 0 or offset % 4 or offset + 4 > len(bank):
        raise ValueError("bank offset is out of bounds")
    return struct.unpack_from(">I", bank, offset)[0]


def _section_info(bank: bytes) -> dict | None:
    """Return the staged checksum description, or None when absent."""
    if len(bank) != zup_bank.BANK_BYTES:
        raise ValueError("section check requires one complete bank")
    if SECTION_OFFSET + 24 > len(bank):
        raise ValueError("section header is out of bounds")
    magic = _read_u32(bank, SECTION_OFFSET)
    if magic != SECTION_MAGIC:
        return None
    stored = _read_u32(bank, SECTION_OFFSET + 4)
    descriptors = [_read_u32(bank, SECTION_OFFSET + 8 + 4 * i) for i in range(4)]
    calculated = CHECKSUM_SEED
    for descriptor in descriptors:
        start = (descriptor >> 16) << 8
        size = (descriptor & 0xFFFF) << 8
        if not size or start % 4 or size % 4 \
                or start + size > len(bank) or start + size < start:
            raise ValueError("section descriptor is invalid")
        for offset in range(start, start + size, 4):
            calculated ^= _read_u32(bank, offset)
    return {"offset": SECTION_OFFSET, "magic": magic, "stored": stored,
            "calculated": calculated & 0xFFFFFFFF,
            "descriptors": descriptors}


def _scan_nested(bank: bytes) -> list:
    """Return bank offsets of parseable ``+kbz`` payloads in order."""
    found = []
    for offset in range(0, len(bank) - zup_bank.NESTED_HEADER_BYTES + 1, 4):
        if bank[offset:offset + 4] != b"+kbz":
            continue
        try:
            zup_bank.parse_nested_payload(bank, offset)
        except ValueError:
            continue
        found.append(offset)
        if len(found) > zup_bank.MAX_NESTED_PAYLOADS:
            raise ValueError("nested payload count exceeds bounded limit")
    return found


def _write_private(path: str, content: bytes) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(parent):
        raise ValueError("output parent is not a directory")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                         | getattr(os, "O_CLOEXEC", 0)
                         | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _spans_overlap(start_a: int, end_a: int, start_b: int, end_b: int) -> bool:
    return start_a < end_b and start_b < end_a


def extract_package(package: bytes, out_dir: str, disasm: bool = False) -> dict:
    """Decompose one validated package into a new private directory."""
    if len(package) < zup_bank.OUTER_BYTES + zup_bank.INNER_HEADER_BYTES \
            or len(package) > zup_bank.MAX_PACKAGE_BYTES:
        raise ValueError("package size is invalid")
    result = zup_bank.build_bank(package)
    bank = result.data
    try:
        os.mkdir(out_dir, 0o700)
    except FileExistsError as exc:
        raise ValueError("refusing to overwrite an existing output") from exc
    os.chmod(out_dir, 0o700)
    payload_dir = os.path.join(out_dir, "payloads")
    os.mkdir(payload_dir, 0o700)
    os.chmod(payload_dir, 0o700)

    section = _section_info(bank)
    headers = []
    for offset in HEADER_CANDIDATES:
        try:
            table = zup_bank.parse_launch_table(bank, offset)
        except ValueError:
            continue
        headers.append({
            "header_offset": table.header_offset,
            "field0": table.field0,
            "table_address": table.table_address,
            "table_offset": table.table_offset,
            "record_count": table.record_count,
            "field3": table.field3,
            "records": [{
                "offset": record.offset,
                "type": record.record_type,
                "field1": record.field1,
                "field2": record.field2,
                "field3": record.field3,
            } for record in table.records],
        })
    if len(headers) > zup_bank.MAX_LAUNCH_HEADERS:
        raise ValueError("launch header count exceeds bounded limit")

    type8_offsets: list[int] = []
    for header in headers:
        for record in header["records"]:
            if record["type"] != 8:
                continue
            address = record["field1"]
            if not zup_bank.RUNTIME_BANK_BASE <= address \
                    < zup_bank.RUNTIME_BANK_BASE + len(bank):
                raise ValueError("type-8 record address is outside the bank")
            offset = address - zup_bank.RUNTIME_BANK_BASE
            if offset not in type8_offsets:
                type8_offsets.append(offset)
    if len(type8_offsets) > zup_bank.MAX_TYPE8_PAYLOADS:
        raise ValueError("type-8 payload count exceeds bounded limit")

    payloads = []
    budget = zup_bank.MAX_TYPE8_OUTPUT_BYTES
    for offset in sorted(type8_offsets):
        payload = zup_bank.parse_type8_payload(bank, offset, budget)
        budget -= payload.output_size
        name = f"type8_0x{offset:x}.bin"
        _write_private(os.path.join(payload_dir, name), payload.data)
        payloads.append({
            "kind": "type8", "offset": offset, "file": f"payloads/{name}",
            "mode": payload.mode, "field": payload.field,
            "compressed_size": payload.compressed_size,
            "output_size": payload.output_size, "crc32": payload.crc32,
            "sha256": hashlib.sha256(payload.data).hexdigest(),
        })
    nested_budget = zup_bank.MAX_NESTED_OUTPUT_BYTES
    for offset in _scan_nested(bank):
        payload = zup_bank.parse_nested_payload(bank, offset, nested_budget)
        nested_budget -= payload.output_size
        name = f"nested_0x{offset:x}.bin"
        _write_private(os.path.join(payload_dir, name), payload.data)
        payloads.append({
            "kind": "nested", "offset": offset, "file": f"payloads/{name}",
            "mode": None, "field": None,
            "compressed_size": payload.stored_size,
            "output_size": payload.output_size, "crc32": payload.crc32,
            "sha256": hashlib.sha256(payload.data).hexdigest(),
        })
    if len(payloads) > MAX_PAYLOAD_FILES:
        raise ValueError("payload count exceeds bounded limit")

    manifest = {
        "format": MANIFEST_FORMAT,
        "package_sha256": hashlib.sha256(package).hexdigest(),
        "bank_sha256": hashlib.sha256(bank).hexdigest(),
        "map_version": result.format_version,
        "raw_regions": [{
            "source": item.source, "destination": item.destination,
            "size": item.size} for item in result.raw_regions],
        "compressed_regions": [{
            "source": item.source, "destination": item.destination,
            "output_size": item.output_size, "stored_size": item.stored_size,
            "crc32": item.crc32} for item in result.compressed_regions],
        "section": section,
        "launch_headers": headers,
        "payloads": payloads,
    }
    _write_private(os.path.join(out_dir, "bank.bin"), bank)
    if disasm:
        bank_path = os.path.join(out_dir, "bank.bin")
        disasm_path = _disasm_bank(bank_path, out_dir)
        if disasm_path:
            manifest["disasm"] = disasm_path
    _write_private(os.path.join(out_dir, "manifest.json"),
                   json.dumps(manifest, indent=2, sort_keys=True).encode())
    return manifest


def _require_int(value: object, name: str, low: int, high: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) \
            or not low <= value <= high:
        raise ValueError(f"manifest field {name} is invalid")
    return value


def _load_manifest(path: str) -> dict:
    raw = _read_regular_file(path, MAX_MANIFEST_BYTES, "manifest")
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("manifest is not valid JSON") from exc
    if not isinstance(manifest, dict) or manifest.get("format") != MANIFEST_FORMAT:
        raise ValueError("manifest format is unsupported")
    return manifest


def _read_regular_file(path: str, limit: int, description: str) -> bytes:
    """Read one bounded regular file without following or racing a symlink."""
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_NONBLOCK"):
        raise ValueError(f"secure {description} opening is unavailable")
    before = os.lstat(path)
    if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
        raise ValueError(f"{description} must be a bounded regular file")
    descriptor = os.open(
        path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        | getattr(os, "O_CLOEXEC", 0))
    try:
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode) or details.st_size > limit \
                or (details.st_dev, details.st_ino) != (
                    before.st_dev, before.st_ino):
            raise ValueError(f"{description} must be a bounded regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as input_file:
            data = input_file.read(limit + 1)
        after = os.fstat(descriptor)
        if len(data) != details.st_size or (
                after.st_dev, after.st_ino, after.st_size,
                after.st_mtime_ns, after.st_ctime_ns) != (
                details.st_dev, details.st_ino, details.st_size,
                details.st_mtime_ns, details.st_ctime_ns):
            raise ValueError(f"{description} changed while being read")
        return data
    finally:
        os.close(descriptor)


def _validate_records(table_offset: int, count: int,
                      records: list) -> list[tuple[int, int, int, int]]:
    if len(records) != count:
        raise ValueError("record count changed; relocation is unsupported")
    parsed = []
    terminal_positions = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValueError("record entry is invalid")
        record_type = _require_int(record.get("type"), "type", 0, 0xFFFFFFFF)
        field1 = _require_int(record.get("field1"), "field1", 0, 0xFFFFFFFF)
        field2 = _require_int(record.get("field2"), "field2", 0, 0xFFFFFFFF)
        field3 = _require_int(record.get("field3"), "field3", 0, 0xFFFFFFFF)
        if record_type not in KNOWN_RECORD_TYPES:
            raise ValueError("unknown record type is rejected")
        if record_type == 3:
            terminal_positions.append(index)
        elif record_type == 1 and field3 > 0x3FFFFFFF:
            raise ValueError("record word count overflows")
        elif record_type == 2 and field2 > 0x3FFFFFFF:
            raise ValueError("record word count overflows")
        parsed.append((record_type, field1, field2, field3))
        _ = table_offset + index * 16
    if terminal_positions != [count - 1]:
        raise ValueError("terminal type-3 record must end the table")
    return parsed


def _source_headers(bank: bytes) -> dict[int, zup_bank.LaunchTable]:
    headers = {}
    for offset in HEADER_CANDIDATES:
        try:
            headers[offset] = zup_bank.parse_launch_table(bank, offset)
        except ValueError:
            continue
    return headers


def _source_payloads(
        bank: bytes, headers: dict[int, zup_bank.LaunchTable]) -> dict[tuple[str, int], dict]:
    type8_offsets = sorted({
        record.field1 - zup_bank.RUNTIME_BANK_BASE
        for table in headers.values() for record in table.records
        if record.record_type == 8
        and zup_bank.RUNTIME_BANK_BASE <= record.field1
        < zup_bank.RUNTIME_BANK_BASE + len(bank)
    })
    payloads: dict[tuple[str, int], dict] = {}
    budget = zup_bank.MAX_TYPE8_OUTPUT_BYTES
    for offset in type8_offsets:
        payload = zup_bank.parse_type8_payload(bank, offset, budget)
        budget -= payload.output_size
        payloads[("type8", offset)] = {
            "kind": "type8", "offset": offset,
            "file": f"payloads/type8_0x{offset:x}.bin",
            "mode": payload.mode, "field": payload.field,
            "compressed_size": payload.compressed_size,
            "output_size": payload.output_size, "crc32": payload.crc32,
            "sha256": hashlib.sha256(payload.data).hexdigest(),
        }
    budget = zup_bank.MAX_NESTED_OUTPUT_BYTES
    for offset in _scan_nested(bank):
        payload = zup_bank.parse_nested_payload(bank, offset, budget)
        budget -= payload.output_size
        payloads[("nested", offset)] = {
            "kind": "nested", "offset": offset,
            "file": f"payloads/nested_0x{offset:x}.bin",
            "mode": None, "field": None,
            "compressed_size": payload.stored_size,
            "output_size": payload.output_size, "crc32": payload.crc32,
            "sha256": hashlib.sha256(payload.data).hexdigest(),
        }
    return payloads


def _validate_source_manifest(manifest: dict, bank: bytes) -> tuple[
        list[tuple[int, tuple[tuple[int, int, int, int], ...]]],
        list[dict]]:
    """Bind editable values to the immutable extracted bank and inventory."""
    digest = manifest.get("bank_sha256")
    if not isinstance(digest, str) or len(digest) != 64 \
            or hashlib.sha256(bank).hexdigest() != digest:
        raise ValueError("decomposition bank does not match its manifest")

    headers = manifest.get("launch_headers")
    payload_entries = manifest.get("payloads")
    if not isinstance(headers, list) or not isinstance(payload_entries, list) \
            or len(headers) > zup_bank.MAX_LAUNCH_HEADERS \
            or len(payload_entries) > MAX_PAYLOAD_FILES:
        raise ValueError("manifest structure is invalid")

    source_headers = _source_headers(bank)
    if len(headers) != len(source_headers):
        raise ValueError("launch header inventory changed")
    proposals: dict[int, tuple[tuple[int, int, int, int], ...]] = {}
    seen_headers = set()
    for header in headers:
        if not isinstance(header, dict):
            raise ValueError("manifest header entry is invalid")
        header_offset = _require_int(
            header.get("header_offset"), "header_offset",
            0, zup_bank.BANK_BYTES - zup_bank.LAUNCH_RECORD_BYTES)
        if header_offset in seen_headers or header_offset not in source_headers:
            raise ValueError("launch header inventory changed")
        seen_headers.add(header_offset)
        source = source_headers[header_offset]
        immutable = (
            ("field0", source.field0),
            ("table_address", source.table_address),
            ("table_offset", source.table_offset),
            ("record_count", source.record_count),
            ("field3", source.field3),
        )
        for name, expected in immutable:
            if _require_int(header.get(name), name, 0, 0xFFFFFFFF) != expected:
                raise ValueError("launch header inventory changed")
        records = header.get("records")
        if not isinstance(records, list):
            raise ValueError("manifest records entry is invalid")
        parsed = tuple(_validate_records(
            source.table_offset, source.record_count, records))
        for index, record in enumerate(records):
            if not isinstance(record, dict) or _require_int(
                    record.get("offset"), "record offset", 0,
                    zup_bank.BANK_BYTES - zup_bank.LAUNCH_RECORD_BYTES) != \
                    source.table_offset + index * zup_bank.LAUNCH_RECORD_BYTES:
                raise ValueError("launch record inventory changed")
        previous = proposals.get(source.table_offset)
        if previous is not None and previous != parsed:
            raise ValueError("duplicate launch headers disagree")
        proposals[source.table_offset] = parsed
    if seen_headers != set(source_headers):
        raise ValueError("launch header inventory changed")

    source_payloads = _source_payloads(bank, source_headers)
    entries: list[dict] = []
    seen_payloads = set()
    for entry in payload_entries:
        if not isinstance(entry, dict):
            raise ValueError("manifest payload entry is invalid")
        kind = entry.get("kind")
        offset = _require_int(entry.get("offset"), "offset",
                              0, zup_bank.BANK_BYTES - 8)
        key = (kind, offset)
        if key in seen_payloads or key not in source_payloads:
            raise ValueError("payload inventory changed")
        seen_payloads.add(key)
        source = source_payloads[key]
        for name in ("file", "mode", "field", "compressed_size",
                     "output_size", "crc32", "sha256"):
            if entry.get(name) != source[name]:
                raise ValueError("payload inventory changed")
        entries.append(entry)
    if seen_payloads != set(source_payloads):
        raise ValueError("payload inventory changed")
    return sorted(proposals.items()), entries


def _repack_type8(data: bytes) -> bytes:
    if not data or len(data) > MAX_PAYLOAD_BYTES:
        raise ValueError("type-8 replacement size is invalid")
    compressor = zlib.compressobj(level=COMPRESSION_LEVEL, wbits=-15)
    stream = compressor.compress(data) + compressor.flush()
    return stream + struct.pack("<I", zlib.crc32(data) & 0xFFFFFFFF)


def _repack_nested(data: bytes) -> tuple[bytes, bytes]:
    if not data or len(data) > MAX_PAYLOAD_BYTES:
        raise ValueError("nested replacement size is invalid")
    compressor = zlib.compressobj(level=COMPRESSION_LEVEL, wbits=-15)
    stream = compressor.compress(data) + compressor.flush()
    trailer = struct.pack("<II", zlib.crc32(data) & 0xFFFFFFFF, len(data))
    header = struct.pack(">4sIIIII", b"+kbz", 2,
                         sum(stream + trailer) & 0xFFFFFFFF,
                         len(stream + trailer),
                         sum(data) & 0xFFFFFFFF, len(data))
    return header, stream + trailer


def compose_bank(manifest: dict, bank: bytes, read_payload) -> bytes:
    """Apply manifest record/payload edits onto ``bank``; return new bytes."""
    if len(bank) != zup_bank.BANK_BYTES:
        raise ValueError("compose requires one complete bank")
    table_proposals, payload_entries = _validate_source_manifest(manifest, bank)
    source_headers = _source_headers(bank)
    source_section = _section_info(bank)
    out = bytearray(bank)
    table_spans = []
    for table_offset, parsed in table_proposals:
        end = table_offset + len(parsed) * zup_bank.LAUNCH_RECORD_BYTES
        if end > len(out):
            raise ValueError("launch table exceeds bank bounds")
        table_spans.append((table_offset, end))
        for index, (record_type, field1, field2, field3) in enumerate(parsed):
            offset = table_offset + index * zup_bank.LAUNCH_RECORD_BYTES
            current = struct.unpack_from(">IIII", out, offset)
            if current != (record_type, field1, field2, field3):
                struct.pack_into(">IIII", out, offset,
                                  record_type, field1, field2, field3)
    protected_spans = [
        (offset, offset + zup_bank.LAUNCH_RECORD_BYTES)
        for offset in source_headers
    ]
    protected_spans.append(
        (SECTION_OFFSET, SECTION_OFFSET + 24))
    for table_start, table_end in table_spans:
        for protected_start, protected_end in protected_spans:
            if _spans_overlap(table_start, table_end,
                              protected_start, protected_end):
                raise ValueError("launch inventory overlaps protected metadata")
    protected_spans.extend(table_spans)
    for entry in payload_entries:
        kind = entry.get("kind")
        offset = entry["offset"]
        expected = entry.get("sha256")
        data = read_payload(entry)
        if not isinstance(data, bytes) or not data \
                or len(data) > MAX_PAYLOAD_BYTES:
            raise ValueError("payload replacement size is invalid")
        if hashlib.sha256(data).hexdigest() == expected:
            continue
        if kind == "type8":
            payload = zup_bank.parse_type8_payload(bytes(out), offset)
            span = 8 + payload.compressed_size + 4
            replacement = bytes(out[offset:offset + 8]) + _repack_type8(data)
        elif kind == "nested":
            payload = zup_bank.parse_nested_payload(bytes(out), offset)
            span = zup_bank.NESTED_HEADER_BYTES + payload.stored_size
            header, stored = _repack_nested(data)
            replacement = header + stored
        else:
            raise ValueError("manifest payload kind is unsupported")
        if len(replacement) > span:
            raise ValueError(
                "replacement exceeds its original span; "
                "relocation is unsupported")
        for start, end in protected_spans:
            if _spans_overlap(offset, offset + span, start, end):
                raise ValueError("payload span overlaps protected metadata")
        out[offset:offset + len(replacement)] = replacement
        pad = span - len(replacement)
        if pad:
            out[offset + len(replacement):offset + span] = b"\xff" * pad
    section = _section_info(bytes(out))
    if source_section is None and section is not None:
        raise ValueError("section metadata changed during composition")
    if source_section is not None:
        if section is None or section["descriptors"] != \
                source_section["descriptors"]:
            raise ValueError("section metadata changed during composition")
        struct.pack_into(">I", out, section["offset"] + 4,
                         section["calculated"])
        checked = _section_info(bytes(out))
        if checked is None or checked["stored"] != checked["calculated"]:
            raise ValueError("section checksum repair failed")
    return bytes(out)


def _read_payload_file(base_dir: str, entry: dict) -> bytes:
    name = entry.get("file")
    if not isinstance(name, str) or not name.startswith("payloads/") \
            or "/" in name[len("payloads/"):] or name.endswith("/") \
            or len(name) > 64:
        raise ValueError("manifest payload path is invalid")
    path = os.path.join(base_dir, name)
    if os.path.dirname(os.path.abspath(path)) != os.path.join(
            os.path.abspath(base_dir), "payloads"):
        raise ValueError("manifest payload path escapes its directory")
    return _read_regular_file(path, MAX_PAYLOAD_BYTES, "payload file")


def build_parser() -> argparse.ArgumentParser:
    parser = SafeArgumentParser(
        prog="zup_extract.py",
        description="decompose a legacy ATA +kxz package and recompose banks")
    parser.add_argument("package", nargs="?",
                        help="bounded regular .zup package to decompose")
    parser.add_argument("--out", metavar="DIR",
                        help="create one new private decomposition directory")
    parser.add_argument("--compose", metavar="DIR",
                        help="recompose a bank from a decomposition directory")
    parser.add_argument("--bank", metavar="PATH",
                        help="atomically create one new private 512 KiB bank")
    parser.add_argument("--disasm", action="store_true", default=False,
                        help="run MAME unidasm on extracted bank if available")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    parser.allow_abbrev = False
    arguments = parser.parse_args(argv)
    try:
        if arguments.compose is not None:
            if arguments.bank is None:
                parser.error("missing --bank PATH")
            if arguments.package is not None or arguments.out is not None:
                parser.error("compose takes no positional package or --out")
            manifest = _load_manifest(
                os.path.join(arguments.compose, "manifest.json"))
            bank = _read_regular_file(
                os.path.join(arguments.compose, "bank.bin"),
                zup_bank.BANK_BYTES, "decomposition bank")
            if len(bank) != zup_bank.BANK_BYTES:
                raise ValueError("decomposition bank must be 512 KiB")
            composed = compose_bank(
                manifest, bank,
                lambda entry: _read_payload_file(arguments.compose, entry))
            zup_bank.publish_private(arguments.bank, composed)
            print(f"bank_sha256={hashlib.sha256(composed).hexdigest()}")
            print(f"bank_bytes={len(composed)}")
            print("private_bank_created=true")
            return 0
        if arguments.package is None or arguments.out is None:
            parser.error("missing PACKAGE or --out DIR")
        if arguments.bank is not None:
            parser.error("extract takes no --bank PATH")
        package = zup_bank.read_package(arguments.package)
        manifest = extract_package(package, arguments.out,
                                   disasm=arguments.disasm)
        print(f"package_sha256={manifest['package_sha256']}")
        print(f"bank_sha256={manifest['bank_sha256']}")
        print(f"headers={len(manifest['launch_headers'])}")
        print(f"payloads={len(manifest['payloads'])}")
        if manifest.get("disasm"):
            print(f"disasm={manifest['disasm']}")
        print("private_decomposition_created=true")
        return 0
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
