#!/bin/bash
# run-qemu-tools.sh -- launch one isolated QEMU guest with the ATA tools
# shared inside (read-only).
#
# Qualification/offline use only. This script never attaches a physical
# device, never forwards bench/office/VPN ports, and never changes host
# routes, interfaces, DNS, packet filters, or VPN state. The guest gets
# user-mode networking in isolated (restrict) mode and no host forwards,
# so it cannot reach the bench ATA, the office LAN, or the WAN. The ATA
# firmware maintenance gate stays blocked; see
# docs/ata-firmware-maintenance.md and firmware/FLASHING.md.
#
# Layout: the firmware/ tools directory is shared into the guest
# read-only via 9p virtfs (mount tag "firmware"). The vintage
# ata_03_01_00_sip_040211_1/ directory is shared the same way (mount tag
# "legacy") for its data files (ptag.dat, example profiles, images,
# docs). Legacy binaries stay reference-only: the guest mount commands
# this script prints use "noexec", and repo policy forbids executing
# them. The guest disk runs in snapshot mode, so the base image is never
# modified.
#
# Agent rules honored here: dry-run default, explicit --apply, bounded
# runtime, read-only preflight snapshots, staged logs, fail closed.

set +x
umask 077
set -eu

SCRIPT_NAME="run-qemu-tools.sh"
VM_NAME="ata-tools-qual"
SLIRP_NET="10.0.2.0/24"
DEFAULT_MEM_MB="1024"
DEFAULT_TIMEOUT_SECS="600"
MIN_TIMEOUT_SECS="60"
MAX_TIMEOUT_SECS="3600"

log() {
    printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*"
}

fail() {
    log "ERROR: $*"
    exit 1
}

usage() {
    cat <<EOF
Usage: $SCRIPT_NAME --disk GUEST_IMAGE [options]

Launches one isolated QEMU x86_64 guest with this repository's firmware/
tools shared inside read-only (9p mount tag "firmware"), plus the vintage
ATA reference directory shared read-only (9p mount tag "legacy") for its
data files (ptag.dat, example profiles, images, docs). Legacy binaries
stay reference-only: mount with "noexec" and do not execute them.
Qualification / offline use only: user-mode networking (isolated), no host
port forwards, guest disk in snapshot mode (base image untouched).

Options:
  --disk PATH        Guest disk image (regular file, required).
  --format FMT       Disk format: qcow2 (default) or raw.
  --ovmf PATH        Optional OVMF code file for EFI guests.
  --mem MB           Guest RAM in MB (default $DEFAULT_MEM_MB, 256-8192).
  --timeout SECS     Bounded runtime in seconds (default
                     $DEFAULT_TIMEOUT_SECS, $MIN_TIMEOUT_SECS-$MAX_TIMEOUT_SECS).
  --tools DIR        Tools directory to share (default: <repo>/firmware).
  --legacy DIR       Vintage reference directory to share read-only for
                     data files (default: <repo>/ata_03_01_00_sip_040211_1).
                     Binaries inside stay reference-only (noexec).
  --apply            Launch the VM. Without it, dry-run: print the exact
                     QEMU command and exit without launching.
  -h, --help         Show this help and exit.

Preflight (always, read-only): qemu binary, disk, tools, route/neighbor
snapshots, numeric overlap review of $SLIRP_NET, stale-instance check.
Post-run: snapshots are compared and drift is reported, never repaired.
EOF
}

# Resolve repository root (script lives in tests/qemu/).
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)"
DEFAULT_TOOLS_DIR="$REPO_ROOT/firmware"
DEFAULT_LEGACY_DIR="$REPO_ROOT/ata_03_01_00_sip_040211_1"
BOUNDED_COMMAND="$SCRIPT_DIR/bounded_command.py"
NETWORK_STATE="$SCRIPT_DIR/network_state.py"
PYTHON_BIN="${PYTHON_BIN:-python3}"

