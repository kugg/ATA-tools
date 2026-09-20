#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""Look up evidence-backed ATA syslog call sites without vendor firmware."""

from __future__ import annotations

import argparse
import json
import os
import sys

if __package__:
    from . import ghidra_decompile_packed, mipsx_dasm, zup_bank, zup_extract
else:
    import ghidra_decompile_packed
    import mipsx_dasm
    import zup_bank
    import zup_extract


HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ATLAS = os.path.join(HERE, "data", "ata_syslog_atlas.json")
MAX_ATLAS_BYTES = 256 * 1024
MAX_ENTRIES = 256
MAX_QUERY_LENGTH = 256
CONFIDENCE = {"exact", "exact-detached-arm", "nearest-owner",
              "conditional-class"}


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, "error: invalid arguments\n")


def _address(value: object, name: str) -> int:
    if not isinstance(value, str) or len(value) > 18:
        raise ValueError(f"atlas {name} is invalid")
    try:
        address = int(value, 16)
    except ValueError as exc:
        raise ValueError(f"atlas {name} is invalid") from exc
    if not 0 <= address <= 0xFFFFFFFF:
        raise ValueError(f"atlas {name} is invalid")
    return address


def _text(value: object, name: str, allow_trailing_newline: bool = False) -> str:
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise ValueError(f"atlas {name} is invalid")
    checked = value[:-1] if allow_trailing_newline and value.endswith("\n") \
        else value
    if any(ord(character) < 0x20 or ord(character) == 0x7f
           for character in checked):
        raise ValueError(f"atlas {name} contains control characters")
    return value


def load_atlas(path: str = DEFAULT_ATLAS) -> dict:
    raw = zup_extract._read_regular_file(path, MAX_ATLAS_BYTES, "syslog atlas")
    try:
        atlas = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("syslog atlas is not valid UTF-8 JSON") from exc
    if not isinstance(atlas, dict) or atlas.get("schema_version") != 1:
        raise ValueError("syslog atlas schema is unsupported")
    entries = atlas.get("entries")
    if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_ENTRIES:
        raise ValueError("syslog atlas entry count is invalid")

    seen_calls = set()
    packed = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("scope") not in {
                "packed", "resident"}:
            raise ValueError("syslog atlas entry is invalid")
        call = _address(entry.get("call"), "call address")
        if call in seen_calls:
            raise ValueError("syslog atlas contains duplicate call addresses")
        seen_calls.add(call)
        _address(entry.get("message_address"), "message address")
        _address(entry.get("owner_address"), "owner address")
        _text(entry.get("message"), "message", True)
        _text(entry.get("owner"), "owner")
        if entry.get("confidence") not in CONFIDENCE:
            raise ValueError("syslog atlas confidence is invalid")
        class_value = entry.get("class")
        if class_value is None:
            _text(entry.get("class_expression"), "class expression")
            evidence = entry.get("class_evidence")
            if not isinstance(evidence, list) or len(evidence) != 4:
                raise ValueError("syslog atlas class evidence is invalid")
            for address in evidence:
                _address(address, "class evidence address")
        elif not isinstance(class_value, int) or not 0 <= class_value <= 255:
            raise ValueError("syslog atlas class is invalid")
        elif entry["scope"] == "packed":
            _address(entry.get("class_instruction"), "class instruction")
        if not isinstance(entry.get("mode"), int) \
                or not 0 <= entry["mode"] <= 255:
            raise ValueError("syslog atlas mode is invalid")
        if entry["scope"] == "packed":
            _address(entry.get("mode_instruction"), "mode instruction")
            _address(entry.get("message_instruction"), "message instruction")
        if "state" in entry:
            _text(entry["state"], "state")
        if entry["scope"] == "packed":
            packed.append(entry)

    runtime = atlas.get("packed_runtime")
    if not isinstance(runtime, dict) \
            or runtime.get("direct_calls") != len(packed) \
            or len(packed) != 27:
        raise ValueError("syslog atlas packed call count is invalid")
    if _address(runtime.get("emitter"), "emitter") != 0x1CC0C:
        raise ValueError("syslog atlas emitter is invalid")
    return atlas


def search(entries: list[dict], query: str) -> list[dict]:
    if not query or len(query) > MAX_QUERY_LENGTH \
            or any(ord(character) < 0x20 or ord(character) == 0x7f
                   for character in query):
        raise ValueError("query is invalid")
    needle = query.casefold()
    matches = []
    for entry in entries:
        fields = [entry["message"], entry["owner"], entry["call"],
                  entry["message_address"], entry["owner_address"],
                  entry["scope"], str(entry["mode"])]
        if entry["class"] is not None:
            fields.append(str(entry["class"]))
        else:
            fields.append(entry["class_expression"])
        if any(needle in field.casefold() for field in fields):
            matches.append(entry)
    return matches


def _runtime_bytes(layout: tuple[ghidra_decompile_packed.RuntimeRegion, ...],
                   address: int, length: int) -> bytes:
    for region in layout:
        if region.data is not None and region.start <= address \
                and address + length <= region.end:
            offset = address - region.start
            return region.data[offset:offset + length]
    raise ValueError("atlas message lies outside initialized runtime data")


