#!/usr/bin/env python3
"""Run one operator-triggered ATA DHCP and firmware service window.

The command never configures an interface, changes a route, sends DTMF, or retries
an ambiguous transfer. Bare invocation is inert; only ``--apply`` opens sockets.
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import hmac
from importlib import import_module
import ipaddress
import os
import re
import stat
import sys
from typing import Any

import dhcp
from refactor import sata186us


DEFAULT_DHCP_TIMEOUT_SECONDS = 600
DEFAULT_SERVE_SECONDS = 60 * 60
DEFAULT_COMPLETION_IDLE_SECONDS = 120
MAX_OPERATION_SECONDS = 24 * 60 * 60
MAX_MANIFEST_BYTES = 128 * 1024
DEFAULT_CLIENT_HOST = 10
INTERFACE_PATTERN = re.compile(r"[A-Za-z0-9_.-]{1,64}\Z")


class FlashError(RuntimeError):
    """An operator-actionable failure whose message is safe to print."""


class InterfaceState:
    __slots__ = ("interface", "address", "addresses", "network", "routes")

    def __init__(self, interface: str, address: ipaddress.IPv4Address,
                 network: ipaddress.IPv4Network,
                 routes: tuple[Any, ...] = (),
                 addresses: tuple[ipaddress.IPv4Address, ...] | None = None):
        self.interface = interface
        self.address = address
        self.addresses = (address,) if addresses is None else addresses
        self.network = network
        self.routes = routes


class SafeArgumentParser(argparse.ArgumentParser):
    """Keep parser errors from reflecting arbitrary argument values."""

    def error(self, _message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, "error: invalid arguments\n")

    def fixed_error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, f"error: {message}\n")


def _validate_interface_name(interface: str) -> str:
    if not INTERFACE_PATTERN.fullmatch(interface):
        raise FlashError("the interface name is invalid")
    return interface


def _parse_ipv4(value: str, message: str) -> ipaddress.IPv4Address:
    try:
        return ipaddress.IPv4Address(value)
    except ValueError as error:
        raise FlashError(message) from error


def _read_bounded_regular(path: str, limit: int) -> bytes:
    flags = (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
             | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0))
    if not hasattr(os, "O_NOFOLLOW"):
        try:
            if stat.S_ISLNK(os.lstat(path).st_mode):
                raise FlashError("checksum manifest is not a bounded regular file")
        except OSError as error:
            raise FlashError("cannot open checksum manifest") from error
    try:
        fd = os.open(path, flags)
    except OSError as error:
        raise FlashError("cannot open checksum manifest") from error
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise FlashError("checksum manifest is not a bounded regular file")
        with os.fdopen(fd, "rb") as source:
            fd = -1
            raw = source.read(limit + 1)
            after = os.fstat(source.fileno())
    except OSError as error:
        raise FlashError("cannot read checksum manifest") from error
    finally:
        if fd >= 0:
            os.close(fd)
    if len(raw) > limit:
        raise FlashError("checksum manifest exceeds its size limit")
    before_identity = (
        before.st_dev, before.st_ino, before.st_size,
        getattr(before, "st_mtime_ns", int(before.st_mtime * 1_000_000_000)),
        getattr(before, "st_ctime_ns", int(before.st_ctime * 1_000_000_000)),
    )
    after_identity = (
        after.st_dev, after.st_ino, after.st_size,
        getattr(after, "st_mtime_ns", int(after.st_mtime * 1_000_000_000)),
        getattr(after, "st_ctime_ns", int(after.st_ctime * 1_000_000_000)),
    )
    if before_identity != after_identity or len(raw) != before.st_size:
        raise FlashError("checksum manifest changed while it was read")
    return raw


def verify_sha256sums(image_path: str, digest: str,
                      manifest_path: str | None = None) -> str:
    """Verify only the selected image's exact basename in a SHA256SUMS file."""
    if manifest_path is None:
        manifest_path = os.path.join(
            os.path.dirname(image_path) or ".", "SHA256SUMS")
    target_name = os.path.basename(os.fsencode(image_path))
    if not target_name or b"\x00" in target_name \
            or b"\n" in target_name or b"\r" in target_name:
        raise FlashError("firmware image filename cannot be matched safely")
    manifest = _read_bounded_regular(manifest_path, MAX_MANIFEST_BYTES)
    matches: list[str] = []
    for line in manifest.splitlines():
        if len(line) < 66 or line[64:66] not in (b"  ", b" *"):
            continue
        if line[66:] != target_name:
            continue
        encoded_digest = line[:64]
        if any(byte not in b"0123456789abcdefABCDEF" for byte in encoded_digest):
            continue
        matches.append(encoded_digest.decode("ascii").lower())
    if len(matches) != 1:
        raise FlashError(
            "checksum manifest must contain exactly one entry for the image filename")
    if not hmac.compare_digest(matches[0], digest.lower()):
        raise FlashError("firmware image SHA-256 does not match the checksum manifest")
    return manifest_path


