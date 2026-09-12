#!/usr/bin/env python3
"""Bounded offline reconstruction of legacy ATA ``+kxz`` bank images.

The implementation is limited to the map form established from the local
legacy extractor and independently validated against the pinned ATA package.
It never executes vendor code or opens a socket. Outputs are complete, private,
new files; an existing path is never overwritten.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import os
import secrets
import stat
import struct
import sys
import zlib


OUTER_BYTES = 24
INNER_HEADER_BYTES = 16
BANK_BYTES = 0x80000
MAX_PACKAGE_BYTES = 1024 * 1024
MAX_REGIONS = 256
RUNTIME_BANK_BASE = 0x0CF80000
LAUNCH_RECORD_BYTES = 16
MAX_LAUNCH_RECORDS = 256
MAX_LAUNCH_HEADERS = 16
NESTED_HEADER_BYTES = 24
MAX_NESTED_PAYLOADS = 16
MAX_NESTED_OUTPUT_BYTES = BANK_BYTES
TYPE8_HEADER_BYTES = 8
MAX_TYPE8_PAYLOADS = 16
MAX_TYPE8_OUTPUT_BYTES = BANK_BYTES


class SafeArgumentParser(argparse.ArgumentParser):
    """Keep parser diagnostics from echoing arbitrary command-line values."""

    def error(self, _message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, "error: invalid arguments\n")


@dataclass(frozen=True)
class RawRegion:
    source: int
    destination: int
    size: int


@dataclass(frozen=True)
class CompressedRegion:
    source: int
    destination: int
    output_size: int
    stored_size: int
    crc32: int


@dataclass(frozen=True)
class BankResult:
    data: bytes
    table_offset: int
    format_version: int
    raw_regions: tuple[RawRegion, ...]
    compressed_regions: tuple[CompressedRegion, ...]


@dataclass(frozen=True)
class LaunchRecord:
    offset: int
    record_type: int
    field1: int
    field2: int
    field3: int


@dataclass(frozen=True)
class LaunchTable:
    header_offset: int
    field0: int
    table_address: int
    table_offset: int
    record_count: int
    field3: int
    records: tuple[LaunchRecord, ...]


@dataclass(frozen=True)
class NestedPayload:
    offset: int
    format_version: int
    stored_checksum: int
    stored_size: int
    output_checksum: int
    output_size: int
    crc32: int
    data: bytes


@dataclass(frozen=True)
class Type8Payload:
    offset: int
    mode: int
    field: int
    compressed_size: int
    output_size: int
    crc32: int
    data: bytes


def read_u32(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from(">I", data, offset)[0]


def read_package(path: str) -> bytes:
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_NONBLOCK"):
        raise ValueError("secure package opening is unavailable")
    before = os.lstat(path)
    if not stat.S_ISREG(before.st_mode) \
            or not OUTER_BYTES + INNER_HEADER_BYTES <= before.st_size \
            <= MAX_PACKAGE_BYTES:
        raise ValueError("package must be a bounded regular file")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) \
        | os.O_NOFOLLOW | os.O_NONBLOCK
    descriptor = os.open(path, flags)
    try:
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode) \
                or not OUTER_BYTES + INNER_HEADER_BYTES <= details.st_size \
                <= MAX_PACKAGE_BYTES \
                or (details.st_dev, details.st_ino) != (before.st_dev, before.st_ino):
            raise ValueError("package must be a bounded regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as package_file:
            data = package_file.read(MAX_PACKAGE_BYTES + 1)
        after = os.fstat(descriptor)
        if len(data) != details.st_size or (
                after.st_dev, after.st_ino, after.st_size,
                after.st_mtime_ns, after.st_ctime_ns) != (
                details.st_dev, details.st_ino, details.st_size,
                details.st_mtime_ns, details.st_ctime_ns):
            raise ValueError("package changed while being read")
        return data
    finally:
        os.close(descriptor)


def _validate_destinations(regions: list[tuple[int, int]]) -> None:
    previous_end = 0
    for start, end in sorted(regions):
        if start < previous_end:
            raise ValueError("bank destination regions overlap")
        if start < 0 or start >= end or end > BANK_BYTES:
            raise ValueError("bank destination is out of bounds")
        previous_end = end


def _inflate_region(stored: bytes, expected_size: int) -> tuple[bytes, int]:
    decoder = zlib.decompressobj(-15)
    try:
        output = decoder.decompress(stored, expected_size + 1)
        if decoder.unconsumed_tail or len(output) > expected_size:
            raise ValueError("compressed region exceeds declared size")
        if len(output) < expected_size:
            output += decoder.flush(expected_size - len(output))
    except zlib.error as exc:
        raise ValueError("invalid raw-DEFLATE region") from exc
    if not decoder.eof or len(output) != expected_size:
        raise ValueError("compressed region has the wrong output size")
    if len(decoder.unused_data) != 8:
        raise ValueError("compressed region must have one CRC/ISIZE trailer")
    expected_crc, expected_isize = struct.unpack("<II", decoder.unused_data)
    if expected_isize != expected_size \
            or zlib.crc32(output) & 0xFFFFFFFF != expected_crc:
        raise ValueError("compressed region trailer does not match output")
    return output, expected_crc


def build_bank(package: bytes) -> BankResult:
    """Validate one legacy package and reconstruct its 512 KiB bank."""
    if len(package) < OUTER_BYTES + INNER_HEADER_BYTES \
            or len(package) > MAX_PACKAGE_BYTES:
        raise ValueError("package size is invalid")
    if package[:4] != b"kup1":
        raise ValueError("unsupported outer package")
    inner = package[OUTER_BYTES:]
    if inner[:4] != b"+kxz":
        raise ValueError("unsupported inner package")
    if read_u32(inner, 8) != len(inner):
        raise ValueError("inner package length does not match")
    if read_u32(inner, 4) != sum(inner[12:]) & 0xFFFFFFFF:
        raise ValueError("inner package checksum does not match")

    table_offset = OUTER_BYTES + read_u32(inner, 12)
    if not OUTER_BYTES + INNER_HEADER_BYTES <= table_offset <= len(package) - 8:
        raise ValueError("map table offset is invalid")
    raw_count, compressed_count = struct.unpack_from(">HH", package, table_offset)
    if raw_count + compressed_count > MAX_REGIONS:
        raise ValueError("map has too many regions")
    table_size = 4 + raw_count * 8 + compressed_count * 12 + 4
    if table_offset + table_size != len(package):
        raise ValueError("map table does not end at package boundary")

    cursor = table_offset + 4
    raw_specs: list[tuple[int, int]] = []
    for _ in range(raw_count):
        raw_specs.append(struct.unpack_from(">II", package, cursor))
        cursor += 8
    compressed_specs: list[tuple[int, int, int]] = []
    for _ in range(compressed_count):
        compressed_specs.append(struct.unpack_from(">III", package, cursor))
        cursor += 12
    format_version = read_u32(package, cursor)
    if format_version != 2:
        raise ValueError("unsupported map version")

    source = OUTER_BYTES + INNER_HEADER_BYTES
    raw_regions: list[RawRegion] = []
    for destination, size in raw_specs:
        if source + size > table_offset:
            raise ValueError("raw region extends into map table")
        raw_regions.append(RawRegion(source, destination, size))
        source += size

    planned_source = source
    planned_destinations = [
        (item.destination, item.destination + item.size)
        for item in raw_regions
    ]
    for destination, output_size, stored_size in compressed_specs:
        if output_size > BANK_BYTES \
                or planned_source + stored_size > table_offset:
            raise ValueError("compressed region extends into map table")
        planned_destinations.append((destination, destination + output_size))
        planned_source += stored_size

    if planned_source == table_offset:
        pass
    elif planned_source == table_offset - 4 \
            and package[planned_source:table_offset] == b"ATA4":
        pass
    else:
        raise ValueError("gap between map data and table is invalid")
    # Nonoverlapping destinations in a fixed bank also cap aggregate output.
    _validate_destinations(planned_destinations)

    compressed_regions: list[CompressedRegion] = []
    inflated: list[bytes] = []
    for destination, output_size, stored_size in compressed_specs:
        output, checksum = _inflate_region(
            package[source:source + stored_size], output_size)
        compressed_regions.append(CompressedRegion(
            source, destination, output_size, stored_size, checksum))
        inflated.append(output)
        source += stored_size

    bank = bytearray(b"\xff" * BANK_BYTES)
    for item in raw_regions:
        bank[item.destination:item.destination + item.size] = \
            package[item.source:item.source + item.size]
    for item, output in zip(compressed_regions, inflated):
        bank[item.destination:item.destination + item.output_size] = output
    return BankResult(bytes(bank), table_offset, format_version,
                      tuple(raw_regions), tuple(compressed_regions))


def parse_launch_table(
        bank: bytes, header_offset: int,
        runtime_base: int = RUNTIME_BANK_BASE) -> LaunchTable:
    """Parse one counted launch-record table without assigning record semantics."""
    if len(bank) != BANK_BYTES:
        raise ValueError("launch table requires one complete bank")
    if header_offset < 0 or header_offset % LAUNCH_RECORD_BYTES \
            or header_offset + LAUNCH_RECORD_BYTES > len(bank):
        raise ValueError("launch header offset is invalid")
    if runtime_base < 0 or runtime_base > 0xFFFFFFFF - len(bank):
        raise ValueError("runtime bank base is invalid")

    field0, table_address, record_count, field3 = struct.unpack_from(
        ">IIII", bank, header_offset)
    if not 0 < record_count <= MAX_LAUNCH_RECORDS:
        raise ValueError("launch record count is invalid")
    if not runtime_base <= table_address < runtime_base + len(bank):
        raise ValueError("launch table address is outside the mapped bank")
    table_offset = table_address - runtime_base
    table_bytes = record_count * LAUNCH_RECORD_BYTES
    if table_offset % LAUNCH_RECORD_BYTES \
            or table_offset + table_bytes > len(bank):
        raise ValueError("launch record table is invalid")

    records = tuple(
        LaunchRecord(table_offset + index * LAUNCH_RECORD_BYTES, *struct.unpack_from(
            ">IIII", bank, table_offset + index * LAUNCH_RECORD_BYTES))
        for index in range(record_count)
    )
    return LaunchTable(header_offset, field0, table_address, table_offset,
                       record_count, field3, records)


def parse_nested_payload(
        bank: bytes, offset: int,
        output_budget: int | None = None) -> NestedPayload:
    """Validate and expand one bank-embedded ``+kbz`` payload."""
    if output_budget is None:
        output_budget = MAX_NESTED_OUTPUT_BYTES
    if not 0 <= output_budget <= MAX_NESTED_OUTPUT_BYTES:
        raise ValueError("nested output budget is invalid")
    if len(bank) != BANK_BYTES:
        raise ValueError("nested payload requires one complete bank")
    if offset < 0 or offset % 4 or offset + NESTED_HEADER_BYTES > len(bank):
        raise ValueError("nested payload offset is invalid")
    magic, format_version, stored_checksum, stored_size, \
        output_checksum, output_size = struct.unpack_from(">4sIIIII", bank, offset)
    if magic != b"+kbz" or format_version != 2:
        raise ValueError("unsupported nested payload")
    if stored_size <= 8 or offset + NESTED_HEADER_BYTES + stored_size > len(bank):
        raise ValueError("nested stored size is invalid")
    if not 0 < output_size <= MAX_NESTED_OUTPUT_BYTES:
        raise ValueError("nested output size is invalid")
    if output_size > output_budget:
        raise ValueError("aggregate nested output is too large")

    start = offset + NESTED_HEADER_BYTES
    stored = bank[start:start + stored_size]
    if sum(stored) & 0xFFFFFFFF != stored_checksum:
        raise ValueError("nested stored checksum does not match")
    output, checksum = _inflate_region(stored, output_size)
    if sum(output) & 0xFFFFFFFF != output_checksum:
        raise ValueError("nested output checksum does not match")
    return NestedPayload(
        offset, format_version, stored_checksum, stored_size,
        output_checksum, output_size, checksum, output)


def parse_type8_payload(
        bank: bytes, offset: int,
        output_budget: int | None = None) -> Type8Payload:
    """Expand one type-8 record payload through its checked CRC-32."""
    if output_budget is None:
        output_budget = MAX_TYPE8_OUTPUT_BYTES
    if not 0 <= output_budget <= MAX_TYPE8_OUTPUT_BYTES:
        raise ValueError("type-8 output budget is invalid")
    if len(bank) != BANK_BYTES:
        raise ValueError("type-8 payload requires one complete bank")
    if offset < 0 or offset % 4 or offset + TYPE8_HEADER_BYTES >= len(bank):
        raise ValueError("type-8 payload offset is invalid")

    mode, field = struct.unpack_from(">II", bank, offset)
    if mode not in (0, 1):
        raise ValueError("type-8 payload mode is invalid")
    if mode == 1:
        if field >= BANK_BYTES:
            raise ValueError("type-8 data destination is out of bounds")
        output_budget = min(output_budget, BANK_BYTES - field)
    decoder = zlib.decompressobj(-15)
    try:
        stored = bank[offset + TYPE8_HEADER_BYTES:]
        output = decoder.decompress(stored, output_budget + 1)
        if decoder.unconsumed_tail or len(output) > output_budget:
            raise ValueError("type-8 payload exceeds output budget")
        output += decoder.flush(output_budget + 1 - len(output))
    except zlib.error as exc:
        raise ValueError("invalid type-8 raw-DEFLATE stream") from exc
    if not decoder.eof or not output or len(output) > output_budget:
        raise ValueError("type-8 payload has invalid output")
    if len(decoder.unused_data) < 4:
        raise ValueError("type-8 payload CRC-32 is missing")
    compressed_size = len(stored) - len(decoder.unused_data)
    expected_crc = struct.unpack_from("<I", decoder.unused_data)[0]
    if compressed_size <= 0 \
            or zlib.crc32(output) & 0xFFFFFFFF != expected_crc:
        raise ValueError("type-8 payload CRC-32 does not match output")
    return Type8Payload(
        offset, mode, field, compressed_size, len(output), expected_crc, output)


def publish_private(path: str, content: bytes) -> None:
    """Atomically publish one complete mode-0600 file without replacement."""
    if not hasattr(os, "O_DIRECTORY") or not hasattr(os, "O_NOFOLLOW"):
        raise ValueError("secure output publication is unavailable")
    target = os.path.abspath(path)
    parent = os.path.dirname(target)
    target_name = os.path.basename(target)
    if not target_name:
        raise ValueError("output path is invalid")
    directory_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) \
        | os.O_DIRECTORY | os.O_NOFOLLOW
    directory = os.open(parent, directory_flags)
    try:
        parent_details = os.fstat(directory)
        if not stat.S_ISDIR(parent_details.st_mode) \
                or parent_details.st_uid != os.getuid() \
                or stat.S_IMODE(parent_details.st_mode) & 0o022:
            raise ValueError("output directory is invalid")
        try:
            os.stat(target_name, dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise ValueError("refusing to overwrite an existing output")

        descriptor = -1
        temporary_name = ""
        for _ in range(32):
            temporary_name = f".{target_name}.{secrets.token_hex(16)}"
            try:
                descriptor = os.open(
                    temporary_name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL
                    | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW,
                    0o600, dir_fd=directory)
                break
            except FileExistsError:
                continue
        if descriptor == -1:
            raise ValueError("cannot allocate a private output staging file")

        published = False
        staged_details = os.fstat(descriptor)
        identity = staged_details.st_dev, staged_details.st_ino
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as output_file:
                descriptor = -1
                output_file.write(content)
                output_file.flush()
                os.fsync(output_file.fileno())
            current_parent = os.stat(parent, follow_symlinks=False)
            if (current_parent.st_dev, current_parent.st_ino) != (
                    parent_details.st_dev, parent_details.st_ino):
                raise ValueError("output directory changed")
            os.link(temporary_name, target_name, src_dir_fd=directory,
                    dst_dir_fd=directory, follow_symlinks=False)
            published = True
            result = os.stat(
                target_name, dir_fd=directory, follow_symlinks=False)
            if (result.st_dev, result.st_ino) != identity:
                raise ValueError("output publication identity changed")
            current_parent = os.stat(parent, follow_symlinks=False)
            if (current_parent.st_dev, current_parent.st_ino) != (
                    parent_details.st_dev, parent_details.st_ino):
                raise ValueError("output directory changed")
            os.fsync(directory)
        except BaseException:
            if published:
                try:
                    result = os.stat(
                        target_name, dir_fd=directory, follow_symlinks=False)
                    if (result.st_dev, result.st_ino) == identity:
                        os.unlink(target_name, dir_fd=directory)
                        os.fsync(directory)
                except OSError:
                    pass
            raise
        finally:
            if descriptor != -1:
                os.close(descriptor)
            if temporary_name:
                try:
                    staged = os.stat(
                        temporary_name, dir_fd=directory, follow_symlinks=False)
                    if (staged.st_dev, staged.st_ino) == identity:
                        os.unlink(temporary_name, dir_fd=directory)
                        os.fsync(directory)
                except OSError:
                    pass
    finally:
        os.close(directory)


def build_parser() -> argparse.ArgumentParser:
    parser = SafeArgumentParser(
        prog="zup_bank.py",
        description="validate a legacy ATA +kxz map and reconstruct its bank")
    parser.add_argument("package", help="bounded regular .zup package")
    parser.add_argument(
        "--extract-bank", metavar="PATH",
        help="atomically create one private 512 KiB bank image")
    parser.add_argument(
        "--launch-header", action="append", default=[], type=lambda value: int(value, 0),
        metavar="OFFSET",
        help="print a counted launch-record table reached from this bank offset")
    parser.add_argument(
        "--runtime-base", type=lambda value: int(value, 0),
        default=RUNTIME_BANK_BASE, metavar="ADDRESS",
        help="runtime address corresponding to bank offset zero")
    parser.add_argument(
        "--nested-payload", action="append", default=[],
        type=lambda value: int(value, 0), metavar="OFFSET",
        help="validate and hash one bank-embedded +kbz payload")
    parser.add_argument(
        "--type8-payload", action="append", default=[],
        type=lambda value: int(value, 0), metavar="OFFSET",
        help="validate and hash one packed payload referenced by a type-8 record")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if len(arguments.launch_header) > MAX_LAUNCH_HEADERS \
            or len(arguments.nested_payload) > MAX_NESTED_PAYLOADS \
            or len(set(arguments.nested_payload)) != len(arguments.nested_payload) \
            or len(arguments.type8_payload) > MAX_TYPE8_PAYLOADS \
            or len(set(arguments.type8_payload)) != len(arguments.type8_payload):
        print("error: package reconstruction failed closed", file=sys.stderr)
        return 1
    try:
        package = read_package(arguments.package)
        result = build_bank(package)
        launch_tables = tuple(
            parse_launch_table(result.data, offset, arguments.runtime_base)
            for offset in arguments.launch_header
        )
        nested_payload_list: list[NestedPayload] = []
        nested_output_size = 0
        for offset in arguments.nested_payload:
            payload = parse_nested_payload(
                result.data, offset,
                MAX_NESTED_OUTPUT_BYTES - nested_output_size)
            nested_output_size += payload.output_size
            nested_payload_list.append(payload)
        nested_payloads = tuple(nested_payload_list)
        type8_payload_list: list[Type8Payload] = []
        type8_output_size = 0
        for offset in arguments.type8_payload:
            payload = parse_type8_payload(
                result.data, offset,
                MAX_TYPE8_OUTPUT_BYTES - type8_output_size)
            type8_output_size += payload.output_size
            type8_payload_list.append(payload)
        type8_payloads = tuple(type8_payload_list)
        if arguments.extract_bank:
            publish_private(arguments.extract_bank, result.data)
    except (OSError, ValueError):
        print("error: package reconstruction failed closed", file=sys.stderr)
        return 1

    print(f"package_sha256={hashlib.sha256(package).hexdigest()}")
    print(f"bank_sha256={hashlib.sha256(result.data).hexdigest()}")
    print(f"bank_bytes={len(result.data)}")
    print(f"table_offset=0x{result.table_offset:x}")
    print(f"format_version={result.format_version}")
    print(f"raw_regions={len(result.raw_regions)}")
    print(f"compressed_regions={len(result.compressed_regions)}")
    for item in result.raw_regions:
        print(f"raw source=0x{item.source:x} destination=0x{item.destination:x} "
              f"bytes=0x{item.size:x}")
    for item in result.compressed_regions:
        print(
            f"deflate source=0x{item.source:x} "
            f"destination=0x{item.destination:x} "
            f"stored=0x{item.stored_size:x} output=0x{item.output_size:x} "
            f"crc32=0x{item.crc32:08x}")
    for table in launch_tables:
        print(
            f"launch_header offset=0x{table.header_offset:x} "
            f"field0=0x{table.field0:08x} "
            f"table_address=0x{table.table_address:08x} "
            f"table_offset=0x{table.table_offset:x} "
            f"records={table.record_count} field3=0x{table.field3:08x}")
        for index, record in enumerate(table.records):
            derived: list[str] = []
            if record.record_type in (1, 8) \
                    and arguments.runtime_base <= record.field1 \
                    < arguments.runtime_base + BANK_BYTES:
                derived.append(
                    f"mapped_bank_offset=0x{record.field1 - arguments.runtime_base:x}")
            if record.record_type == 1:
                byte_count = record.field3 * 4
                derived.extend((
                    f"derived_bytes=0x{byte_count:x}",
                    f"derived_destination_end=0x{record.field2 + byte_count:x}",
                ))
            elif record.record_type == 2:
                byte_count = record.field2 * 4
                derived.extend((
                    f"derived_bytes=0x{byte_count:x}",
                    f"derived_destination_end=0x{record.field1 + byte_count:x}",
                ))
            suffix = f" {' '.join(derived)}" if derived else ""
            print(
                f"launch_record index={index} offset=0x{record.offset:x} "
                f"type=0x{record.record_type:x} field1=0x{record.field1:08x} "
                f"field2=0x{record.field2:08x} "
                f"field3=0x{record.field3:08x}{suffix}")
    for payload in nested_payloads:
        print(
            f"nested_payload offset=0x{payload.offset:x} "
            f"format_version={payload.format_version} "
            f"stored=0x{payload.stored_size:x} "
            f"stored_checksum=0x{payload.stored_checksum:08x} "
            f"output=0x{payload.output_size:x} "
            f"output_checksum=0x{payload.output_checksum:08x} "
            f"crc32=0x{payload.crc32:08x} "
            f"sha256={hashlib.sha256(payload.data).hexdigest()}")
    for payload in type8_payloads:
        destination = ""
        if payload.mode == 1:
            destination = (
                f" destination=0x{payload.field:x}"
                f" destination_end=0x{payload.field + payload.output_size:x}")
        print(
            f"type8_payload offset=0x{payload.offset:x} "
            f"mode={payload.mode} field=0x{payload.field:08x} "
            f"compressed=0x{payload.compressed_size:x} "
            f"output=0x{payload.output_size:x} "
            f"crc32=0x{payload.crc32:08x}{destination} "
            f"sha256={hashlib.sha256(payload.data).hexdigest()}")
    if arguments.extract_bank:
        print("private_bank_created=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
