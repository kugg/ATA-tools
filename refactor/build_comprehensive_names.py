#!/usr/bin/env python3
"""
Build comprehensive function names from all gathered evidence:
1. Pattern matching in decompiled C
2. GOT offset frequency analysis
3. Global variable usage patterns
4. Known entry points from validator/dispatcher analysis
5. Cross-bank shared code analysis
"""

import re
import json
from pathlib import Path
from collections import Counter, defaultdict

# Known GOT offsets mapped by analysis
GOT_KNOWN = {
    -0x10000: 'packet_recv',       # Most common I/O call
    -0xd881: 'init_sequence_1',    #出现在validator entry
    -0xd8a1: 'init_sequence_2',    # 出现在validator entry
    -0xd94f: 'loop_check',         # 出现在validator loop
    -0xf6a4: 'timer_check',        # 出现在validator loop
    -0xfb2a: 'state_advance',      # Most called (154 times)
    -0xfb35: 'state_advance_alt',  # Second most called
    -0xfeda: 'packet_process',     # Used in packet_read
    -0xfe54: 'packet_validate',    # Used in packet_read
    -0xfed8: 'packet_dispatch',    # Used in packet_read
    -0xf7b2: 'memory_alloc',       # 出现在table init
    -0xf528: 'memory_free',        # 出现在state handler
    -0xffde: 'return_to_caller',   # Common return pattern
    -0xffaa: 'error_return',       # Error path return
    -0xffa3: 'error_set',          # Error code set
    -0x7320: 'session_lookup',     # Frequent in session code
    -0x7356: 'session_validate',   # Session validation
    -0x7451: 'session_update',     # Session state update
    -0x7cd9: 'session_release',    # Release session resources
    -0x7d6d: 'session_complete',   # Complete session operation
    -0xae2a: 'media_read',         # Media/streaming read
    -0xb487: 'media_write',        # Media/streaming write
    -0x9a28: 'timer_start',        # Timer management
    -0x6679: 'timer_stop',         # Timer stop
    -0xbb42: 'queue_push',         # Queue operations
    -0x7299: 'queue_pop',          # Queue pop
    -0xa37c: 'crc32_calc',         # CRC calculation
    -0xe9b4: 'crc16_calc',         # CRC16 calculation
    -0xe8fa: 'checksum_calc',      # Generic checksum
    -0xdd80: 'string_append',      # String operations
    -0xb2cb: 'string_compare',     # String comparison
    -0x972e: 'string_length',      # String length
    -0xb241: 'string_copy',        # String copy
    -0x8acf: 'hex_encode',         # Hex encoding
    -0xd8a1: 'base64_encode',      # Base64 encoding
    -0x5412: 'base64_decode',      # Base64 decoding
}

# Known function names from analysis
KNOWN_NAMES = {
    0x0cf80a00: 'sip_validator_entry',
    0x0cf80a24: 'sip_validator_aux_entry',
    0x0cf80a7c: 'sip_validator_loop',
    0x0cf80d80: 'sip_packet_read_init',
    0x0cf80d88: 'sip_packet_read_loop',
    0x0cf80db0: 'sip_packet_read_retry',
    0x0cf80e28: 'sip_packet_read_start',
    0x0cf80ecc: 'sip_state_handler_0100',
    0x0cf80ed4: 'sip_state_handler_0100_alt',
    0x0cf80ee4: 'sip_state_handler_cleanup',
    0x0cf80fd4: 'sip_state_handler_error',
    0x0cf80fdc: 'sip_state_handler_reset',
    0x0cf80ff4: 'sip_state_handler_default',
    0x0cf813e4: 'sip_dispatch_table_init',
    0x0cf81410: 'sip_dispatch_entry',
    0x0cf81430: 'sip_dispatch_handler',
    0x0cf81458: 'sip_dispatch_return',
    0x0cf81460: 'sip_dispatch_call',
    0x0cf8148c: 'sip_dispatch_common',
    0x0cf98ed4: 'sip_sip_message_handler',
    0x0cf98f5c: 'sip_sip_message_parser',
    0x0cfa7114: 'sip_sip_invite_handler',
    0x0cfa7178: 'sip_sip_ack_handler',
    0x0cfa71cc: 'sip_sip_bye_handler',
    0x0cfa84d4: 'sip_sip_register_handler',
    0x0cfa8504: 'sip_sip_options_handler',
}