def prepare_image(image_path: str, manifest_path: str | None = None):
    try:
        digest, info, store = sata186us.inspect_image(image_path)
        if store.data[:4] != b"+kxz":
            raise ValueError("live service supports only validated +kxz packages")
    except Exception as error:
        raise FlashError("firmware image failed structural validation") from error
    verify_sha256sums(image_path, digest, manifest_path)
    return digest, info, store


def _route_network(record: Any) -> ipaddress.IPv4Network:
    if not isinstance(record, (tuple, list)) or len(record) < 6:
        raise FlashError("cannot inspect the current IPv4 route table")
    raw_network, raw_mask = record[:2]
    try:
        network_address = ipaddress.IPv4Address(raw_network)
        netmask = ipaddress.IPv4Address(raw_mask)
        return ipaddress.IPv4Network(
            f"{network_address}/{netmask}", strict=False)
    except (ValueError, TypeError) as error:
        raise FlashError("cannot inspect the current IPv4 route table") from error


def _route_interface(record: Any) -> str:
    value = record[3]
    return (getattr(value, "network_name", None)
            or getattr(value, "name", None) or str(value))


def _route_output_address(record: Any) -> ipaddress.IPv4Address:
    try:
        return ipaddress.IPv4Address(record[4])
    except (ValueError, TypeError, IndexError) as error:
        raise FlashError("cannot inspect the current IPv4 route table") from error


def _netstat_route_records(scapy: Any) -> tuple[Any, ...] | None:
    """Read IPv4 routes via netstat, returning only valid route tuples.

    On Darwin, scapy's PF_ROUTE parser reports corrupted netmasks for several
    records (the multicast ``224.0.0/4`` entries come back as ``240.255.255.0``
    and connected prefixes collapse to ``/32``). Scapy's own netstat-based
    parser represents those masks correctly, so it is preferred on Darwin when
    every returned record still parses cleanly; otherwise ``None`` is returned
    and the caller keeps its fail-closed default.
    """
    try:
        from scapy.arch.unix import read_routes as _netstat_read_routes
        records = tuple(_netstat_read_routes())
    except Exception:
        return None
    if not records:
        return None
    try:
        for record in records:
            _route_network(record)
    except (FlashError, ValueError, TypeError):
        return None
    return records


def _capture_route_records(scapy: Any) -> tuple[Any, ...]:
    """Return the IPv4 route table in scapy's six-element tuple shape.

    Scapy's PF_ROUTE parser corrupts several netmasks on Darwin (see
    ``_netstat_route_records``). Only when scapy's own records cannot be parsed
    is the netstat-based parser consulted, so clean records (including test
    doubles and other platforms) are returned unchanged.
    """
    records = tuple(scapy.conf.route.routes)
    try:
        for record in records:
            _route_network(record)
        return records
    except (FlashError, ValueError, TypeError):
        netstat_records = _netstat_route_records(scapy)
        if netstat_records is not None:
            return netstat_records
        return records


def _is_direct_route(record: Any) -> bool:
    return record[2] in (0, None, "", "0.0.0.0")


def route_conflicts(routes: list[Any] | tuple[Any, ...],
                    candidate: ipaddress.IPv4Network, interface: str,
                    local_addresses: tuple[ipaddress.IPv4Address, ...]
                    ) -> tuple[ipaddress.IPv4Network, ...]:
    """Return numerically overlapping non-default routes on other interfaces."""
    conflicts: set[ipaddress.IPv4Network] = set()
    for record in routes:
        network = _route_network(record)
        route_interface = _route_interface(record)
        if network.prefixlen == 0 or route_interface == interface:
            continue
        if route_interface in {"lo", "lo0"} \
                and network.prefixlen == 32 \
                and network.network_address in local_addresses:
            continue
        if network.overlaps(candidate):
            conflicts.add(network)
    return tuple(sorted(conflicts, key=lambda item: (
        int(item.network_address), item.prefixlen)))


