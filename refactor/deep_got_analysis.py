#!/usr/bin/env python3
"""
Deep analysis: map GOT offsets to target functions using disassembly + decompiled C.
Then build a comprehensive function naming map.
"""

import re
import json
from pathlib import Path
from collections import Counter, defaultdict

BANK_BASE = 0xcf80000
GOT_OFFSET_RE = re.compile(r'in_r24 \+ (-?[0-9a-fx]+)')
GLOBAL_RE = re.compile(r'[iu]Ram([0-9a-f]{8})')

def load_functions_from_decompiled(filepath):
    """Parse decompiled C into function dict keyed by address."""
    content = filepath.read_text()
    parts = content.split('// === ')
    funcs = {}
    for part in parts[1:]:
        lines = part.split('\n')
        m = re.match(r'(\w+) @ ([0-9a-f]+) ===', lines[0])
        if not m:
            continue
        name, addr = m.group(1), int(m.group(2), 16)
        body = '\n'.join(lines[1:]).strip()
        got_offsets = [int(g, 16) if 'x' in g else int(g) for g in GOT_OFFSET_RE.findall(body)]
        globals_used = set(GLOBAL_RE.findall(body))
        funcs[addr] = {
            'name': name,
            'body': body,
            'got_offsets': got_offsets,
            'globals': globals_used,
            'line_count': body.count('\n') + 1,
        }
    return funcs

def load_disasm_functions(disasm_path):
    """Parse disassembly to find function boundaries and internal jumps."""
    funcs = {}
    current_func = None
    current_lines = []

    with open(disasm_path) as f:
        for line in f:
            m = re.match(r'([0-9a-f]+):', line)
            if not m:
                continue
            addr = int(m.group(1), 16)

            # Check if this is a function entry (addi r29, #FFFFFFxx, r29)
            if 'addi r29,#ffffff' in line.lower() or 'addi r29,#ffffffff' in line.lower():
                if current_func is not None:
                    funcs[current_func] = current_lines
                current_func = addr
                current_lines = [line.strip()]
            elif current_func is not None:
                current_lines.append(line.strip())

    if current_func is not None:
        funcs[current_func] = current_lines

    return funcs

def find_got_base_locations(disasm_path):
    """Find where r24 is initialized with a GOT base address."""
    # In MIPS-X, the GOT base is typically set via:
    # addi r24, #offset, rN  (where rN contains the base)
    # The key pattern is at function entry where r24 gets its value

    r24_init = []
    with open(disasm_path) as f:
        for line in f:
            # Pattern: addi r24, #imm, rN (N != 24)
            m = re.match(r'([0-9a-f]+):.*addi r24,#([0-9a-f]+),r(\d+)', line)
            if m:
                addr = int(m.group(1), 16)
                imm = int(m.group(2), 16)
                src_reg = int(m.group(3))
                r24_init.append({
                    'addr': addr,
                    'offset': imm if imm < 0x80000000 else imm - 0x100000000,
                    'src_reg': src_reg,
                })

    return r24_init

def build_got_mapping(decompiled_funcs, disasm_funcs, r24_inits):
    """
    The GOT is a table of function addresses stored in memory.
    When a function does (*(code *)((in_r24 + offset) * 4))(),
    it reads from memory at (r24 + offset), divides by 4, and calls that address.

    So: target_addr = memory[r24 + offset] / 4

    We need to figure out where the GOT is in memory.
    """
    # Strategy: look for functions that are called through the GOT
    # by matching the pattern. The most-called GOT offsets should correspond
    # to important functions.

    # Count GOT offset usage across all functions
    offset_counts = Counter()
    for func in decompiled_funcs.values():
        for off in func['got_offsets']:
            offset_counts[off] += 1

    print(f"Unique GOT offsets: {len(offset_counts)}")
    print(f"\nTop 30 most-called GOT offsets:")
    for off, count in offset_counts.most_common(30):
        print(f"  r24{off:+d} ({off:#x}): {count} calls")

    return offset_counts

def identify_function_patterns(decompiled_funcs):
    """Classify functions based on their patterns."""
    classifications = {}

    for addr, func in decompiled_funcs.items():
        body = func['body']
        globals_used = func['globals']
        got_offsets = func['got_offsets']

        # Known validator/setup functions (from earlier analysis)
        if addr == 0x0cf80a00:
            classifications[addr] = 'sip_validator_entry'
            continue
        if addr == 0x0cf80a24:
            classifications[addr] = 'sip_validator_aux_entry'
            continue
        if addr == 0x0cf80a7c:
            classifications[addr] = 'sip_validator_loop'
            continue

        # String copy pattern
        if 'while ((char)uVar' in body and '*in_r5' in body:
            classifications[addr] = 'str_copy'
            continue

        # Packet read pattern (uses r24-0x10000)
        if -0x10000 in got_offsets:
            classifications[addr] = 'packet_recv'
            continue

        # State machine patterns
        if '000026f4' in globals_used and 'while' in body:
            classifications[addr] = 'state_handler'
            continue

        # Error handler
        if '00002bc4' in globals_used and ('= -' in body or '= 0xffffff' in body):
            classifications[addr] = 'error_handler'
            continue

        # Message buffer handler
        if '00002aac' in globals_used:
            classifications[addr] = 'msg_buffer_handler'
            continue

        # Dispatch table handler
        if '00002bc8' in body:
            classifications[addr] = 'cmd_dispatch'
            continue

        # High call count = dispatcher
        if len(got_offsets) > 8:
            classifications[addr] = 'dispatcher'
            continue

        # Default
        classifications[addr] = f'func_{addr:08x}'

    return classifications

def main():
    root = Path(__file__).resolve().parents[1]
    sip_decompiled = root / 'research/decompiled/sip_bank.c'
    sip_disasm = root / 'research/sip_complete_disasm.txt'

    print("Loading decompiled SIP bank...")
    decompiled = load_functions_from_decompiled(sip_decompiled)
    print(f"  {len(decompiled)} functions")

    print("\nLoading disassembly...")
    disasm = load_disasm_functions(sip_disasm)
    print(f"  {len(disasm)} functions")

    print("\nFinding r24 initialization patterns...")
    r24_inits = find_got_base_locations(sip_disasm)
    print(f"  {len(r24_inits)} r24 init sites")

    print("\nBuilding GOT mapping...")
    offset_counts = build_got_mapping(decompiled, disasm, r24_inits)

    print("\nIdentifying function patterns...")
    classifications = identify_function_patterns(decompiled)

    # Count classifications
    class_counts = Counter(classifications.values())
    print(f"\nClassification summary:")
    for cls, count in class_counts.most_common():
        print(f"  {cls}: {count}")

    # Save mapping
    output = {
        'got_offsets': {f'{k:#x}': v for k, v in offset_counts.most_common(100)},
        'classifications': {f'{k:#x}': v for k, v in classifications.items()},
    }

    out_path = root / 'research/got_mapping.json'
    out_path.write_text(json.dumps(output, indent=2))
    print(f"\nSaved mapping to {out_path}")

if __name__ == '__main__':
    main()
