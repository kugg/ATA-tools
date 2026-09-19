#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""Regenerate the readable packed-main C deterministically.

Two stages, both driven only by pinned artifacts and the evidence-backed
naming map (refactor/naming/packed_main.json):

1. ``ghidra_decompile_packed.py`` decompiles the packed main, resolves the
   jspci call/tail targets, and applies the naming map (function names and
   global labels, each with its evidence as a plate comment).
2. ``annotate_packed_c.py`` substitutes the resolved r23/r24 call targets and
   normalises scalar types.

The output is regenerable from scratch: do not hand-edit the generated C;
edit the naming map and re-run this script.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_PACKAGE = os.path.join(
    ROOT, "ata_03_01_00_sip_040211_1", "ATA030100SIP040211A.zup")
DEFAULT_NAMES = os.path.join(HERE, "naming", "packed_main.json")
OUT_DIR = os.path.join(ROOT, "research", "decompiled", "named")


def run(command: list[str]) -> None:
    print("+", " ".join(command))
    result = subprocess.run(command)
    if result.returncode != 0:
        raise SystemExit(f"stage failed: {command[1]}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", default=DEFAULT_PACKAGE)
    parser.add_argument("--names", default=DEFAULT_NAMES)
    parser.add_argument("--project", default=None,
                        help="persistent Ghidra project (else a temp project)")
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args(argv)

    os.makedirs(OUT_DIR, exist_ok=True)
    readable = os.path.join(OUT_DIR, "packed_main_readable.c")
    annotated = os.path.join(OUT_DIR, "packed_main_annotated.c")

    decompile = [
        sys.executable, os.path.join(HERE, "ghidra_decompile_packed.py"),
        args.package, "--type8-payload", "0x479bc", "--reg-base", "r23=0x40000",
        "--names", args.names, "--out", readable, "--timeout", str(args.timeout),
    ]
    if args.project:
        decompile += ["--project", args.project]
    run(decompile)

    run([
        sys.executable, os.path.join(HERE, "annotate_packed_c.py"),
        readable, args.package, "--out", annotated, "--names", args.names,
    ])
    print(f"readable={readable}\nannotated={annotated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
