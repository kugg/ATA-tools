#!/usr/bin/env python3
"""Temporary direct-bench DHCP for a directly attached ATA."""

from __future__ import annotations

import argparse
from importlib import import_module
import ipaddress
import json
import re
import sys

DEFAULT_TIMEOUT_SECONDS = 600
MAX_TIMEOUT_SECONDS = 24 * 60 * 60
DEFAULT_LEASE_SECONDS = 600
MAX_PACKET_BYTES = 1024
MAX_DHCP_OPTIONS = 64
MAX_DHCP_OPTION_BYTES = 512
DHCP_COOKIE = b"\x63\x82\x53\x63"
INTERFACE_PATTERN = re.compile(r"[A-Za-z0-9_.-]{1,64}\Z")


class DhcpError(RuntimeError):
    """A fixed, operator-actionable DHCP failure."""


class DhcpConfig:
    __slots__ = (
        "interface", "server_address", "client_address", "subnet_mask",
        "server_bytes", "client_bytes", "expected_client_mac",
        "lease_seconds", "timeout_seconds",
    )

    def __init__(self, interface: str, server_address: str, client_address: str,
                 subnet_mask: str, expected_client_mac: bytes | None = None,
                 lease_seconds: int = DEFAULT_LEASE_SECONDS,
                 timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS):
        if not INTERFACE_PATTERN.fullmatch(interface):
            raise ValueError("DHCP interface name is invalid")
        try:
            server = ipaddress.IPv4Address(server_address)
            client = ipaddress.IPv4Address(client_address)
            network = ipaddress.IPv4Network(
                f"{server}/{subnet_mask}", strict=False)
        except ValueError as error:
            raise ValueError("DHCP address configuration is invalid") from error
        if server not in network or client not in network or server == client:
            raise ValueError("DHCP server and client addresses are incompatible")
        if network.prefixlen <= 30 and client in (
                network.network_address, network.broadcast_address):
            raise ValueError("DHCP client address is not a usable host address")
        if expected_client_mac is not None \
                and not _valid_client_mac(expected_client_mac):
            raise ValueError("DHCP client MAC is invalid")
        if not 1 <= lease_seconds <= 0xFFFFFFFF:
            raise ValueError("DHCP lease duration is invalid")
        if not 1 <= timeout_seconds <= MAX_TIMEOUT_SECONDS:
            raise ValueError("DHCP timeout is invalid")
        self.interface = interface
        self.server_address = str(server)
        self.client_address = str(client)
        self.subnet_mask = str(network.netmask)
        self.server_bytes = server.packed
        self.client_bytes = client.packed
        self.expected_client_mac = expected_client_mac
        self.lease_seconds = lease_seconds
        self.timeout_seconds = timeout_seconds


class DhcpLease:
    __slots__ = ("client_address", "client_mac")

    def __init__(self, client_address: str, client_mac: bytes):
        self.client_address = client_address
        self.client_mac = client_mac


class SafeArgumentParser(argparse.ArgumentParser):
    """Keep parser diagnostics from reflecting arbitrary argument values."""

    def error(self, _message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, "error: invalid arguments\n")

    def fixed_error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, f"error: {message}\n")


def _valid_client_mac(value: bytes) -> bool:
    return (isinstance(value, bytes) and len(value) == 6
            and value != b"\x00" * 6 and not value[0] & 1)


def parse_mac(value: str) -> bytes:
    parts = value.split(":")
    if len(parts) != 6 or any(len(part) != 2 for part in parts):
        raise ValueError("client MAC must contain six hexadecimal octets")
    try:
        parsed = bytes(int(part, 16) for part in parts)
    except ValueError as error:
        raise ValueError("client MAC must contain six hexadecimal octets") from error
    if not _valid_client_mac(parsed):
        raise ValueError("client MAC must be a unicast hardware address")
    return parsed


def format_mac(value: bytes) -> str:
    return ":".join(f"{byte:02x}" for byte in value)