DISK=""
FORMAT="qcow2"
OVMF=""
MEM_MB="$DEFAULT_MEM_MB"
TIMEOUT_SECS="$DEFAULT_TIMEOUT_SECS"
TOOLS_DIR="$DEFAULT_TOOLS_DIR"
LEGACY_DIR="$DEFAULT_LEGACY_DIR"
APPLY="0"

need_value() {
    [ "$#" -ge 2 ] || fail "$1 requires a value"
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --disk) need_value "$@"; DISK="$2"; shift 2 ;;
        --disk=*) DISK="${1#--disk=}"; shift ;;
        --format) need_value "$@"; FORMAT="$2"; shift 2 ;;
        --format=*) FORMAT="${1#--format=}"; shift ;;
        --ovmf) need_value "$@"; OVMF="$2"; shift 2 ;;
        --ovmf=*) OVMF="${1#--ovmf=}"; shift ;;
        --mem) need_value "$@"; MEM_MB="$2"; shift 2 ;;
        --mem=*) MEM_MB="${1#--mem=}"; shift ;;
        --timeout) need_value "$@"; TIMEOUT_SECS="$2"; shift 2 ;;
        --timeout=*) TIMEOUT_SECS="${1#--timeout=}"; shift ;;
        --tools) need_value "$@"; TOOLS_DIR="$2"; shift 2 ;;
        --tools=*) TOOLS_DIR="${1#--tools=}"; shift ;;
        --legacy) need_value "$@"; LEGACY_DIR="$2"; shift 2 ;;
        --legacy=*) LEGACY_DIR="${1#--legacy=}"; shift ;;
        --apply) APPLY="1"; shift ;;
        -h|--help) usage; exit 0 ;;
        --) shift; break ;;
        -*) fail "unknown switch $1 (see --help)" ;;
        *) fail "unexpected positional argument $1 (see --help)" ;;
    esac
done

is_uint() {
    case "$1" in
        ''|*[!0-9]*) return 1 ;;
        *) return 0 ;;
    esac
}

is_safe_qemu_path() {
    if [[ "$1" == *","* || "$1" =~ [[:cntrl:]] ]]; then
        return 1
    fi
    return 0
}

canonical_file() {
    parent="$(CDPATH= cd -- "$(dirname -- "$1")" && pwd -P)" || return 1
    printf '%s/%s\n' "$parent" "$(basename -- "$1")"
}

canonical_directory() {
    CDPATH= cd -- "$1" && pwd -P
}

[ -n "$DISK" ] || fail "--disk GUEST_IMAGE is required"
is_safe_qemu_path "$DISK" || fail "guest disk path contains unsafe QEMU syntax"
[ -f "$DISK" ] || fail "guest disk is not a regular file: $DISK"
[ -r "$DISK" ] || fail "guest disk is not readable: $DISK"
DISK="$(canonical_file "$DISK")" || fail "cannot canonicalize guest disk path"
is_safe_qemu_path "$DISK" || fail "guest disk path contains unsafe QEMU syntax"
case "$FORMAT" in
    qcow2|raw) ;;
    *) fail "--format must be qcow2 or raw" ;;
esac
if [ -n "$OVMF" ]; then
    is_safe_qemu_path "$OVMF" || fail "OVMF path contains unsafe QEMU syntax"
    [ -f "$OVMF" ] || fail "OVMF file is not a regular file: $OVMF"
    [ -r "$OVMF" ] || fail "OVMF file is not readable: $OVMF"
    OVMF="$(canonical_file "$OVMF")" || fail "cannot canonicalize OVMF path"
    is_safe_qemu_path "$OVMF" || fail "OVMF path contains unsafe QEMU syntax"
fi
is_uint "$MEM_MB" || fail "--mem must be an integer (MB)"
[ "$MEM_MB" -ge 256 ] && [ "$MEM_MB" -le 8192 ] || fail "--mem out of range 256-8192"
is_uint "$TIMEOUT_SECS" || fail "--timeout must be an integer (seconds)"
[ "$TIMEOUT_SECS" -ge "$MIN_TIMEOUT_SECS" ] && [ "$TIMEOUT_SECS" -le "$MAX_TIMEOUT_SECS" ] \
    || fail "--timeout out of range $MIN_TIMEOUT_SECS-$MAX_TIMEOUT_SECS"