def _interface_ipv4_addresses(scapy: Any, interface: str,
                              *, reload: bool = False
                              ) -> tuple[ipaddress.IPv4Address, ...]:
    if reload:
        scapy.conf.ifaces.reload()
    device = scapy.conf.ifaces.dev_from_name(interface)
    raw_addresses = tuple(getattr(device, "ips", {}).get(4, ()))
    if not raw_addresses and getattr(device, "ip", None):
        raw_addresses = (device.ip,)
    addresses: set[ipaddress.IPv4Address] = set()
    for raw_address in raw_addresses:
        address = _parse_ipv4(
            str(raw_address), "an interface IPv4 address is invalid")
        if not address.is_unspecified:
            addresses.add(address)
    return tuple(sorted(addresses, key=int))


def current_interface_state(scapy: Any, interface: str,
                             expected_address: ipaddress.IPv4Address | None
                             ) -> InterfaceState:
    interface = _validate_interface_name(interface)
    try:
        scapy.conf.ifaces.reload()
        scapy.conf.route.resync()
        interfaces = tuple(str(item) for item in scapy.get_if_list())
        if interface not in interfaces:
            raise FlashError("the selected interface does not exist")
        addresses = _interface_ipv4_addresses(scapy, interface)
        routes = _capture_route_records(scapy)
    except FlashError:
        raise
    except Exception as error:
        raise FlashError("cannot inspect the selected interface") from error
    if not addresses:
        raise FlashError(
            f"{interface} has no IPv4 address; configure one and run again")
    if expected_address is not None and expected_address not in addresses:
        raise FlashError("the optional --address assertion does not match the interface")
    if expected_address is None and len(addresses) != 1:
        raise FlashError(
            "--address is required when the interface has multiple IPv4 addresses")
    address = addresses[0] if expected_address is None else expected_address

    connected = []
    selected_networks = []
    for record in routes:
        network = _route_network(record)
        if _route_interface(record) == interface:
            selected_networks.append(network)
            if not _is_direct_route(record):
                if network.prefixlen == 0:
                    raise FlashError(
                        "the selected interface owns a default route; "
                        "use an isolated interface")
                raise FlashError(
                    "the selected interface owns a gateway route; "
                    "use an isolated interface")
        if (_route_interface(record) == interface and _is_direct_route(record)
                and _route_output_address(record) in addresses
                and 0 < network.prefixlen < 32 and address in network):
            connected.append(network)
    if not connected:
        raise FlashError("cannot determine the selected interface IPv4 subnet")
    network = max(connected, key=lambda item: item.prefixlen)
    if any(item.prefixlen == 0 for item in ipaddress.collapse_addresses(
            selected_networks)):
        raise FlashError(
            "the selected interface has default-equivalent route coverage; "
            "use an isolated interface")
    conflicts = route_conflicts(routes, network, interface, addresses)
    if conflicts:
        raise FlashError(
            f"selected subnet overlaps another active route ({conflicts[0]})")
    return InterfaceState(interface, address, network, routes, addresses)


def choose_client_address(value: str | None,
                          state: InterfaceState) -> ipaddress.IPv4Address:
    if value is None:
        raw_candidate = int(state.network.network_address) + DEFAULT_CLIENT_HOST
        if raw_candidate >= int(state.network.broadcast_address):
            raise FlashError(
                "cannot derive a client address; supply --client-address")
        candidate = ipaddress.IPv4Address(raw_candidate)
    else:
        candidate = _parse_ipv4(value, "the client IPv4 address is invalid")
    if candidate not in state.network or candidate in state.addresses:
        raise FlashError("the client address is incompatible with the interface subnet")
    if candidate in (state.network.network_address, state.network.broadcast_address):
        raise FlashError("the client address is not a usable host address")
    return candidate


