#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""Bounded offline MIPS-X boot tracer and dispatch resolver for ATA186 banks.

The tool reconstructs the runtime RAM image of one pinned bank (7
stored-deflate streams at fixed offsets), then interprets big-endian
MIPS-X machine code with the semantics validated against the resident
boot tail: two delay slots for branches and calls, word-scaled ``jspcii``
targets (byte address = (register + displacement) * 4), and call links at
instruction start + 12 bytes.

It never opens a socket, never writes files, and executes only the bank
given on the command line.  Bare invocation is inert because the package
and bank paths are required.  A step ceiling bounds every run.

Two entry modes are supported:

``boot``   entry at the resident reset stub and step the launch pipeline.
``entry``  apply the pinned launch ABI registers and enter the main
           program at its terminal type-3 record target.

Both modes log each indirect ``jspci`` transfer (call site, base register,
resolved byte target) so the position-independent call family can be
resolved statically.
"""

from __future__ import annotations

import argparse
import struct
import sys
import time

try:
    from . import mipsx_image
except ImportError:  # executed as a script with firmware/ on sys.path
    import mipsx_image


MAX_PACKAGE_BYTES = 2 * 1024 * 1024
MAX_BANK_BYTES = 0x80000
FLAT_BYTES = 0x100000          # every alias window folds into 1 MiB
MASK32 = 0xFFFFFFFF
DEFAULT_STEP_LIMIT = 120_000_000
MIN_STEPS = 1
MAX_STEPS = 400_000_000

RUNTIME_BASE = 0x0CF80000      # alias window start; identity with the bank
PC_TAG = 0x40000000            # terminal type-3 PC tag, stripped on transfer

# The bank image is no longer rebuilt here.  firmware/zup_bank.py owns
# reconstruction and firmware/mipsx_image.py gates it on the pinned digest;
# hardcoding region tables here previously dropped the four raw regions.

# Pinned launch ABI register state (main launch table, records 0..26),
# and the terminal type-3 entry: (0x400031d3 & ~PC_TAG) * 4 = bank 0xc74c.
SIP_ABI_REGS = {
    4: 0x0CFC79BC,
    5: 0x0000C74C,
    19: 0x00007B84,
    23: 0x000131D3,
    24: 0x033F0280,
    25: 0x0007FC00,
    29: 0x0007F800,
}
SIP_ENTRY_WORD = 0x0000C74C // 4
BOOT_ENTRY_WORD = 0x7FF80 // 4
VALIDATOR_CALL_PC = 0x7FD0C
SELECTOR_PC = 0x7FD18
SELECTED_HEADER = 0x0CFC0100


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, f"error: {message}\n")


def s17(value: int) -> int:
    value &= 0x1FFFF
    return value - 0x20000 if value & 0x10000 else value


def s16(value: int) -> int:
    value &= 0xFFFF
    return value - 0x10000 if value & 0x8000 else value


def shift_amount(encoded: int) -> int:
    low = encoded & 0x0F
    adjustment = {1: 0, 2: 1, 4: 2, 8: 3}.get(low)
    if adjustment is None:
        return 0
    return 32 - (((encoded & 0x70) >> 2) + adjustment)


# Shared alias/memory model: firmware/mipsx_image.py owns address folding so
# the emulator, resolver, and table scanner cannot disagree about which byte
# an address names.
Memory = mipsx_image.Memory


class CPU:
    """MIPS-X interpreter with two delay slots and word-scaled transfers.

    Semantics validated against the resident boot tail: a taken branch or
    call executes two delay-slot instructions (or one when the SQ bit
    squashes it), then transfers.  ``jspci`` links the word address of
    instruction start + 12 bytes and computes its target as
    ``(register + displacement) * 4`` with the 0x40000000 tag stripped.
    """

    def __init__(self, mem: Memory, pc_byte: int) -> None:
        self.mem = mem
        self.r = [0] * 32
        self.pc = pc_byte & ~3
        self.pending = False
        self.slots_left = 0
        self.target = 0
        self.halt: str | None = None
        self.calls: list[tuple[int, int, int]] = []
        self.unique_targets: dict[int, int] = {}

    def step(self) -> None:
        pc = self.pc
        w = self.mem.load(pc)
        kind = (w >> 30) & 3
        op = (w >> 27) & 7
        s1 = (w >> 22) & 0x1F
        s2 = (w >> 17) & 0x1F
        dest = (w >> 12) & 0x1F
        fn = w & 0xFFF
        reg = self.r

        if kind == 0:
            taken_target = (pc + 8 + s16(w & 0xFFFF) * 4) & MASK32
            a, b = reg[s1], reg[s2]
            if op == 1:
                cond = a == b
            elif op == 5:
                cond = a != b
            elif op == 2:
                cond = a >= b
            elif op == 3:
                cond = (a - 0x100000000 if a & 0x80000000 else a) < (
                    b - 0x100000000 if b & 0x80000000 else b)
            elif op == 6:
                cond = a < b
            elif op == 7:
                cond = (a - 0x100000000 if a & 0x80000000 else a) >= (
                    b - 0x100000000 if b & 0x80000000 else b)
            else:
                cond = False
            if cond:
                # the sleigh models the SQ form with the same two delay slots
                self._begin_transfer(taken_target, squash=False)
            else:
                self.pc = pc + 4
            return

        if kind == 2:
            imm = s17(w & 0x1FFFF)
            addr = (reg[s1] + imm) & MASK32
            if op in (0, 1, 4):
                reg[s2] = self.mem.load(addr)
            elif op in (2, 3, 6):
                self.mem.store(addr, reg[s2])
            self.pc = pc + 4
            return

        if kind == 1:
            if op == 0:
                self.pc = pc + 4  # multiplier steps left conservative
                return
            if op == 1:
                if fn == 0x080:
                    reg[dest] = (reg[s1] << 1 | reg[s2] >> 31) & MASK32
                elif fn == 0x0C0:
                    reg[dest] = (reg[s1] >> 1 | reg[s2] << 31) & MASK32
                elif (fn & 0xF80) == 0x100:
                    amount = fn & 0x7F
                    v = reg[s1]
                    if v & 0x80000000:
                        v |= 0xFF000000
                    reg[dest] = v >> amount
                elif (fn & 0xF80) == 0x200:
                    amount = shift_amount(fn & 0x7F)
                    if s1 == 0:
                        reg[dest] = (reg[s2] << (32 - amount)) & MASK32
                    elif s2 == 0:
                        reg[dest] = reg[s1] >> amount
                    else:
                        reg[dest] = (reg[s1] << amount | reg[s2] >> (32 - amount)) & MASK32
                self.pc = pc + 4
                return
            if op == 4:
                if fn == 0x00B:
                    reg[dest] = ~reg[s1]
                elif fn == 0x01B:
                    reg[dest] = reg[s1] ^ reg[s2]
                elif fn == 0x023:
                    reg[dest] = reg[s1] & reg[s2]
                elif fn == 0x026:
                    reg[dest] = reg[s1] - reg[s2]
                elif fn == 0x03B:
                    reg[dest] = reg[s1] | reg[s2]
                elif fn == 0x066:
                    reg[dest] = reg[s1] - reg[s2]
                elif fn == 0x00F:
                    reg[dest] = ~reg[s1]
                elif fn == 0x019:
                    if s1 == 0 or s2 == 0:
                        reg[dest] = reg[s1 | s2]
                    else:
                        reg[dest] = reg[s1] + reg[s2]
                self.pc = pc + 4
                return
            self.halt = f"unimplemented ty1 op{op} at 0x{pc:08x}"
            return

        if op == 0:
            disp = s17(w & 0x1FFFF)
            target_word = (reg[s1] + disp) & MASK32
            target = (target_word & ~PC_TAG) * 4
            if s2 != 0:
                reg[s2] = ((pc + 12) >> 2) & MASK32
            if s1 != 31 or disp != 0:
                self.calls.append((pc, s1, target))
                self.unique_targets[target] = self.unique_targets.get(target, 0) + 1
            self._begin_transfer(target, squash=False)
            return
        if op == 1:
            self.halt = f"hsc at 0x{pc:08x}"
            return
        if op in (2, 3):
            self.pc = pc + 4  # special-register moves left conservative
            return
        if op == 4:
            reg[s2] = (reg[s1] + s17(w & 0x1FFFF)) & MASK32
            self.pc = pc + 4
            return
        self.halt = f"unimplemented ty3 op{op} at 0x{pc:08x}"

    def _begin_transfer(self, target: int, squash: bool) -> None:
        self.target = target & ~3
        self.pending = True
        # the pending transfer itself applies after two delay-slot steps:
        # three pending steps consume the call step plus both slots
        self.slots_left = 3
        self.pc = self.pc + 4

    def run(self, limit: int) -> int:
        steps = 0
        while self.halt is None and steps < limit:
            self.step()
            if self.pending:
                self.slots_left -= 1
                if self.slots_left <= 0:
                    self.pc = self.target
                    self.pending = False
            steps += 1
        return steps


def build_runtime_image(package: bytes) -> bytes:
    """Reconstruct the pinned SIP bank through the single validated builder.

    Delegates to firmware/mipsx_image.py (which wraps firmware/zup_bank.py)
    and asserts the pinned SHA-256, so an incomplete or wrong image raises
    instead of silently steering the interpreter down a bogus branch.
    """
    if len(package) > MAX_PACKAGE_BYTES:
        raise ValueError("package exceeds the bounded size")
    return mipsx_image.build_bank_checked(
        package, mipsx_image.PINNED_SIP_SHA256)


def resolve_dispatch(offset: int, anchor: int = 0x40A00) -> int:
    """Static target of one ``jspci r24, offset`` family dispatch.

    The offset is the signed word displacement as printed by Ghidra as
    ``(in_r24 + offset) * 4``.  Validated by execution: ``-0xd881`` maps to
    bank byte 0xa7fc, the most-called program function.
    """
    if not -0x20000 <= offset < 0x20000:
        raise ValueError("displacement outside the 17-bit signed field")
    return RUNTIME_BASE + ((anchor + 4 * offset) & 0x3FFFF)


def main(argv: list[str] | None = None) -> int:
    parser = SafeArgumentParser(description=__doc__ or None if False else "boot tracer")
    parser.description = "Bounded offline MIPS-X boot tracer and dispatch resolver."
    parser.add_argument("package", help="path to a pinned .zup package (read-only)")
    parser.add_argument("bank", help="path to the reconstructed 512 KiB bank (read-only)")
    parser.add_argument("--mode", choices=("boot", "entry"), required=True,
                        help="boot = resident reset stub; entry = main program ABI entry")
    parser.add_argument("--steps", type=int, default=DEFAULT_STEP_LIMIT,
                        help=f"instruction ceiling (default {DEFAULT_STEP_LIMIT})")
    args = parser.parse_args(argv)

    if not MIN_STEPS <= args.steps <= MAX_STEPS:
        parser.error("steps outside the bounded range")

    with open(args.package, "rb") as handle:
        package = handle.read()
    entry = BOOT_ENTRY_WORD if args.mode == "boot" else SIP_ENTRY_WORD
    cpu = CPU(Memory(build_runtime_image(package)), entry * 4)
    if args.mode == "entry":
        for reg, value in SIP_ABI_REGS.items():
            cpu.r[reg] = value

    started = time.time()
    steps = cpu.run(args.steps)
    elapsed = time.time() - started
    print(f"steps={steps} halt={cpu.halt} transfers={len(cpu.calls)}")
    for target, count in sorted(cpu.unique_targets.items(), key=lambda kv: -kv[1])[:16]:
        print(f"  transfer -> bank byte 0x{target & 0x7FFFF:05x} x{count}")
    print(f"elapsed_seconds={elapsed:.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