is_safe_qemu_path "$TOOLS_DIR" || fail "tools path contains unsafe QEMU syntax"
[ -d "$TOOLS_DIR" ] || fail "tools directory not found: $TOOLS_DIR"
TOOLS_DIR="$(canonical_directory "$TOOLS_DIR")" || fail "cannot canonicalize tools path"
is_safe_qemu_path "$TOOLS_DIR" || fail "tools path contains unsafe QEMU syntax"
for tool in cfgfmt.py prserv.py sata186us.py; do
    [ -f "$TOOLS_DIR/$tool" ] || fail "expected tool missing: $TOOLS_DIR/$tool"
done
is_safe_qemu_path "$LEGACY_DIR" || fail "legacy path contains unsafe QEMU syntax"
[ -d "$LEGACY_DIR" ] || fail "legacy directory not found: $LEGACY_DIR"
LEGACY_DIR="$(canonical_directory "$LEGACY_DIR")" \
    || fail "cannot canonicalize legacy path"
is_safe_qemu_path "$LEGACY_DIR" || fail "legacy path contains unsafe QEMU syntax"
[ -f "$LEGACY_DIR/ptag.dat" ] || fail "expected legacy data missing: $LEGACY_DIR/ptag.dat"
command -v qemu-system-x86_64 >/dev/null 2>&1 \
    || fail "qemu-system-x86_64 not found in PATH"
command -v "$PYTHON_BIN" >/dev/null 2>&1 || fail "python3 is required"
[ -f "$BOUNDED_COMMAND" ] || fail "bounded command helper is missing"
[ -r "$BOUNDED_COMMAND" ] || fail "bounded command helper is unreadable"
[ -f "$NETWORK_STATE" ] || fail "network-state helper is missing"
[ -r "$NETWORK_STATE" ] || fail "network-state helper is unreadable"

RUNDIR="$(mktemp -d "${TMPDIR:-/tmp}/ata-qemu-tools.XXXXXX")"
chmod 700 "$RUNDIR"
log "rundir: $RUNDIR"

# Stale-instance guard: refuse if our named VM is already running.
if command -v pgrep >/dev/null 2>&1; then
    if pgrep -f "qemu-system.*$VM_NAME" >/dev/null 2>&1; then
        fail "an instance named $VM_NAME is already running; refusing a second launch"
    fi
fi

# Read-only preflight snapshots are mandatory before launch.
command -v netstat >/dev/null 2>&1 || fail "netstat is required for route review"
command -v scutil >/dev/null 2>&1 || fail "scutil is required for network-state review"
"$PYTHON_BIN" -B "$BOUNDED_COMMAND" "$RUNDIR/pre-route4.txt" 10 \
    netstat -rn -f inet \
    || fail "cannot capture IPv4 routes"
"$PYTHON_BIN" -B "$BOUNDED_COMMAND" "$RUNDIR/pre-route6.txt" 10 \
    netstat -rn -f inet6 \
    || fail "cannot capture IPv6 routes"
"$PYTHON_BIN" -B "$BOUNDED_COMMAND" "$RUNDIR/pre-nwi.txt" 10 \
    scutil --nwi \
    || fail "cannot capture network state"
if command -v arp >/dev/null 2>&1; then
    "$PYTHON_BIN" -B "$BOUNDED_COMMAND" "$RUNDIR/pre-arp.txt" 10 \
        arp -an || true
fi

# Numeric overlap review uses the same fail-closed parser as the Python wrappers.
if ! "$PYTHON_BIN" -B "$NETWORK_STATE" check-overlap \
        "$RUNDIR/pre-route4.txt" "$SLIRP_NET"; then
    fail "stopping on subnet ambiguity"
else
    log "route overlap review for $SLIRP_NET: none found"
fi

