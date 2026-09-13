#!/usr/bin/env python3
"""Map GOT offsets to function addresses and identify common functions."""

import re
from pathlib import Path
from collections import Counter, defaultdict

ROOT = Path(__file__).resolve().parents[1]

def parse_disasm(disasm_path):
    """Parse MAME disassembly to extract branch targets."""
    targets = {}
    with open(disasm_path) as f:
        for line in f:
            # Match: cf80000: 0cfc0110  beq r19,r30,0x0cf8044c
            m = re.match(r'([0-9a-f]+): [0-9a-f]+  \w+ .*0x([0-9a-f]+)', line)
            if m:
                src = int(m.group(1), 16)
                dst = int(m.group(2), 16)
                targets[src] = dst
    return targets

def analyze_got_table(disasm_path, bank_base=0xcf80000, table_size=0x40000):
    """Analyze the GOT-like dispatch tables by tracking r23/r24 loads."""
    # Find all r23/r24 base loads (addi r24, #imm, rXX)
    table_entries = defaultdict(list)

    with open(disasm_path) as f:
        for line in f:
            m = re.match(r'([0-9a-f]+): [0-9a-f]+  addi r0,#([0-9a-f]+),r(23|24)', line)
            if m:
                addr = int(m.group(1), 16)
                offset = int(m.group(2), 16)
                reg = int(m.group(3))
                table_entries[reg].append((addr, offset))

    return table_entries

def find_function_by_offset(funcs, r24_base, offset):
    """Given an r24 base and a GOT offset, find the target function."""
    # The GOT entry is at r24_base + offset
    # The function call is: (*(code *)((r24 + offset) * 4))()
    # So the GOT entry contains (function_address / 4)
    target_pc = r24_base + offset
    return target_pc

def main():
    sip_disasm = ROOT / "research" / "sip_complete_disasm.txt"
    trans_disasm = ROOT / "research" / "transition_complete_disasm.txt"

    # Parse function entries
    sip_funcs = {}
    trans_funcs = {}

    for path, store in [(sip_disasm, sip_funcs), (trans_disasm, trans_funcs)]:
        with open(path) as f:
            for line in f:
                m = re.match(r'([0-9a-f]+):.*addi r29,#(ffffff[0-9a-f]+),r29', line)
                if m:
                    addr = int(m.group(1), 16)
                    store[addr] = {
                        'frame_size': -int(m.group(2), 16) if m.group(2).startswith('ffff') else int(m.group(2), 16),
                    }

    print(f"SIP functions: {len(sip_funcs)}")
    print(f"Transition functions: {len(trans_funcs)}")

    # Analyze the GOT dispatch pattern
    # The r24 register is loaded with a base, then offsets are added
    # Let's find what address ranges are most commonly called

    sip_call_targets = Counter()
    with open(sip_disasm) as f:
        for line in f:
            m = re.match(r'([0-9a-f]+):.*\w+ .*r24.*0x([0-9a-f]+)', line)
            if m:
                offset = int(m.group(2), 16)
                sip_call_targets[offset] += 1

    print(f"\n=== SIP Call Target Analysis ===")
    print(f"Unique call offsets: {len(sip_call_targets)}")

    # The r24 base is typically set to point to the GOT
    # Let's find where r24 is loaded
    r24_loads = []
    with open(sip_disasm) as f:
        for line in f:
            m = re.match(r'([0-9a-f]+):.*addi r(23|24),#([0-9a-f]+),r\2', line)
            if m:
                addr = int(m.group(1), 16)
                reg = int(m.group(2))
                offset = int(m.group(3), 16)
                r24_loads.append((addr, reg, offset))

    print(f"\nr24/r23 base loads found: {len(r24_loads)}")
    for addr, reg, off in r24_loads[:10]:
        print(f"  0x{addr:08x}: r{reg} = r{reg} + 0x{off:x}")

    # Build function name map based on patterns
    print(f"\n=== Function Families by Call Pattern ===")

    # Group functions by the GOT offsets they call
    func_call_groups = defaultdict(list)
    with open(sip_disasm) as f:
        current_func = None
        func_calls = []

        for line in f:
            m = re.match(r'([0-9a-f]+):', line)
            if m:
                addr = int(m.group(1), 16)
                if addr in sip_funcs:
                    if current_func and func_calls:
                        func_call_groups[tuple(sorted(func_calls))].append(current_func)
                    current_func = addr
                    func_calls = []

            m = re.search(r'r24\+(-?0x[0-9a-f]+)', line)
            if m and current_func:
                func_calls.append(int(m.group(1), 16))

    print(f"Unique call patterns: {len(func_call_groups)}")

    # Find the most common patterns
    for pattern, funcs in sorted(func_call_groups.items(), key=lambda x: -len(x[1]))[:10]:
        if len(funcs) >= 3:
            print(f"\n  Pattern ({len(funcs)} functions):")
            for f in funcs[:5]:
                print(f"    0x{f:08x}")

    # Identify common library functions by their patterns
    print(f"\n=== Potential Library Functions ===")

    # strcpy pattern: loop copying bytes until null
    strcpy_candidates = []
    with open(sip_disasm) as f:
        for line in f:
            if 'ld' in line and 'r0' in line and 'r2' in line:
                # Could be loading from memory
                pass

    # Print the most-called GOT offsets with their likely targets
    print(f"\n=== Most Called GOT Offsets (SIP) ===")
    for offset, count in sip_call_targets.most_common(20):
        # Try to find what function is at this offset from a known base
        print(f"  Offset 0x{offset:04x}: called {count} times")

if __name__ == '__main__':
    main()
