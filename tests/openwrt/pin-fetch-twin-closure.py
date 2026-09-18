#!/usr/bin/env python3
# pin-fetch-twin-closure.py
# Stage the 65-ipk OpenWrt 24.10.8 x86_64 twin closure as SHA-verified .ipk bytes
# on THIS Mac. Device / APU never touched here; install is a separate --apply gate.
#
# Behaviour (all read-only egress from this Mac, TLS-verified, bounded):
#   * reads telephony/openwrt-twin-manifest-24.10.8.txt (65 package names)
#   * for each of the closure feeds (base, packages, telephony) fetches Packages.gz
#     ONCE (single bounded HTTPS GET, verify peer via stdlib ssl default roots),
#   * builds name->(feed, filename, sha256) index,
#   * requires ALL 65 names present in the combined index, else aborts read-only
#     (lists the missing, stages nothing, leaves no partial ipk),
#   * fetches each of the 65 exactly once, bounded, to a sealed staging dir,
#   * verifies SHA256(inode bytes) == feed-paragraph SHA256sum,
#   * on ANY mismatch: deletes that partial file, aborts, lists the culprit.
#
# Default: dry-run (probe only). --stage to write ipks into stage_dir.
# Always umask 077. Never touches the device.

import argparse, gzip, hashlib, os, re, sys, tempfile, urllib.request, urllib.error, ssl, shutil, io

RELEASE = "24.10.8"
ARCH = "x86_64"
BASE = f"https://downloads.openwrt.org/releases/{RELEASE}/packages/{ARCH}"
FEEDS = {
    "base":      f"{BASE}/base/Packages.gz",
    "packages":  f"{BASE}/packages/Packages.gz",
    "telephony": f"{BASE}/telephony/Packages.gz",
}
ABS_MANIFEST = "/Users/user/devel/ata/telephony/openwrt-twin-manifest-24.10.8.txt"

def fetch_gz(url: str) -> bytes:
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": "ata-twin-closure-pin/1.0"})
    with urllib.request.urlopen(req, timeout=60, context=ctx) as r:
        data = r.read()
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return data


def parse_paragraphs(text: str):
    # block per "\n\n"; header key:
    for block in text.split("\n\n"):
        head = {}
        for line in block.splitlines():
            if ":" in line and not line.startswith(" "):
                k, _, v = line.partition(":")
                head[k.strip()] = v.strip()
            elif line and " " in line and not line.startswith(" "):
                pass
        name = head.get("Package")
        if name and head.get("Filename") and head.get("SHA256sum"):
            yield name, head["Filename"], head["SHA256sum"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", action="store_true", help="write verified ipks (default: dry-run)")
    ap.add_argument("--stage-dir", default=None)
    args = ap.parse_args()

    umask = os.umask(0o077)
    with open(ABS_MANIFEST, "r", encoding="utf-8") as f:
        manifest = [l.strip() for l in f
                    if l.strip() and not l.strip().startswith("#")]

    if not manifest:
        print("EMPTY-MANIFEST abort"); return 2
    target = set(manifest)

    index = {}   # name -> (feed, filename, sha)
    for feed, url in FEEDS.items():
        try:
            text = fetch_gz(url).decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            print(f"FETCH-FEED {feed} HTTP {e.code} (skip)"); continue
        except Exception as e:
            print(f"FETCH-FEED {feed} ERR {e}"); continue
        n = 0
        for name, fn, sha in parse_paragraphs(text):
            if name in target and name not in index:
                index[name] = (feed, fn, sha); n += 1
        print(f"INDEXED {feed}: +{n}")

    missing = sorted(target - set(index))
    if missing:
        print(f"MISSING-FROM-FEEDS ({len(missing)}): " + " ".join(missing))
        print("ABORT read-only; staged nothing; device untouched")
        return 3

    if not args.stage:
        print(f"DRY-RUN ok: all {len(target)} pinnable; invoke --stage to fetch+verify")
        return 0

    stage = args.stage_dir or os.path.join(tempfile.mkdtemp(prefix="twin-closure-"), "ipks")
    os.makedirs(stage, exist_ok=True)
    n_ok = n_bad = 0
    for name in sorted(index):
        feed, fn, want = index[name]
        url = FEEDS[feed].rsplit("/", 1)[0] + "/" + fn
        try:
            data = fetch_gz(url)
        except Exception as e:
            print(f"FETCH-FAIL {name}: {e}"); return 4
        got = hashlib.sha256(data).hexdigest()
        if got != want:
            print(f"SHA-MISMATCH {name}: want {want[:16]}... got {got[:16]}... ABORT")
            os.remove(os.path.join(stage, fn)) if os.path.exists(os.path.join(stage, fn)) else None
            return 5
        p = os.path.join(stage, fn)
        if os.path.exists(p):
            os.remove(p)
        with open(p, "wb") as f:
            f.write(data)
        ln = os.path.getsize(p)
        n_ok += 1
        print(f"OK {name} {ln} {got[:12]}")
    print(f"STAGED {n_ok} ipk(s) in {stage}; SHA256-verified against official feed index")
    return 0


if __name__ == "__main__":
    sys.exit(main())
