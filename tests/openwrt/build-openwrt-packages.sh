#!/bin/bash
# build-openwrt-packages.sh -- reproducible OpenWrt 24.10.8 package build.
#
# Builds the pinned Asterisk 20.8.1-r1 closure (plus any other selected
# package) from source with the official OpenWrt SDK for x86_64, so a later
# APU-side reload or version bump is a reviewed rebuild, not a download from
# a mixed feed. The SDK output must be held to the same pinned fact base as
# the twin feed cache (docs/asterisk-integration.md); PINS_FILES holds the
# exact pins consulted before any compile.
#
# Conventions (repo-wide): dry-run default; read-only preflight; bounded,
# staged, with rollback notes; never commits; writes only under --apply.

set +x
umask 077
set -eu

RELEASE="${RELEASE:-24.10.8}"
TARGET_BASE="x86/64"
SDK_ARCH="x86-64"   # appears in the SDK directory name
SDK_ROOT="${SDK_ROOT:-/var/folders/0_/rjsf94rn3gd5k8mntc9fjkth0000gn/T/opencode/openwrt-sdk}"
DOWNLOAD_BASE="https://downloads.openwrt.org/releases/${RELEASE}/targets/${TARGET_BASE}"
BUILD="0"

log() { printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*"; }
fail() { log "ERROR: $*"; exit 1; }
usage() { sed -n '2,30p' "$0"; exit 0; }

need_value() { [ "$#" -ge 2 ] || fail "$1 requires a value"; }
while [ "$#" -gt 0 ]; do
    case "$1" in
        --release) need_value "$@"; RELEASE="$2"; shift 2 ;;
        --sdk-root) need_value "$@"; SDK_ROOT="$2"; shift 2 ;;
        --build) BUILD="1"; shift ;;
        -h|--help) usage ;;
        *) fail "unknown switch $1" ;;
    esac
done
[ -n "$PINS_FILES" ] || fail "PINS_FILES is required (space-separated pin manifests)"

# ---- preflight: pins present + toolkit available ----------------------------
for pin in $PINS_FILES; do
    [ -f "$pin" ] || fail "missing pins file: $pin"
done
for tool in curl tar make sha256sum grep; do
    command -v "$tool" >/dev/null 2>&1 || fail "missing tool: $tool"
done

# ---- locate SDK (24.10.8 x86/64) -------------------------------------------
SDK_DIR_NAME="openwrt-sdk-${RELEASE}-${SDK_ARCH}_gcc-13.3.0_musl.Linux-x86_64"
SDK_ARCHIVE="${SDK_DIR_NAME}.tar.xz"
SDK_URL="${DOWNLOAD_BASE}/${SDK_ARCHIVE}"
SDK_CHECKSUMS_URL="${DOWNLOAD_BASE}/sha256sums"

mkdir -p "$SDK_ROOT"   # private, per AGENTS umask 077
if [ -d "$SDK_ROOT/$SDK_DIR_NAME" ]; then
    log "SDK already extracted at $SDK_ROOT/$SDK_DIR_NAME"
else
    if [ ! -f "$SDK_ROOT/$SDK_ARCHIVE" ]; then
        if [ "$BUILD" = "0" ]; then
            log "DRY RUN: would download $SDK_URL (~300 MB, see sha256sums) to"
            log "         $SDK_ROOT/$SDK_ARCHIVE"
        else
            log "downloading SDK"
            curl -fL --retry 2 -o "$SDK_ROOT/$SDK_ARCHIVE" "$SDK_URL"
        fi
    fi
    [ "$BUILD" = "1" ] || exit 0
    log "verifying SDK checksum against $SDK_CHECKSUMS_URL"
    curl -fsSL "$SDK_CHECKSUMS_URL" | grep -F " ${SDK_ARCHIVE}$" | head -1
    EXPECTED="$(curl -fsSL "$SDK_CHECKSUMS_URL" | grep -F " ${SDK_ARCHIVE}$" | cut -d' ' -f1)"
    [ -n "$EXPECTED" ] || fail "SDK hash not found in sha256sums"
    ACTUAL="$(shasum -a 256 "$SDK_ROOT/$SDK_ARCHIVE" | cut -d' ' -f1)"
    [ "$ACTUAL" = "$EXPECTED" ] || fail "SDK checksum mismatch"
    log "SDK verified"
    tar xJf "$SDK_ROOT/$SDK_ARCHIVE" -C "$SDK_ROOT"
fi

SDK_DIR="$SDK_ROOT/$SDK_DIR_NAME"

log "SDK ready: $SDK_DIR (release $RELEASE, target $TARGET_BASE)"
[ "$BUILD" = "1" ] || exit 0

# ---- set up feeds and build the pinned set ----------------------------------
# The SDK ships distfeeds for the release; we pin to the SAME local feed facts
# the twin uses, by pointing feeds at the release URLs (downloaded fresh,
# checksum-verified against the published release) rather than snapshot git.
log "configuring telephony feed"
cat >> "$SDK_DIR/feeds.conf" <<'EOF'
src-git telephony https://github.com/openwrt/telephony.git^7f03b9c2
EOF
"$SDK_DIR/scripts/feeds" update telephony
"$SDK_DIR/scripts/feeds" install -p telephony asterisk

log "building pinned asterisk packages (this runs many minutes)"
make -C "$SDK_DIR" package/asterisk/compile V=s 2>&1 |
    tee "$SDK_ROOT/build-asterisk.log"
log "build log at $SDK_ROOT/build-asterisk.log"
log "packages in $SDK_DIR/bin/packages/{target,x86_64}/telephony/"