#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""Look up evidence-backed ATA web-server and TFTP-client firmware paths."""

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
DEFAULT_ATLAS = os.path.join(HERE, "data", "ata_service_atlas.json")
MAX_ATLAS_BYTES = 512 * 1024
MAX_ENTRIES = 256
MAX_QUERY_LENGTH = 256
CONFIDENCE = {"exact", "inferred-operation", "shared-downstream"}


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, "error: invalid arguments\n")


def _address(value: object, name: str) -> int:
    if not isinstance(value, str) or len(value) > 18:
        raise ValueError(f"service atlas {name} is invalid")
    try:
        result = int(value, 16)
    except ValueError as exc:
        raise ValueError(f"service atlas {name} is invalid") from exc
    if not 0 <= result <= 0xFFFFFFFF:
        raise ValueError(f"service atlas {name} is invalid")
    return result


def _text(value: object, name: str, allow_empty: bool = False,
          allow_line_endings: bool = False) -> str:
    if not isinstance(value, str) or len(value) > 4096 \
            or (not value and not allow_empty):
        raise ValueError(f"service atlas {name} is invalid")
    for character in value:
        if ord(character) == 0x7F or ord(character) < 0x20 \
                and not (allow_line_endings and character in "\r\n"):
            raise ValueError(f"service atlas {name} contains control characters")
    return value


def load_atlas(path: str = DEFAULT_ATLAS) -> dict:
    raw = zup_extract._read_regular_file(path, MAX_ATLAS_BYTES, "service atlas")
    try:
        atlas = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("service atlas is not valid UTF-8 JSON") from exc
    if not isinstance(atlas, dict) or atlas.get("schema_version") != 1:
        raise ValueError("service atlas schema is unsupported")
    services = atlas.get("services")
    if not isinstance(services, dict) or set(services) != {"web", "tftp"}:
        raise ValueError("service atlas inventory is invalid")
    seen_ids = set()
    for service_name, service in services.items():
        entries = service.get("entries") if isinstance(service, dict) else None
        if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_ENTRIES:
            raise ValueError("service atlas entry count is invalid")
        _text(service.get("role"), "role")
        _text(service.get("completeness"), "completeness")
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("service atlas entry is invalid")
            identifier = _text(entry.get("id"), "entry id")
            if identifier in seen_ids:
                raise ValueError("service atlas contains duplicate entry ids")
            seen_ids.add(identifier)
            _text(entry.get("kind"), "entry kind")
            _text(entry.get("query"), "entry query")
            _text(entry.get("operation"), "operation")
            if entry.get("confidence") not in CONFIDENCE:
                raise ValueError("service atlas confidence is invalid")
            if "text" in entry:
                _text(entry["text"], "runtime text", True, True)
            for field in ("data_address", "handler_address", "dispatch_address",
                          "table_slot", "descriptor"):
                if field in entry:
                    _address(entry[field], field)
            if "table_slot" in entry:
                _address(entry.get("table_mask"), "table mask")
            if "descriptor" in entry:
                words = entry.get("descriptor_words")
                if not isinstance(words, list) or len(words) != 5:
                    raise ValueError("service atlas descriptor is invalid")
                for word in words:
                    _address(word, "descriptor word")
            materializations = entry.get("materializations", [])
            if not isinstance(materializations, list):
                raise ValueError("service atlas materializations are invalid")
            for materialization in materializations:
                if not isinstance(materialization, dict) \
                        or not isinstance(materialization.get("register"), int) \
                        or not 0 <= materialization["register"] <= 31:
                    raise ValueError("service atlas materialization is invalid")
                _address(materialization.get("address"), "instruction address")
                _address(materialization.get("value"), "instruction value")
            callers = entry.get("callers", [])
            if not isinstance(callers, list):
                raise ValueError("service atlas callers are invalid")
            for caller in callers:
                _address(caller, "caller")
            checks = entry.get("instruction_checks", [])
            if not isinstance(checks, list) or len(checks) > 64:
                raise ValueError("service atlas instruction checks are invalid")
            for check in checks:
                if not isinstance(check, dict):
                    raise ValueError(
                        "service atlas instruction check is invalid")
                _address(check.get("address"), "instruction address")
                _text(check.get("text"), "instruction text")
    web = services["web"]
    routes = [entry for entry in web["entries"] if entry["kind"] == "route"]
    methods = [entry for entry in web["entries"] if entry["kind"] == "method"]
    if len(routes) != 14 or len(methods) != 2 \
            or web.get("counts") != {"routes": 14, "methods": 2}:
        raise ValueError("web route/method inventory is incomplete")
    if services["tftp"].get("role") != "client" \
            or services["tftp"].get("server_present") is not False:
        raise ValueError("TFTP role is invalid")
    return atlas


