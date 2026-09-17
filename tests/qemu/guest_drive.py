#!/usr/bin/env python3
"""Bounded serial-console driver for a QEMU OpenWrt guest.

Connects to a loopback-only QEMU serial TCP console, waits for the shell
prompt, sends a short list of commands (each under 100 chars, prompt-synced —
the emulated 8250 drops bytes on long pastes), captures output to a log, and
exits nonzero if a command's marker is not observed.

Usage:
  guest_drive.py --port N --expect-marker ok --timeout 120 -- cmd1 -- cmd2

Markers: every command is echoed and must produce its marker line
("MMARK N ok") within the timeout; output is capped.
"""

import argparse
import re
import socket
import sys
import time

PROMPT = "D0NE# "
MAX_LINE = 96
MAX_OUTPUT_BYTES = 1024 * 1024


def _log(message):
    print("guest-drive %s" % message, file=sys.stderr, flush=True)


def read_until(sock, patterns, deadline):
    buf = b""
    while time.time() < deadline and not any(p in buf for p in patterns):
        sock.settimeout(max(0.5, deadline - time.time()))
        try:
            chunk = sock.recv(4096)
        except socket.timeout:
            continue
        except OSError as exc:
            _log("serial socket error: %s" % exc)
            break
        if not chunk:
            break
        buf += chunk
        if len(buf) > MAX_OUTPUT_BYTES:
            buf = buf[-4096:]
    return buf


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--command", action="append", required=True,
                        help="command to run in the guest (repeatable)")
    parser.add_argument("--boot-wait", type=float, default=60,
                        help="seconds to wait for the shell prompt")
    args = parser.parse_args(argv)

    for command in args.command:
        if len(command) > MAX_LINE:
            _log("refusing long command (%d chars): %s..."
                 % (len(command), command[:40]))
            return 2

    start = time.time()
    deadline = start + args.boot_wait + args.timeout * len(args.command)
    sock = socket.create_connection((args.host, args.port), timeout=10)
    boot_deadline = time.time() + args.boot_wait
    read_until(sock, [b"OpenWrt", PROMPT.encode()], boot_deadline)
    # poke to get a prompt
    sock.sendall(b"\n")
    read_until(sock, [PROMPT.encode()], time.time() + 10)
    sock.sendall(b"export PS1='" + PROMPT[0:-2].encode() + b" '\n")
    read_until(sock, [PROMPT.encode()], time.time() + 10)

    failures = []
    for index, command in enumerate(args.command):
        marker = "MMARK%d" % index
        line = "%s; echo %s-$?" % (command, marker)
        sock.sendall(line.encode() + b"\n")
        expected = [("%s-%d" % (marker, code)).encode()
                    for code in range(256)]
        output = read_until(sock, expected, time.time() + args.timeout)
        match = re.search((r"%s-(\d+)" % marker).encode(), output)
        if not match:
            failures.append((index, command, "no marker"))
            _log("FAIL cmd=%s no marker; tail=%r" % (command, output[-200:]))
        else:
            code = int(match.group(1))
            if code == 0:
                _log("ok  cmd=%s" % command)
            else:
                failures.append((index, command, "exit %d" % code))
                _log("FAIL cmd=%s exit=%d; tail=%r"
                     % (command, code, output[-200:]))
    sock.close()
    if failures:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
