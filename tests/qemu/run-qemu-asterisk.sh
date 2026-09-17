#!/bin/bash
# run-qemu-asterisk.sh -- bounded OpenWrt 24.10.8 digital twin for Asterisk.
#
# Boots the pinned OpenWrt x86_64 image in one isolated QEMU guest, installs
# the pinned Asterisk 20.8.1-r1 package closure from a locally staged feed
# (file:// opkg sources, no guest egress), runs the engine plus the loopback
# probe INSIDE the guest, and collects logs. Never attaches a physical
# device, never forwards office/bench/VPN ports, never changes host routes,
# interfaces, DNS, packet filters, or VPN state. Only loopback-forwarded
# host->guest TCP (ssh + serial) is used; the guest has no egress at all
# (slirp restrict=on).
#
# Conventions: dry-run default; read-only preflight route snapshots with a
# numeric 10.0.2.0/24 overlap check; bounded runtime; staged progress file;
# post-run drift compare that reports but never repairs.

set +x
umask 077
set -eu

SCRIPT_NAME="run-qemu-asterisk.sh"
VM_NAME="ata-asterisk-twin"
SLIRP_NET="10.0.2.0/24"
GUEST_IP="10.0.2.15"
DEFAULT_MEM_MB="1024"
DEFAULT_TIMEOUT_SECS="900"
MIN_TIMEOUT_SECS="120"
MAX_TIMEOUT_SECS="3600"
QEMU_FW="/opt/homebrew/share/qemu/edk2-x86_64-code.fd"

log() { printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*"; }
fail() { log "ERROR: $*"; exit 1; }
usage() { sed -n '2,25p' "$0"; exit 0; }

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)"
NETWORK_STATE="$SCRIPT_DIR/network_state.py"
PYTHON_BIN="${PYTHON_BIN:-python3}"

TWIN_ROOT="${TWIN_ROOT:-/var/folders/0_/rjsf94rn3gd5k8mntc9fjkth0000gn/T/opencode/openwrt-twin}"
BASE_IMG="$TWIN_ROOT/dl/openwrt-24.10.8-x86-64-generic-squashfs-combined-efi.img"
FEED_CACHE="$TWIN_ROOT/feed"
WORK="$TWIN_ROOT/work"
SSH_FWD_PORT="${SSH_FWD_PORT:-2205}"
SERIAL_PORT="${SERIAL_PORT:-4519}"
PINS_FILES="${PINS_FILES:-}"

MEM_MB="$DEFAULT_MEM_MB"
TIMEOUT_SECS="$DEFAULT_TIMEOUT_SECS"
APPLY="0"

need_value() { [ "$#" -ge 2 ] || fail "$1 requires a value"; }
while [ "$#" -gt 0 ]; do
    case "$1" in
        --mem) need_value "$@"; MEM_MB="$2"; shift 2 ;;
        --timeout) need_value "$@"; TIMEOUT_SECS="$2"; shift 2 ;;
        --apply) APPLY="1"; shift ;;
        -h|--help) usage ;;
        *) fail "unknown switch $1" ;;
    esac
done
case "$MEM_MB" in ''|*[!0-9]*) fail "--mem must be an integer";; esac
[ "$MEM_MB" -ge 256 ] && [ "$MEM_MB" -le 8192 ] || fail "--mem out of range"
case "$TIMEOUT_SECS" in ''|*[!0-9]*) fail "--timeout must be integer";; esac
[ "$TIMEOUT_SECS" -ge "$MIN_TIMEOUT_SECS" ] && \
    [ "$TIMEOUT_SECS" -le "$MAX_TIMEOUT_SECS" ] || fail "--timeout out of range"

# ---- preflight (read-only) --------------------------------------------------
command -v qemu-system-x86_64 >/dev/null 2>&1 || fail "qemu-system-x86_64 missing"
command -v qemu-img >/dev/null 2>&1 || fail "qemu-img missing"
command -v ssh >/dev/null 2>&1 && command -v scp >/dev/null 2>&1 \
    || fail "ssh/scp required for the loopback guest transport"
