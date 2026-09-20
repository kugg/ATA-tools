#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""Resolve a packed-main data-span pointer table to function names.

The packed main is loaded at runtime ``0xc74c`` (type-9 code start).  A pointer
stored in a type-8 mode-1 data span is a **runtime** word address, so the
payload-relative offset the decompiler uses is::

    payload_offset = value * 4 - 0xc74c

This resolves the ``g_dispatch_7580`` table (called as
``(*(code *)(*(int *)(idx*4 + 0x7580) << 2))()``) and any similar table, so the
result is reproducible and evidence-backed rather than hand-listed.
"""

from __future__ import annotations

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from firmware import zup_bank
except ImportError:
    import zup_bank

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_PACKAGE = os.path.join(
    ROOT, "ata_03_01_00_sip_040211_1", "ATA030100SIP040211A.zup")
DEFAULT_C = os.path.join(
    ROOT, "research", "decompiled", "named", "packed_main_annotated.c")

CODE_START = 0xC74C          # runtime load address of the packed main
SPAN2_BASE = 0x2FBC          # destination of the type-8 mode-1 payload 0x6cbcc
SPAN2_SRC = 0x6CBCC


def function_names(c_path: str) -> dict[int, str]:
    names: dict[int, str] = {}
    with open(c_path, "r") as handle:
        for match in re.finditer(r"// === (\S+) @ ([0-9a-f]+) ===", handle.read()):
            names[int(match.group(2), 16)] = match.group(1)
    return names


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", default=DEFAULT_PACKAGE)
    parser.add_argument("--c", default=DEFAULT_C,
                        help="named C using packed-main runtime addresses")
    parser.add_argument("--table", default="0x7580",
                        help="data-span address of the pointer table")
    parser.add_argument("--entries", type=int, default=14)
    args = parser.parse_args(argv)

    bank = zup_bank.build_bank(zup_bank.read_package(args.package)).data
    span = zup_bank.parse_type8_payload(bank, SPAN2_SRC).data
    names = function_names(args.c)
    table = int(args.table, 0)

    resolved = []
    for index in range(args.entries):
        off = table - SPAN2_BASE + index * 4
        value = int.from_bytes(span[off:off + 4], "big")
        runtime = (value * 4) & 0xFFFFFFFF
        payload = runtime - CODE_START
        name = names.get(runtime)
        resolved.append(name or f"?0x{payload:05x}")
        print(f"  [{index:2d}] value=0x{value:08x} runtime=0x{runtime:05x} "
              f"payload=0x{payload:05x} {resolved[-1]}")
    print("resolved:", ", ".join(resolved))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
