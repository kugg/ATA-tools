#!/usr/bin/env python3
# Pin + fetch + SHA-verify the official OpenWrt 24.10.8 x86_64 gptfdisk ipk.
# Bounded/read-only on the network; stages ONE ipk under the repo temp dir.
# device untouched by this script. Operator install is a separate gated step.
import gzip, hashlib, os, re, stat, sys, tempfile, urllib.request, urllib.error

rel = "24.10.8"
arch = "x86_64"
# gptfdisk lives in the BASE (targets) feed for x86_64 on OpenWrt.
cands = [
    f"https://downloads.openwrt.org/releases/{rel}/packages/x86_64/base/Packages.gz",
    f"https://downloads.openwrt.org/releases/{rel}/packages/x86_64/packages/Packages.gz",
    f"https://downloads.openwrt.org/releases/{rel}/targets/x86_64/generic/packages/Packages.gz",
]

tmp = tempfile.gettempdir()
stage = os.path.join(tmp, "opencode", "gptfdisk-fetch")
os.makedirs(stage, exist_ok=True)
os.chmod(stage, 0o700)

idx = None
for url in cands:
    print(f"FETCH-IDX {url}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ata-pin-1"})
        with urllib.request.urlopen(req, timeout=90) as r:
            raw = r.read()
        if len(raw) < 1000:
            print(f"  too-small {len(raw)}B skip")
            continue
        data = gzip.decompress(raw).decode("utf-8", "replace")
        if "Package: gptfdisk" in data:
            idx = data
            print(f"  OK bytes={len(raw)} PARAGRAPH-FOUND, feed={url}")
            break
        else:
            print(f"  no gptfdisk paragraph in this feed ({len(raw)}B)")
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code} skip")

if not idx:
    sys.exit("GPTFDISK-NOT-PINNED in either feed -- abort")

blk = next(
    (b for b in idx.split("\n\n") if re.match(r"^Package: gptfdisk\n", b, re.M)),
    None,
)
kv = {}
for line in blk.splitlines():
    m = re.match(r"^([A-Za-z0-9]+):\s?(.*)$", line)
    if m:
        kv[m.group(1)] = m.group(2).strip()

ver = kv.get("Version")
fn = kv.get("Filename")
sha = kv.get("SHA256sum")
size = int(kv.get("Size", 0) or 0)
print(
    f"PIN gptfdisk ver={ver} filename={fn} sha256={sha} size={size}"
)
if not (ver and fn and sha):
    sys.exit("INCOMPLETE-PIN")

url = cands[0].rsplit("/", 1)[0] + "/" + fn
dst = os.path.join(stage, os.path.basename(fn))
print(f"FETCH-IPK {url}")
try:
    req = urllib.request.Request(url, headers={"User-Agent": "ata-pin-1"})
    with urllib.request.urlopen(req, timeout=180) as r:
        body = r.read()
except urllib.error.HTTPError as e:
    sys.exit(f"IPK-HTTP {e.code}")
got = hashlib.sha256(body).hexdigest()
if got != sha:
    sys.exit(f"SHA-MISMATCH (got {got}, want {sha}) -- refusing to stage")
with open(dst, "wb") as f:
    f.write(body)
os.chmod(dst, 0o600)
print(f"STAGED {dst} bytes={len(body)} SHA256-MATCH=YES")
print("NEXT (operator-gated, separate step):")
print(f'  scp -o BatchMode=yes {dst} root@10.47.11.97:/tmp/')
print(
    "  ssh root@10.47.11.97 'opkg install /tmp/%s && command -v sgdisk'"
    % os.path.basename(fn)
)
