#!/bin/sh
# apu2-asterisk-dtls-preload.sh
# Give ONLY Asterisk the DTLS-enabled OpenSSL build; leave the box's system
# OpenSSL untouched (dropbear/SSH and every other service keep the stock libs).
#
# Why: OpenWrt ships libopenssl built with `no-dtls`, so Asterisk's DTLS-SRTP
# (required for WebRTC media) fails with "no protocols available". Instead of
# replacing the system library, we stage the DTLS build privately and preload it
# for the asterisk process only.
#
#   libs    : /usr/lib/asterisk-dtls/{libssl.so.3,libcrypto.so.3}  (DTLS build)
#   wrapper : /usr/sbin/asterisk  (script)  ->  exec /usr/sbin/asterisk.real
#             with LD_PRELOAD pointing at the private libs.
#
# AGENTS: dry-run default; --apply is the only state-writing flag (operator
# attended); --rollback restores the real binary and removes the private libs.
# The system /usr/lib/libssl.so.3 and libcrypto.so.3 are never modified.
umask 077
set -u
HOST="${APU2_HOST:-root@10.47.11.97}"
LIBSRC="${DTLS_LIB_DIR:-/tmp/dtls-libs-final}"
LIBDIR="/usr/lib/asterisk-dtls"
WRAPPER="/usr/sbin/asterisk"
REAL="/usr/sbin/asterisk.real"
MODE="${1:-}"

echo "=== preflight (read-only) ==="
for f in libssl.so.3 libcrypto.so.3; do
  test -f "$LIBSRC/$f" || { echo "LOCAL-MISS:$LIBSRC/$f"; exit 3; }
  echo "local $f: $(wc -c < "$LIBSRC/$f")B sha256=$(shasum -a 256 "$LIBSRC/$f" | cut -c1-16)"
done
ssh -o BatchMode=yes -o ConnectTimeout=15 "$HOST" '
  echo "asterisk-bin:$(file /usr/sbin/asterisk 2>/dev/null | cut -d: -f2 | cut -c1-40)"
  echo "real-exists:$(test -f /usr/sbin/asterisk.real && echo YES || echo NO)"
  echo "libdir-exists:$(test -d /usr/lib/asterisk-dtls && echo YES || echo NO)"
  echo "asterisk-running:$(test -f /var/run/asterisk/asterisk.pid && echo YES || echo NO)"
' 2>&1 | grep -viE "WARNING:connection is not|post-quantum|store now|decrypt later|need to be upgraded|openssh.com/pq"

if [ "$MODE" = "--rollback" ]; then
  echo "=== ROLLBACK (attended) ==="
  ssh -o BatchMode=yes -o ConnectTimeout=20 "$HOST" "
    if [ -f $REAL ]; then
      rm -f $WRAPPER && mv $REAL $WRAPPER && echo restored-real-binary
    else
      echo no-real-binary-nothing-to-restore
    fi
    rm -rf $LIBDIR && echo removed-libs
    /etc/init.d/asterisk restart >/dev/null 2>&1; sleep 8
    echo \"after: asterisk=\$(pgrep -f /usr/sbin/asterisk | wc -l) 5060=\$(netstat -tuln 2>/dev/null | grep -c ':5060 ')\"
  " 2>&1 | grep -viE "WARNING:connection is not|post-quantum|store now|decrypt later|need to be upgraded|openssh.com/pq"
  exit 0
fi

if [ "$MODE" != "--apply" ]; then
  echo
  echo "DRY-RUN: would do (attended --apply):"
  echo "  1) mkdir -p $LIBDIR ; copy the two DTLS libs there (chmod 755)"
  echo "  2) mv $WRAPPER -> $REAL ; install wrapper at $WRAPPER with"
  echo "     LD_PRELOAD=$LIBDIR/libssl.so.3:$LIBDIR/libcrypto.so.3"
  echo "  3) /etc/init.d/asterisk restart"
  echo "  4) verify: process up, DTLS libs mapped, 5060 listening, ATA registered"
  echo "ROLLBACK: $0 --rollback"
  exit 0
fi

echo "=== APPLY (operator-attended) ==="
ssh -o BatchMode=yes -o ConnectTimeout=20 "$HOST" "mkdir -p $LIBDIR" || exit 4
scp -O -q "$LIBSRC/libssl.so.3"    "$HOST:$LIBDIR/libssl.so.3"    || exit 5
scp -O -q "$LIBSRC/libcrypto.so.3" "$HOST:$LIBDIR/libcrypto.so.3" || exit 5
ssh -o BatchMode=yes -o ConnectTimeout=20 "$HOST" "
  chmod 755 $LIBDIR/libssl.so.3 $LIBDIR/libcrypto.so.3
  if [ ! -f $REAL ]; then mv $WRAPPER $REAL; fi
  cat > $WRAPPER <<'EOF'
#!/bin/sh
# Asterisk-only DTLS-enabled OpenSSL (system libopenssl untouched).
# Managed by tests/apu2/apu2-asterisk-dtls-preload.sh ; real binary: asterisk.real
LD_PRELOAD=/usr/lib/asterisk-dtls/libssl.so.3:/usr/lib/asterisk-dtls/libcrypto.so.3
export LD_PRELOAD
exec /usr/sbin/asterisk.real \"\$@\"
EOF
  chmod 755 $WRAPPER
  /etc/init.d/asterisk restart >/dev/null 2>&1
  sleep 10
  PID=\$(cat /var/run/asterisk/asterisk.pid 2>/dev/null)
  echo \"proc:\$(pgrep -f /usr/sbin/asterisk | wc -l) 5060:\$(netstat -tuln 2>/dev/null | grep -c ':5060 ')\"
  echo \"dtls-libs-mapped:\$(grep -c asterisk-dtls /proc/\$PID/maps 2>/dev/null)\"
  echo \"system-libssl-untouched: \$(md5sum /usr/lib/libssl.so.3 | cut -c1-8)\"
" 2>&1 | grep -viE "WARNING:connection is not|post-quantum|store now|decrypt later|need to be upgraded|openssh.com/pq"
echo "=== done. Verify with: node tests/apu2/webrtc-echo-test.mjs ==="
