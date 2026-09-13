#!/usr/bin/env python3
"""Analyze cross-references in MIPS-X decompiled C to identify library functions."""

import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def analyze_decompiled(filepath):
    """Parse decompiled C and extract function-level statistics."""
    content = filepath.read_text()

    # Split into functions
    func_pattern = re.compile(r'// === (\w+) @ (0?[0-9a-f]+) ===\n\n(.*?)(?=\n\n// ===|\Z)', re.DOTALL)

    functions = {}
    for match in func_pattern.finditer(content):
        name = match.group(1)
        addr_str = match.group(2)
        addr = int(addr_str, 16) if addr_str.startswith('0x') else int(addr_str, 16)
        body = match.group(3)
        functions[name] = {
            'addr': addr,
            'body': body,
            'calls': [],
            'patterns': [],
            'params': set(),
            'global_refs': set(),
        }

        # Extract calls through r23/r24 PIC
        calls = re.findall(r'\(in_r24 \+ (-?0x[0-9a-f]+)\)', body)
        calls += re.findall(r'\(in_r23 \+ (-?0x[0-9a-f]+)\)', body)
        functions[name]['calls'] = [int(c, 16) for c in calls]

        # Extract global variable references
        globals_found = re.findall(r'[iu]Ram([0-9a-f]{8})', body)
        functions[name]['global_refs'] = set(globals_found)

        # Extract register parameters
        params = re.findall(r'in_r(\d+)', body)
        functions[name]['params'] = set(int(p) for p in params)

        # Detect common patterns
        if 'while ((char)uVar' in body and '*in_r5' in body:
            functions[name]['patterns'].append('strcpy')
        if 'mipsx_xop5()' in body and 'mipsx_xop7()' in body:
            functions[name]['patterns'].append('io_sequence')
        if 'in_r24 + -0x10000' in body:
            functions[name]['patterns'].append('packet_read')
        if 'in_r24 + -0xffde' in body:
            functions[name]['patterns'].append('return_to_caller')
        if len(functions[name]['calls']) > 10:
            functions[name]['patterns'].append('dispatch_heavy')

    return functions

def find_common_got_offsets(functions):
    """Find most-called GOT offsets across all functions."""
    offset_counter = Counter()
    for func in functions.values():
        for offset in func['calls']:
            offset_counter[offset] += 1
    return offset_counter.most_common(50)

def find_function_families(functions):
    """Group functions by their call patterns."""
    call_sets = defaultdict(list)
    for name, func in functions.items():
        call_tuple = tuple(sorted(func['calls']))
        if call_tuple:
            call_sets[call_tuple].append(name)

    # Return families with 2+ members
    return {k: v for k, v in call_sets.items() if len(v) >= 2}

def identify_library_candidates(functions, got_offsets):
    """Identify likely library functions based on patterns."""
    candidates = {}

    # Known addresses from validator/dispatcher analysis
    known = {
        '0xcf80a00': 'validator_entry',
        '0xcf80a24': 'validator_aux_entry',
        '0xcf80a7c': 'validator_loop',
    }

    # Pattern-based identification
    for name, func in functions.items():
        addr_hex = f"0x{func['addr']:08x}"
        if addr_hex in known:
            candidates[name] = known[addr_hex]
            continue

        patterns = func['patterns']
        if 'strcpy' in patterns:
            candidates[name] = 'string_copy'
        elif 'packet_read' in patterns:
            candidates[name] = 'packet_read'
        elif len(func['calls']) > 15:
            candidates[name] = 'dispatcher'
        elif len(func['global_refs']) > 5:
            candidates[name] = 'state_handler'

    return candidates

def main():
    sip_path = ROOT / "research" / "decompiled" / "sip_bank.c"
    trans_path = ROOT / "research" / "decompiled" / "transition_bank.c"

    print("=== SIP Bank Analysis ===")
    sip_funcs = analyze_decompiled(sip_path)
    print(f"Functions: {len(sip_funcs)}")

    got_top = find_common_got_offsets(sip_funcs)
    print(f"\nTop 20 GOT offsets (r23/r24):")
    for offset, count in got_top[:20]:
        print(f"  r24{offset:+d}: {count} calls")

    families = find_function_families(sip_funcs)
    print(f"\nFunction families (2+ similar): {len(families)}")
    for call_pattern, names in sorted(families.items(), key=lambda x: -len(x[1]))[:5]:
        print(f"  {len(names)} functions: {', '.join(names[:3])}...")

    candidates = identify_library_candidates(sip_funcs, got_top)
    print(f"\nLibrary candidates identified: {len(candidates)}")
    for name, role in sorted(candidates.items()):
        print(f"  {name}: {role}")

    print("\n=== Transition Bank Analysis ===")
    trans_funcs = analyze_decompiled(trans_path)
    print(f"Functions: {len(trans_funcs)}")

    got_top_trans = find_common_got_offsets(trans_funcs)
    print(f"\nTop 20 GOT offsets:")
    for offset, count in got_top_trans[:20]:
        print(f"  r24{offset:+d}: {count} calls")

    # Find functions present in both banks
    sip_addrs = {f['addr'] for f in sip_funcs.values()}
    trans_addrs = {f['addr'] for f in trans_funcs.values()}
    common = sip_addrs & trans_addrs
    print(f"\nFunctions at same address in both banks: {len(common)}")
    for addr in sorted(common)[:10]:
        sip_name = next(n for n, f in sip_funcs.items() if f['addr'] == addr)
        trans_name = next(n for n, f in trans_funcs.items() if f['addr'] == addr)
        print(f"  0x{addr:08x}: SIP={sip_name}, TRANS={trans_name}")

if __name__ == '__main__':
    main()
