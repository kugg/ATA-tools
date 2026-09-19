#!/bin/sh
# Stage the WebRTC site draft onto the office APU's uhttpd docroot.
#   -> /www/webrtc/  (served at https://<apu>/webrtc/ once certs exist)
#
# AGENTS contract:
#   * DEFAULT = read-only dry-run. --apply is the ONLY state-writing flag and is
#     operator-attended. This script writes site files ONLY; it never touches
#     Asterisk config, packages, or firewall (Phase 4 engine work is separate
#     and gated).
#   * Bounded timeouts; no device egress; umask 077.
#   * Rollback: rm -rf /www/webrtc  (project-owned path only).
umask 077
set -u
HOST="${APU2_HOST:-root@10.47.11.97}"
REPO="/Users/user/devel/ata"
SITE="$REPO/webrtc/site"
VENDOR="$REPO/webrtc/vendor/sip.min.js"
DEST="/www/webrtc"
APPLY=0
case "${1:-}" in
  --apply) APPLY=1 ;;
  "") : ;;
  *) echo "usage: $0 [--apply]  (default dry-run)"; exit 2 ;;
esac

echo "=== preflight (read-only) ==="
test -d "$SITE" || { echo "SITE-MISS:$SITE"; exit 3; }
test -f "$VENDOR" || echo "WARN: $VENDOR missing (run webrtc/vendor/fetch-sipjs.sh first)"
ssh -o BatchMode=yes -o ConnectTimeout=15 "$HOST" '
  echo "uhttpd:$(test -x /etc/init.d/uhttpd && echo present || echo MISSING)"
  echo "www:$(ls -ld /www 2>/dev/null | awk "{print \$1, \$3}")"
  echo "pjsip/srtp modules:$(ls /usr/lib/asterisk/modules 2>/dev/null | grep -cE "pjsip|res_srtp") (0 = Phase 4 packages not installed yet)"
  echo "webrtc cert:$(test -f /etc/asterisk/keys/webrtc.crt && echo present || echo absent)"
' 2>&1 | grep -viE "WARNING:connection is not|post-quantum|store now|decrypt later|need to be upgraded|openssh.com/pq"
echo "would-copy: $SITE/{index.html,app.js,style.css,config.js} -> $HOST:$DEST/"
echo "would-copy: $VENDOR -> $HOST:$DEST/vendor/sip.min.js"

if [ "$APPLY" -eq 0 ]; then
  echo "DRY-RUN: nothing written. Re-run with --apply (operator-attended)."
  exit 0
fi

echo "=== APPLY (operator-attended) ==="
ssh -o BatchMode=yes -o ConnectTimeout=20 "$HOST" "mkdir -p $DEST/vendor" || exit 4
for f in index.html app.js style.css config.js; do
  scp -O -q "$SITE/$f" "$HOST:$DEST/$f" || { echo "COPY-FAIL:$f"; exit 5; }
done
if [ -f "$VENDOR" ]; then
  scp -O -q "$VENDOR" "$HOST:$DEST/vendor/sip.min.js" || { echo "COPY-FAIL:sip.min.js"; exit 5; }
fi
ssh -o BatchMode=yes -o ConnectTimeout=15 "$HOST" \
  "chmod 755 $DEST $DEST/vendor; chmod 644 $DEST/*.html $DEST/*.js $DEST/*.css; chmod 644 $DEST/vendor/*.js 2>/dev/null; ls -la $DEST" \
  2>&1 | grep -viE "WARNING:connection is not|post-quantum|store now|decrypt later|need to be upgraded|openssh.com/pq"
echo "=== done: site staged at https://<apu>/webrtc/ (engine configs still gated) ==="
