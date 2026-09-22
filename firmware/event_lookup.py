#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""Look up the 108 evidence-backed ATA packed log-event call sites offline.

The packed function ``maybe_log_event`` (runtime ``0x1c9b4``) receives a
message address in ``r4`` and up to four further arguments in ``r5``..``r8``.
Unlike ``maybe_syslog_emit_class`` it carries no class or mode argument; the
atlas records that explicitly.  Every entry is derived from the pinned
package: the call address, the last argument-producing instruction for each
register, and the message text at the recorded runtime address.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import unicodedata

if __package__:
    from . import ghidra_decompile_packed, mipsx_dasm, zup_bank, zup_extract
else:
    import ghidra_decompile_packed
    import mipsx_dasm
    import zup_bank
    import zup_extract


HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ATLAS = os.path.join(HERE, "data", "ata_event_atlas.json")
MAX_ATLAS_BYTES = 1024 * 1024
MAX_ENTRIES = 256
MAX_ARGS = 5
MAX_QUERY_LENGTH = 256
EMITTER = 0x1C9B4
TYPE8_PAYLOAD = 0x479BC
REG_BASE = 0x40000
CONFIDENCE = {"exact-message", "unresolved-message"}
ARG_KINDS = {"constant", "global-load", "other", "register-move",
             "struct-load"}
CLASS_SOURCES = {"none", "inherited-from-maybe_syslog_emit_class"}


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, "error: invalid arguments\n")


def _address(value: object, name: str) -> int:
    if not isinstance(value, str) or len(value) > 18:
        raise ValueError(f"event atlas {name} is invalid")
    try:
        address = int(value, 16)
    except ValueError as exc:
        raise ValueError(f"event atlas {name} is invalid") from exc
    if not 0 <= address <= 0xFFFFFFFF:
        raise ValueError(f"event atlas {name} is invalid")
    return address


def _text(value: object, name: str, allow_newline: bool = False) -> str:
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise ValueError(f"event atlas {name} is invalid")
    checked = value.replace("\n", "") if allow_newline else value
    if any(unicodedata.category(character) in {"Cc", "Cf"}
           for character in checked):
        raise ValueError(f"event atlas {name} contains control characters")
    return value


def load_atlas(path: str = DEFAULT_ATLAS) -> dict:
    raw = zup_extract._read_regular_file(path, MAX_ATLAS_BYTES, "event atlas")
    try:
        atlas = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("event atlas is not valid UTF-8 JSON") from exc
    if not isinstance(atlas, dict) or atlas.get("schema_version") != 1:
        raise ValueError("event atlas schema is unsupported")
    if _address(atlas.get("emitter"), "emitter") != EMITTER:
        raise ValueError("event atlas emitter is invalid")
    entries = atlas.get("entries")
    if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_ENTRIES:
        raise ValueError("event atlas entry count is invalid")
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("event atlas entry is invalid")
        call = _address(entry.get("call"), "call address")
        if call in seen:
            raise ValueError("event atlas contains duplicate call addresses")
        seen.add(call)
        _address(entry.get("owner"), "owner address")
        if entry.get("owner_name") is not None:
            _text(entry["owner_name"], "owner name")
        callers = entry.get("callers")
        if not isinstance(callers, list) or len(callers) > 256:
            raise ValueError("event atlas caller list is invalid")
        for caller in callers:
            _address(caller, "caller address")
        if entry.get("subsystem") is not None:
            _text(entry["subsystem"], "subsystem")
        if entry.get("message") is not None:
            _text(entry["message"], "message", True)
        args = entry.get("args")
        if not isinstance(args, list) or not 1 <= len(args) <= MAX_ARGS:
            raise ValueError("event atlas argument list is invalid")
        for item in args:
            if not isinstance(item, dict):
                raise ValueError("event atlas argument is invalid")
            register = item.get("register")
            if not isinstance(register, int) or not 4 <= register <= 8:
                raise ValueError("event atlas argument register is invalid")
            _address(item.get("address"), "argument address")
            _text(item.get("text"), "argument text")
            if item.get("kind") not in ARG_KINDS:
                raise ValueError("event atlas argument kind is invalid")
            for field in ("value", "from", "base", "offset"):
                if field in item:
                    _text(item[field], f"argument {field}")
            if item.get("string") is not None:
                _text(item["string"], "argument string", True)
            if ("base" in item) != ("offset" in item):
                raise ValueError(
                    "event atlas argument base/offset pair is invalid")
        if entry.get("class_source") not in CLASS_SOURCES:
            raise ValueError("event atlas class source is invalid")
        if entry.get("confidence") not in CONFIDENCE:
            raise ValueError("event atlas confidence is invalid")
        dominance = entry.get("args_dominance", "linear")
        if dominance not in {"linear", "may-be-conditional"}:
            raise ValueError("event atlas argument dominance is invalid")
        if "conditional_args" in entry:
            registers = entry["conditional_args"]
            if not isinstance(registers, list) or not registers or not all(
                    isinstance(register, int) and 4 <= register <= 8
                    for register in registers):
                raise ValueError("event atlas conditional arguments are invalid")
        if dominance == "may-be-conditional" and "conditional_args" not in entry:
            raise ValueError("event atlas conditional arguments are missing")
        if entry["confidence"] == "exact-message":
            _address(entry.get("message_address"), "message address")
            if entry.get("message") is None:
                raise ValueError("event atlas exact message is missing")
    if atlas.get("direct_calls") != len(entries):
        raise ValueError("event atlas direct call count is invalid")
    return atlas


