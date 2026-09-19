#!/bin/sh
# Fetch the pinned SIP.js browser bundle into webrtc/vendor/sip.min.js.
# Dry-run by default; --apply downloads and verifies the supplied SHA256.
# No CDN dependency at page runtime; the artifact is gitignored.
umask 077
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
DEST="$HERE/sip.min.js"
URL="${SIPJS_URL:-https://github.com/onsip/SIP.js/releases/download/0.21.2/sip-0.21.2.min.js}"
SHA=""
APPLY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --sha256) SHA="${2:-}"; shift 2 ;;
    --url)    URL="${2:-}"; shift 2 ;;
    --apply)  APPLY=1; shift ;;
    *) echo "usage: $0 [--sha256 HEX] [--url URL] [--apply]"; exit 2 ;;
  esac
done
echo "url:  $URL"
echo "dest: $DEST"
[ -n "$SHA" ] || { echo "REFUSING: pass --sha256 of the reviewed artifact"; exit 3; }
if [ "$APPLY" -eq 0 ]; then
  echo "DRY-RUN: would download and verify sha256=$SHA; nothing written"
  exit 0
fi
TMP="$DEST.tmp.$$"
trap 'rm -f "$TMP"' EXIT
curl -fsSL "$URL" -o "$TMP" || { echo "download failed"; exit 4; }
ACTUAL=$(shasum -a 256 "$TMP" | awk '{print $1}')
[ "$ACTUAL" = "$SHA" ] || { echo "SHA MISMATCH: got $ACTUAL"; exit 5; }
mv "$TMP" "$DEST"
trap - EXIT
echo "WROTE $DEST sha256=$ACTUAL"
