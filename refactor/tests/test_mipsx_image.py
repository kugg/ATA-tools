#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""Tests for the single hash-asserted bank image source."""

import hashlib
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from refactor import mipsx_image


ROOT = Path(__file__).resolve().parents[2]
_CANDIDATES = [
    Path(os.environ["ATA186_TEST_ARTIFACT_DIR"]) if
    os.environ.get("ATA186_TEST_ARTIFACT_DIR") else None,
    ROOT / "vendor",
    ROOT / "ata_03_01_00_sip_040211_1",
]
ATA_ZUP = next(
    (base / "ATA030100SIP040211A.zup"
     for base in _CANDIDATES if base is not None
     and (base / "ATA030100SIP040211A.zup").exists()),
    ROOT / "vendor" / "ATA030100SIP040211A.zup",
)


class FlatOffsetTests(unittest.TestCase):
    def test_low_identity(self):
        self.assertEqual(mipsx_image.flat_offset(0x0000C74C), 0xC74C)

    def test_runtime_identity_alias(self):
        self.assertEqual(mipsx_image.flat_offset(0x0CF80000), 0)
        self.assertEqual(mipsx_image.flat_offset(0x0CFC79BC), 0x479BC)

    def test_bit31_tagged_window(self):
        self.assertEqual(mipsx_image.flat_offset(0x80000123), 0x123)

    def test_high_bits_masked(self):
        self.assertEqual(
            mipsx_image.flat_offset(0xFFFFFFFF), 0x7FFFF)


class MemoryTests(unittest.TestCase):
    def _bank(self):
        if not ATA_ZUP.exists():
            self.skipTest("needs pinned ATA .zup")
        return mipsx_image.load_bank(str(ATA_ZUP))

    def test_sfr_window_absorbs_writes(self):
        mem = mipsx_image.Memory(self._bank())
        before = mem.load(0x10)
        mem.store(0x20000010, 0xDEADBEEF)
        self.assertEqual(mem.load(0x20000010), 0xDEADBEEF)
        # the SFR write must not alias onto RAM offset 0x10
        self.assertEqual(mem.load(0x10), before)

    def test_raw_region_present_at_descriptor(self):
        """The deflate-only builder left 0x479C0 zero; raw regions must fill it."""
        bank = self._bank()
        word = int.from_bytes(bank[0x479C0:0x479C4], "big")
        self.assertNotEqual(word, 0)


@unittest.skipUnless(ATA_ZUP.exists(), "needs pinned ATA .zup")
class PinnedImageTests(unittest.TestCase):
    def test_pinned_digest_matches(self):
        bank = mipsx_image.load_pinned_sip(str(ATA_ZUP))
        self.assertEqual(
            hashlib.sha256(bank).hexdigest(),
            mipsx_image.PINNED_SIP_SHA256)

    def test_wrong_digest_fails_closed(self):
        with self.assertRaises(mipsx_image.ImageError):
            mipsx_image.load_bank(str(ATA_ZUP), "0" * 64)

    def test_image_is_full_bank_size(self):
        bank = mipsx_image.load_pinned_sip(str(ATA_ZUP))
        self.assertEqual(len(bank), mipsx_image.BANK_BYTES)


if __name__ == "__main__":
    unittest.main()
