#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
# Decode-table attribution: Copyright David Haywood and MAME contributors.
# See ../THIRD_PARTY_NOTICES.md for the pinned source and BSD-3-Clause terms.
"""Bounded offline MIPS-X disassembler and cross-reference scanner.

The decode table follows MAME's BSD-3-Clause ``mipsxdasm.cpp`` at commit
``844b0763d46e1fbd2f21aea9528316a7b0cab7da``
and is checked against the MIPS-X architecture report, DTIC ADA181619.  The
type-2 op5/op7 names remain tentative because MAME notes that ES3210/ES3890
variants may use those encodings for byte operations.

This tool only reads a bounded regular file.  It opens no sockets and writes no
files.  Bare invocation is inert because an image path is required.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import os
import stat
import struct
import sys
from typing import Iterable, Sequence

if __package__:
    from . import zup_bank
else:
    import zup_bank


MAX_IMAGE_BYTES = 16 * 1024 * 1024
MAX_REGIONS = 64
MAX_RESULT_LIMIT = 1000
MAX_DISASSEMBLY_WORDS = 100000
MAX_INFERENCE_DISPLACEMENTS = 1024
MAX_INFERENCE_PROLOGUES = 5000
MAX_INFERENCE_PAIRS = 500000
MAX_CANDIDATE_SCORING_PAIRS = 50000000
MAX_SHARED_DISPLACEMENTS = 512
MAX_XREF_RECORDS = 65536
MAX_CFG_LOCAL_TARGETS = 65536
REGISTERS = tuple(f"r{index}" for index in range(32))


class SafeArgumentParser(argparse.ArgumentParser):
    """Keep parser diagnostics from echoing arbitrary command-line values."""

    def error(self, _message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, "error: invalid arguments\n")


@dataclass(frozen=True)
class Decoded:
    text: str
    kind: str
    target: int | None = None
    role: str | None = None
    base_register: int | None = None


@dataclass(frozen=True)
class BaseCandidate:
    base: int
    prologue_references: int
    prologue_targets: int
    in_range_references: int
    in_range_targets: int
    addi_prologue_references: int
    addi_prologue_targets: int


@dataclass(frozen=True)
class SharedDelta:
    delta: int
    shared_targets: int
    weighted_references: int


@dataclass(frozen=True)
class FlowTransfer:
    source: int
    kind: str
    target: int | None
    continuation: int | None
    delay_slots: tuple[int, ...]
    selected_slot_count: int
    slot_policy: str


def sign_extend(value: int, bits: int) -> int:
    sign = 1 << (bits - 1)
    return (value & (sign - 1)) - (value & sign)


def format_signed(value: int) -> str:
    if value < 0:
        return f"-0x{-value:x}"
    return f"+0x{value:x}"


def parse_int(text: str) -> int:
    try:
        value = int(text, 0)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected an integer") from exc
    if not 0 <= value <= 0xFFFFFFFF:
        raise argparse.ArgumentTypeError("integer must fit in 32 bits")
    return value


def parse_register(text: str) -> int:
    value = text.lower()
    if value.startswith("r"):
        value = value[1:]
    try:
        register = int(value, 10)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected r0 through r31") from exc
    if not 0 <= register < 32:
        raise argparse.ArgumentTypeError("expected r0 through r31")
    return register


def parse_register_base(text: str) -> tuple[int, int]:
    register_text, separator, base_text = text.partition("=")
    if not separator:
        raise argparse.ArgumentTypeError("expected rN=VALUE")
    return parse_register(register_text), parse_int(base_text)


def parse_region(text: str) -> tuple[int, int]:
    start_text, separator, end_text = text.partition(":")
    if not separator:
        raise argparse.ArgumentTypeError("expected START:END")
    start = parse_int(start_text)
    end = parse_int(end_text)
    if start >= end:
        raise argparse.ArgumentTypeError("region start must precede end")
    return start, end


def shift_amount(encoded: int) -> int:
    low = encoded & 0x0F
    adjustment = {1: 0, 2: 1, 4: 2, 8: 3}.get(low)
    if adjustment is None:
        return 0
    return 32 - (((encoded & 0x70) >> 2) + adjustment)


def decode(word: int, pc: int,
           register_bases: dict[int, int] | None = None) -> Decoded:
    """Decode one host-order MIPS-X word at byte address ``pc``.

    ``register_bases`` uses byte-coordinate call anchors. MIPS-X stores jump
    addresses in word units, so an architectural register value is one quarter
    of the corresponding anchor.
    """
    instruction_type = (word >> 30) & 0x3
    operation = (word >> 27) & 0x7
    source1 = (word >> 22) & 0x1F
    source2 = (word >> 17) & 0x1F
    destination = (word >> 12) & 0x1F
    function = word & 0xFFF

    if instruction_type == 0:
        displacement = sign_extend(word & 0xFFFF, 16) * 4
        target = (pc + 8 + displacement) & 0xFFFFFFFF
        squash = "sq" if (word >> 16) & 1 else ""
        mnemonic = {1: "beq", 2: "bhs", 3: "blt", 5: "bne",
                    6: "blo", 7: "bge"}.get(operation)
        if mnemonic is None:
            return Decoded(f"unknown TY0 (0x{word:08x})", "unknown")
        if operation == 1 and source1 == 0 and source2 == 0:
            text = f"bra{squash} 0x{target:08x}"
        else:
            text = (f"{mnemonic}{squash} {REGISTERS[source1]},"
                    f"{REGISTERS[source2]},0x{target:08x}")
        return Decoded(text, "branch", target, "branch")

    if instruction_type == 1:
        if operation == 0:
            if function == 0x0E6 and source1 == 0:
                text = f"mstart {REGISTERS[source2]},{REGISTERS[destination]}"
            elif function == 0x099:
                text = (f"mstep {REGISTERS[source1]},{REGISTERS[source2]},"
                        f"{REGISTERS[destination]}")
            elif function == 0x166:
                text = (f"dstep {REGISTERS[source1]},{REGISTERS[source2]},"
                        f"{REGISTERS[destination]}")
            else:
                return Decoded(f"unknown TY1 OP0 (0x{word:08x})", "unknown")
            return Decoded(text, "compute")

        if operation == 1:
            if function == 0x080:
                text = (f"rotlcb {REGISTERS[source1]},{REGISTERS[source2]},"
                        f"{REGISTERS[destination]}")
            elif function == 0x0C0:
                text = (f"rotlb {REGISTERS[source1]},{REGISTERS[source2]},"
                        f"{REGISTERS[destination]}")
            elif (function & 0xF80) == 0x100 and source2 == 0:
                amount = shift_amount(function & 0x7F)
                if not amount:
                    return Decoded(f"invalid asr TY1 OP1 (0x{word:08x})", "unknown")
                text = f"asr {REGISTERS[source1]},{REGISTERS[destination]},#{amount}"
            elif (function & 0xF80) == 0x200:
                amount = shift_amount(function & 0x7F)
                if not amount:
                    return Decoded(f"invalid sh TY1 OP1 (0x{word:08x})", "unknown")
                if source1 == 0:
                    text = (f"lsl {REGISTERS[source2]},{REGISTERS[destination]},"
                            f"#{32 - amount}")
                elif source2 == 0:
                    text = (f"lsr {REGISTERS[source1]},{REGISTERS[destination]},"
                            f"#{amount}")
                else:
                    text = (f"sh {REGISTERS[source1]},{REGISTERS[source2]},"
                            f"{REGISTERS[destination]},#{amount}")
            else:
                return Decoded(f"unknown TY1 OP1 (0x{word:08x})", "unknown")
            return Decoded(text, "compute")

        if operation == 4:
            if function == 0x00B:
                mnemonic = "bic"
            elif function == 0x01B:
                mnemonic = "xor"
            elif function == 0x023:
                mnemonic = "and"
            elif function == 0x026:
                mnemonic = "subnc"
            elif function == 0x03B:
                mnemonic = "or"
            elif function == 0x066:
                mnemonic = "sub"
            else:
                mnemonic = ""
            if mnemonic:
                return Decoded(
                    f"{mnemonic} {REGISTERS[source1]},{REGISTERS[source2]},"
                    f"{REGISTERS[destination]}", "compute")
            if function == 0x00F and source2 == 0:
                return Decoded(
                    f"not {REGISTERS[source1]},{REGISTERS[destination]}", "compute")
            if function == 0x019:
                if source1 == 0 or source2 == 0:
                    if destination == 0:
                        return Decoded("nop", "nop")
                    source = source1 | source2
                    return Decoded(
                        f"mov {REGISTERS[source]},{REGISTERS[destination]}", "compute")
                return Decoded(
                    f"add {REGISTERS[source1]},{REGISTERS[source2]},"
                    f"{REGISTERS[destination]}", "compute")
            return Decoded(f"unknown TY1 OP4 (0x{word:08x})", "unknown")
        return Decoded(f"unknown TY1 (0x{word:08x})", "unknown")

    if instruction_type == 2:
        immediate = sign_extend(word & 0x1FFFF, 17)
        if operation in (0, 1, 2, 3, 4, 6):
            mnemonic = {0: "ld", 1: "ldt", 2: "st", 3: "stt",
                        4: "ldf", 6: "stf"}[operation]
            text = (f"{mnemonic} {format_signed(immediate)}[{REGISTERS[source1]}],"
                    f"{REGISTERS[source2]}")
        else:
            mnemonic = "movfrc" if operation == 5 else "movtoc"
            if source1:
                text = (f"{mnemonic}? {format_signed(immediate)}"
                        f"[{REGISTERS[source1]}],{REGISTERS[source2]}")
            else:
                component2 = word & 0xF
                component1 = (word >> 4) & 0xF
                subfunction = (word >> 8) & 0x3F
                suboperation = (word >> 14) & 0x7
                components = (f"({suboperation:02x},{subfunction:02x},"
                              f"{component1:02x},{component2:02x})")
                if operation == 5:
                    text = f"movfrc? {components},{REGISTERS[source2]}"
                else:
                    text = f"movtoc? {REGISTERS[source2]},{components}"
        return Decoded(text, "memory", base_register=source1)

    if operation == 0:
        displacement = sign_extend(word & 0x1FFFF, 17) * 4
        target = None
        if register_bases is not None and source1 in register_bases:
            target = (register_bases[source1] + displacement) & 0xFFFFFFFF
        role = "tail" if source2 == 0 else "call"
        text = (f"jspci {REGISTERS[source1]},{format_signed(displacement)},"
                f"{REGISTERS[source2]}")
        if target is not None:
            text += f" -> 0x{target:08x}"
        return Decoded(text, "jump", target, role, source1)

    if operation == 1:
        if (word & 0x07FFFFFF) == 0x07C00000:
            return Decoded("hsc", "control")
        return Decoded(f"invalid hsc TY3 OP1 (0x{word:08x})", "unknown")

    if operation in (2, 3):
        if (function & 0xFFE) != 0:
            return Decoded(f"invalid special move (0x{word:08x})", "unknown")
        special = function & 0x7
        if operation == 2 and source2 == 0:
            return Decoded(f"movtos {REGISTERS[source1]},{special:x}", "control")
        if operation == 3 and source1 == 0:
            return Decoded(f"movfrs {special:x},{REGISTERS[source2]}", "control")
        return Decoded(f"invalid special move (0x{word:08x})", "unknown")

    if operation == 4:
        immediate = sign_extend(word & 0x1FFFF, 17)
        return Decoded(
            f"addi {REGISTERS[source1]},{format_signed(immediate)},"
            f"{REGISTERS[source2]}", "compute")

    if operation in (5, 7):
        mnemonic = "jpc" if operation == 5 else "jpcrs"
        if function == 3 and source1 == 0 and source2 == 0:
            return Decoded(mnemonic, "control")
        return Decoded(f"invalid {mnemonic} (0x{word:08x})", "unknown")

    if operation == 6:
        if (word & 0x07FFF807) == 3:
            vector = (~((word & 0x7F8) >> 3)) & 0xFF
            return Decoded(f"trap 0x{vector:02x}", "control")
        return Decoded(f"invalid trap (0x{word:08x})", "unknown")

    return Decoded(f"unknown TY3 (0x{word:08x})", "unknown")


def read_image(path: str) -> bytes:
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_NONBLOCK"):
        raise ValueError("secure image opening is unavailable")
    before = os.lstat(path)
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_IMAGE_BYTES:
        raise ValueError("image must be a bounded regular file")
    flags = os.O_RDONLY | os.O_NONBLOCK
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) \
                or metadata.st_size > MAX_IMAGE_BYTES \
                or (metadata.st_dev, metadata.st_ino) != (before.st_dev, before.st_ino):
            raise ValueError("image must be a bounded regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as image_file:
            data = image_file.read(MAX_IMAGE_BYTES + 1)
        after = os.fstat(descriptor)
        if len(data) != metadata.st_size or (
                after.st_dev, after.st_ino, after.st_size,
                after.st_mtime_ns, after.st_ctime_ns) != (
                metadata.st_dev, metadata.st_ino, metadata.st_size,
                metadata.st_mtime_ns, metadata.st_ctime_ns):
            raise ValueError("image changed while being read")
        return data
    finally:
        os.close(descriptor)


def validate_regions(regions: Iterable[tuple[int, int]],
                     image_size: int) -> list[tuple[int, int]]:
    result = sorted(regions)
    if len(result) > MAX_REGIONS:
        raise ValueError("too many regions")
    previous_end = -1
    for start, end in result:
        if start >= end:
            raise ValueError("regions must be nonempty")
        if start % 4 or end % 4:
            raise ValueError("region boundaries must be four-byte aligned")
        if end > image_size:
            raise ValueError("region extends beyond image")
        if start < previous_end:
            raise ValueError("regions must not overlap")
        previous_end = end
    if not result:
        raise ValueError("at least one nonempty region is required")
    return result


def iter_words(data: bytes, regions: Iterable[tuple[int, int]],
               byte_order: str):
    unpack = struct.Struct(">I" if byte_order == "big" else "<I").unpack_from
    for start, end in regions:
        for address in range(start, end, 4):
            yield address, unpack(data, address)[0]


def address_in_regions(address: int,
                       regions: Sequence[tuple[int, int]]) -> bool:
    low = 0
    high = len(regions)
    while low < high:
        middle = (low + high) // 2
        if regions[middle][0] <= address:
            low = middle + 1
        else:
            high = middle
    return low > 0 and address < regions[low - 1][1]


def is_stack_prologue(word: int) -> bool:
    return ((word >> 30) & 3) == 3 and ((word >> 27) & 7) == 4 \
        and ((word >> 22) & 0x1F) == 29 and ((word >> 17) & 0x1F) == 29 \
        and sign_extend(word & 0x1FFFF, 17) < 0


def infer_base_candidates(data: bytes, regions: list[tuple[int, int]],
                          register: int, byte_order: str = "big",
                          limit: int = 10) -> tuple[int, int, list[BaseCandidate]]:
    """Rank byte-coordinate call anchors by local stack-prologue targets."""
    displacements: Counter[int] = Counter()
    addi_immediates: Counter[int] = Counter()
    prologues: list[int] = []
    for address, word in iter_words(data, regions, byte_order):
        instruction_type = (word >> 30) & 3
        operation = (word >> 27) & 7
        source1 = (word >> 22) & 0x1F
        link = (word >> 17) & 0x1F
        if instruction_type == 3 and operation == 0 \
                and source1 == register and link != 0:
            displacements[sign_extend(word & 0x1FFFF, 17) * 4] += 1
            if len(displacements) > MAX_INFERENCE_DISPLACEMENTS:
                raise ValueError("base inference exceeds bounded work limits")
        if instruction_type == 3 and operation == 4 and source1 == register:
            addi_immediates[sign_extend(word & 0x1FFFF, 17)] += 1
        if is_stack_prologue(word):
            prologues.append(address)
            if len(prologues) > MAX_INFERENCE_PROLOGUES:
                raise ValueError("base inference exceeds bounded work limits")

    if len(displacements) > MAX_INFERENCE_DISPLACEMENTS \
            or len(prologues) > MAX_INFERENCE_PROLOGUES \
            or len(displacements) * len(prologues) > MAX_INFERENCE_PAIRS:
        raise ValueError("base inference exceeds bounded work limits")

    prologue_set = set(prologues)

    prologue_scores: Counter[int] = Counter()
    prologue_targets: dict[int, set[int]] = defaultdict(set)
    for target in prologues:
        for displacement, references in displacements.items():
            base = (target - displacement) & 0xFFFFFFFF
            prologue_scores[base] += references
            prologue_targets[base].add(target)

    if len(prologue_scores) * (len(displacements) + len(addi_immediates)) \
            > MAX_CANDIDATE_SCORING_PAIRS:
        raise ValueError("base inference exceeds bounded work limits")

    candidates: list[BaseCandidate] = []
    for base, score in prologue_scores.items():
        in_range_references = 0
        in_range_targets: set[int] = set()
        for displacement, references in displacements.items():
            target = (base + displacement) & 0xFFFFFFFF
            if address_in_regions(target, regions):
                in_range_references += references
                in_range_targets.add(target)
        addi_prologue_references = 0
        addi_prologue_targets: set[int] = set()
        if base % 4 == 0:
            raw_base = base // 4
            for immediate, references in addi_immediates.items():
                target = (((raw_base + immediate) & 0xFFFFFFFF) * 4
                          & 0xFFFFFFFF)
                if target in prologue_set:
                    addi_prologue_references += references
                    addi_prologue_targets.add(target)
        candidates.append(BaseCandidate(
            base, score, len(prologue_targets[base]),
            in_range_references, len(in_range_targets),
            addi_prologue_references, len(addi_prologue_targets)))
    candidates.sort(
        key=lambda item: (item.prologue_references, item.prologue_targets,
                          item.addi_prologue_references,
                          item.addi_prologue_targets,
                          item.in_range_references, item.in_range_targets,
                          -item.base),
        reverse=True)
    return sum(displacements.values()), len(displacements), candidates[:limit]


def collect_call_displacements(
        data: bytes, regions: list[tuple[int, int]], register: int,
        byte_order: str = "big") -> Counter[int]:
    displacements: Counter[int] = Counter()
    for _, word in iter_words(data, regions, byte_order):
        if ((word >> 30) & 3) == 3 and ((word >> 27) & 7) == 0 \
                and ((word >> 22) & 0x1F) == register \
                and ((word >> 17) & 0x1F) != 0:
            displacements[sign_extend(word & 0x1FFFF, 17) * 4] += 1
    return displacements


def infer_shared_base_deltas(
        first_data: bytes, first_regions: list[tuple[int, int]],
        second_data: bytes, second_regions: list[tuple[int, int]], register: int,
        byte_order: str = "big", limit: int = 10
) -> tuple[int, int, int, int, list[SharedDelta]]:
    """Rank relative call anchors that make targets common across two images."""
    first = collect_call_displacements(
        first_data, first_regions, register, byte_order)
    second = collect_call_displacements(
        second_data, second_regions, register, byte_order)
    if len(first) > MAX_SHARED_DISPLACEMENTS \
            or len(second) > MAX_SHARED_DISPLACEMENTS:
        raise ValueError("too many unique call displacements to compare")

    target_counts: Counter[int] = Counter()
    weighted_counts: Counter[int] = Counter()
    for first_displacement, first_references in first.items():
        for second_displacement, second_references in second.items():
            # Equal targets imply B2-B1 = D1-D2.
            delta = first_displacement - second_displacement
            target_counts[delta] += 1
            weighted_counts[delta] += min(first_references, second_references)
    candidates = [
        SharedDelta(delta, shared_targets, weighted_counts[delta])
        for delta, shared_targets in target_counts.items()
    ]
    candidates.sort(key=lambda item: (
        -item.shared_targets, -item.weighted_references,
        abs(item.delta), item.delta))
    return (sum(first.values()), len(first), sum(second.values()), len(second),
            candidates[:limit])


def collect_xrefs(data: bytes, regions: list[tuple[int, int]],
                   byte_order: str, register_bases: dict[int, int],
                   include_details: bool = True):
    counts: Counter[tuple[int, str, str]] = Counter()
    kinds: Counter[str] = Counter()
    ranges: Counter[str] = Counter()
    for address, word in iter_words(data, regions, byte_order):
        instruction = decode(word, address, register_bases)
        kinds[instruction.kind] += 1
        if instruction.target is None:
            if instruction.kind == "jump":
                ranges["jump_unresolved"] += 1
            continue
        relation = "in_range" if address_in_regions(
            instruction.target, regions) else "out_of_range"
        ranges[f"{instruction.kind}_{relation}"] += 1
        if include_details:
            key = (instruction.target, instruction.kind,
                   instruction.role or instruction.kind)
            if key not in counts and len(counts) >= MAX_XREF_RECORDS:
                raise ValueError("xref summary has too many unique records")
            counts[key] += 1
    return kinds, ranges, counts


def collect_control_flow(
        data: bytes, regions: list[tuple[int, int]], byte_order: str,
        register_bases: dict[int, int], limit: int = MAX_RESULT_LIMIT
) -> tuple[list[FlowTransfer], int, Counter[int]]:
    """Summarize control transfers with MIPS-X's two delay slots explicit."""
    if not 1 <= limit <= MAX_RESULT_LIMIT:
        raise ValueError("control-flow result limit is invalid")
    transfers: list[FlowTransfer] = []
    transfer_count = 0
    local_call_targets: Counter[int] = Counter()

    def record(kind: str, source: int, target: int | None,
               continuation: int | None, slots: tuple[int, ...],
               slot_policy: str) -> None:
        nonlocal transfer_count
        transfer_count += 1
        if len(transfers) >= limit:
            return
        selected_slot_count = sum(
            address_in_regions(slot, regions) for slot in slots)
        transfers.append(FlowTransfer(
            source, kind, target, continuation, slots,
            selected_slot_count, slot_policy))

    for address, word in iter_words(data, regions, byte_order):
        instruction = decode(word, address, register_bases)
        slots = (address + 4, address + 8)
        if instruction.kind == "branch":
            unconditional = ((word >> 27) & 7) == 1 \
                and ((word >> 22) & 0x1F) == 0 \
                and ((word >> 17) & 0x1F) == 0
            record(
                "branch_always" if unconditional else "branch", address,
                instruction.target, None if unconditional else address + 12,
                slots, "taken_only" if not unconditional and (word >> 16) & 1
                else "always")
            continue
        if instruction.kind == "jump":
            continuation = address + 12 if instruction.role == "call" else None
            record(instruction.role or "jump", address, instruction.target,
                   continuation, slots, "always")
            if instruction.role == "call" and instruction.target is not None \
                    and address_in_regions(instruction.target, regions):
                if instruction.target not in local_call_targets \
                        and len(local_call_targets) >= MAX_CFG_LOCAL_TARGETS:
                    raise ValueError(
                        "control-flow summary has too many local call targets")
                local_call_targets[instruction.target] += 1
            continue
        if instruction.kind != "control":
            continue
        operation = (word >> 27) & 7
        if operation == 1:
            record("halt", address, None, None, (), "none")
        elif operation == 5:
            record("jpc", address, None, None, slots, "always")
        elif operation == 7:
            record("jpcrs", address, None, None, slots, "always")
        elif operation == 6:
            record("trap", address, None, None, (), "none")
    return transfers, transfer_count, local_call_targets