def _instruction_text(code: ghidra_decompile_packed.RuntimeRegion,
                      address: int) -> str:
    if code.data is None or address < code.start or address + 4 > code.end:
        raise ValueError("atlas argument instruction is outside packed code")
    offset = address - code.start
    word = int.from_bytes(code.data[offset:offset + 4], "big")
    return mipsx_dasm.decode(word, address).text


def _verify_addi(code: ghidra_decompile_packed.RuntimeRegion, entry: dict,
                 field: str, register: int, value: int) -> None:
    address = _address(entry[f"{field}_instruction"],
                       f"{field} instruction")
    expected = f"addi r0,+0x{value:x},r{register}"
    if _instruction_text(code, address) != expected:
        raise ValueError(f"atlas {field} argument does not match the package")


def verify_package(atlas: dict, package_path: str) -> None:
    package = zup_bank.read_package(package_path)
    bank = zup_bank.build_bank(package)
    layout = ghidra_decompile_packed.build_runtime_layout(
        bank.data, 0, 0x479BC)
    code = next(region for region in layout if region.kind == "code")
    sites = ghidra_decompile_packed.resolve_call_sites(
        code.data, "big", {23: code.start + 0x40000}, code.start)
    actual = {source for source, target, kind in sites
              if target == 0x1CC0C and kind == "call"}
    packed = [entry for entry in atlas["entries"]
              if entry["scope"] == "packed"]
    expected = {_address(entry["call"], "call address") for entry in packed}
    if actual != expected:
        raise ValueError("atlas call inventory does not match the package")
    for entry in packed:
        message = entry["message"].encode("ascii") + b"\0"
        address = _address(entry["message_address"], "message address")
        if _runtime_bytes(layout, address, len(message)) != message:
            raise ValueError("atlas message does not match the package")
        _verify_addi(code, entry, "mode", 5, entry["mode"])
        _verify_addi(code, entry, "message", 6, address)
        if entry["class"] is not None:
            _verify_addi(code, entry, "class", 4, entry["class"])
    conditional = next(entry for entry in packed if entry["class"] is None)
    conditional_text = {
        address: _instruction_text(code, _address(address, "class evidence"))
        for address in conditional["class_evidence"]
    }
    expected_conditional = {
        "0x4d94c": "mov r4,r16",
        "0x4da20": "beq r3,r2,0x0004da40",
        "0x4da28": "addi r0,+0x7,r4",
        "0x4da34": "bne r3,r2,0x0004db9c",
    }
    if conditional_text != expected_conditional:
        raise ValueError("atlas conditional class does not match the package")


def _print_entry(entry: dict) -> None:
    message = entry["message"].removesuffix("\n")
    class_value = str(entry["class"]) if entry["class"] is not None \
        else entry["class_expression"]
    print(f"Message:      {message}")
    print(f"Scope:        {entry['scope']}")
    print(f"Class/mode:   {class_value} / {entry['mode']}")
    print(f"Message data: {entry['message_address']}")
    if entry["scope"] == "packed":
        class_source = entry["class_instruction"] \
            if "class_instruction" in entry \
            else ", ".join(entry["class_evidence"])
        print(f"Arg sources:  class {class_source}, mode "
              f"{entry['mode_instruction']}, message "
              f"{entry['message_instruction']}")
    print(f"Emitter call: {entry['call']}")
    print(f"Owning path:  {entry['owner']} @ {entry['owner_address']}")
    print(f"Confidence:   {entry['confidence']}")
    if "state" in entry:
        print(f"State:        {entry['state']}")


def build_parser() -> argparse.ArgumentParser:
    parser = SafeArgumentParser(description=__doc__)
    parser.add_argument("query", nargs="?",
                        help="message text, owner, or 0x-prefixed address")
    parser.add_argument("--atlas", default=DEFAULT_ATLAS,
                        help="bounded atlas JSON (default: checked-in atlas)")
    parser.add_argument("--list", action="store_true",
                        help="show every atlas entry")
    parser.add_argument("--json", action="store_true",
                        help="emit matching entries as JSON")
    parser.add_argument("--verify-package", metavar="PATH",
                        help="verify all 27 packed calls and strings against a .zup")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    try:
        atlas = load_atlas(arguments.atlas)
        if arguments.verify_package:
            verify_package(atlas, arguments.verify_package)
            print("package_verification=PASS packed_calls=27")
        if arguments.list:
            matches = atlas["entries"]
        elif arguments.query:
            matches = search(atlas["entries"], arguments.query)
        elif arguments.verify_package:
            return 0
        else:
            parser.error("query or --list is required")
        if not matches:
            print("no matching syslog entries", file=sys.stderr)
            return 1
        if arguments.json:
            print(json.dumps(matches, indent=2, sort_keys=True))
        else:
            for index, entry in enumerate(matches):
                if index:
                    print()
                _print_entry(entry)
        return 0
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