def validate_client_route(state: InterfaceState,
                          client_address: ipaddress.IPv4Address) -> None:
    """Require the effective route to the offered address to stay on-link."""
    matching = []
    for record in state.routes:
        network = _route_network(record)
        if client_address in network:
            try:
                metric = int(record[5])
            except (TypeError, ValueError) as error:
                raise FlashError("cannot inspect the current IPv4 route table") from error
            matching.append((network.prefixlen, metric, record))
    if not matching:
        raise FlashError("the client address has no current route")
    longest_prefix = max(item[0] for item in matching)
    best_metric = min(item[1] for item in matching if item[0] == longest_prefix)
    effective = [item[2] for item in matching
                 if item[0] == longest_prefix and item[1] == best_metric]
    if not effective or any(
            _route_interface(record) != state.interface
            or not _is_direct_route(record)
            or _route_output_address(record) not in state.addresses
            for record in effective):
        raise FlashError(
            "the effective client route is not direct on the selected interface")


def _interface_address_matches(scapy: Any, interface: str,
                               address: ipaddress.IPv4Address) -> bool:
    try:
        return address in _interface_ipv4_addresses(
            scapy, interface, reload=True)
    except Exception:
        return False


def revalidate_network(scapy: Any, before: InterfaceState,
                       client_address: ipaddress.IPv4Address) -> InterfaceState:
    current = current_interface_state(scapy, before.interface, before.address)
    if current.addresses != before.addresses or current.network != before.network:
        raise FlashError("the selected interface changed during the operation")
    validate_client_route(current, client_address)
    return current


def _log_line(logger: sata186us.Logger, message: str) -> None:
    logger.logs("%s\n", message)


def run_flash(args: argparse.Namespace, *, scapy_module=None,
              logger: sata186us.Logger | None = None) -> int:
    interface = _validate_interface_name(args.interface)
    if not 1 <= args.dhcp_timeout_seconds <= MAX_OPERATION_SECONDS:
        raise FlashError("--dhcp-timeout-seconds must be between 1 and 86400")
    if not 1 <= args.duration_seconds <= MAX_OPERATION_SECONDS:
        raise FlashError("--duration-seconds must be between 1 and 86400")
    completion_idle_seconds = (
        min(DEFAULT_COMPLETION_IDLE_SECONDS, args.duration_seconds)
        if args.completion_idle_seconds is None
        else args.completion_idle_seconds)
    if not 0 <= completion_idle_seconds <= args.duration_seconds:
        raise FlashError(
            "--completion-idle-seconds must not exceed --duration-seconds")
    expected_address = (_parse_ipv4(args.address, "--address is not a valid IPv4 address")
                        if args.address is not None else None)
    expected_mac = dhcp.parse_mac(args.client_mac) if args.client_mac else None
    digest, info, store = prepare_image(args.image, args.sha256sums)

    if scapy_module is None:
        try:
            scapy_module = import_module("scapy.all")
        except ImportError as error:
            raise FlashError("Scapy is unavailable; no network socket was opened") from error
    state = current_interface_state(scapy_module, interface, expected_address)
    client_address = choose_client_address(args.client_address, state)
    validate_client_route(state, client_address)
    lease_seconds = min(0xFFFFFFFF, args.duration_seconds + 600)
    dhcp_config = dhcp.DhcpConfig(
        interface, str(state.address), str(client_address),
        str(state.network.netmask), expected_mac,
        lease_seconds=lease_seconds,
        timeout_seconds=args.dhcp_timeout_seconds)
    if logger is None:
        logger = sata186us.Logger()

    logger.logs(
        "Firmware image verified (sha256=%s, platform=0x%08x, "
        "version=0x%04x, blocks=%d).\n",
        digest, info.platform, info.version, len(store.sums))
    logger.logs("Network verified (interface=%s, address=%s, subnet=%s).\n",
                state.interface, state.address, state.network)

    with ExitStack() as sockets:
        try:
            command_sock = sockets.enter_context(
                sata186us.bind_udp(
                    str(state.address), sata186us.DEFAULT_PORT,
                    interface=state.interface))
            data_sock = sockets.enter_context(
                sata186us.bind_udp(
                    str(state.address), sata186us.DATA_PORT,
                    interface=state.interface))
        except OSError as error:
            raise FlashError(
                "cannot reserve the firmware UDP ports on the selected address") from error
        lease = dhcp.run_dhcp(
            dhcp_config, scapy_module=scapy_module,
            address_check=lambda: _interface_address_matches(
                scapy_module, interface, state.address),
            logger=lambda message: _log_line(logger, message))
        revalidate_network(scapy_module, state, client_address)
        if lease.client_address != str(client_address) \
                or expected_mac is not None and lease.client_mac != expected_mac:
            raise FlashError("DHCP completed for an unexpected client")
        try:
            queued = (sata186us.drain_udp(command_sock)
                      + sata186us.drain_udp(data_sock))
        except (OSError, ValueError) as error:
            raise FlashError("cannot clear the pre-service firmware queues") from error
        if queued:
            raise FlashError(
                "firmware traffic arrived before service readiness; restart manually")

        logger.logs("DHCP client locked (address=%s, mac=%s).\n",
                    lease.client_address, dhcp.format_mac(lease.client_mac))
        dial_address = str(state.address).replace(".", "*")
        logger.logs("Python firmware service ready at %s:%d (data port %d).\n",
                    state.address, sata186us.DEFAULT_PORT, sata186us.DATA_PORT)
        logger.logs("Manually enter 100#%s*%d# once; never auto-retry.\n",
                    dial_address, sata186us.DEFAULT_PORT)
        try:
            result = sata186us.serve_firmware(
                command_sock, data_sock, info, store, str(state.address),
                sata186us.DATA_PORT, str(client_address), args.duration_seconds,
                logger, completion_grace_seconds=completion_idle_seconds,
                safety_check=lambda: bool(revalidate_network(
                    scapy_module, state, client_address)))
        except OSError as error:
            raise FlashError("firmware response transmission failed") from error

    if not result.complete:
        if result.unique_blocks:
            logger.logs("Firmware service ended incomplete (blocks=%d/%d).\n",
                        len(result.unique_blocks), result.total_blocks)
            raise FlashError("firmware service ended before all blocks were served")
        raise FlashError("firmware service ended without a transfer")
    logger.logs("All firmware blocks were served; verify the ATA with 123#.\n")
    return 0


