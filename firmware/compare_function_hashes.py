#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""Compare bounded Ghidra function-hash exports without proprietary bytes."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import os
import stat
import sys

MAX_FUNCTIONS = 10000
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_FUNCTION_BYTES = 16 * 1024 * 1024


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, "error: invalid arguments\n")


def read_hashes(path: str) -> list[tuple[int, int, str]]:
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_NONBLOCK"):
        raise ValueError("secure function hash opening is unavailable")
    before = os.lstat(path)
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_FILE_BYTES:
        raise ValueError("function hash input must be a bounded regular file")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                         | getattr(os, "O_CLOEXEC", 0))
    try:
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode) or details.st_size > MAX_FILE_BYTES \
                or (before.st_dev, before.st_ino) != (
                    details.st_dev, details.st_ino):
            raise ValueError("function hash input must be a bounded regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as input_file:
            raw = input_file.read(MAX_FILE_BYTES + 1)
        after = os.fstat(descriptor)
        if len(raw) != details.st_size or (
                after.st_dev, after.st_ino, after.st_size,
                after.st_mtime_ns, after.st_ctime_ns) != (
                details.st_dev, details.st_ino, details.st_size,
                details.st_mtime_ns, details.st_ctime_ns):
            raise ValueError("function hash input changed while being read")
    finally:
        os.close(descriptor)
    rows = []
    try:
        lines = raw.decode("ascii").splitlines()
    except UnicodeDecodeError as exc:
        raise ValueError("function hash input is not ASCII") from exc
    for line in lines:
        fields = line.split("\t")
        if len(fields) != 3 or len(fields[2]) != 64:
            raise ValueError("function hash row is invalid")
        try:
            address = int(fields[0], 16)
            size = int(fields[1], 16)
            int(fields[2], 16)
        except ValueError as exc:
            raise ValueError("function hash row is invalid") from exc
        if not 0 <= address <= 0xFFFFFFFF \
                or not 0 < size <= MAX_FUNCTION_BYTES:
            raise ValueError("function hash row is invalid")
        rows.append((address, size, fields[2].lower()))
        if len(rows) > MAX_FUNCTIONS:
            raise ValueError("too many function hash rows")
    return rows


def compare(left: list[tuple[int, int, str]],
            right: list[tuple[int, int, str]]) -> tuple[list[tuple[int, int, int]], Counter]:
    left_by_hash = defaultdict(list)
    right_by_hash = defaultdict(list)
    for address, size, digest in left:
        left_by_hash[(size, digest)].append(address)
    for address, size, digest in right:
        right_by_hash[(size, digest)].append(address)
    matches = []
    deltas = Counter()
    for key in sorted(set(left_by_hash) & set(right_by_hash)):
        if len(left_by_hash[key]) != 1 or len(right_by_hash[key]) != 1:
            continue
        left_address = left_by_hash[key][0]
        right_address = right_by_hash[key][0]
        matches.append((left_address, right_address, key[0]))
        deltas[right_address - left_address] += 1
    return matches, deltas


def main(argv: list[str] | None = None) -> int:
    parser = SafeArgumentParser(description=__doc__)
    parser.add_argument("sip")
    parser.add_argument("transition")
    arguments = parser.parse_args(argv)
    try:
        sip = read_hashes(arguments.sip)
        transition = read_hashes(arguments.transition)
    except (OSError, ValueError):
        print("error: invalid function hash input", file=sys.stderr)
        return 1
    matches, deltas = compare(sip, transition)
    print(f"sip_functions={len(sip)}")
    print(f"transition_functions={len(transition)}")
    print(f"unique_exact_matches={len(matches)}")
    for delta, count in deltas.most_common(10):
        print(f"delta={delta:+#x} matches={count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
