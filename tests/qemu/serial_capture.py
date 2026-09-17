#!/usr/bin/env python3
"""Persistently capture a loopback QEMU serial TCP console to a log file."""
import argparse
import socket
import sys
import time

parser = argparse.ArgumentParser()
parser.add_argument("--port", type=int, required=True)
parser.add_argument("--log", required=True)
args = parser.parse_args()
start = time.time()
while time.time() - start < 3600:
    try:
        sock = socket.create_connection(("127.0.0.1", args.port), timeout=5)
    except OSError:
        time.sleep(1)
        continue
    with open(args.log, "ab") as handle:
        sock.settimeout(5)
        try:
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                handle.write(chunk)
                handle.flush()
        except OSError:
            pass
    sock.close()
    break
