#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""Bounded operator-in-the-loop ATA reset planner and runner.

Achieves a device reboot through the only device-triggered remote path in
the pinned SIP 3.1.0 image: the profile pipeline.  A deliberately
reversible one-knob profile change trips ``cfgNeedReboot`` when the device
fetches the profile from TFTP; the original profile is then re-served so
the next fetch restores the exact stored state.  The flash config is the
persistent store, so nothing is lost when the collected baseline agrees
with the source profile.

Subcommands (always dry and offline unless ``--apply`` is also given):
  collect   GET the device's machine config view (read-only HTTP) to the
            private work directory and record its SHA-256.
  prepare   copy the pinned text profile, flip one reversible knob, and
            compile both the tripped and the revert profiles with the
            published ``cfgfmt.py`` converter.
  serve     run the proven TFTP pumpkin server for a bounded window on
            the prepared (or, with ``--revert``, the original) profile.
  verify    refetch the machine config view and compare with the
            collected baseline; ambiguous state is a stop condition.

Every step is deterministic and idempotent-by-regeneration.  Device
identity material stays in the private work directory, never in this
repository.  Bare invocation is inert; ``--apply`` is required for any
network or device-facing effect.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import os
import shutil
import stat
import subprocess
import sys


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
CFGFMT = os.path.join(REPO_ROOT, "refactor", "cfgfmt.py")
TFTP_TOOL = os.path.join(REPO_ROOT, "telephony", "tftp_profile.py")

DEVICE_HTTP_HOST = "192.168.2.10"
DEVICE_HTTP_PORT = 80
BENCH_HOST = "192.168.2.2"
OTA_PORT = 69
MAX_CONFIG_BYTES = 128 * 1024
DEFAULT_RUN_SECONDS = 300
MIN_RUN_SECONDS = 10
MAX_RUN_SECONDS = 4000
KNOB_NAME = "AltGkTimeOut"          # benign, service-idle on the bench
KNOB_TRIP_VALUE = 1
KNOB_RESTORE_VALUE = 0


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, f"error: {message}\n")


def fail(message: str) -> "NoReturn":  # type: ignore[valid-type]
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def private_dir(path: str) -> str:
    """Create (or validate) a 0700 work directory."""
    if os.path.exists(path):
        mode = stat.S_IMODE(os.stat(path).st_mode)
        if not os.path.isdir(path) or mode & 0o077:
            fail(f"work directory must be private: {path}")
        return path
    os.makedirs(path, mode=0o700)
    return path


def publish_private(path: str, content: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_CLOEXEC,
                 0o600)
    try:
        os.write(fd, content)
    finally:
        os.close(fd)


def parse_profile_lines(text: str) -> list[str]:
    return text.splitlines()


def render_toggled_profile(lines: list[str], knob: str, value: str,
                           header: bool = False) -> bytes:
    out = []
    changed = 0
    for line in lines:
        if line.split(":", 1)[0].strip() == knob:
            out.append(f"{knob}:{value}")
            changed += 1
        else:
            out.append(line)
    if changed != 1:
        raise ValueError(f"knob {knob!r} appears {changed} times, expected 1")
    if header:
        out = ["#txt"] + out
    return ("\n".join(out) + "\n").encode("latin-1")


def read_profile_lines(path: str) -> list[str]:
    with open(path, "rb") as fh:
        raw = fh.read(256 * 1024 + 1)
    if len(raw) > 256 * 1024:
        fail(f"{path} exceeds the 256 KiB bounded profile size")
    text = raw.decode("latin-1")
    if not text.startswith("#txt") and not text.splitlines()[0].strip() \
            .replace(":", "").isalnum():
        fail(f"{path} is neither a #txt profile nor a key:value list")
    return text.splitlines()


def find_value(lines: list[str], knob: str) -> str | None:
    for line in lines:
        if line.split(":", 1)[0].strip() == knob:
            return line.split(":", 1)[1].strip()
    return None


def http_get_text(host: str, path: str, seconds: int) -> bytes:
    conn = http.client.HTTPConnection(host, DEVICE_HTTP_PORT,
                                      timeout=seconds)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        if resp.status != 200:
            fail(f"HTTP {resp.status} from {host}{path}")
        return resp.read(MAX_CONFIG_BYTES + 1)
    except OSError as exc:
        fail(f"cannot reach {host}:{DEVICE_HTTP_PORT} ({exc!r}); the bench "
             "pair must be up and the device powered - check the host owns "
             "its bench IPv4 and the device is cabled; run the read-only "
             "gate from TODO.md before retrying")
    finally:
        conn.close()


def run_checked(argv: list[str]) -> None:
    print("+", " ".join(argv), flush=True)
    result = subprocess.run(argv, cwd=REPO_ROOT)
    if result.returncode != 0:
        fail(f"command failed: {' '.join(argv)}")