def search(entries: list[dict], query: str) -> list[dict]:
    if not query or len(query) > MAX_QUERY_LENGTH \
            or any(ord(character) < 0x20 or ord(character) == 0x7F
                   for character in query):
        raise ValueError("query is invalid")
    needle = query.casefold()
    matches = []
    for entry in entries:
        fields = [entry["id"], entry["kind"], entry["query"],
                  entry["operation"], entry.get("text", ""),
                  entry.get("handler", ""), entry.get("data_address", ""),
                  entry.get("handler_address", "")]
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
    raise ValueError("service atlas data lies outside initialized runtime memory")


def _code_text(code: ghidra_decompile_packed.RuntimeRegion, address: int) -> str:
    if code.data is None or address < code.start or address + 4 > code.end:
        raise ValueError("service atlas instruction lies outside packed code")
    offset = address - code.start
    word = int.from_bytes(code.data[offset:offset + 4], "big")
    return mipsx_dasm.decode(word, address).text


def verify_package(atlas: dict, package_path: str) -> None:
    bank = zup_bank.build_bank(zup_bank.read_package(package_path))
    layout = ghidra_decompile_packed.build_runtime_layout(
        bank.data, 0, 0x479BC)
    code = next(region for region in layout if region.kind == "code")
    for service in atlas["services"].values():
        for entry in service["entries"]:
            if "data_address" in entry and "text" in entry:
                address = _address(entry["data_address"], "data address")
                expected = entry["text"].encode("ascii") + b"\0"
                if _runtime_bytes(layout, address, len(expected)) != expected:
                    raise ValueError("service atlas text does not match package")
            for item in entry.get("materializations", []):
                instruction = _address(item["address"], "instruction address")
                value = _address(item["value"], "instruction value")
                expected = f"addi r0,+0x{value:x},r{item['register']}"
                if _code_text(code, instruction) != expected:
                    raise ValueError("service materialization does not match package")
            for check in entry.get("instruction_checks", []):
                instruction = _address(check["address"],
                                       "instruction address")
                if _code_text(code, instruction) != check["text"]:
                    raise ValueError(
                        "service instruction check does not match package")
            if "table_slot" in entry:
                slot = _address(entry["table_slot"], "table slot")
                data = _runtime_bytes(layout, slot, 8)
                words = [int.from_bytes(data[index:index + 4], "big")
                         for index in (0, 4)]
                expected = [_address(entry["data_address"], "route address"),
                            _address(entry["table_mask"], "table mask")]
                if words != expected:
                    raise ValueError("web route table does not match package")
            if "descriptor" in entry:
                descriptor = _address(entry["descriptor"], "descriptor")
                data = _runtime_bytes(layout, descriptor, 20)
                words = [int.from_bytes(data[index:index + 4], "big")
                         for index in range(0, 20, 4)]
                expected = [_address(value, "descriptor word")
                            for value in entry["descriptor_words"]]
                if words != expected:
                    raise ValueError("TFTP descriptor does not match package")


def _display(value: str) -> str:
    return value.encode("unicode_escape").decode("ascii")


def _print_entry(service: str, entry: dict) -> None:
    print(f"Entry:       {entry['id']}")
    print(f"Service:     {service}")
    print(f"Kind:        {entry['kind']}")
    print(f"Query/name:  {_display(entry['query'])}")
    if "text" in entry:
        print(f"Runtime text:{' ' if entry['text'] else ''}{_display(entry['text'])}")
    if "data_address" in entry:
        print(f"Data:        {entry['data_address']}")
    if "handler" in entry:
        print(f"Handler:     {entry['handler']} @ {entry['handler_address']}")
    print(f"Operation:   {entry['operation']}")
    print(f"Confidence:  {entry['confidence']}")


def build_parser() -> argparse.ArgumentParser:
    parser = SafeArgumentParser(description=__doc__)
    parser.add_argument("service", choices=("web", "http", "tftp"))
    parser.add_argument("query", nargs="?")
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
        service = "web" if arguments.service == "http" else arguments.service
        details = atlas["services"][service]
        if arguments.verify_package:
            verify_package(atlas, arguments.verify_package)
            print("package_verification=PASS web_routes=14 web_methods=2 "
                  "tftp_role=client")
        if arguments.list:
            matches = details["entries"]
        elif arguments.query:
            matches = search(details["entries"], arguments.query)
        elif arguments.verify_package:
            return 0
        else:
            parser.error("query or --list is required")
        if not matches:
            print("no matching service entries", file=sys.stderr)
            return 1
        if arguments.json:
            print(json.dumps(matches, indent=2, sort_keys=True))
        else:
            print(f"Role:        {details['role']}")
            if service == "tftp":
                print("Server:      absent from this firmware image")
            for index, entry in enumerate(matches):
                if index or service == "tftp":
                    print()
                _print_entry(service, entry)
        return 0
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