def build_parser() -> argparse.ArgumentParser:
    parser = SafeArgumentParser(
        prog="mipsx_dasm.py",
        description="bounded offline MIPS-X disassembler and xref scanner")
    parser.add_argument(
        "image", help="regular binary image, or .zup with --type8-payload")
    parser.add_argument(
        "--type8-payload", type=parse_int, metavar="OFFSET",
        help="analyze one checked launch type-8 payload from a .zup package")
    parser.add_argument(
        "--region", action="append", type=parse_region, metavar="START:END",
        help="exclusive byte range; repeat for discontiguous code")
    parser.add_argument(
        "--byte-order", choices=("big", "little"), default="big",
        help="instruction byte order (default: big)")
    parser.add_argument(
        "--reg-base", action="append", type=parse_register_base, default=[],
        metavar="rN=VALUE",
        help="resolve JSPCI targets from a byte-coordinate call anchor")
    parser.add_argument(
        "--stats", action="store_true", help="print instruction/range counts")
    parser.add_argument(
        "--xref-summary", type=int, metavar="N",
        help="print the N most-referenced resolved targets")
    parser.add_argument(
        "--infer-base", type=parse_register, metavar="rN",
        help="rank byte-coordinate JSPCI anchors by stack-prologue targets")
    parser.add_argument(
        "--candidate-limit", type=int, default=10, metavar="N",
        help="maximum inferred bases to print (default: 10)")
    parser.add_argument(
        "--compare-image", metavar="PATH",
        help="second bounded image for relative call-anchor inference")
    parser.add_argument(
        "--compare-region", action="append", type=parse_region,
        metavar="START:END",
        help="exclusive code range in --compare-image; repeat if needed")
    parser.add_argument(
        "--infer-shared-delta", type=parse_register, metavar="rN",
        help="rank second-minus-first call-anchor deltas")
    parser.add_argument(
        "--cfg-summary", type=int, metavar="N",
        help="print N delay-slot-aware transfers and local call-target labels")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.xref_summary is not None \
            and not 1 <= arguments.xref_summary <= MAX_RESULT_LIMIT:
        parser.error("--xref-summary is outside its allowed range")
    if arguments.cfg_summary is not None \
            and not 1 <= arguments.cfg_summary <= MAX_RESULT_LIMIT:
        parser.error("--cfg-summary is outside its allowed range")
    if not 1 <= arguments.candidate_limit <= MAX_RESULT_LIMIT:
        parser.error("--candidate-limit is outside its allowed range")
    if (arguments.compare_image is None) != (arguments.infer_shared_delta is None):
        parser.error("--compare-image and --infer-shared-delta require each other")
    if arguments.compare_region and arguments.compare_image is None:
        parser.error("--compare-region requires --compare-image")

    try:
        if arguments.type8_payload is None:
            data = read_image(arguments.image)
        else:
            package = zup_bank.read_package(arguments.image)
            bank = zup_bank.build_bank(package)
            data = zup_bank.parse_type8_payload(
                bank.data, arguments.type8_payload).data
        regions = validate_regions(
            arguments.region or [(0, len(data) - (len(data) % 4))], len(data))
        if arguments.compare_image is not None:
            compare_data = read_image(arguments.compare_image)
            compare_regions = validate_regions(
                arguments.compare_region
                or [(0, len(compare_data) - (len(compare_data) % 4))],
                len(compare_data))
    except (OSError, ValueError):
        print("error: cannot read a valid bounded image", file=sys.stderr)
        return 1

    register_bases = dict(arguments.reg_base)
    if arguments.infer_base is not None:
        try:
            calls, unique_offsets, candidates = infer_base_candidates(
                data, regions, arguments.infer_base, arguments.byte_order,
                arguments.candidate_limit)
        except ValueError:
            print("error: base inference failed closed", file=sys.stderr)
            return 1
        print(f"register=r{arguments.infer_base} call_references={calls} "
              f"unique_displacements={unique_offsets}")
        for candidate in candidates:
            print(
                f"byte_anchor=0x{candidate.base:08x} "
                f"raw_word_value=0x{candidate.base // 4:08x} "
                f"prologue_references={candidate.prologue_references} "
                f"prologue_targets={candidate.prologue_targets} "
                f"in_range_references={candidate.in_range_references} "
                f"in_range_targets={candidate.in_range_targets} "
                f"addi_prologue_references="
                f"{candidate.addi_prologue_references} "
                f"addi_prologue_targets={candidate.addi_prologue_targets}")

    if arguments.infer_shared_delta is not None:
        try:
            first_calls, first_offsets, second_calls, second_offsets, deltas = \
                infer_shared_base_deltas(
                    data, regions, compare_data, compare_regions,
                    arguments.infer_shared_delta, arguments.byte_order,
                    arguments.candidate_limit)
        except ValueError:
            print("error: call-anchor comparison failed closed", file=sys.stderr)
            return 1
        print(
            f"register=r{arguments.infer_shared_delta} "
            f"first_call_references={first_calls} "
            f"first_unique_displacements={first_offsets} "
            f"second_call_references={second_calls} "
            f"second_unique_displacements={second_offsets}")
        for candidate in deltas:
            print(
                f"second_minus_first={candidate.delta:+#x} "
                f"shared_targets={candidate.shared_targets} "
                f"weighted_references={candidate.weighted_references}")

    if arguments.stats or arguments.xref_summary is not None:
        try:
            kinds, ranges, xrefs = collect_xrefs(
                data, regions, arguments.byte_order, register_bases,
                arguments.xref_summary is not None)
        except ValueError:
            print("error: xref summary failed closed", file=sys.stderr)
            return 1
        if arguments.stats:
            print(f"words={sum(kinds.values())}")
            for name, count in sorted(kinds.items()):
                print(f"{name}={count}")
            for name, count in sorted(ranges.items()):
                print(f"{name}={count}")
        if arguments.xref_summary is not None:
            print(f"resolved_xrefs={sum(xrefs.values())}")
            print(f"unique_targets={len({target for target, _, _ in xrefs})}")
            ordered = sorted(
                xrefs.items(), key=lambda item: (-item[1], item[0]))
            for (target, kind, role), count in ordered[:arguments.xref_summary]:
                print(f"0x{target:08x} {kind} {role} references={count}")

    if arguments.cfg_summary is not None:
        try:
            transfers, transfer_count, call_targets = collect_control_flow(
                data, regions, arguments.byte_order, register_bases,
                arguments.cfg_summary)
        except ValueError:
            print("error: control-flow summary failed closed", file=sys.stderr)
            return 1
        print(f"local_call_targets={len(call_targets)}")
        for target, references in sorted(
                call_targets.items(), key=lambda item: (-item[1], item[0])
        )[:arguments.cfg_summary]:
            print(f"call_target=sub_{target:08x} address=0x{target:08x} "
                  f"call_references={references}")
        print(f"control_transfers={transfer_count}")
        for transfer in transfers:
            target = "unknown" if transfer.target is None \
                else f"0x{transfer.target:08x}"
            continuation = "none" if transfer.continuation is None \
                else f"0x{transfer.continuation:08x}"
            delay_slots = "none" if not transfer.delay_slots else ",".join(
                f"0x{slot:08x}" for slot in transfer.delay_slots)
            print(
                f"flow source=0x{transfer.source:08x} kind={transfer.kind} "
                f"target={target} continuation={continuation} "
                f"delay_slots={delay_slots} "
                f"selected_slots={transfer.selected_slot_count}/"
                f"{len(transfer.delay_slots)} "
                f"slot_policy={transfer.slot_policy}")

    if arguments.infer_base is not None \
            or arguments.infer_shared_delta is not None or arguments.stats \
            or arguments.xref_summary is not None \
            or arguments.cfg_summary is not None:
        return 0

    word_count = sum((end - start) // 4 for start, end in regions)
    if word_count > MAX_DISASSEMBLY_WORDS:
        print("error: disassembly output exceeds bounded limit", file=sys.stderr)
        return 1
    for address, word in iter_words(data, regions, arguments.byte_order):
        instruction = decode(word, address, register_bases)
        print(f"{address:08x}: {word:08x}  {instruction.text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
