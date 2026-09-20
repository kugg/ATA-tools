#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""Annotate the packed-main decompilation with resolved call targets.

The Ghidra MIPS-X SLEIGH models ``jspci`` as ``call [(rN + disp) << 2]``,
so the decompiler renders an unresolved indirect call even when a
computed-call reference is present.  For the packed main the anchor is a
known constant (``type7 * 4 = type9 + 0x40000``), and with the payload
imported at base 0 that is ``r23 = 0x10000`` (word).  The substitution is
therefore exact:

    (*(code *)((in_r23 + disp) * 4))()   ->   sub_<target>()

Every produced target is cross-checked against the set of real ``jspci
r23`` targets decoded from the same payload; a target that is not in that
set is left untouched and counted.  ``jspci`` through the link register
``r31`` (link r0) is a return and becomes ``return;``.
"""

from __future__ import annotations

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from firmware import mipsx_dasm, zup_bank
except ImportError:  # executed with firmware/ on sys.path
    import mipsx_dasm
    import zup_bank


R23_ANCHOR_WORD = 0x10000  # type7*4 - type9 = 0x40000 byte, base-0 import
R24_ANCHOR_WORD = 0x10280  # resident r24 anchor: the packed main calls the resident
RUNTIME_BASE = 0x0CF80000

CALL_R23 = re.compile(
    r'\(\*\(code \*\)\(\((?:unaff_|in_)?r23 \+ (-?0x[0-9a-fA-F]+)\) \* 4\)\)')
CALL_R24 = re.compile(
    r'\(\*\(code \*\)\(\((?:unaff_|in_)?r24 \+ (-?0x[0-9a-fA-F]+)\) \* 4\)\)')
RETURN_R31 = re.compile(
    r'\(\*\(code \*\)\((?:unaff_|in_)?r31 << 2\)\)\(\)')


def load_resident_names(named_c_path: str) -> dict[str, str]:
    """Map runtime address hex (e.g. '0cf8d228') to the resident function name."""
    names: dict[str, str] = {}
    with open(named_c_path, "r") as handle:
        for match in re.finditer(r"// === (\S+) @ ([0-9a-fA-F]+)", handle.read()):
            names[match.group(2).lower()] = match.group(1)
    return names


def load_function_names(names_path: str) -> dict[int, str]:
    """Map packed-main address (int) to its evidence-backed name."""
    import json
    names: dict[int, str] = {}
    with open(names_path, "r") as handle:
        data = json.load(handle)
    for item in data.get("functions", []):
        names[int(item["address"], 16)] = item["name"]
    return names


def payload_r23_targets(payload: bytes) -> set[int]:
    regions = mipsx_dasm.validate_regions(
        [(0, len(payload) - (len(payload) % 4))], len(payload))
    targets: set[int] = set()
    for address, word in mipsx_dasm.iter_words(payload, regions, "big"):
        kind = (word >> 30) & 3
        operation = (word >> 27) & 7
        source1 = (word >> 22) & 0x1F
        if kind == 3 and operation == 0 and source1 == 23:
            displacement = word & 0x1FFFF
            if displacement & 0x10000:
                displacement -= 0x20000
            targets.add(((R23_ANCHOR_WORD + displacement) * 4) & 0xFFFFFFFF)
    return targets


def annotate(text: str, valid_targets: set[int],
             resident_names: dict[str, str] | None = None,
             function_names: dict[int, str] | None = None
             ) -> tuple[str, dict[str, int]]:
    stats = {"r23_resolved": 0, "r23_unverified": 0, "r24_resolved": 0,
             "r24_unverified": 0, "returns": 0, "retyped": 0}
    function_names = function_names or {}

    def replace_call(match: re.Match[str]) -> str:
        displacement = int(match.group(1), 16)
        target = ((R23_ANCHOR_WORD + displacement) * 4) & 0xFFFFFFFF
        if target in valid_targets:
            stats["r23_resolved"] += 1
            return function_names.get(target, f"sub_{target:08x}")
        stats["r23_unverified"] += 1
        return match.group(0)

    text = CALL_R23.sub(replace_call, text)

    if resident_names:
        def replace_resident(match: re.Match[str]) -> str:
            displacement = int(match.group(1), 16)
            target = ((R24_ANCHOR_WORD + displacement) * 4) & 0xFFFFFFFF
            name = resident_names.get(f"{RUNTIME_BASE + target:08x}")
            if name:
                stats["r24_resolved"] += 1
                return name
            stats["r24_unverified"] += 1
            return match.group(0)

        text = CALL_R24.sub(replace_resident, text)

    def replace_return(match: re.Match[str]) -> str:
        stats["returns"] += 1
        return "return"

    text = RETURN_R31.sub(replace_return, text)

    # Ghidra leaves unknown 4-byte scalars as undefined4; the ABI is 32-bit,
    # so present scalar return types and parameters as int.
    text, n_ret = re.subn(r'^undefined4 (\*?sub_[0-9a-f]{8}\()', r'int \1',
                          text, flags=re.MULTILINE)
    text, n_par = re.subn(r'\bundefined4 (\*?)param_', r'int \1param_', text)
    stats["retyped"] = n_ret + n_par
    return text, stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("c_file", help="Ghidra C for the packed payload")
    parser.add_argument("package", help="pinned .zup package (read-only)")
    parser.add_argument("--type8-payload", default=0x479BC,
                        type=lambda v: int(v, 0),
                        help="payload bank offset (SIP main: 0x479bc)")
    parser.add_argument("--out", default=None, help="annotated output C file")
    parser.add_argument("--resident-c", default=None,
                        help="resident named C used to resolve r24 cross-module calls")
    parser.add_argument("--names", default=None,
                        help="evidence-backed function naming map (JSON)")
    args = parser.parse_args(argv)

    out_path = args.out or re.sub(r"\.c$", "_annotated.c", args.c_file)
    with open(args.c_file, "r") as handle:
        text = handle.read()

    names_path = args.names or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "naming", "packed_main.json")
    function_names = load_function_names(names_path) \
        if os.path.isfile(names_path) else {}
    print(f"function names: {len(function_names)}")

    resident_c = args.resident_c or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "research", "decompiled", "named", "sip_bank_named_readable.c")
    resident_names = load_resident_names(resident_c) \
        if os.path.isfile(resident_c) else {}
    print(f"resident names: {len(resident_names)}")

    bank = zup_bank.build_bank(zup_bank.read_package(args.package))
    payload = zup_bank.parse_type8_payload(bank.data, args.type8_payload).data
    valid = payload_r23_targets(payload)
    print(f"valid r23 targets in payload: {len(valid)}")

    annotated, stats = annotate(text, valid, resident_names, function_names)
    with open(out_path, "w") as handle:
        handle.write(annotated)
    print(f"r23_resolved={stats['r23_resolved']} "
          f"r23_unverified={stats['r23_unverified']} "
          f"r24_resolved={stats['r24_resolved']} "
          f"r24_unverified={stats['r24_unverified']} "
          f"returns={stats['returns']}")
    print(f"output={out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