def locate_ptag(explicit: str) -> str:
    if explicit:
        return explicit
    for candidate in (os.path.join(REPO_ROOT, "vendor", "ptag.dat"),
                      os.path.join(REPO_ROOT, "ata_03_01_00_sip_040211_1",
                                   "ptag.dat")):
        if os.path.isfile(candidate):
            return candidate
    fail("ptag.dat not found; pass --ptag (supplied with the exact "
         "firmware release)")


def cfgfmt_compile(profile_txt: str, out_bin: str, ptag: str) -> None:
    ptag = locate_ptag(ptag)
    run_checked([sys.executable, CFGFMT, "-t" + ptag, "-sip",
                 profile_txt, out_bin])


def cmd_collect(args: argparse.Namespace) -> int:
    private_dir(args.work)
    out = os.path.join(args.work, "dev.xml")
    body = http_get_text(args.device, "/dev.xml", args.timeout)
    if len(body) > MAX_CONFIG_BYTES:
        fail("machine config view exceeds the bounded size")
    publish_private(out, body)
    digest = hashlib.sha256(body).hexdigest()
    state = os.path.join(args.work, "baseline.sha256")
    publish_private(state, f"{digest}  dev.xml\n".encode())
    print(f"collected {len(body)} bytes; sha256={digest}; saved to {out}")
    return 0


def cmd_prepare(args: argparse.Namespace) -> int:
    private_dir(args.work)
    # the converter never replaces an existing output; clear only the
    # derived artifacts (never the collected baseline/dev view)
    if args.fresh:
        for name in ("profile_trip.txt", "profile_revert.txt",
                     "profile_trip.bin", "profile_revert.bin"):
            path = os.path.join(args.work, name)
            if os.path.exists(path):
                os.unlink(path)
    existing = os.path.join(args.work, "profile_trip.bin")
    if os.path.exists(existing) and not args.fresh:
        fail(f"{existing} already exists and the converter never replaces "
             f"outputs; rerun with --fresh (clears only the derived "
             f"profiles, never the collected baseline)")
    lines = read_profile_lines(args.profile)
    current = find_value(lines, KNOB_NAME)
    if current is None:
        fail(f"profile lacks the {KNOB_NAME} knob")
    # tripped profile: flip the knob; revert profile: the untouched original
    trip_txt = os.path.join(args.work, "profile_trip.txt")
    revert_txt = os.path.join(args.work, "profile_revert.txt")
    trip_bin = os.path.join(args.work, "profile_trip.bin")
    revert_bin = os.path.join(args.work, "profile_revert.bin")
    trip_value = KNOB_TRIP_VALUE if current != str(KNOB_TRIP_VALUE) \
        else KNOB_RESTORE_VALUE
    body = ("#txt\n" + "\n".join(lines) + "\n").encode("latin-1")
    publish_private(trip_txt, render_toggled_profile(lines, KNOB_NAME,
                                                     str(trip_value), True))
    publish_private(revert_txt, body)
    print(f"knob {KNOB_NAME}: {current} -> {trip_value}")
    cfgfmt_compile(trip_txt, trip_bin, args.ptag)
    cfgfmt_compile(revert_txt, revert_bin, args.ptag)
    for path in (trip_txt, revert_txt, trip_bin, revert_bin):
        os.chmod(path, 0o600)
    print(f"prepared {trip_bin} (trips reset) and {revert_bin} (restores)")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    if not args.apply:
        which = "profile_trip.bin" if not args.revert else "profile_revert.bin"
        plan = [sys.executable, TFTP_TOOL, "--apply",
                "--address", args.address,
                "--expected-client", args.client,
                "--run-seconds", str(args.run_seconds),
                "--profile", os.path.join(args.work, which)]
        print("DRY RUN:", " ".join(plan))
        return 0
    which = "profile_trip.bin" if not args.revert else "profile_revert.bin"
    profile = os.path.join(args.work, which)
    if not os.path.isfile(profile):
        fail(f"missing {profile}; run prepare first")
    run_checked([sys.executable, TFTP_TOOL, "--apply",
                 "--address", args.address,
                 "--expected-client", args.client,
                 "--run-seconds", str(args.run_seconds),
                 "--profile", profile])
    return 0


