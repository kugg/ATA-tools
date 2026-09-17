#!/usr/bin/env python3
"""Validate captured host network state without changing it."""

from __future__ import annotations

import ipaddress
import os
from pathlib import Path
import stat
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from refactor import qemu_i386_flash  # noqa: E402


MAX_SNAPSHOT_BYTES = 2 * 1024 * 1024


def _read_snapshot(path: str) -> str:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    path_details = os.lstat(path)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as file:
        details = os.fstat(file.fileno())
        if (details.st_dev, details.st_ino) != (path_details.st_dev,
                                                path_details.st_ino) \
                or not stat.S_ISREG(details.st_mode) \
                or details.st_uid != os.getuid() \
                or stat.S_IMODE(details.st_mode) != 0o600 \
                or details.st_size > MAX_SNAPSHOT_BYTES:
            raise ValueError("invalid network snapshot")
        raw = file.read(MAX_SNAPSHOT_BYTES + 1)
    if len(raw) > MAX_SNAPSHOT_BYTES:
        raise ValueError("invalid network snapshot")
    return raw.decode("utf-8")


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv
    try:
        if len(argv) == 4 and argv[1] == "check-overlap":
            snapshot = _read_snapshot(argv[2])
            candidate = ipaddress.ip_network(argv[3])
            if not isinstance(candidate, ipaddress.IPv4Network):
                raise ValueError("candidate is not IPv4")
            overlaps = [
                network for network in qemu_i386_flash.route_networks(snapshot)
                if network.prefixlen != 0 and network.overlaps(candidate)
            ]
            return 1 if overlaps else 0
        if len(argv) == 8 and argv[1] == "compare":
            before_routes = (
                qemu_i386_flash.route_state(
                    _read_snapshot(argv[2]), frozenset(("inet",))),
                qemu_i386_flash.route_state(
                    _read_snapshot(argv[4]), frozenset(("inet6",))),
            )
            after_routes = (
                qemu_i386_flash.route_state(
                    _read_snapshot(argv[3]), frozenset(("inet",))),
                qemu_i386_flash.route_state(
                    _read_snapshot(argv[5]), frozenset(("inet6",))),
            )
            before_nwi = qemu_i386_flash.nwi_state(_read_snapshot(argv[6]))
            after_nwi = qemu_i386_flash.nwi_state(_read_snapshot(argv[7]))
            return 0 if (before_routes, before_nwi) == (after_routes, after_nwi) else 1
    except (OSError, UnicodeError, ValueError):
        pass
    print("error: network snapshot validation failed", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
