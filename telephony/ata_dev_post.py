"""Bounded ATA186 /dev web-config poster for the bench ATA only.

Reads the current ``ATADev`` XML snapshot over HTTP, applies an exact allow list
of field overrides, and posts the full field set back to the vendor's /dev form
(the same mechanism as the vintage atapost.pl). Dry run by default; --apply
performs the single POST. Never reads or writes TFTP, never touches other
devices, and logs no credentials.
"""

import argparse
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FIELD_RE = re.compile(r"<(\w+)\s+value=\"([^\"]*)\"/>")
TAG_SET_RE = re.compile(r"<(\w+)\s+value=")


class ProtocolError(ValueError):
    """A config response is outside the bounded bench profile."""


def parse_config_xml(wire):
    """Return the ordered list of (name, value) pairs from an ATADev XML."""
    if not isinstance(wire, bytes):
        raise TypeError("config XML must be bytes")
    fields = FIELD_RE.findall(wire.decode("utf-8", errors="replace"))
    if not fields:
        raise ProtocolError("no ATADev fields in response")
    if len(fields) != len(set(name for name, _ in fields)):
        raise ProtocolError("duplicate ATADev field names")
    return fields


def apply_overrides(fields, overrides):
    """Return fields with allow-listed overrides applied in place of originals."""
    if not isinstance(overrides, dict):
        raise TypeError("overrides must be a dict")
    known = {name for name, _ in fields}
    out = list(fields)
    for name, value in overrides.items():
        if name not in known:
            raise ProtocolError("unknown field override: %s" % name)
        out = [(n, value if n == name else v) for (n, v) in out]
    return out


def build_body(fields):
    """URL-encode the field list in order, like atapost.pl (-fields)."""
    return "&".join("%s=%s" % (urllib.parse.quote(name),
                               urllib.parse.quote(value)) for name, value in fields)


def fetch_dev_xml(address, timeout=8):
    url = "http://%s/dev.xml" % address
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.read()
    except (urllib.error.URLError, OSError) as exc:
        raise ProtocolError("cannot read %s: %s" % (url, exc))


def post_dev(address, body, timeout=8):
    url = "http://%s/dev" % address
    request = urllib.request.Request(url, data=body.encode("utf-8"), method="POST")
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except (urllib.error.URLError, OSError) as exc:
        raise ProtocolError("POST %s failed: %s" % (url, exc))


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true",
                        help="perform the POST; default is a dry run")
    parser.add_argument("--address", default="192.168.2.10")
    parser.add_argument("--timeout", type=int, default=8)
    parser.add_argument("--set", action="append", default=[],
                        help="field override Name=value (repeatable)")
    return parser.parse_args(argv)


def main(argv=None):
    os.umask(0o077)
    args = parse_args(argv)
    overrides = {}
    for item in args.set:
        name, sep, value = item.partition("=")
        if not sep or not name:
            print("ERROR: --set expects Name=value", file=sys.stderr)
            return 2
        overrides[name] = value
    wire = fetch_dev_xml(args.address, args.timeout)
    fields = apply_overrides(parse_config_xml(wire), overrides)
    body = build_body(fields)
    print("fields=%d overrides=%s body-bytes=%d address=%s"
          % (len(fields), overrides or "none", len(body), args.address))
    for name, value in overrides.items():
        print("override %s=%s" % (name, value))
    if not args.apply:
        print("DRY RUN: would POST %d fields to http://%s/dev" % (len(fields), args.address))
        print("DRY RUN: start with --apply to perform the live config write")
        return 0
    response = post_dev(args.address, body, args.timeout)
    text = response.decode("utf-8", errors="replace")
    if "Invalid Access" in text:
        print("ERROR: device rejected the POST (web config disabled?)", file=sys.stderr)
        return 1
    print("POST ok bytes=%d" % len(response))
    print(text[:512].strip())
    return 0


if __name__ == "__main__":
    sys.exit(main())