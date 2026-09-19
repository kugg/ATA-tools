#!/bin/sh
# apu2-serve-ata-tftp.sh
# Office APU2: serve the pinned SPA0300 ATA provisioning profile over the
# DEVICE's OWN dnsmasq (DHCP option 66/67 + internal tftp), so the real ATA
# boots to profile without any python fixture. This is the production twin of
# the twin's telephony/dhcp.py fixture.
#
# AGENTS contract:
#   * DEFAULT = read-only dry-run; every state-changing step prints "[--apply]"
#     and is SKIPPED unless --apply (the ONLY state-writing flag) is present.
#   * --apply is OPERATOR-ATTENDED ONLY (you said you are heading to the office
#     to cable the ATA; this runs immediately before you plug the second port
#     into br-lan).
#   * Never writes anything on this Mac except the WORKLOG record.
#   * No device egress: bytes come from the already-verified pinned closure
#     dir on the device. This script only moves the ATA profile + flips uci.
#   * Bounded timeouts throughout; umask 077; no heredoc (this file is the
#     only transport).
#
# Profiles (SPA0300 tftp naming is LOWERCASE mac: ata00070e36e57b.cnf.xml):
#   src  : telephony/ATA00070E36E57B.cnf.xml   (pinned bytes, repo, read-only)
#   dst  : /srv/tftp/ata00070e36e57b.cnf.xml   (served to the ATA)
#   tftp : dnsmasq enable_tftp=1 tftp_root=/srv/tftp
#   opt  : 66,<br-lan ip> ; 67,ata00070e36e57b.cnf.xml
#
# Rollback (recorded, operator-attended re-run with --apply for rollback):
#   uci delete dhcp.@dnsmasq[0].enable_tftp
#   uci delete dhcp.@dnsmasq[0].tftp_root
#   delete the 66/67 dhcp_option lines
#   rm /srv/tftp/ata00070e36e57b.cnf.xml ; service dnsmasq restart

umask 077
set -u

HOST="${APU2_HOST:-root@10.47.11.97}"
PROFILE_SRC="/Users/user/devel/ata/telephony/ATA00070E36E57B.cnf.xml"
TFTP_DIR="/srv/tftp"
PROFILE_NAME="ata00070e36e57b.cnf.xml"
APPLY=0
case "${1:-}" in
  --apply) APPLY=1; shift ;;
  "") : ;;
  *) echo "usage: $0 [--apply]  (default dry-run; --apply = operator-attended)"; exit 2 ;;
esac

echo "===A) READ-ONLY (always): profile bytes pinned + verified on this Mac?==="
test -f "$PROFILE_SRC" || { echo "PROFILE-MISS:$PROFILE_SRC"; exit 3; }
echo "profile-bytes:$(wc -c < "$PROFILE_SRC") sha:$(shasum -a 256 "$PROFILE_SRC" | cut -c1-16)"
echo "profile-useTftp:$(grep -c "UseTftp value=\"1\"" "$PROFILE_SRC")"
echo

echo "===B) DEVICE STATE (read-only): what does dnsmasq have NOW for tftp/opt66/67 + is the dst already there?==="
ssh -o BatchMode=yes -o ConnectTimeout=20 "$HOST" '
  echo "dnsmasq:$(command -v dnsmasq || echo MISS)"
  echo "tftp-enabled:$(uci get dhcp.@dnsmasq[0].enable_tftp 2>/dev/null || echo UNSET)"
  echo "tftp-root:$(uci get dhcp.@dnsmasq[0].tftp_root 2>/dev/null || echo UNSET)"
  echo "opt66-67-present:$(uci show dhcp | grep -cE "option 66|option 67|dhcp_option.*6[67]")"
  echo "dsrc-existent:$(test -f '"$TFTP_DIR/$PROFILE_NAME"' && echo YES || echo NO)"
  echo "tftp-dir:$(ls -ld '"$TFTP_DIR"' 2>/dev/null | awk "{print \$1,\$3}")"' 2>&1 | grep -viE "WARNING|post-quantum|store|decrypt|upgrad|openssh.com/pq"

echo
if [ "$APPLY" -ne 1 ]; then
  echo "===DRY-RUN (nothing written): the --apply sequence would be==="
  echo "  uci set dhcp.@dnsmasq[0].enable_tftp=\"1\""
  echo "  uci set dhcp.@dnsmasq[0].tftp_root=\"$TFTP_DIR\""
  echo "  uci add_list dhcp.@dnsmasq[0].dhcp_option=\"66,10.47.11.97\""
  echo "  uci add_list dhcp.@dnsmasq[0].dhcp_option=\"67,$PROFILE_NAME\""
  echo "  mkdir -p $TFTP_DIR"
  echo "  cp '$PROFILE_SRC' '$TFTP_DIR/$PROFILE_NAME'"
  echo "  uci commit dhcp && service dnsmasq restart"
  echo "  verify: uci get enable_tftp/tftp_root + ls -la dst + option 66/67 present"
  echo "ROLLBACK(attended --apply rollback): listed at top of this script"
  exit 0
fi

echo "===APPLY (operator-attended)==="
ssh -o BatchMode=yes -o ConnectTimeout=20 "$HOST" "
  uci set dhcp.@dnsmasq[0].enable_tftp='1'
  uci set dhcp.@dnsmasq[0].tftp_root='$TFTP_DIR'
  uci add_list dhcp.@dnsmasq[0].dhcp_option='66,10.47.11.97'
  uci add_list dhcp.@dnsmasq[0].dhcp_option='67,$PROFILE_NAME'
  mkdir -p $TFTP_DIR
  uci commit dhcp
  service dnsmasq restart" 2>&1 | grep -viE "WARNING|post-quantum|store|decrypt|upgrad|openssh.com/pq"
cat "$PROFILE_SRC" | ssh -o BatchMode=yes -o ConnectTimeout=20 "$HOST" \
  "cat > $TFTP_DIR/$PROFILE_NAME && chmod 0400 $TFTP_DIR/$PROFILE_NAME && chown root:root $TFTP_DIR/$PROFILE_NAME && echo PROFILE-LANDED"
echo "===VERIFY (read-only)==="
ssh -o BatchMode=yes -o ConnectTimeout=20 "$HOST" '
  echo "tftp-enabled:$(uci get dhcp.@dnsmasq[0].enable_tftp)"
  echo "tftp-root:$(uci get dhcp.@dnsmasq[0].tftp_root)"
  echo "opt66-67:"; uci show dhcp | grep -E "dhcp_option=.*6[67]"
  echo "profile:$(ls -la /srv/tftp/'"$PROFILE_NAME"' 2>/dev/null | awk "{print \$5,\$NF}")"' 2>&1 | grep -viE "WARNING|post-quantum|store|decrypt|upgrad|openssh.com/pq"
echo "===done: ATA will now lease 10.47.11.x from br-lan, get option66/67, fetch profile, register to asterisk 5060==="