def search(entries: list[dict], query: str) -> list[dict]:
    if not query or len(query) > MAX_QUERY_LENGTH \
            or any(ord(character) < 0x20 or ord(character) == 0x7F
                   for character in query):
        raise ValueError("query is invalid")
    needle = query.casefold()
    matches = []
    for entry in entries:
        fields = [entry["call"], entry["owner"], entry.get("owner_name") or "",
                  entry.get("subsystem") or "", entry.get("message") or "",
                  entry.get("message_address") or ""]
        fields.extend(item["text"] for item in entry["args"])
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
    raise ValueError("event atlas data lies outside initialized runtime data")


def _instruction_text(code: ghidra_decompile_packed.RuntimeRegion,
                      address: int) -> str:
    if code.data is None or address < code.start or address + 4 > code.end:
        raise ValueError("event atlas instruction is outside packed code")
    offset = address - code.start
    word = int.from_bytes(code.data[offset:offset + 4], "big")
    return mipsx_dasm.decode(word, address).text


def verify_package(atlas: dict, package_path: str) -> None:
    package = zup_bank.read_package(package_path)
    bank = zup_bank.build_bank(package)
    layout = ghidra_decompile_packed.build_runtime_layout(
        bank.data, 0, TYPE8_PAYLOAD)
    code = next(region for region in layout if region.kind == "code")
    sites = ghidra_decompile_packed.resolve_call_sites(
        code.data, "big", {23: code.start + REG_BASE}, code.start)
    actual = {source for source, target, kind in sites
              if target == EMITTER and kind == "call"}
    expected = {_address(entry["call"], "call address")
                for entry in atlas["entries"]}
    if actual != expected or len(actual) != 108:
        raise ValueError("event atlas call inventory does not match the package")
    for entry in atlas["entries"]:
        for item in entry["args"]:
            address = _address(item["address"], "argument address")
            actual_text = _instruction_text(code, address)
            if actual_text != item["text"]:
                raise ValueError(
                    f"event atlas argument text does not match the package at "
                    f"0x{address:x}: expected {item['text']!r}, "
                    f"got {actual_text!r}")
        if entry["confidence"] == "exact-message":
            message = entry["message"].encode("ascii") + b"\0"
            address = _address(entry["message_address"], "message address")
            if _runtime_bytes(layout, address, len(message)) != message:
                raise ValueError(
                    "event atlas message does not match the package")


def _display(value: str) -> str:
    return value.encode("unicode_escape").decode("ascii")


def _print_entry(entry: dict) -> None:
    print(f"Event call:   {entry['call']}")
    print(f"Owner:        {entry.get('owner_name') or entry['owner']} "
          f"@ {entry['owner']}")
    print(f"Subsystem:    {entry.get('subsystem') or 'unresolved'}")
    if entry.get("message") is not None:
        print(f"Message:      {_display(entry['message'].removesuffix(chr(10)))}")
        print(f"Message data: {entry['message_address']}")
    else:
        print("Message:      unresolved")
    for item in entry["args"]:
        resolved = item.get("string") or item.get("value") \
            or (item.get("from") and f"from {item['from']}") \
            or (item.get("base") and f"{item['base']}{item['offset']}") \
            or "dynamic"
        print(f"  r{item['register']} <- {item['address']}: {item['text']} "
              f"[{item['kind']}: {_display(resolved)}]")
    if entry.get("args_dominance") == "may-be-conditional":
        registers = ",".join(f"r{r}" for r in entry["conditional_args"])
        print(f"Arg dominance: may be conditional for {registers} "
              f"(a control-flow target lies between the write and the call)")
    print(f"Class:        {entry['class_source']}")
    print(f"Confidence:   {entry['confidence']}")


def build_parser() -> argparse.ArgumentParser:
    parser = SafeArgumentParser(description=__doc__)
    parser.add_argument("query", nargs="?",
                        help="message text, owner, subsystem, or 0x address")
    parser.add_argument("--atlas", default=DEFAULT_ATLAS,
                        help="bounded atlas JSON (default: checked-in atlas)")
    parser.add_argument("--list", action="store_true",
                        help="show every atlas entry")
    parser.add_argument("--json", action="store_true",
                        help="emit matching entries as JSON")
    parser.add_argument("--verify-package", metavar="PATH",
                        help="verify all 108 calls, argument instructions, and "
                             "messages against a .zup")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    try:
        atlas = load_atlas(arguments.atlas)
        if arguments.verify_package:
            verify_package(atlas, arguments.verify_package)
            print("package_verification=PASS event_calls=108")
        if arguments.list:
            matches = atlas["entries"]
        elif arguments.query:
            matches = search(atlas["entries"], arguments.query)
        elif arguments.verify_package:
            return 0
        else:
            parser.error("query or --list is required")
        if not matches:
            print("no matching event entries", file=sys.stderr)
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