def parse_request(raw, config: DhcpConfig):
    """Return the minimal safe DHCP request fields, or None for any other frame."""
    if not isinstance(raw, (bytes, bytearray)) or not 286 <= len(raw) <= MAX_PACKET_BYTES:
        return None
    source_mac = bytes(raw[6:12])
    if not _valid_client_mac(source_mac) or raw[12:14] != b"\x08\x00":
        return None
    if config.expected_client_mac is not None \
            and source_mac != config.expected_client_mac:
        return None

    ip_offset = 14
    version_ihl = raw[ip_offset]
    ihl = (version_ihl & 0x0F) * 4
    if version_ihl >> 4 != 4 or ihl < 20 or ip_offset + ihl > len(raw):
        return None
    total_length = int.from_bytes(raw[ip_offset + 2:ip_offset + 4], "big")
    ip_end = ip_offset + total_length
    fragments = int.from_bytes(raw[ip_offset + 6:ip_offset + 8], "big")
    if total_length < ihl + 8 + 240 or ip_end > len(raw) or fragments & 0x3FFF:
        return None
    if raw[ip_offset + 9] != 17:
        return None

    udp_offset = ip_offset + ihl
    udp_length = int.from_bytes(raw[udp_offset + 4:udp_offset + 6], "big")
    udp_end = udp_offset + udp_length
    if (raw[udp_offset:udp_offset + 2], raw[udp_offset + 2:udp_offset + 4]) != (b"\x00D", b"\x00C"):
        return None
    if udp_length < 248 or udp_end != ip_end:
        return None

    bootp_offset = udp_offset + 8
    if raw[bootp_offset:bootp_offset + 4] != b"\x01\x01\x06\x00":
        return None
    if raw[bootp_offset + 24:bootp_offset + 28] != b"\0" * 4:
        return None
    chaddr = bytes(raw[bootp_offset + 28:bootp_offset + 44])
    if chaddr[:6] != source_mac:
        return None
    if raw[bootp_offset + 236:bootp_offset + 240] != DHCP_COOKIE:
        return None

    message_type = None
    requested_address = None
    server_id = None
    options = raw[bootp_offset + 240:udp_end]
    if len(options) > MAX_DHCP_OPTION_BYTES:
        return None
    index = 0
    option_count = 0
    ended = False
    while index < len(options):
        code = options[index]
        index += 1
        if code == 0:
            continue
        if code == 255:
            ended = True
            break
        if index >= len(options):
            return None
        size = options[index]
        index += 1
        if size > len(options) - index:
            return None
        value = options[index:index + size]
        index += size
        option_count += 1
        if option_count > MAX_DHCP_OPTIONS:
            return None
        if code == 53:
            if size != 1 or message_type is not None:
                return None
            message_type = value[0]
        elif code == 50:
            if size != 4 or requested_address is not None:
                return None
            requested_address = bytes(value)
        elif code == 52:
            return None
        elif code == 54:
            if size != 4 or server_id is not None:
                return None
            server_id = bytes(value)

    if not ended or message_type not in (1, 3):
        return None
    if message_type == 1 and server_id not in (None, config.server_bytes):
        return None
    if message_type == 3:
        if requested_address is None:
            requested_address = bytes(raw[bootp_offset + 12:bootp_offset + 16])
        if requested_address != config.client_bytes \
                or server_id not in (None, config.server_bytes):
            return None
    xid = int.from_bytes(raw[bootp_offset + 4:bootp_offset + 8], "big")
    return message_type, xid, chaddr


def run_dhcp(config: DhcpConfig, *, scapy_module=None, address_check=None,
             logger=None) -> DhcpLease:
    """Offer one lease and return only after that same client receives an ACK."""
    if scapy_module is None:
        try:
            scapy_module = import_module("scapy.all")
        except ImportError as error:
            raise DhcpError("Scapy is unavailable; no DHCP socket was opened") from error
    scapy = scapy_module
    BOOTP = scapy.BOOTP
    DHCP = scapy.DHCP
    Ether = scapy.Ether
    IP = scapy.IP
    UDP = scapy.UDP
    get_if_hwaddr = scapy.get_if_hwaddr
    sendp = scapy.sendp
    sniff = scapy.sniff

    if logger is None:
        logger = lambda message: print(message, flush=True)
    if address_check is None:
        address_check = (
            lambda: scapy.get_if_addr(config.interface) == config.server_address)
    try:
        address_ok = bool(address_check())
        server_mac = format_mac(parse_mac(get_if_hwaddr(config.interface)))
    except Exception as error:
        raise DhcpError("cannot inspect the selected DHCP interface") from error
    if not address_ok:
        raise DhcpError("the selected interface address is no longer present")

    logger(f"DHCP ready on {config.interface}: offering "
           f"{config.client_address}; no gateway or DNS; "
           f"TFTP server {config.server_address}")
    client_mac = config.expected_client_mac
    offered_xid = None
    acknowledged = False
    interface_changed = False
    reply_failed = False

    def respond(packet):
        nonlocal client_mac, offered_xid, acknowledged, interface_changed, reply_failed
        parsed = parse_request(getattr(packet, "original", b""), config)
        if parsed is None:
            return
        kind, xid, chaddr = parsed
        if client_mac is not None and chaddr[:6] != client_mac:
            return
        if kind == 3:
            if offered_xid is not None and xid != offered_xid:
                return
            if offered_xid is None and config.expected_client_mac is None:
                return
        try:
            address_ok = bool(address_check())
        except Exception:
            address_ok = False
        if not address_ok:
            interface_changed = True
            logger("DHCP stopped because the selected interface address changed")
            return
        client_mac = chaddr[:6]
        if kind == 1:
            offered_xid = xid
        reply = (Ether(src=server_mac, dst="ff:ff:ff:ff:ff:ff")
                 / IP(src=config.server_address, dst="255.255.255.255")
                 / UDP(sport=67, dport=68)
                 / BOOTP(op=2, htype=1, hlen=6, xid=xid, flags=0x8000,
                         yiaddr=config.client_address,
                         siaddr=config.server_address, chaddr=chaddr)
                 / DHCP(options=[("message-type", 2 if kind == 1 else 5),
                                  ("server_id", config.server_address),
("subnet_mask", config.subnet_mask),
                                 ("lease_time", config.lease_seconds),
                                 ("tftp_server_name", config.server_address),
                                 ("tftp_server_address", config.server_address),
                                 "end"]))
        try:
            sendp(reply, iface=config.interface, promisc=False, verbose=False)
        except Exception:
            reply_failed = True
            logger("DHCP reply failed; no retry will be started automatically")
            return
        event = {
            "client_mac": format_mac(client_mac),
            "ip": config.client_address,
            "response": "OFFER" if kind == 1 else "ACK",
        }
        logger(json.dumps(event, separators=(",", ":"), sort_keys=True))
        if kind == 3:
            acknowledged = True

    # BPF capture and layer-2 replies coexist with launchd's reserved UDP port.
    try:
        sniff(iface=config.interface,
              filter="udp src port 68 and udp dst port 67 and greater 285 and less 1025",
              prn=respond, store=False, promisc=False,
              timeout=config.timeout_seconds,
              stop_filter=lambda _: acknowledged or interface_changed or reply_failed)
    except KeyboardInterrupt:
        raise
    except Exception as error:
        raise DhcpError(
            "DHCP capture could not start; no privilege change was attempted") from error
    if interface_changed:
        raise DhcpError("the selected interface address changed during DHCP")
    if reply_failed:
        raise DhcpError("the DHCP reply could not be sent")
    if not acknowledged or client_mac is None:
        raise DhcpError("DHCP timed out before the selected client received an ACK")
    return DhcpLease(config.client_address, client_mac)