def parse_options(argv: list[str]) -> argparse.Namespace:
    parser = SafeArgumentParser(prog="ata_flash.py", description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="run one DHCP and firmware service window")
    parser.add_argument("--interface", metavar="NAME",
                        help="existing Ethernet interface used for DHCP and serving")
    parser.add_argument(
        "--address", metavar="ADDRESS",
        help="optional assertion that ADDRESS is currently assigned to INTERFACE; "
             "never configures it")
    parser.add_argument("--client-address", metavar="ADDRESS",
                        help="address to offer; default is host 10 in the interface subnet")
    parser.add_argument("--client-mac", metavar="MAC",
                        help="optional DHCP client MAC; otherwise lock the first client")
    parser.add_argument("--sha256sums", metavar="PATH",
                        help="checksum manifest; default is SHA256SUMS beside IMAGE")
    parser.add_argument("--dhcp-timeout-seconds", type=int, metavar="SECONDS",
                        default=DEFAULT_DHCP_TIMEOUT_SECONDS)
    parser.add_argument("--duration-seconds", type=int, metavar="SECONDS",
                        default=DEFAULT_SERVE_SECONDS,
                        help="firmware deadline after DHCP ACK (default: 3600)")
    parser.add_argument("--completion-idle-seconds", type=int, metavar="SECONDS",
                        default=None,
                        help="quiet period after all blocks are served (default: 120)")
    parser.add_argument("image", nargs="?", metavar="IMAGE")
    args = parser.parse_args(argv[1:])
    if args.apply and (args.interface is None or args.image is None):
        parser.fixed_error("--apply requires --interface and IMAGE")
    return args


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv
    args = parse_options(argv)
    if not args.apply:
        print("DRY RUN: no files or sockets opened and no settings changed; "
              "use --apply with --interface and IMAGE.")
        return 0
    try:
        return run_flash(args)
    except KeyboardInterrupt:
        print("error: operation interrupted; no DTMF or transfer is replayed",
              file=sys.stderr)
        return 1
    except (FlashError, dhcp.DhcpError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except Exception:
        print("error: ATA flash service failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
