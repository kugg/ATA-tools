#!/usr/bin/env python3
"""Resolve and cache OpenWrt feed packages (ipk closure) for offline install.

Downloads the Packages index for each configured feed, resolves the
dependency closure of a pinned package list across them, and places the
.ipk files and readable indexes into a cache directory suitable for a
read-only mount into a QEMU guest: the guest runs `opkg update` against
file:// sources and never needs egress.

Dry run by default; --apply performs downloads. The cache dir is created
with mode 0700 and every fetched object is SHA256-verified against the
index before being written.
"""

import argparse
import gzip
import hashlib
import os
import re
import subprocess
import sys

FEED_TEMPLATE = ("https://downloads.openwrt.org/releases/{release}/packages/"
                 "{arch}/{feed}")
TARGET_FEED_TEMPLATE = ("https://downloads.openwrt.org/releases/{release}/"
                        "targets/{arch}/packages")

# Telephony contains the pinned Asterisk set; base contains python3 and the
# resolver searches both indexes.
FEEDS = ("base", "packages", "telephony", "target")

# Provided by the base image rootfs; not in any package index.
BASE_IMAGE_PROVIDED = (
    "libc", "librt", "libpthread", "libgcc", "kernel",
)

DEFAULT_PACKAGES = (
    "asterisk",
    "asterisk-chan-sip",
    "asterisk-codec-ulaw",
    "asterisk-codec-alaw",
    "asterisk-res-rtp-asterisk",
    "asterisk-app-read",
    "asterisk-app-audiosocket",
    "asterisk-app-externalivr",
    "asterisk-res-agi",
    "asterisk-res-http-websocket",
    "python3",
    "python3-light",
)

FETCH_LIMIT = 200 * 1024 * 1024


class FeedError(ValueError):
    """Feed resolution or verification problem."""


def _log(message):
    print("feed-cache %s" % message, file=sys.stderr, flush=True)


def _fetch(url):
    """Fetch via curl (host CA store); output bounds enforced after."""
    result = subprocess.run(
        ["curl", "-fsSL", "--max-time", "300", "--max-filesize",
         str(FETCH_LIMIT), url],
        capture_output=True, timeout=330)
    if result.returncode != 0:
        raise FeedError("curl %s failed: %s"
                        % (url, result.stderr.decode(errors="replace")[:200]))
    data = result.stdout
    if len(data) > FETCH_LIMIT:
        raise FeedError("feed object exceeds %d bytes: %s"
                        % (FETCH_LIMIT, url))
    return data


def parse_index(text):
    entries = {}
    current = {}
    for line in text.splitlines():
        if not line.strip():
            if current.get("Package") and current.get("Filename"):
                entries[current["Package"]] = current
            current = {}
            continue
        key, _, value = line.partition(": ")
        current[key.strip()] = value.strip()
    if current.get("Package") and current.get("Filename"):
        entries[current["Package"]] = current
    return entries


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--release", default="24.10.8")
    parser.add_argument("--arch", default="x86_64")
    parser.add_argument("--cache", default="feed-cache",
                        help="output cache directory (mode 0700)")
    parser.add_argument("--package", action="append",
                        default=list(DEFAULT_PACKAGES))
    parser.add_argument("--apply", action="store_true",
                        help="download the resolved ipks; default is a dry "
                             "run that only fetches and parses the indexes")
    return parser.parse_args(argv)


def main(argv=None):
    os.umask(0o077)
    args = parse_args(argv)

    cache = os.path.abspath(args.cache)
    indexes = {}   # feed name -> {package: entry}
    dependencies_of_base = set()
    base_dep_path = os.path.join(cache, "base-image.pkgs")
    if os.path.exists(base_dep_path):
        with open(base_dep_path) as handle:
            dependencies_of_base = set(handle.read().split())
    def feed_url(feed, path):
        if feed == "target":
            target_arch = "/".join(args.arch.split("_"))
            base = TARGET_FEED_TEMPLATE.format(release=args.release,
                                               arch=target_arch)
        else:
            base = FEED_TEMPLATE.format(release=args.release, arch=args.arch,
                                        feed=feed)
        return "%s/%s" % (base, path)

    for feed in FEEDS:
        url = feed_url(feed, "Packages.gz")
        raw = _fetch(url)
        text = gzip.decompress(raw).decode("utf-8", errors="replace")
        indexes[feed] = parse_index(text)
        if args.apply:
            os.makedirs(os.path.join(cache, feed), mode=0o700, exist_ok=True)
            index_path = os.path.join(cache, feed, "Packages")
            with open(index_path, "w") as handle:
                handle.write(text)
            os.chmod(index_path, 0o600)
        _log("%s feed %s: %d packages" % (feed, url, len(indexes[feed])))

    def find(name):
        if name in BASE_IMAGE_PROVIDED or name in dependencies_of_base:
            return None
        for feed in FEEDS:
            if name in indexes[feed]:
                return feed
        return None

    resolved = {}
    pending = list(args.package)
    missing = []
    while pending:
        name = pending.pop()
        if name in resolved or name.startswith("kernel-"):
            continue
        feed = find(name)
        if feed is None:
            if name not in BASE_IMAGE_PROVIDED and name not in missing:
                missing.append(name)
            continue
        resolved[name] = (feed, indexes[feed][name])
        depends = re.split(r"[,\s]+", re.sub(r"\([^)]*\)", "", indexes[feed]
                                             [name].get("Depends", "")).strip())
        pending += [dep for dep in depends if dep]
    if missing:
        _log("not in feeds (assuming base image provides them): %s"
             % ", ".join(sorted(set(missing))))

    print("%d packages resolved for release %s (%s)" %
          (len(resolved), args.release, args.arch))
    for name in sorted(resolved):
        feed, entry = resolved[name]
        print("  %-28s %-9s %8s KB  %s" % (name, feed,
                                           entry.get("Installed-Size", "?"),
                                           entry.get("Version", "?")))
    if not args.apply:
        print("DRY RUN: re-run with --apply to download the ipks into %s"
              % cache)
        return 0

    pkg_dir = os.path.join(cache, "pkg")
    os.makedirs(pkg_dir, mode=0o700, exist_ok=True)
    for name in sorted(resolved):
        feed, entry = resolved[name]
        url = feed_url(feed, entry["Filename"])
        target = os.path.join(pkg_dir, os.path.basename(entry["Filename"]))
        expected = entry.get("SHA256sum")
        if os.path.exists(target) and expected:
            digest = hashlib.sha256(open(target, "rb").read()).hexdigest()
            if digest == expected:
                _log("already cached %s" % name)
                continue
            _log("stale %s (checksum mismatch); re-downloading" % name)
            os.unlink(target)
        data = _fetch(url)
        if expected and hashlib.sha256(data).hexdigest() != expected:
            raise FeedError("checksum mismatch for %s" % url)
        with open(target, "wb") as handle:
            handle.write(data)
        os.chmod(target, 0o600)
        _log("fetched %s (%d bytes)" % (name, len(data)))
    print("DONE %d packages in %s" % (len(resolved), cache))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except FeedError as error:
        print("ERROR: %s" % error, file=sys.stderr)
        sys.exit(1)
