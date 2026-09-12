#!/usr/bin/env python3
"""Rebuild a legacy ATA ``+kxz`` package from its mapped 512 KiB bank.

Unchanged compressed regions retain their exact stored bytes. Changed regions
are encoded as raw DEFLATE plus the legacy little-endian CRC-32/ISIZE trailer.
The tool is offline and creates one complete private output without overwrite.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import struct
import sys
import zlib

if __package__:
    from . import zup_bank
else:
    import zup_bank


COMPRESSION_LEVEL = 9


@dataclass(frozen=True)
class RebuildResult:
    data: bytes
    changed_raw_regions: int
    recompressed_regions: int
    preserved_compressed_regions: int


def read_bank(path: str) -> bytes:
    """Read one exact bank through the reconstructor's bounded file gate."""
    data = zup_bank.read_package(path)
    if len(data) != zup_bank.BANK_BYTES:
        raise ValueError("bank must be exactly 512 KiB")
    return data


def _deflate_region(data: bytes) -> bytes:
    compressor = zlib.compressobj(level=COMPRESSION_LEVEL, wbits=-15)
    encoded = compressor.compress(data) + compressor.flush()
    return encoded + struct.pack(
        "<II", zlib.crc32(data) & 0xFFFFFFFF, len(data))


def _validate_outer_header(template: bytes) -> None:
    name = template[4:12].split(b"\x00", 1)[0]
    if not name or any(byte < 0x20 or byte > 0x7E for byte in name):
        raise ValueError("outer package name is invalid")


def rebuild_package(template: bytes, bank: bytes,
                    preserve_unchanged: bool = True) -> RebuildResult:
    """Return a checked package representing ``bank`` under ``template``'s map."""
    if len(bank) != zup_bank.BANK_BYTES:
        raise ValueError("bank must be exactly 512 KiB")
    layout = zup_bank.build_bank(template)
    _validate_outer_header(template)

    raw_streams: list[bytes] = []
    changed_raw_regions = 0
    for region in layout.raw_regions:
        replacement = bank[region.destination:region.destination + region.size]
        original = layout.data[
            region.destination:region.destination + region.size]
        changed_raw_regions += replacement != original
        raw_streams.append(replacement)

    compressed_streams: list[bytes] = []
    recompressed_regions = 0
    preserved_compressed_regions = 0
    for region in layout.compressed_regions:
        replacement = bank[
            region.destination:region.destination + region.output_size]
        original = layout.data[
            region.destination:region.destination + region.output_size]
        if preserve_unchanged and replacement == original:
            stored = template[region.source:region.source + region.stored_size]
            preserved_compressed_regions += 1
        else:
            stored = _deflate_region(replacement)
            recompressed_regions += 1
        compressed_streams.append(stored)

    source_end = zup_bank.OUTER_BYTES + zup_bank.INNER_HEADER_BYTES
    for region in layout.raw_regions:
        source_end = region.source + region.size
    for region in layout.compressed_regions:
        source_end = region.source + region.stored_size
    gap = template[source_end:layout.table_offset]

    table_parts = [struct.pack(
        ">HH", len(layout.raw_regions), len(layout.compressed_regions))]
    table_parts.extend(struct.pack(
        ">II", region.destination, region.size)
        for region in layout.raw_regions)
    table_parts.extend(struct.pack(
        ">III", region.destination, region.output_size, len(stored))
        for region, stored in zip(layout.compressed_regions, compressed_streams))
    table_parts.append(struct.pack(">I", layout.format_version))
    table = b"".join(table_parts)

    streams = b"".join(raw_streams + compressed_streams)
    table_offset = zup_bank.INNER_HEADER_BYTES + len(streams) + len(gap)
    inner_size = table_offset + len(table)
    inner = bytearray(
        b"+kxz" + b"\x00" * 4 + struct.pack(">II", inner_size, table_offset)
        + streams + gap + table)
    struct.pack_into(">I", inner, 4, sum(inner[12:]) & 0xFFFFFFFF)
    package = template[:zup_bank.OUTER_BYTES] + bytes(inner)
    if len(package) > zup_bank.MAX_PACKAGE_BYTES:
        raise ValueError("rebuilt package exceeds the size limit")

    checked = zup_bank.build_bank(package)
    if checked.data != bank:
        raise ValueError("bank changes outside mapped regions cannot be represented")
    if preserve_unchanged and bank == layout.data and package != template:
        raise ValueError("unchanged package did not rebuild byte-identically")
    return RebuildResult(
        package, changed_raw_regions, recompressed_regions,
        preserved_compressed_regions)


def build_parser() -> argparse.ArgumentParser:
    parser = zup_bank.SafeArgumentParser(
        prog="zup_rebuild.py",
        description="rebuild a checked legacy ATA package from a 512 KiB bank",
        allow_abbrev=False)
    parser.add_argument("template", help="original bounded .zup package")
    parser.add_argument("bank", help="complete 512 KiB reconstructed bank")
    parser.add_argument("output", help="new private .zup output path")
    parser.add_argument(
        "--recompress-all", action="store_true",
        help="re-encode unchanged compressed regions instead of preserving them")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        template = zup_bank.read_package(arguments.template)
        bank = read_bank(arguments.bank)
        result = rebuild_package(
            template, bank, preserve_unchanged=not arguments.recompress_all)
        zup_bank.publish_private(arguments.output, result.data)
    except (OSError, ValueError, zlib.error):
        print("error: package rebuild failed closed", file=sys.stderr)
        return 1

    print(f"template_sha256={hashlib.sha256(template).hexdigest()}")
    print(f"bank_sha256={hashlib.sha256(bank).hexdigest()}")
    print(f"output_sha256={hashlib.sha256(result.data).hexdigest()}")
    print(f"output_bytes={len(result.data)}")
    print(f"changed_raw_regions={result.changed_raw_regions}")
    print(f"recompressed_regions={result.recompressed_regions}")
    print(f"preserved_compressed_regions={result.preserved_compressed_regions}")
    print(f"byte_identical_to_template={str(result.data == template).lower()}")
    print("private_package_created=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
