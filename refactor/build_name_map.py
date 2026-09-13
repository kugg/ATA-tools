#!/usr/bin/env python3
"""
Build function name mappings from decompiled C patterns.
Produces a rename map that can be applied to the decompiled output.
"""

import re
from pathlib import Path
from collections import Counter, defaultdict

ROOT = Path(__file__).resolve().parents[1]

def parse_decompiled(filepath):
    """Parse decompiled C into function objects."""
    content = filepath.read_text()

    # Split into functions
    parts = content.split('// === ')
    functions = []

    for part in parts[1:]:
        lines = part.split('\n')
        header = lines[0]
        m = re.match(r'(\w+) @ ([0-9a-f]+) ===', header)
        if not m:
            continue

        name = m.group(1)
        addr = int(m.group(2), 16)
        body = '\n'.join(lines[1:]).strip()

        func = {
            'name': name,
            'addr': addr,
            'body': body,
            'line_count': len([l for l in body.split('\n') if l.strip()]),
            'has_loop': 'while' in body or 'for' in body,
            'has_switch': False,  # TODO: detect switch patterns
            'global_refs': set(re.findall(r'[iu]Ram([0-9a-f]{8})', body)),
            'calls': [],
            'params': set(int(p) for p in re.findall(r'in_r(\d+)', body)),
            'is_strcpy': 'while ((char)uVar' in body and '*in_r5' in body,
            'is_packet_read': 'in_r24 + -0x10000' in body,
            'is_state_machine': 'iRam000026f4' in body and 'while' in body,
            'is_dispatcher': body.count('(in_r24 +') > 5,
        }

        # Extract GOT calls
        for m in re.finditer(r'\(in_r24 \+ (-?[0-9a-fx]+)\)', body):
            func['calls'].append(int(m.group(1), 16) if 'x' in m.group(1) else int(m.group(1)))
        for m in re.finditer(r'\(in_r23 \+ (-?[0-9a-fx]+)\)', body):
            func['calls'].append(int(m.group(1), 16) if 'x' in m.group(1) else int(m.group(1)))

        functions.append(func)

    return functions

def classify_function(func):
    """Assign a meaningful name based on function characteristics."""
    addr = func['addr']
    body = func['body']

    # Known entry points (from validator/dispatcher analysis)
    known_names = {
        0x0cf80a00: 'sip_validator_main',
        0x0cf80a24: 'sip_validator_aux',
        0x0cf80a7c: 'sip_validator_loop',
        0x0cf80d80: 'sip_packet_read',
        0x0cf80d88: 'sip_packet_read_aux',
        0x0cf80db0: 'sip_packet_read_loop',
        0x0cf80e28: 'sip_packet_read_init',
        0x0cf813e4: 'sip_dispatch_table_init',
        0x0cf81410: 'sip_dispatch_entry',
        0x0cf81430: 'sip_dispatch_handler',
        0x0cf81458: 'sip_dispatch_return',
        0x0cf81460: 'sip_dispatch_call',
        0x0cf8148c: 'sip_dispatch_common',
    }

    if addr in known_names:
        return known_names[addr]

    # Pattern-based naming
    is_strcopy = 'while ((char)uVar' in body and '*in_r5' in body
    is_packet_read = 'in_r24 + -0x10000' in body
    is_state_machine = 'iRam000026f4' in body and 'while' in body
    is_dispatcher = body.count('(in_r24 +') > 5

    if is_strcopy:
        return f'sip_str_copy_{addr:08x}'
    if is_packet_read:
        return f'sip_packet_recv_{addr:08x}'
    if is_state_machine:
        return f'sip_state_machine_{addr:08x}'
    if is_dispatcher:
        return f'sip_dispatcher_{addr:08x}'

    # Global variable based naming
    globals_used = func['global_refs']
    if '000026f4' in globals_used:
        return f'sip_state_handler_{addr:08x}'
    if '00002bc4' in globals_used:
        return f'sip_error_handler_{addr:08x}'
    if '00002aac' in globals_used:
        return f'sip_message_handler_{addr:08x}'
    if '000026d8' in globals_used:
        return f'sip_transfer_handler_{addr:08x}'

    # Size-based naming
    if func['line_count'] > 100:
        return f'sip_complex_handler_{addr:08x}'
    if func['line_count'] < 5:
        return f'sip_simple_wrapper_{addr:08x}'

    return f'sip_function_{addr:08x}'

def build_rename_map(functions):
    """Build a mapping from original names to meaningful names."""
    rename_map = {}

    for func in functions:
        new_name = classify_function(func)
        if new_name != func['name']:
            rename_map[func['name']] = new_name

    return rename_map

def apply_rename_map(filepath, rename_map, output_path):
    """Apply rename map to decompiled C file."""
    content = filepath.read_text()

    for old_name, new_name in sorted(rename_map.items()):
        content = content.replace(old_name, new_name)

    output_path.write_text(content)
    return len(rename_map)

def main():
    sip_path = ROOT / "research" / "decompiled" / "sip_bank.c"
    trans_path = ROOT / "research" / "decompiled" / "transition_bank.c"

    output_dir = ROOT / "research" / "decompiled" / "named"
    output_dir.mkdir(exist_ok=True)

    print("=== SIP Bank ===")
    sip_funcs = parse_decompiled(sip_path)
    print(f"Functions: {len(sip_funcs)}")

    sip_rename = build_rename_map(sip_funcs)
    print(f"Renamed: {len(sip_rename)}")

    # Show some examples
    print("\nSample renames:")
    for old, new in list(sip_rename.items())[:20]:
        print(f"  {old} -> {new}")

    count = apply_rename_map(sip_path, sip_rename, output_dir / 'sip_bank_named.c')
    print(f"\nWritten: {output_dir / 'sip_bank_named.c'} ({count} renames)")

    print("\n=== Transition Bank ===")
    trans_funcs = parse_decompiled(trans_path)
    print(f"Functions: {len(trans_funcs)}")

    trans_rename = build_rename_map(trans_funcs)
    print(f"Renamed: {len(trans_rename)}")

    count = apply_rename_map(trans_path, trans_rename, output_dir / 'transition_bank_named.c')
    print(f"\nWritten: {output_dir / 'transition_bank_named.c'} ({count} renames)")

    # Save rename maps for reference
    import json
    rename_data = {
        'sip': sip_rename,
        'transition': trans_rename,
    }
    (output_dir / 'rename_map.json').write_text(json.dumps(rename_data, indent=2))
    print(f"\nRename map: {output_dir / 'rename_map.json'}")

if __name__ == '__main__':
    main()
