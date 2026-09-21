#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""Look up evidence-backed ATA SIP registration and call transitions."""

from __future__ import annotations

import argparse
import json
import os
import sys

if __package__:
    from . import mipsx_dasm, mipsx_strings, zup_bank, zup_extract
else:
    import mipsx_dasm
    import mipsx_strings
    import zup_bank
    import zup_extract


HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ATLAS = os.path.join(HERE, "data", "ata_lifecycle_atlas.json")
MAX_ATLAS_BYTES = 512 * 1024
MAX_ENTRIES = 128
MAX_QUERY_LENGTH = 256
CONFIDENCE = {"exact-control-flow", "direct-message", "inferred-state"}
MACHINES = {"registration", "outgoing-call", "incoming-call", "call-teardown"}


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, "error: invalid arguments\n")


def _address(value: object, name: str) -> int:
    if not isinstance(value, str) or len(value) > 18:
        raise ValueError(f"lifecycle atlas {name} is invalid")
    try:
        result = int(value, 16)
    except ValueError as exc:
        raise ValueError(f"lifecycle atlas {name} is invalid") from exc
    if not 0 <= result < mipsx_strings.BANK_BYTES:
        raise ValueError(f"lifecycle atlas {name} is invalid")
    return result


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise ValueError(f"lifecycle atlas {name} is invalid")
    if any(ord(character) < 0x20 or ord(character) == 0x7F
           for character in value):
        raise ValueError(f"lifecycle atlas {name} contains control characters")
    return value


def _checks(entry: dict) -> None:
    checks = entry.get("instruction_checks", [])
    if not isinstance(checks, list) or len(checks) > 32:
        raise ValueError("lifecycle atlas instruction checks are invalid")
    for check in checks:
        if not isinstance(check, dict):
            raise ValueError("lifecycle atlas instruction check is invalid")
        _address(check.get("address"), "instruction address")
        _text(check.get("text"), "instruction text")


def load_atlas(path: str = DEFAULT_ATLAS) -> dict:
    raw = zup_extract._read_regular_file(path, MAX_ATLAS_BYTES,
                                         "lifecycle atlas")
    try:
        atlas = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("lifecycle atlas is not valid UTF-8 JSON") from exc
    if not isinstance(atlas, dict) or atlas.get("schema_version") != 1:
        raise ValueError("lifecycle atlas schema is unsupported")
    contexts = atlas.get("contexts")
    transitions = atlas.get("transitions")
    if not isinstance(contexts, list) or not isinstance(transitions, list) \
            or not 1 <= len(contexts) <= MAX_ENTRIES \
            or not 1 <= len(transitions) <= MAX_ENTRIES:
        raise ValueError("lifecycle atlas inventory is invalid")
    seen = set()
    for entry in contexts + transitions:
        if not isinstance(entry, dict):
            raise ValueError("lifecycle atlas entry is invalid")
        identifier = _text(entry.get("id"), "entry id")
        if identifier in seen:
            raise ValueError("lifecycle atlas contains duplicate entry ids")
        seen.add(identifier)
        for field in ("kind", "query", "handler"):
            _text(entry.get(field), field)
        _address(entry.get("handler_address"), "handler address")
        if entry.get("confidence") not in CONFIDENCE:
            raise ValueError("lifecycle atlas confidence is invalid")
        if "data_address" in entry:
            _address(entry["data_address"], "data address")
        if "materialization" in entry:
            _address(entry["materialization"], "materialization")
        _checks(entry)
        if entry["kind"] == "transition":
            if entry.get("machine") not in MACHINES:
                raise ValueError("lifecycle atlas machine is invalid")
            for field in ("event", "current_state", "guard", "next_state",
                          "action", "timer", "text"):
                _text(entry.get(field), field)
            if "data_address" not in entry or "materialization" not in entry:
                raise ValueError("lifecycle transition evidence is incomplete")
        elif entry["kind"] == "context":
            _text(entry.get("operation"), "operation")
        else:
            raise ValueError("lifecycle atlas entry kind is invalid")
    return atlas


def entries(atlas: dict) -> list[dict]:
    return atlas["contexts"] + atlas["transitions"]