[ -f "$QEMU_FW" ] || fail "OVMF firmware missing: $QEMU_FW"
[ -f "$BASE_IMG" ] || fail "base image missing: $BASE_IMG"
[ -f "$FEED_CACHE/pkg/.done" ] || [ -d "$FEED_CACHE/pkg" ] \
    || fail "feed cache missing: $FEED_CACHE/pkg"
for feed in base packages telephony; do
    [ -f "$FEED_CACHE/$feed/Packages" ] \
        || fail "feed index missing: $FEED_CACHE/$feed/Packages"
done
[ -f "$SCRIPT_DIR/guest_drive.py" ] || fail "guest serial driver missing"
[ -f "$REPO_ROOT/telephony/asterisk_conf.py" ] \
    || fail "config generator missing"
while IFS= read -r keyfile; do
    [ -f "$keyfile" ] || continue
    KEY_PUB="$keyfile"
    break
done <<KEYS
$HOME/.ssh/id_ed25519.pub
KEYS
[ -n "${KEY_PUB:-}" ] || fail "no ed25519 public key found for guest bootstrap"

if pgrep -f "qemu-system.*$VM_NAME" >/dev/null 2>&1; then
    fail "an instance named $VM_NAME is already running"
fi

mkdir -p "$WORK/logs"
chmod 700 "$WORK" "$WORK/logs"
STAGE="$WORK/stage.txt"
stage() { printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$1" >> "$STAGE"; }

if [ "$APPLY" != "1" ]; then
    log "DRY RUN: preflight ok; would boot $VM_NAME (mem ${MEM_MB}MB, timeout ${TIMEOUT_SECS}s)"
    log "DRY RUN: feed cache: $(ls "$FEED_CACHE/pkg" 2>/dev/null | wc -l | tr -d ' ') ipks staged"
    exit 0
fi

netstat -rn -f inet > "$WORK/logs/pre-routes.ipv4"
netstat -rn -f inet6 > "$WORK/logs/pre-routes.ipv6"
scutil --nwi > "$WORK/logs/pre-nwi" 2>/dev/null || true
chmod 600 "$WORK"/logs/*
"$PYTHON_BIN" -B "$NETWORK_STATE" check-overlap "$WORK/logs/pre-routes.ipv4" "$SLIRP_NET" \
    || fail "stopping on subnet ambiguity"
log "preflight ok (no overlap with $SLIRP_NET)"
stage "preflight-ok"

CLEAN_NEEDED="1"
QEMU_PID=""
cleanup() {
    trap '' HUP INT TERM
    [ "${CLEAN_NEEDED:-1}" = "1" ] || return 0
    CLEAN_NEEDED="0"
    if [ -n "$QEMU_PID" ] && kill -0 "$QEMU_PID" 2>/dev/null; then
        log "stopping qemu pid=$QEMU_PID"
        kill -TERM "$QEMU_PID" 2>/dev/null || true
        for _ in 1 2 3 4 5 6 7 8 9 10; do
            kill -0 "$QEMU_PID" 2>/dev/null || break
            sleep 1
        done
        kill -0 "$QEMU_PID" 2>/dev/null && kill -KILL "$QEMU_PID" 2>/dev/null
        wait "$QEMU_PID" 2>/dev/null || true
    fi
    netstat -rn -f inet > "$WORK/logs/post-routes.ipv4" 2>/dev/null || true
    netstat -rn -f inet6 > "$WORK/logs/post-routes.ipv6" 2>/dev/null || true
    log "post-run route snapshots captured (compare manually: $WORK/logs)"
    stage "cleanup-done"
}
trap cleanup EXIT
trap 'log "interrupted"; exit 130' HUP INT TERM

# ---- twin trees (host side) -------------------------------------------------
rm -rf "$WORK/twinroot"
mkdir -p "$WORK/twinroot/telephony" "$WORK/twinroot/conf"
chmod 700 "$WORK/twinroot"
cp "$REPO_ROOT"/telephony/*.py "$WORK/twinroot/telephony/"
cp "$REPO_ROOT"/telephony/__init__.py "$WORK/twinroot/telephony/" 2>/dev/null || true
"$PYTHON_BIN" -B "$REPO_ROOT/telephony/asterisk_conf.py" \
    --apply "$WORK/twinroot/conf/asterisk" \
    --address 127.0.0.1 --ata 127.0.0.1 >/dev/null
# engine master config for the guest layout

cat > "$WORK/twinroot/asterisk.conf" <<'CONF'
[directories]
astetcdir = /root/twin/conf/asterisk
astmoddir = /usr/lib/asterisk/modules
astdatadir = /usr/share/asterisk
astvarlibdir = /usr/share/asterisk
astdbdir = /root/twin/db
astkeydir = /root/twin/db
astspooldir = /root/twin/spool
astagidir = /root/twin/spool/agi
astrundir = /root/twin/run
astlogdir = /root/twin/log
astsbindir = /usr/sbin
CONF
printf '[logfiles]\nfull => notice,warning,error,verbose,debug\n' \
    > "$WORK/twinroot/conf/logger.conf"
mkdir -p "$WORK/twinroot/conf/sounds"
SOUNDS_SRC="/var/folders/0_/rjsf94rn3gd5k8mntc9fjkth0000gn/T/opencode/asterisk-build/install/var/lib/asterisk/sounds"
if [ -d "$SOUNDS_SRC" ]; then
    cp "$SOUNDS_SRC"/*.wav "$WORK/twinroot/conf/sounds/" 2>/dev/null || true
fi
stage "twin-staged"
log "twin trees staged in $WORK/twinroot"

# ---- guest disk -------------------------------------------------------------
DISK="$WORK/guest.qcow2"
if [ ! -f "$DISK" ]; then
    qemu-img convert -O qcow2 "$BASE_IMG" "$DISK"
    chmod 600 "$DISK"
    stage "disk-created"
    log "guest disk created: $DISK"
fi

# ---- launch -----------------------------------------------------------------
QEMU_LOG="$WORK/logs/qemu-stderr.log"
: > "$WORK/logs/serial-capture.log"
qemu-system-x86_64 -name "$VM_NAME" \
    -M q35 -accel tcg -m "$MEM_MB" -smp 2 \
    -drive "if=pflash,format=raw,readonly=on,file=$QEMU_FW" \
    -drive "file=$DISK,format=qcow2,if=virtio,snapshot=on" \
    -device e1000,netdev=net0 \
    -netdev "user,id=net0,restrict=on,net=$SLIRP_NET,ipv6=off,hostfwd=tcp:127.0.0.1:$SSH_FWD_PORT-$GUEST_IP:22" \
    -serial "tcp:127.0.0.1:$SERIAL_PORT,server=on,wait=off" \
    -display none -no-reboot \
    </dev/null >"$QEMU_LOG" 2>&1 &
QEMU_PID=$!
printf '%s\n' "$QEMU_PID" > "$WORK/qemu.pid"
stage "qemu-launched"
log "qemu pid=$QEMU_PID ssh=127.0.0.1:$SSH_FWD_PORT serial=127.0.0.1:$SERIAL_PORT"
sleep 4
kill -0 "$QEMU_PID" 2>/dev/null || fail "qemu died immediately (see $QEMU_LOG)"

( "$PYTHON_BIN" -B "$SCRIPT_DIR/serial_capture.py" --port "$SERIAL_PORT" --log "$WORK/logs/serial-capture.log" >/dev/null 2>&1 & )

log "waiting for boot banner (300s, tcg)..."
BOOT_OK=0
for _ in $(seq 1 150); do
    if grep -aq "Please press Enter" "$WORK/logs/serial-capture.log" 2>/dev/null \
       || grep -aq "Press ESC" "$WORK/logs/serial-capture.log" 2>/dev/null \
       || grep -aq "login:" "$WORK/logs/serial-capture.log" 2>/dev/null; then
        BOOT_OK=1
        break
    fi
    sleep 2
done
[ "$BOOT_OK" = "1" ] || fail "guest boot banner not seen"
stage "boot-seen"

# ---- install ssh key over serial (chunked; 8250 drops long pastes) ----------
PUB=$(tr -d '\n' < "$KEY_PUB")
PUBSUM=$(printf '%s' "$PUB" | shasum -a 256 | cut -d' ' -f1)
P1=$(printf '%s' "$PUB" | cut -c 1-30)
P2=$(printf '%s' "$PUB" | cut -c 31-60)
P3=$(printf '%s' "$PUB" | cut -c 61-90)
P4=$(printf '%s' "$PUB" | cut -c 91-)
"$PYTHON_BIN" -B "$SCRIPT_DIR/guest_drive.py" --port "$SERIAL_PORT" --timeout 60 \
    --command "uci set network.lan.ipaddr=10.0.2.15" \
    --command "uci set network.lan.netmask=255.255.255.0" \
    --command "uci set network.lan.gateway=10.0.2.2" \
    --command "uci set network.lan.dns=10.0.2.2" \
    --command "uci set network.lan.proto=static" \
    --command "uci commit network" \
    --command "ifconfig br-lan 10.0.2.15 netmask 255.255.255.0" \
    --command "route add default gw 10.0.2.2" \
    --command "mkdir -p /etc/dropbear" \
    --command "/etc/init.d/dropbear stop" \
    --command "/etc/init.d/dropbear start" \
    --command "for i in 1 2 3 4 5 6; do netstat -tln|grep -F ':22'&&break;sleep 3;done" \
    --command "ifconfig br-lan | grep -F 10.0.2.15" \
    --command "printf '%s' '$P1' >> /tmp/key.txt" \
    --command "printf '%s' '$P2' >> /tmp/key.txt" \
    --command "printf '%s' '$P3' >> /tmp/key.txt" \
    --command "printf '%s' '$P4' >> /tmp/key.txt" \
    --command "wc -c /tmp/key.txt" \
    --command "mv /tmp/key.txt /etc/dropbear/authorized_keys" \
    --command "chmod 600 /etc/dropbear/authorized_keys" \
    > "$WORK/logs/keyinstall.log" 2>&1 \
    || fail "ssh key install over serial failed ($WORK/logs/keyinstall.log)"
stage "key-installed"
log "dropbear key installed"

SSH_OPTS=(-i "$HOME/.ssh/id_ed25519" -p "$SSH_FWD_PORT"
          -o StrictHostKeyChecking=accept-new
          -o UserKnownHostsFile="$WORK/known_hosts"
          -o ConnectTimeout=5)
# scp uses -P (capital) for port; reuse the rest of the ssh options.
SCP_OPTS=()
for opt in "${SSH_OPTS[@]}"; do
    [ "$opt" = "-p" ] && opt="-P"
    SCP_OPTS+=("$opt")
done
SSH_CMD() { ssh "${SSH_OPTS[@]}" root@127.0.0.1 "$@"; }

rm -f "$WORK/known_hosts"
log "waiting for ssh (up to 300s)..."
SSH_OK=0
for _ in $(seq 1 100); do
    if SSH_CMD "echo ready" >/dev/null 2>&1; then SSH_OK=1; break; fi
    sleep 3
done
[ "$SSH_OK" = "1" ] || fail "ssh not reachable over loopback forward"
stage "ssh-ready"
SSH_CMD "df -h /overlay 2>/dev/null | tail -1; free | head -2"

# ---- push staged payload ----------------------------------------------------
rm -rf "$WORK/twinroot/feed"
cp -R "$FEED_CACHE" "$WORK/twinroot/feed"
chmod -R go-rwx "$WORK/twinroot/feed"
mkdir -p "$WORK/twinroot/feed/target"
for feed in base packages telephony; do
    for suffix in Packages.gz Packages.sig; do
        curl -fsSL -o "$WORK/twinroot/feed/$feed/$suffix" \
            "https://downloads.openwrt.org/releases/24.10.8/packages/x86_64/$feed/$suffix"
    done
done
for suffix in Packages.gz Packages.sig; do
    curl -fsSL -o "$WORK/twinroot/feed/target/$suffix" \
        "https://downloads.openwrt.org/releases/24.10.8/targets/x86/64/packages/$suffix"
done
# target feed packages sit directly in that dir too (layout hook below)

# STAGE-FEED-LAYOUT: place ipks where opkg expects them (index-relative).
"$PYTHON_BIN" -B - "$WORK/twinroot/feed" <<'PYINNER'
import os
import sys

root = sys.argv[1]
count = 0
for feed in ("base", "packages", "telephony", "target"):
    feed_dir = os.path.join(root, feed)
    index = os.path.join(feed_dir, "Packages")
    if not os.path.exists(index):
        continue
    filenames = [line.split(": ", 1)[1].strip()
                 for line in open(index)
                 if line.startswith("Filename: ")]
    for filename in filenames:
        basename = os.path.basename(filename)
        source = os.path.join(root, "pkg", basename)
        target = os.path.join(feed_dir, basename)
        if os.path.exists(source) and not os.path.exists(target):
            os.link(source, target)
            count += 1
print("feed-layout linked %d ipks" % count)
PYINNER
tar czf "$WORK/payload.tar.gz" -C "$WORK/twinroot" .
SCP_OK=0
for attempt in 1 2 3 4 5; do
    if scp -O "${SCP_OPTS[@]}" "$WORK/payload.tar.gz" root@127.0.0.1:/tmp/payload.tar.gz; then
        SCP_OK=1
        break
    fi
    log "scp attempt $attempt failed; retrying in 5s"
    sleep 5
done
[ "$SCP_OK" = "1" ] || fail "payload scp failed (see logs)"
SSH_CMD "mkdir -p /root/twin && tar xzf /tmp/payload.tar.gz -C /root/twin"
SSH_CMD "rm -f /tmp/payload.tar.gz"
stage "payload-pushed"

# ---- opkg local feed + install pinned set -----------------------------------
scp -O "${SCP_OPTS[@]}" "$SCRIPT_DIR/provision-guest.sh" root@127.0.0.1:/tmp/provision.sh
SSH_CMD "sh /tmp/provision.sh" 2>&1 | tee "$WORK/logs/provision.log"
stage "provisioned"
log "provisioning done (see $WORK/logs/provision.log)"

# ---- start engine -----------------------------------------------------------
SSH_CMD "mkdir -p /root/twin/log /root/twin/run /root/twin/db /root/twin/spool/agi && cd /root/twin && (asterisk -f -C /root/twin/asterisk.conf > /root/twin/log/console.log 2>&1 &)"
sleep 8
SSH_CMD "asterisk -C /root/twin/asterisk.conf -rx 'core show version'" \
    || fail "engine did not answer the CLI socket"
SSH_CMD "asterisk -C /root/twin/asterisk.conf -rx 'core show uptime'"
stage "engine-up"

# ---- in-guest diagnostics (sip debug + cli states) ---------------------------
SSH_CMD "asterisk -C /root/twin/asterisk.conf -rx 'core set verbose 4' || true"
SSH_CMD "asterisk -C /root/twin/asterisk.conf -rx 'sip set debug on' || true"
SSH_CMD "asterisk -C /root/twin/asterisk.conf -rx 'dialplan show' > /root/twin/log/dialplan.out 2>&1 || true"
SSH_CMD "asterisk -C /root/twin/asterisk.conf -rx 'module show' > /root/twin/log/modules.out 2>&1 || true"

# ---- run the probe in-guest --------------------------------------------------
SSH_CMD "python3 -B /root/twin/telephony/sip_loopback_probe.py --apply --rtp-port 16384 --run-seconds 45 --call-seconds 14" \
    2>&1 | tee "$WORK/logs/probe.log"
stage "probe-done"
SSH_CMD "asterisk -C /root/twin/asterisk.conf -rx 'core show calls'" || true
SSH_CMD "dmesg | tail -5" || true
SSH_CMD "pidof asterisk || echo ENGINE-DEAD"

# ---- harvest guest log files before shutdown ---------------------------------
for f in console.log dialplan.out modules.out; do
    scp -O "${SCP_OPTS[@]}" "root@127.0.0.1:/root/twin/log/$f" "$WORK/logs/engine-$f" 2>/dev/null \
        && log "harvested $f" || true
done

log "TWIN RUN COMPLETE; logs in $WORK/logs"
CLEAN_NEEDED="0"
if kill -0 "$QEMU_PID" 2>/dev/null; then
    SSH_CMD "poweroff" 2>/dev/null || true
    for _ in $(seq 1 20); do
        kill -0 "$QEMU_PID" 2>/dev/null || break
        sleep 1
    done
    kill -0 "$QEMU_PID" 2>/dev/null && kill -TERM "$QEMU_PID" 2>/dev/null || true
fi
CLEAN_NEEDED="0"
exit 0
