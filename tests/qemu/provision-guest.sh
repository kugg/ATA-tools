#!/bin/sh
# provision-guest.sh -- runs INSIDE the twin guest (see run-qemu-asterisk.sh).
# Installs the pinned Asterisk 20.8.1-r1 module set from the staged local
# feed cache; no network egress is configured or used: every default feed
# is replaced with the local staged file:// sources.

set -x

cd /root/twin/feed || exit 1

# Rewrite all opkg sources: only the locally staged feeds, no egress.
cat > /etc/opkg/distfeeds.conf <<LOCALFEEDS
src/gz ata_base file:///root/twin/feed/base
src/gz ata_packages file:///root/twin/feed/packages
src/gz ata_telephony file:///root/twin/feed/telephony
src/gz ata_target file:///root/twin/feed/target
LOCALFEEDS
: > /etc/opkg/customfeeds.conf

for feed in base packages telephony target; do
    test -f /root/twin/feed/$feed/Packages.sig || exit 1
done
opkg update || exit 1

# Pinned set per docs/asterisk-integration.md (Phase 1-3 local stages).
opkg install asterisk asterisk-chan-sip asterisk-codec-ulaw \
    asterisk-codec-alaw asterisk-res-rtp-asterisk asterisk-app-read \
    asterisk-app-audiosocket asterisk-app-externalivr asterisk-res-agi \
    asterisk-res-http-websocket python3 python3-light || exit 1

asterisk -V || exit 1

# Which RTP/timing modules shipped in this build (segfault trap check).
echo "--- rtp/timing modules ---"
ls /usr/lib/asterisk/modules/ | grep -Ei "rtp|timing" || true

# Show the resolved dependency state of the engine (manifest evidence).
echo "--- asterisk package info ---"
opkg info asterisk | head -6
echo "--- depends ---"
opkg info asterisk | grep "^Depends" || true
echo provision-ok