# Host architecture determines the accelerator probe order.
HOST_ARCH="$(uname -m 2>/dev/null || echo unknown)"
case "$HOST_ARCH" in
    x86_64|i386) ACCEL="hvf:tcg" ;;
    *) ACCEL="tcg" ;;
esac

QEMU_ARGS=(
    -name "$VM_NAME,process=$VM_NAME"
    -machine "q35,accel=$ACCEL"
    -m "$MEM_MB"
    -smp 2
    -display none
    -serial mon:stdio
    -nic user,model=virtio-net-pci,restrict=on
    -drive "file=$DISK,format=$FORMAT,if=virtio,snapshot=on"
    -virtfs "local,path=$TOOLS_DIR,mount_tag=firmware,security_model=mapped-xattr,readonly=on"
    -virtfs "local,path=$LEGACY_DIR,mount_tag=legacy,security_model=mapped-xattr,readonly=on"
)
if [ -n "$OVMF" ]; then
    QEMU_ARGS+=( -drive "if=pflash,format=raw,readonly=on,file=$OVMF" )
fi

{
    echo "vm_name=$VM_NAME"
    echo "disk=$DISK"
    echo "format=$FORMAT"
    echo "mem_mb=$MEM_MB"
    echo "timeout_secs=$TIMEOUT_SECS"
    echo "tools_dir=$TOOLS_DIR"
    echo "legacy_dir=$LEGACY_DIR"
    echo "accel=$ACCEL"
    echo "ovmf=${OVMF:-none}"
    echo "network=user-mode,restrict=on,forwards=none"
} >"$RUNDIR/stage.env"

log "qemu command:"
printf -v QEMU_COMMAND '%q ' qemu-system-x86_64 "${QEMU_ARGS[@]}"
log "$QEMU_COMMAND"

if [ "$APPLY" != "1" ]; then
    log "dry run: launch suppressed (re-run with --apply to start the VM)"
    log "in-guest follow-ups once booted:"
    log "  mount -t 9p -o version=9p2000.L,ro,trans=virtio firmware /mnt/firmware"
    log "  mount -t 9p -o version=9p2000.L,ro,trans=virtio,noexec legacy /mnt/legacy"
    log "  legacy binaries are reference-only: do not execute them (repo policy)"
    log "  python3 -B /mnt/firmware/sata186us.py --help"
    log "  cd /mnt && python3 -B -m unittest firmware.tests.test_sata186us"
    exit 0
fi

log "apply: starting VM (bounded ${TIMEOUT_SECS}s, snapshot-mode disk)"
RUNNER_PID=""
RUNNER_FINISHED="0"

stop_child() {
    if [ "$RUNNER_FINISHED" = "1" ]; then
        return
    fi
    child_pid="$RUNNER_PID"
    if [ -z "$child_pid" ]; then
        set +u
        child_pid="$!"
        set -u
    fi
    if [ -n "$child_pid" ] && kill -0 "$child_pid" 2>/dev/null; then
        RUNNER_PID="$child_pid"
        kill -TERM "$child_pid" 2>/dev/null || true
        i=0
        while kill -0 "$child_pid" 2>/dev/null && [ "$i" -lt 10 ]; do
            sleep 1
            i=$((i + 1))
        done
        if kill -0 "$child_pid" 2>/dev/null; then
            kill -KILL "$child_pid" 2>/dev/null || true
        fi
        wait "$child_pid" 2>/dev/null || true
        RUNNER_FINISHED="1"
    fi
}

HOST_DRIFT="0"
CLEANED_UP="0"

