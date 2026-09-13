#!/usr/bin/env python3
"""Small field-level sanity check for the ATA186 MIPS-X SLEIGH profile."""
from __future__ import annotations


def u32(v: int) -> int:
    return v & 0xFFFFFFFF


def sx(v: int, bits: int) -> int:
    sign = 1 << (bits - 1)
    return (v ^ sign) - sign


def type1(op: int, s1: int, s2: int, d: int, func: int) -> int:
    return u32((1 << 30) | (op << 27) | (s1 << 22) | (s2 << 17) | (d << 12) | func)


def type3(op: int, s1: int = 0, s2: int = 0, imm17: int = 0) -> int:
    return u32((3 << 30) | (op << 27) | (s1 << 22) | (s2 << 17) | (imm17 & 0x1FFFF))


def branch(op: int, s1: int, s2: int, sq: int, disp_words: int) -> int:
    # bit16 is SQ; the low 16 bits are the signed branch displacement.
    return u32((op << 27) | (s1 << 22) | (s2 << 17) | ((sq & 1) << 16) | (disp_words & 0xFFFF))


def fields(word: int) -> dict[str, int]:
    return {
        "ty": (word >> 30) & 3,
        "op": (word >> 27) & 7,
        "src1": (word >> 22) & 31,
        "src2": (word >> 17) & 31,
        "dest": (word >> 12) & 31,
        "func12": word & 0xFFF,
        "imm17": sx(word & 0x1FFFF, 17),
        "disp16": sx(word & 0xFFFF, 16),
        "sq": (word >> 16) & 1,
    }


NOP = type1(4, 0, 0, 0, 0x019)
HSC = 0xCFC00000
JPC = 0xE8000003
JPCRS = 0xF8000003
ADDI_SP_NEG16 = type3(4, 29, 29, -16)
BEQ_R1_R2_P3 = branch(1, 1, 2, 0, 3)

assert NOP == 0x60000019
assert HSC == 0xCFC00000
assert JPC == 0xE8000003
assert JPCRS == 0xF8000003
assert fields(ADDI_SP_NEG16)["imm17"] == -16
assert fields(BEQ_R1_R2_P3)["disp16"] == 3

for name, word in [
    ("nop", NOP),
    ("hsc", HSC),
    ("jpc", JPC),
    ("jpcrs", JPCRS),
    ("addi r29,-16,r29", ADDI_SP_NEG16),
    ("beq r1,r2,+3 words", BEQ_R1_R2_P3),
]:
    print(f"{name:22s} {word:08x}  bytes={word.to_bytes(4, 'big').hex()}  fields={fields(word)}")