def parse_options(argv: list[str]) -> argparse.Namespace:
    parser = SafeArgumentParser(prog="dhcp.py", description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="offer one DHCP lease on the selected interface")
    parser.add_argument("--interface", metavar="NAME",
                        help="existing Ethernet interface used for DHCP")
    parser.add_argument("--client-address", metavar="ADDRESS",
                        help="address to offer; default is host 10 in "
                             "the interface /24")
    parser.add_argument("--client-mac", metavar="MAC",
                        help="optional DHCP client MAC; otherwise lock "
                             "the first client")
    parser.add_argument("--lease-seconds", type=int, metavar="SECONDS",
                        default=DEFAULT_LEASE_SECONDS,
                        help=f"lease duration to offer (default: "
                             f"{DEFAULT_LEASE_SECONDS})")
    parser.add_argument("--timeout-seconds", type=int, metavar="SECONDS",
                        default=DEFAULT_TIMEOUT_SECONDS,
                        help=f"capture deadline (default: "
                             f"{DEFAULT_TIMEOUT_SECONDS})")
    args = parser.parse_args(argv[1:])
    if args.apply and args.interface is None:
        parser.fixed_error("--apply requires --interface")
    return args


def _config_from_args(args: argparse.Namespace) -> DhcpConfig:
    try:
        scapy = import_module("scapy.all")
    except ImportError as error:
        raise DhcpError("Scapy is unavailable; no DHCP socket was opened") from error
    try:
        server_address = scapy.get_if_addr(args.interface)
        server = ipaddress.IPv4Address(server_address)
    except Exception as error:
        raise DhcpError("cannot resolve the selected DHCP interface") from error
    if server.is_unspecified:
        raise DhcpError(
            f"interface {args.interface} has no assigned IPv4 address")
    network = ipaddress.IPv4Network(f"{server}/24", strict=False)
    client_address = args.client_address or str(network.network_address + 10)
    expected_mac = None
    if args.client_mac is not None:
        try:
            expected_mac = parse_mac(args.client_mac)
        except ValueError as error:
            raise DhcpError(str(error)) from error
    try:
        return DhcpConfig(
            args.interface, str(server), client_address, str(network.netmask),
            expected_mac, lease_seconds=args.lease_seconds,
            timeout_seconds=args.timeout_seconds)
    except ValueError as error:
        raise DhcpError(str(error)) from error


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv
    args = parse_options(argv)
    if not args.apply:
        print("DRY RUN: no sockets opened. Re-run with --apply and "
              "--interface to offer one DHCP lease.")
        return 0
    try:
        run_dhcp(_config_from_args(args))
    except DhcpError as error:
        print(f"dhcp.py: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