cleanup() {
    trap '' HUP INT TERM
    if [ "$CLEANED_UP" = "1" ]; then
        return
    fi
    CLEANED_UP="1"
    stop_child
    "$PYTHON_BIN" -B "$BOUNDED_COMMAND" "$RUNDIR/post-route4.txt" 10 \
        netstat -rn -f inet || HOST_DRIFT="1"
    "$PYTHON_BIN" -B "$BOUNDED_COMMAND" "$RUNDIR/post-route6.txt" 10 \
        netstat -rn -f inet6 || HOST_DRIFT="1"
    "$PYTHON_BIN" -B "$BOUNDED_COMMAND" "$RUNDIR/post-nwi.txt" 10 \
        scutil --nwi || HOST_DRIFT="1"
    if "$PYTHON_BIN" -B "$NETWORK_STATE" compare \
            "$RUNDIR/pre-route4.txt" "$RUNDIR/post-route4.txt" \
            "$RUNDIR/pre-route6.txt" "$RUNDIR/post-route6.txt" \
            "$RUNDIR/pre-nwi.txt" "$RUNDIR/post-nwi.txt"; then
        log "post-run route/NWI state: unchanged"
    else
        log "post-run route/NWI state: DIFFERS (reported only, never repaired here)"
        HOST_DRIFT="1"
    fi
}

handle_signal() {
    signal_status="$1"
    trap '' HUP INT TERM
    cleanup
    trap - EXIT HUP INT TERM
    exit "$signal_status"
}

trap cleanup EXIT
trap 'handle_signal 129' HUP
trap 'handle_signal 130' INT
trap 'handle_signal 143' TERM

# Recheck exact host state immediately before launch to close the staging window.
"$PYTHON_BIN" -B "$BOUNDED_COMMAND" "$RUNDIR/prelaunch-route4.txt" 10 \
    netstat -rn -f inet \
    || fail "cannot recapture IPv4 routes before launch"
"$PYTHON_BIN" -B "$BOUNDED_COMMAND" "$RUNDIR/prelaunch-route6.txt" 10 \
    netstat -rn -f inet6 \
    || fail "cannot recapture IPv6 routes before launch"
"$PYTHON_BIN" -B "$BOUNDED_COMMAND" "$RUNDIR/prelaunch-nwi.txt" 10 \
    scutil --nwi \
    || fail "cannot recapture network state before launch"
if ! "$PYTHON_BIN" -B "$NETWORK_STATE" compare \
        "$RUNDIR/pre-route4.txt" "$RUNDIR/prelaunch-route4.txt" \
        "$RUNDIR/pre-route6.txt" "$RUNDIR/prelaunch-route6.txt" \
        "$RUNDIR/pre-nwi.txt" "$RUNDIR/prelaunch-nwi.txt"; then
    fail "host route/NWI state changed before launch"
fi
if ! "$PYTHON_BIN" -B "$NETWORK_STATE" check-overlap \
        "$RUNDIR/prelaunch-route4.txt" "$SLIRP_NET"; then
    fail "stopping on prelaunch subnet ambiguity"
fi

"$PYTHON_BIN" -B "$BOUNDED_COMMAND" "$RUNDIR/console.log" \
    "$TIMEOUT_SECS" qemu-system-x86_64 "${QEMU_ARGS[@]}" &
RUNNER_PID="$!"
echo "$RUNNER_PID" >"$RUNDIR/runner.pid"
log "bounded runner pid: $RUNNER_PID"
STATUS="0"
wait "$RUNNER_PID" || STATUS="$?"
RUNNER_FINISHED="1"
TIMED_OUT="0"
if [ "$STATUS" = "124" ]; then
    TIMED_OUT="1"
    log "timeout reached; VM was stopped"
fi
cleanup
trap - EXIT HUP INT TERM
log "qemu exited with status $STATUS (timeout=$TIMED_OUT)"
log "logs kept at: $RUNDIR"
log "in-guest follow-ups for next session:"
log "  mount -t 9p -o version=9p2000.L,ro,trans=virtio firmware /mnt/firmware"
log "  mount -t 9p -o version=9p2000.L,ro,trans=virtio,noexec legacy /mnt/legacy"
log "  legacy binaries are reference-only: do not execute them (repo policy)"
log "  python3 -B /mnt/firmware/sata186us.py --help"
if [ "$TIMED_OUT" = "1" ]; then
    exit 124
fi
if [ "$HOST_DRIFT" = "1" ]; then
    exit 1
fi
exit "$STATUS"
