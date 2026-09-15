#!/usr/bin/env python3
"""Synthetic tests for the bounded MIPS-X boot tracer.

Every vector is synthetic: no firmware bytes, no package images, and no
network access.  The tests pin the semantics validated against the resident
boot tail: two delay slots, the word-scaled ``jspci`` target, the link
value at instruction start + 12 bytes, the 1 MiB page-mask memory map, and
the static dispatch resolution formula.
"""

import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from refactor.mipsx_boot_trace import (
    CPU,
    Memory,
    resolve_dispatch,
    s17,
    shift_amount,
)


def nop() -> int:
    return 0x60000019


class MipsxSemanticsTest(unittest.TestCase):
    def test_jspci_two_delay_slots_and_link(self) -> None:
        # jspci r13,+0,r31 (encoding taken from the resident return stub);
        # the target register holds a WORD address, the transfer lands on
        # the byte address, and two delay slots execute before it.
        mem = Memory(bytes(0x80000))
        call_pc = 0x4000
        mem.store(call_pc, 0xC37E0000)            # jspci r13,+0,r31
        mem.store(call_pc + 4, nop())             # delay slot 1
        mem.store(call_pc + 8, nop())             # delay slot 2
        target = 0x8000
        mem.store(target + 4, 0xE0040001)         # addi r0,+1,r2 marker
        cpu = CPU(mem, call_pc)
        cpu.r[13] = target >> 2                   # register holds the word form
        cpu.run(4)
        self.assertIsNone(cpu.halt)
        self.assertEqual(cpu.pc, target + 4)
        self.assertEqual(cpu.calls, [(call_pc, 13, target)])
        # link = instruction start + 12 bytes, stored as a word address
        self.assertEqual(cpu.r[31], (call_pc + 12) >> 2)

    def test_jspci_return_form_is_not_recorded(self) -> None:
        # jspci r31,+0,r0 is the plain-return epilogue and must not appear
        # in the logged transfer list.
        mem = Memory(bytes(0x80000))
        mem.store(0x4000, 0xC7C00000)
        mem.store(0x4004, nop())
        mem.store(0x4008, nop())
        return_pc = 0x2000
        mem.store(return_pc, nop())
        cpu = CPU(mem, 0x4000)
        cpu.r[31] = return_pc >> 2
        cpu.run(3)
        self.assertEqual(cpu.pc, return_pc)
        self.assertEqual(cpu.calls, [])

    def test_squashed_branch_matches_sleigh(self) -> None:
        # the SQ form runs both delay slots on a taken transfer, exactly
        # like the published sleigh constructor
        mem = Memory(bytes(0x80000))
        mem.store(0x4000, 0x088503FE)             # beq.sq r2,r2,target
        mem.store(0x4004, 0xE0040001)             # slot 1: addi r0,+1,r2
        mem.store(0x4008, 0xE0040002)             # slot 2: addi r0,+2,r2
        target = 0x5000
        mem.store(target, nop())
        cpu = CPU(mem, 0x4000)
        cpu.r[2] = 7                              # r2 == r2: taken
        cpu.run(3)
        self.assertEqual(cpu.pc, target)
        self.assertEqual(cpu.r[2], 2)             # both slots executed

    def test_page_mask_memory_map(self) -> None:
        mem = Memory(bytes(0x80000))
        mem.store(0x40104, 0x0CFC0110)
        # aliased windows resolve to the same flat cell
        for window in (0x40104, 0x0CFC0104, 0x0D040104, 0x01040104, 0x80040104):
            self.assertEqual(mem.load(window), 0x0CFC0110)
        # the bit28 bank window is offset by its own base
        mem.store(0x7D104, 0x0CFC0110)
        self.assertEqual(mem.load(0x1CFFD104), 0x0CFC0110)
        # the SFR window absorbs writes instead of corrupting the image
        mem.store(0x20004030, 0x1234)
        self.assertEqual(mem.load(0x20004030), 0x1234)
        self.assertEqual(mem.load(0x4030), 0)

    def test_static_dispatch_resolution(self) -> None:
        # validated by execution: the most-called program function
        self.assertEqual(resolve_dispatch(-0xD881), 0x0CF8A7FC)
        self.assertEqual(resolve_dispatch(-0x10000), 0x0CF80A00)
        with self.assertRaises(ValueError):
            resolve_dispatch(0x20000)


if __name__ == "__main__":
    unittest.main()
