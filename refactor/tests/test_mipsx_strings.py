#!/usr/bin/env python3
"""Synthetic tests for the bounded string inventory scanner.

No firmware bytes: bank images are synthetic byte arrays assembled by the
tests themselves.
"""

import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from refactor.mipsx_strings import (
    extract_strings,
    function_starts,
    materialized_pointers,
)


def bank(size: int = 0x100) -> bytes:
    return bytearray(size)


class StringScanTest(unittest.TestCase):
    def test_extract_strings(self) -> None:
        image = bytearray(0x40)
        image[0x10:0x10 + len(b"SyslogCtrl")] = b"SyslogCtrl\x00"
        found = extract_strings(bytes(image))
        self.assertIn(0x10, found)
        self.assertEqual(found[0x10], "SyslogCtrl")

    def test_materialization_triple(self) -> None:
        # exact boot-tail triple: addi r0,#0xcff,r2 ; lsl r2,r2,#16 ;
        # addi r2,#0xf9fc,r2 -> 0x0cfff9fc (encodings verified by the
        # published disassembler against the resident setup)
        mem = bytearray(0x60)
        mem[0x00:4] = struct.pack(">I", 0xE0040CFF)
        mem[0x04:8] = struct.pack(">I", 0x48042241)
        mem[0x08:12] = struct.pack(">I", 0xE084F9FC)
        words = struct.unpack(">%dI" % (len(mem) // 4), bytes(mem))
        self.assertEqual(function_starts(words), [])
        refs = materialized_pointers(words)
        self.assertEqual(refs, [(8, 0x0CFFF9FC)])

    def test_function_start_prologue(self) -> None:
        # the real prologue encoding from the packed main, e77bff98 =
        # addi r29,-0x68,r29, verified by the published disassembler
        mem = bytearray(0x20)
        mem[0x10:14] = struct.pack(">I", 0xE77BFF98)
        words = struct.unpack(">%dI" % (len(mem) // 4), bytes(mem))
        self.assertEqual(function_starts(words), [0x10])


if __name__ == "__main__":
    unittest.main()