def cmd_dhcp(args: argparse.Namespace) -> int:
    """Keep the lease answer up: REQUIRED across the reset window.

    After a profile-driven reset the ATA immediately re-DHCPs; without a
    live responder it drops off the bench (the blinking state).  Run this
    BEFORE the trip serve, with a capture deadline long enough to span the
    reset; it offers one lease (options 66/150 -> this bench address) and
    exits once the device ACKs.
    """
    if not args.apply:
        print("DRY RUN: dhcp.RunDhcp on", repr(args.interface),
              "-> client", args.client, "lease", args.lease_seconds,
              "capture deadline", args.dhcp_seconds)
        return 0
    if not args.interface:
        fail("--interface is required with --apply")
    import dhcp as dhcp_module

    args_ns = dhcp_module.parse_options([
        "dhcp.py", "--apply", "--interface", args.interface,
        "--client-address", args.client,
        "--lease-seconds", str(args.lease_seconds),
        "--timeout-seconds", str(args.dhcp_seconds)])
    try:
        config = dhcp_module._config_from_args(args_ns)
    except dhcp_module.DhcpError as exc:
        fail(str(exc))
    print(f"dhcp: offering {config.client_address} on {config.interface} "
          f"for up to {config.timeout_seconds}s", flush=True)
    try:
        lease = dhcp_module.run_dhcp(config)
    except dhcp_module.DhcpError as exc:
        fail(f"DHCP capture ended: {exc}")
    print(f"dhcp: ACK'd {dhcp_module.format_mac(lease.client_mac)} "
          f"-> {lease.client_address}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    baseline_path = os.path.join(args.work, "baseline.sha256")
    if not os.path.isfile(baseline_path):
        fail("no baseline; run collect first")
    with open(baseline_path) as fh:
        expected = fh.read().split()[0]
    body = http_get_text(args.device, "/dev.xml", args.timeout)
    digest = hashlib.sha256(body).hexdigest()
    if digest == expected:
        print("verify: device config is byte-identical to the baseline")
        return 0
    out = os.path.join(args.work, "dev.xml.changed")
    publish_private(out, body)
    print(f"verify: MISMATCH sha256={digest} (baseline {expected}); "
          f"new view saved to {out}; AMBIGUOUS STATE - restore via "
          f"'--serve --revert --apply' and re-verify; do not retry blind")
    return 1


def cmd_status(args: argparse.Namespace) -> int:
    """Read-only rehearsal: print the full plan without any device I/O."""
    print("plan (dry):")
    print(f"  0 dhcp    : keep the lease answer up across the reset "
          f"(run FIRST; the device re-DHCPs after reset or it drops off)")
    print(f"  collect  : GET http://{args.device}/dev.xml -> {args.work}")
    print(f"  prepare  : flip {KNOB_NAME} in {args.profile}, "
          "compile trip + revert profiles")
    print(f"  serve    : tftp_profile --apply {args.address}:{OTA_PORT} "
          f"for {args.run_seconds}s (trip profile)")
    print(f"  serve -r : same but the revert profile, after the reset")
    print(f"  verify   : re-GET /dev.xml; expect identical to baseline")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = SafeArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add(p: argparse.ArgumentParser) -> None:
        p.add_argument("--work", default=os.path.join(REPO_ROOT, "work",
                                                      "reboot"),
                       help="private output directory (0700)")
        p.add_argument("--profile", default=os.path.join(
            REPO_ROOT, "telephony", "ata00070e36e57b.txt"),
            help="pinned text profile (source of truth)")
        p.add_argument("--device", default=DEVICE_HTTP_HOST,
            help="device IPv4 for the machine config view")
        p.add_argument("--address", default=BENCH_HOST,
            help="bench IPv4 the TFTP server binds")
        p.add_argument("--client", default=DEVICE_HTTP_HOST,
            help="expected TFTP client IPv4")
        p.add_argument("--run-seconds", type=int,
                       default=DEFAULT_RUN_SECONDS)
        p.add_argument("--timeout", type=int, default=5,
                       help="HTTP timeout seconds")
        p.add_argument("--ptag", default="",
                       help="parameter-description file for cfgfmt "
                            "(default: vendor/ptag.dat, else the pinned "
                            "release artifact dir)")
        p.add_argument("--apply", action="store_true",
                       help="execute device-facing effects; default dry")

    for name, fn in (("status", cmd_status), ("collect", cmd_collect),
                     ("prepare", cmd_prepare), ("serve", cmd_serve),
                     ("dhcp", cmd_dhcp), ("verify", cmd_verify)):
        p = sub.add_parser(name)
        add(p)
        if name == "prepare":
            p.add_argument("--fresh", action="store_true",
                           help="clear previously prepared profile "
                                "artifacts first (never the baseline)")
        if name == "dhcp":
            p.add_argument("--interface", help="bench Ethernet interface "
                                              "(required with --apply)")
            p.add_argument("--lease-seconds", type=int, default=600,
                           help="lease duration to offer (default 600)")
            p.add_argument("--dhcp-seconds", type=int, default=1800,
                           help="capture deadline; must span the reset "
                                "(default 1800)")
        if name == "serve":
            p.add_argument("--revert", action="store_true",
                           help="serve the original profile (post-reset)")
        p.set_defaults(fn=fn)

    args = parser.parse_args(argv)
    if args.run_seconds < MIN_RUN_SECONDS or args.run_seconds > MAX_RUN_SECONDS:
        fail("run-seconds outside the bounded range")
    if not args.apply and args.cmd != "status":
        print("DRY RUN: add --apply for device-facing effects")
    return args.fn(args)


if __name__ == "__main__":
    os.umask(0o077)
    raise SystemExit(main())
