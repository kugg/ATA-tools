#!/usr/bin/env python3
"""Bounded UDP syslog receiver for the office SPA (project-owned).

Listens on 0.0.0.0:514, appends timestamped lines to /var/log/ata-syslog.log
and rotates once past ~1 MB. No egress, no parsing beyond decode.
"""
import os
import socket
import time

LOG = "/var/log/ata-syslog.log"
MAX_BYTES = 1000000


def rotate():
    try:
        if os.path.exists(LOG) and os.path.getsize(LOG) > MAX_BYTES:
            os.replace(LOG, LOG + ".1")
    except OSError:
        pass


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", 514))
    rotate()
    with open(LOG, "ab", buffering=0) as out:
        while True:
            data, addr = sock.recvfrom(4096)
            stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
            text = data.decode("utf-8", "replace").strip()
            out.write(("%s %s %s\n" % (stamp, addr[0], text)).encode())


if __name__ == "__main__":
    main()
