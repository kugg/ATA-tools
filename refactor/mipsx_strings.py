#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""Bounded offline MIPS-X string inventory and reference cross-index.

Reads one pinned ``.zup`` package and its 512 KiB reconstructed bank,
expands the runtime image (raw map regions plus the stored-deflate
streams), extracts printable ASCII with bank addresses, and cross-indexes
strings against code found by pointer materialization (``addi``/``lsl``/
``addi`` triples) anywhere in the executable zones.

Read-only: no sockets, no file writes, bounded decompression sizes, and a
bounded scan window.  Bare invocation is inert because both paths are
required arguments.
"""

from __future__ import annotations

import argparse
import bisect
import re
import struct
import sys
import zlib


MASK32 = 0xFFFFFFFF

if __package__:
    from . import zup_bank
    from . import mipsx_dasm
else:
    import zup_bank
    import mipsx_dasm

if __package__:
    from . import zup_bank
else:
    import zup_bank


MAX_PACKAGE_BYTES = 32 * 1024 * 1024
BANK_BYTES = 0x80000
BANK_BASE = 0x0CF80000
MIN_STRING = 4
MAX_STRING = 256
STRING_RUN = re.compile(rb"[\x20-\x7e]{%d,%d}" % (MIN_STRING, MAX_STRING))

# (package offset, stored bytes, bank destination, output bytes) for the
# stored-deflate streams of the pinned SIP 3.1.0 image.
SIP_DEFLATE_STREAMS = (
    (0x2E96C, 0x1A, 0x0, 0x100),
    (0x2E986, 0x1366A, 0xA00, 0x2E00C),
    (0x41FF0, 0x29, 0x2EA0C, 0xF4),
    (0x42019, 0x77E9, 0x40000, 0x79BC),
    (0x49802, 0x33B9, 0x77000, 0x3400),
    (0x4CBBB, 0xCA1, 0x7D000, 0x1F00),
    (0x4D85C, 0x5DB, 0x7F400, 0xC00),
)

# raw map regions (package offset, bank destination, size)
SIP_RAW_REGIONS = (
    (0x28, 0x479BC, 0x241A4),
    (0x241CC, 0x70000, 0x7000),
    (0x2B1CC, 0x6BB60, 0x106C),
    (0x2C238, 0x6CBCC, 0x2734),
)

# type-8 payload offsets (mode-1 data destinations confirmed by the
# parse function; CRC-checked on expansion)
SIP_TYPE8_PAYLOADS = (0x479BC, 0x6BB60, 0x6CBCC, 0x70010, 0x76C20)

CODE_ZONES = ((0xA00, 0x2EA0C), (0x479BC, 0x6BB60), (0x77000, 0x7A400),
              (0x7D000, 0x7EF00), (0x7B84, 0xC74C))


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, f"error: {message}\n")


def build_runtime_image(package: bytes, bank: bytes) -> bytes:
    if len(package) > MAX_PACKAGE_BYTES or len(bank) != BANK_BYTES:
        raise ValueError("bounded package/bank size check failed")
    image = bytearray(bank)
    for src, dst, size in SIP_RAW_REGIONS:
        if src + size > len(package):
            raise ValueError("raw region outside package")
        image[dst:dst + size] = package[src:src + size]
    for src, stored, dst, out in SIP_DEFLATE_STREAMS:
        if src + stored > len(package):
            raise ValueError("deflate stream outside package")
        data = zlib.decompress(package[src:src + stored], -15)
        if len(data) != out:
            raise ValueError("stream size mismatch at 0x%x" % src)
        image[dst:dst + out] = data
    for payload_offset in SIP_TYPE8_PAYLOADS:
        payload = zup_bank.parse_type8_payload(bytes(image), payload_offset)
        if payload.mode == 1:
            image[payload.field:payload.field + payload.output_size] = payload.data
    return bytes(image)



def extract_strings(image: bytes) -> dict[int, str]:
    """Printable runs keyed by bank address."""
    return {m.start(): m.group().decode("ascii") for m in STRING_RUN.finditer(image)}

def materialized_pointers(words: tuple[int, ...]) -> list[tuple[int, int]]:
    """Code addresses and runtime constants built by addi/lsl/addi triples."""
    refs: list[tuple[int, int]] = []
    decs = [mipsx_dasm.decode(w, i * 4) for i, w in enumerate(words)]
    for i in range(len(words) - 2):
        d0 = decs[i]
        # addi r0,#imm,rX  builds a page half; the decoder text is
        # "addi r0,<imm>,rX"
        if not (d0.kind == "compute" and d0.text.startswith("addi r0,")):
            continue
        parts = d0.text.split(",")
        if len(parts) != 3:
            continue
        reg = parts[2].strip()
        if reg == "r0":
            continue
        d1 = decs[i + 1]
        # lsl rX,rX,#16
        if not (d1.kind == "compute" and d1.text.startswith("lsl ") and
                f"{reg},{reg}," in d1.text and ",#16" in d1.text):
            continue
        d2 = decs[i + 2]
        # addi rX,#imm,rX
        if not (d2.kind == "compute" and d2.text.startswith(f"addi {reg},")
                and d2.text.endswith(f",{reg}")):
            continue
        try:
            lo = int(d2.text.split(",")[1].strip().lstrip("+"), 0)
        except ValueError:
            continue
        hi = int(parts[1].strip().lstrip("+"), 0)
        if not 0 < hi < 0x10000 or not -0x10000 <= lo < 0x10000:
            continue
        value = ((hi << 16) + lo) & MASK32
        refs.append(((i + 2) * 4, value))
    return refs


def function_starts(words: tuple[int, ...]) -> list[int]:
    """Entry heuristic: ``addi r29,#imm,r29`` frame prologues, decoded by
    the published disassembler rather than hand-rolled field paths."""
    starts: list[int] = []
    for idx, w in enumerate(words):
        d = mipsx_dasm.decode(w, idx * 4)
        if d.kind == "compute" and d.text.startswith("addi r29,") \
                and d.text.endswith(",r29"):
            starts.append(idx * 4)
    return starts


def main(argv: list[str] | None = None) -> int:
    parser = SafeArgumentParser()
    parser.description = "Extract strings and code references from a reconstructed bank."
    parser.add_argument("package", help="pinned .zup package (read-only)")
    parser.add_argument("bank", help="reconstructed 512 KiB bank (read-only)")
    parser.add_argument("--strings-zones", default="0x2fbc:0x4bc8,0x100:0x25d0",
                        help="bank_off:span list treated as string cabins")
    parser.add_argument("--filter", default="",
                        help="only print strings matching this regex")
    args = parser.parse_args(argv)

    with open(args.package, "rb") as fh:
        package = fh.read(MAX_PACKAGE_BYTES + 1)
    with open(args.bank, "rb") as fh:
        bank = fh.read(BANK_BYTES + 1)
    if len(bank) != BANK_BYTES or len(package) > MAX_PACKAGE_BYTES:
        parser.error("package/bank size outside the bounded range")
    image = build_runtime_image(package, bank)
    words = struct.unpack(">%dI" % (len(image) // 4), image[: len(image) // 4 * 4])

    cabins = []
    for spec in args.strings_zones.split(","):
        off, span = spec.split(":")
        cabins.append((int(off, 0), int(span, 0)))

    selected = filter_re = re.compile(args.filter) if args.filter else None
    for off, span in cabins:
        print(f"== strings in cabin 0x{off:05x}..0x{off + span:05x}"
              + (f" (filter {args.filter!r})" if selected else "") + " ==")
        for m in STRING_RUN.finditer(image[off:off + span]):
            text = m.group().decode("ascii")
            if selected is None or selected.search(text):
                print(f"  0x{off + m.start():05x}  {text[:100]}")

    print("\n== pointer materializations landing inside string cabins ==")
    starts = function_starts(words)
    for pc, value in materialized_pointers(words):
        bank_off = value - BANK_BASE
        if not any(lo <= bank_off < lo + span for lo, span in cabins):
            continue
        i = bisect.bisect_right(starts, pc) - 1
        fn = f"sub_{starts[i]:05x}" if i >= 0 else "?"
        text = ""
        for lo, span in cabins:
            if lo <= bank_off < lo + span:
                m = STRING_RUN.match(image, bank_off)
                if m:
                    text = m.group()[:60].decode("ascii", "replace")
        print(f"  pc 0x{pc:05x} fn {fn} -> runtime 0x{value:08x} "
              f"(bank 0x{bank_off:05x}) {text!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
