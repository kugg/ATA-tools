#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""Single, hash-asserted source of the reconstructed ATA bank image.

Every consumer (emulators, dispatch resolvers, table scanners) must build
its memory from here, so "which bytes are we executing" has exactly one
answer.  Reconstruction is delegated to refactor/zup_bank.py, which is
already validated to reproduce the pinned bank SHA-256 byte-for-byte.

Two failure modes motivated this module and are now rejected:

* Rebuilding the image from a hand-maintained subset of regions.  A
  deflate-only builder silently omitted the four raw regions (190,788 of
  524,288 bytes, 36% of the bank), leaving the launch descriptor at bank
  offset 0x479BC zero and sending the interpreter down a bogus branch.
* Trusting an image without checking its digest.  ``load_bank`` fails
  closed on a SHA-256 mismatch instead of proceeding on wrong bytes.

This module is intentionally free of instruction semantics; that belongs
to one execution engine, not to each caller.
"""

from __future__ import annotations

import hashlib
import os
import sys

try:
    from refactor import zup_bank
except ImportError:  # executed with refactor/ on sys.path
    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)
    from refactor import zup_bank


# Pinned artifact digests (see docs/firmware-analysis.md "Pinned Inputs").
PINNED_SIP_SHA256 = (
    "ee2247ad3b9cbd5d711f4985cbdce220359e6edff6555d8486e119e767c8f8c6"
)
PINNED_TRANSITION_SHA256 = (
    "ad7abb7575a14885c171f4cf6a630f60547d2ccd03b47b55c04a279278332eee"
)

DEFAULT_SIP_PACKAGE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "ata_03_01_00_sip_040211_1",
    "ATA030100SIP040211A.zup",
)

BANK_BYTES = 0x80000            # 512 KiB reconstructed bank
FLAT_BYTES = 0x100000           # every alias window folds into 1 MiB
RUNTIME_BASE = 0x0CF80000       # identity alias window start
ALIAS_END = 0x0D000000
SFR_BASE = 0x20000000           # special-function register window
SFR_END = 0x20100000
MASK32 = 0xFFFFFFFF


class ImageError(Exception):
    """The reconstructed image is missing, malformed, or unexpected."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_bank(package_path: str, expected_sha256: str | None = None) -> bytes:
    """Reconstruct the 512 KiB bank and fail closed on a digest mismatch."""
    package = zup_bank.read_package(package_path)
    return build_bank_checked(package, expected_sha256)


def build_bank_checked(package: bytes,
                       expected_sha256: str | None = None) -> bytes:
    """Reconstruct the bank from package bytes, optionally asserting digest."""
    result = zup_bank.build_bank(package)
    data = bytes(result.data)
    if len(data) != BANK_BYTES:
        raise ImageError(
            f"bank is {len(data)} bytes, expected {BANK_BYTES}")
    if expected_sha256 is not None:
        actual = _sha256(data)
        if actual != expected_sha256:
            raise ImageError(
                f"bank sha256 {actual} != expected {expected_sha256}")
    return data


def load_pinned_sip(package_path: str | None = None) -> bytes:
    """Load the pinned SIP bank, asserting the documented digest."""
    return load_bank(package_path or DEFAULT_SIP_PACKAGE, PINNED_SIP_SHA256)


def flat_offset(addr: int) -> int:
    """Fold a 32-bit MIPS-X address into the 1 MiB flat window.

    The alias model is the one developed for the boot tracer and is kept
    here so every consumer agrees.  Bit-28 and bit-31 tagged forms, the
    0x0D mirror page, the 0x0CF80000 identity window, and the low identity
    all collapse onto the reconstructed bank.
    """
    addr &= MASK32
    if 0x1C000000 <= addr < 0x1D000000:
        # bit-28 window: bank-relative read/write alias
        return (addr - 0x1CF80000) & (BANK_BYTES - 1)
    if 0x0D000000 <= addr < 0x0E000000:
        # bank mirror page used for data reads past the 512 KiB mark
        return addr & 0xFFFFFF
    if RUNTIME_BASE <= addr < ALIAS_END:
        # bank identity alias
        return addr - RUNTIME_BASE
    if addr & 0x80000000:
        # bit-31 tagged window
        return addr & (BANK_BYTES - 1)
    if 0x01000000 <= addr < 0x02000000:
        return (addr - 0x01000000) & (FLAT_BYTES - 1)
    return addr & (FLAT_BYTES - 1)


class Memory:
    """Flat 1 MiB window plus the 0x2000xxxx special-function window.

    Writes to the SFR window are absorbed, so device initialization cannot
    corrupt the image.  Reads and writes outside the flat window raise
    instead of silently aliasing, which is what let earlier image builders
    hide a missing 36% of the bank.
    """

    def __init__(self, image: bytes) -> None:
        if len(image) < BANK_BYTES:
            raise ImageError(
                f"image is {len(image)} bytes, need at least {BANK_BYTES}")
        self.m = bytearray(FLAT_BYTES)
        self.m[: len(image)] = image
        self.sfr: dict[int, int] = {}

    def _flat(self, addr: int) -> int:
        addr &= MASK32
        if 0x0D000000 <= addr < 0x0E000000:
            offset = addr & 0xFFFFFF
            if offset >= FLAT_BYTES:
                raise MemoryError(f"mirror read outside flat window: {addr:#x}")
            return offset
        offset = flat_offset(addr)
        if offset >= FLAT_BYTES:
            raise MemoryError(f"address {addr:#x} folds outside flat window")
        return offset

    def load(self, addr: int) -> int:
        addr &= MASK32
        if SFR_BASE <= addr < SFR_END:
            return self.sfr.get(addr & 0xFFFF, 0)
        offset = self._flat(addr)
        return int.from_bytes(self.m[offset:offset + 4], "big")

    def store(self, addr: int, value: int) -> None:
        addr &= MASK32
        value &= MASK32
        if SFR_BASE <= addr < SFR_END:
            self.sfr[addr & 0xFFFF] = value
            return
        offset = self._flat(addr)
        self.m[offset:offset + 4] = value.to_bytes(4, "big")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", nargs="?", default=DEFAULT_SIP_PACKAGE)
    parser.add_argument("--expect", default=PINNED_SIP_SHA256,
                        help="expected bank SHA-256 (default: pinned SIP)")
    args = parser.parse_args()
    bank = load_bank(args.package, args.expect or None)
    print(f"package={args.package}")
    print(f"bank_bytes={len(bank)}")
    print(f"bank_sha256={_sha256(bank)}")
    print("digest_ok=True")