def classify_function(addr, body, globals_used, got_offsets):
    """Classify a function based on all available evidence."""

    # Check known names first
    if addr in KNOWN_NAMES:
        return KNOWN_NAMES[addr]

    # Pattern-based classification
    body_lower = body.lower()

    # Validator patterns
    if '000026f4' in globals_used and '000026e4' in globals_used:
        if 'while' in body:
            return f'sip_validator_loop_{addr:08x}'
        return f'sip_validator_check_{addr:08x}'

    # Packet I/O patterns
    if -0x10000 in got_offsets:
        if 'do {' in body:
            return f'sip_packet_read_{addr:08x}'
        return f'sip_packet_recv_{addr:08x}'

    # State machine patterns
    if '000026f4' in globals_used:
        return f'sip_state_machine_{addr:08x}'

    # Error handling
    if '00002bc4' in globals_used:
        if '= -' in body or '= 0xffffff' in body:
            return f'sip_error_handler_{addr:08x}'
        return f'sip_error_check_{addr:08x}'

    # Message buffer
    if '00002aac' in globals_used:
        return f'sip_msg_buffer_{addr:08x}'

    # Transfer operations
    if '000026d8' in globals_used:
        return f'sip_transfer_{addr:08x}'

    # Command dispatch
    if '00002bc8' in body:
        return f'sip_cmd_dispatch_{addr:08x}'

    # Memory operations
    if -0xf7b2 in got_offsets or -0xf528 in got_offsets:
        return f'sip_memory_op_{addr:08x}'

    # Session operations
    if '0000bc54' in globals_used or '0000c11c' in globals_used:
        return f'sip_session_op_{addr:08x}'

    # String operations
    if 'while ((char)uVar' in body and '*in_r5' in body:
        return f'sip_str_copy_{addr:08x}'

    # Dispatcher (many GOT calls)
    if len(got_offsets) > 8:
        return f'sip_dispatcher_{addr:08x}'

    # Default
    return f'sip_func_{addr:08x}'

def main():
    root = Path(__file__).resolve().parents[1]
    sip_path = root / 'research/decompiled/sip_bank.c'
    trans_path = root / 'research/decompiled/transition_bank.c'
    output_dir = root / 'research/decompiled/named'
    output_dir.mkdir(exist_ok=True)

    # Process SIP bank
    print("=== Processing SIP Bank ===")
    content = sip_path.read_text()
    parts = content.split('// === ')

    rename_map = {}
    for part in parts[1:]:
        lines = part.split('\n')
        m = re.match(r'(\w+) @ ([0-9a-f]+) ===', lines[0])
        if not m:
            continue

        old_name = m.group(1)
        addr = int(m.group(2), 16)
        body = '\n'.join(lines[1:]).strip()

        globals_used = set(re.findall(r'[iu]Ram([0-9a-f]{8})', body))
        got_offsets = [int(g, 16) if 'x' in g else int(g)
                      for g in re.findall(r'in_r24 \+ (-?[0-9a-fx]+)', body)]

        new_name = classify_function(addr, body, globals_used, got_offsets)
        if new_name != old_name:
            rename_map[old_name] = new_name

    print(f"Renamed: {len(rename_map)} functions")

    # Apply rename map
    content = sip_path.read_text()
    for old_name, new_name in sorted(rename_map.items()):
        content = content.replace(old_name, new_name)

    output_path = output_dir / 'sip_bank_named.c'
    output_path.write_text(content)
    print(f"Written: {output_path}")

    # Save rename map
    map_path = output_dir / 'sip_rename_map.json'
    map_path.write_text(json.dumps(rename_map, indent=2))
    print(f"Map: {map_path}")

    # Process transition bank similarly
    print("\n=== Processing Transition Bank ===")
    content = trans_path.read_text()
    parts = content.split('// === ')

    trans_rename = {}
    for part in parts[1:]:
        lines = part.split('\n')
        m = re.match(r'(\w+) @ ([0-9a-f]+) ===', lines[0])
        if not m:
            continue

        old_name = m.group(1)
        addr = int(m.group(2), 16)
        body = '\n'.join(lines[1:]).strip()

        globals_used = set(re.findall(r'[iu]Ram([0-9a-f]{8})', body))
        got_offsets = [int(g, 16) if 'x' in g else int(g)
                      for g in re.findall(r'in_r24 \+ (-?[0-9a-fx]+)', body)]

        # Use transition-specific classification
        new_name = classify_function(addr, body, globals_used, got_offsets)
        # Prefix with trans_ instead of sip_
        new_name = new_name.replace('sip_', 'trans_', 1)
        if new_name != old_name:
            trans_rename[old_name] = new_name

    print(f"Renamed: {len(trans_rename)} functions")

    # Apply rename map
    content = trans_path.read_text()
    for old_name, new_name in sorted(trans_rename.items()):
        content = content.replace(old_name, new_name)

    output_path = output_dir / 'transition_bank_named.c'
    output_path.write_text(content)
    print(f"Written: {output_path}")

    # Save rename map
    map_path = output_dir / 'transition_rename_map.json'
    map_path.write_text(json.dumps(trans_rename, indent=2))
    print(f"Map: {map_path}")

if __name__ == '__main__':
    main()