def search(atlas_entries: list[dict], query: str) -> list[dict]:
    if not query or len(query) > MAX_QUERY_LENGTH \
            or any(ord(character) < 0x20 or ord(character) == 0x7F
                   for character in query):
        raise ValueError("query is invalid")
    needle = query.casefold()
    fields = ("id", "kind", "machine", "query", "event", "current_state",
              "guard", "action", "operation", "next_state", "timer", "text",
              "handler")
    return [entry for entry in atlas_entries
            if any(needle in str(entry.get(field, "")).casefold()
                   for field in fields)]


def _instruction(image: bytes, address: int) -> str:
    if address + 4 > len(image):
        raise ValueError("lifecycle instruction lies outside runtime image")
    word = int.from_bytes(image[address:address + 4], "big")
    return mipsx_dasm.decode(word, address).text


def verify_package(atlas: dict, package_path: str) -> None:
    package = zup_extract._read_regular_file(
        package_path, mipsx_strings.MAX_PACKAGE_BYTES, "ATA package")
    bank = zup_bank.build_bank(package).data
    image = mipsx_strings.build_runtime_image(package, bank)
    for entry in entries(atlas):
        if "text" in entry:
            address = _address(entry["data_address"], "data address")
            # Atlas text omits the resident logger's trailing line feed.
            expected = entry["text"].encode("ascii") + b"\n\0"
            if image[address:address + len(expected)] != expected:
                actual = image[address:address + len(expected)]
                raise ValueError(
                    f"lifecycle message does not match package for "
                    f"{entry['id']} at 0x{address:x}: expected "
                    f"{expected!r}, got {actual!r}")
            materialization = _address(entry["materialization"],
                                       "materialization")
            expected_instruction = f"addi r0,+0x{address:x},r4"
            actual_instruction = _instruction(image, materialization)
            if actual_instruction != expected_instruction:
                raise ValueError(
                    f"lifecycle materialization does not match package at "
                    f"0x{materialization:x}: expected {expected_instruction!r}, "
                    f"got {actual_instruction!r}")
        for check in entry.get("instruction_checks", []):
            address = _address(check["address"], "instruction address")
            actual = _instruction(image, address)
            if actual != check["text"]:
                raise ValueError(
                    f"lifecycle instruction check does not match package at "
                    f"0x{address:x}: expected {check['text']!r}, got {actual!r}")


def _display(value: str) -> str:
    return value.encode("unicode_escape").decode("ascii")


def _print_entry(entry: dict) -> None:
    print(f"Entry:       {entry['id']}")
    print(f"Kind:        {entry['kind']}")
    if "machine" in entry:
        print(f"Machine:     {entry['machine']}")
        print(f"Event:       {entry['event']}")
        print(f"Current:     {entry['current_state']}")
        print(f"Next:        {entry['next_state']}")
        print(f"Timer:       {entry['timer']}")
        print(f"Message:     {_display(entry['text'])}")
    print(f"Handler:     {entry['handler']} @ {entry['handler_address']}")
    print(f"Operation:   {entry.get('action', entry.get('operation'))}")
    print(f"Confidence:  {entry['confidence']}")


def build_parser() -> argparse.ArgumentParser:
    parser = SafeArgumentParser(description=__doc__)
    parser.add_argument("query", nargs="?")
    parser.add_argument("--machine", choices=sorted(MACHINES))
    parser.add_argument("--atlas", default=DEFAULT_ATLAS)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--verify-package", metavar="PATH")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    try:
        atlas = load_atlas(arguments.atlas)
        matches = entries(atlas)
        if arguments.machine:
            matches = [entry for entry in matches
                       if entry.get("machine") == arguments.machine]
        if arguments.query:
            matches = search(matches, arguments.query)
        elif not arguments.list and not arguments.verify_package:
            parser.error("query, --list, or --verify-package is required")
        if arguments.verify_package:
            verify_package(atlas, arguments.verify_package)
            print(f"package_verification=PASS contexts={len(atlas['contexts'])} "
                  f"transitions={len(atlas['transitions'])}")
        if arguments.json:
            print(json.dumps(matches, indent=2, sort_keys=True))
        else:
            for index, entry in enumerate(matches):
                if index:
                    print()
                _print_entry(entry)
        return 0 if matches or arguments.verify_package else 1
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
