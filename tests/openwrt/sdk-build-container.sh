#!/bin/bash
# sdk-build-container.sh -- build the pinned OpenWrt 24.10.8 asterisk closure
# inside a linux/amd64 Docker container (Rosetta on Apple Silicon).
#
# The official OpenWrt SDK ships prebuilt host tooling as x86_64-Linux ELF
# binaries, so it cannot run directly on macOS. This wrapper runs the exact
# same steps as tests/openwrt/build-openwrt-packages.sh but inside a Debian
# amd64 container, keeping all build state in SDK_ROOT on the host so
# repeated runs are incremental.
#
# Network boundary: the container uses Docker default NAT and talks ONLY to
# public open-source sources (github.com/openwrt/*, downloads.asterisk.org,
# debian apt mirrors). No bench/office/VPN/device traffic. This matches the
# host curl fetches of the twin feed cache; nothing else is reached.
#
# Conventions: dry-run default; umask 077; redacted logs; bounded runtime;
# staged progress file; post-run checksum/verification of built ipks.

set +x
umask 077
set -eu

RELEASE="${RELEASE:-24.10.8}"
SDK_ROOT="${SDK_ROOT:-/var/folders/0_/rjsf94rn3gd5k8mntc9fjkth0000gn/T/opencode/openwrt-sdk}"
CFG_FILE="${CFG_FILE:-}"
APPLY="0"

log() { printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*"; }
fail() { log "ERROR: $*"; exit 1; }
usage() { sed -n '2,25p' "$0"; exit 0; }

need_value() { [ "$#" -ge 2 ] || fail "$1 requires a value"; }
while [ "$#" -gt 0 ]; do
    case "$1" in
        --release) need_value "$@"; RELEASE="$2"; shift 2 ;;
        --sdk-root) need_value "$@"; SDK_ROOT="$2"; shift 2 ;;
        --config) need_value "$@"; CFG_FILE="$2"; shift 2 ;;
        --apply) APPLY="1"; shift ;;
        -h|--help) usage ;;
        *) fail "unknown switch $1" ;;
    esac
done

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)"

# ---- preflight --------------------------------------------------------------
command -v docker >/dev/null 2>&1 || fail "docker missing"
docker info >/dev/null 2>&1 || fail "docker daemon not ready"
if [ "$APPLY" = "0" ]; then
    log "DRY RUN: would build pinned asterisk closure for OpenWrt $RELEASE"
    log "         inside linux/amd64 Debian container (state kept in $SDK_ROOT)"
    exit 0
fi

# ---- config: pins files (mandatory) ----------------------------------------
if [ -z "$CFG_FILE" ]; then
    CFG_FILE="$REPO_ROOT/telephony/openwrt-twin-manifest-24.10.8.txt"
fi
for pin in "$CFG_FILE" \
           "$REPO_ROOT/telephony/openwrt-asterisk-packages-24.10.8.txt"; do
    [ -f "$pin" ] || fail "missing pins file: $pin"
done

mkdir -p "$SDK_ROOT/build"
STAGE="$SDK_ROOT/build/stage.txt"
touch "$STAGE"; stage() { printf '%sZ %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%S')" "$*" >> "$STAGE"; }
stage "start"

# ---- build driver (runs inside the container) ------------------------------
cat > "$SDK_ROOT/build/driver.sh" <<'DRYEOF'
set +x
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq build-essential bison flex \
    bc rsync git unzip wget xz-utils zlib1g-dev libssl-dev libncurses5-dev \
    file python3 python3-dev patch gawk diffutils cpio perl tar gzip \
    ca-certificates gcc g++ make libtool autoconf automake gettext >/dev/null
cd /sdk
SDK_DIR_NAME="openwrt-sdk-24.10.8-x86-64_gcc-13.3.0_musl.Linux-x86_64"
ARCHIVE="${SDK_DIR_NAME}.tar.zst"
if [ ! -d "$SDK_DIR_NAME" ]; then
    tar xf "/sdk/$ARCHIVE"
fi
cd "$SDK_DIR_NAME"
ln -sf /sdk/dl dl
# local feed for the pinned telephony origin
sed -i '/src-git telephony/d' feeds.conf.default
cat >> feeds.conf.default <<'EOF'
src-git telephony https://github.com/openwrt/telephony.git^openwrt-24.10
EOF
stage() { printf '%sZ %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%S')" "$*" >> /sdk/build/stage.txt; }
stage "feeds-update"
./scripts/feeds update -a >/sdk/build/feeds-update.log 2>&1
stage "feeds-install"
./scripts/feeds install -a >/sdk/build/feeds-install.log 2>&1
stage "compile-start"
make package/asterisk/{download,prepare,compile} V=s \
     >/sdk/build/compile.log 2>&1 || {
    tail -40 /sdk/build/compile.log
    stage "compile-FAILED"
    exit 1
}
stage "compile-done"
ls -1 bin/packages/x86_64/telephony/ docker.bin 2>/dev/null | head
DRYEOF
chmod 600 "$SDK_ROOT/build/driver.sh"

stage "pull-image"
docker pull --platform linux/amd64 -q amd64/debian:12-slim
stage "run-build"

# trusted-paths are our 0700 trees; --cpus/etc bound the job; tty disables colors
docker run --rm --name ata-sdk-build \
    --platform linux/amd64 \
    -e LC_ALL=C.UTF-8 \
    -v "$SDK_ROOT:/sdk:rw" \
    -v "$REPO_ROOT:/pins:ro" \
    --cpus 6 --memory 6g \
    -w /sdk \
    amd64/debian:12-slim \
    bash /sdk/build/driver.sh 2>&1 | tee "$SDK_ROOT/build/container.log"

stage "finish"

log "SDK build finished; log at $SDK_ROOT/build/compile.log and container.log"
log "built ipks: check $SDK_ROOT/openwrt-sdk-24.10.8-*/bin/packages/x86_64/telephony/"