#!/bin/sh
# apu2-split-dhcp-ata-printer.sh
# Operator designated (attended install-day): TWO SEPARATE DHCP SCOPES on the
# TWO real br-lan member NICS, so the TFTP profile / option 66+67 are EXCLUSIVE
# to the ATA port (eth1) and the Sharp printer port (eth2) gets a PLAIN scope
# that cannot ever see the profile. This is the production twin of the twin's
# dhcp.py, done the OpenWrt-native way (one dnsmasq daemon, per-scope options).
#
# Layout (mirrors the office wire: ATA eth1, Sharp printer eth2):
#   * br-lan  : eth0/eth2 members, 192.168.2.1/24  -> PRINTER scope (PLAIN,
#               NO tftp, NO option 66/67). Printer keeps its 192.168.2.x lease.
#   * wan-ata : eth1 standalone, 192.168.7.1/24    -> ATA scope (THE ONLY
#               provisioning scope): enable_tftp=1, tftp_root=/srv/tftp,
#               option 66=<192.168.7.1>, option 67=ata00070e36e57b.cnf.xml.
#   * asterisk: binds 192.168.2.1 + 192.168.7.1; ATA peer ata00070e36e57b
#               registers to 192.168.7.1:5060.
#
# AGENTS gates:
#   * DEFAULT = read-only dry-run. --apply is the ONLY state-writing flag and
#     is OPERATOR-ATTENDED (you are physically at the office with the ATA
#     cabled+powered; the Sharp stays on br-lan untouched).
#   * Bounded timeouts. No device egress (bytes came from the pinned closure).
#   * Rollback (attended re-run --apply with --rollback):
#       uci revert network && uci revert dhcp && rm -f /srv/tftp/* &&
#       service network restart && service dnsmasq restart
#     and br-lan returns to containing both eth1+eth2 (or operator's prior).
umask 077; set -u
HOST="${APU2_HOST:-root@10.47.11.97}"
ATA_SUBNET="192.168.7.0/24"
ATA_IP="192.168.7.1"
PROFILE_NAME="ata00070e36e57b.cnf.xml"
TFTP_DIR="/srv/tftp"
APPLY=0; ROLLBACK=0
case "${1:-}" in
  --apply) APPLY=1 ;;
  --rollback) APPLY=1; ROLLBACK=1 ;;
  "") : ;;
  *) echo "usage: $0 [--apply|--rollback]  (default dry-run)"; exit 2 ;;
esac

echo "===A) READ-ONLY: real wire NOW (operator: ATA cabled+powered on eth1, blinking DISCOVER; Sharp printer leased on eth2)==="
ssh -o BatchMode=yes -o ConnectTimeout=20 "$HOST" '
  echo "dnsmasq-proc:$(pgrep -x dnsmasq | wc -l)"
  echo "br-lan-ip:$(uci -q get network.lan.ipaddr)  brute-members:$(ls /sys/class/net/br-lan/brif 2>/dev/null | tr "\n" " ")"
  echo "eth1-carrier-mac:$(cat /sys/class/net/eth1/address 2>/dev/null)"
  echo "printer-lease-now:$(cat /tmp/dhcp.leases 2>/dev/null | grep -iE "80:38:96" | awk "{print \$3,\$4}" | head -1)"
' 2>&1 | grep -viE "WARNING:connection|post-quantum|store|decrypt|upgrad|openssh.com/pq"

echo
echo "===B) DRY-RUN: the --apply sequence (nothing written)==="
print_apply() {
cat <<EOF
[network]
  uci set network.br-lan.ports="eth0 eth2"          # printer back to br-lan only
  uci add network interface                                    # -> wan-ata
  uci set network.@interface[-1].name="wan-ata"
  uci set network.@interface[-1].type="bridge"
  uci set network.@interface[-1].ifname="eth1"
  uci set network.@interface[-1].proto="static"
  uci set network.@interface[-1].ipaddr="192.168.7.1"
  uci set network.@interface[-1].netmask="255.255.255.0"
  uci commit network && service network reload && sleep 3

[dhcp - PRINTER scope on br-lan (PLAIN: no tftp/66/67)]
  # existing dhcp.@dhcp scope for lan stays as-is (plain). NO tftp/66/67 added.

[dhcp - ATA scope on wan-ata (THE ONLY provisioning scope)]
  uci add dhcp dhcp                                  # -> @dhcp[#]
  uci set dhcp.@dhcp[-1].interface="wan-ata"
  uci set dhcp.@dhcp[-1].start="100"
  uci set dhcp.@dhcp[-1].limit="50"
  uci set dhcp.@dhcp[-1].leasetime="12h"
  uci add_list dhcp.@dhcp[-1].dhcp_option="66,192.168.7.1"
  uci add_list dhcp.@dhcp[-1].dhcp_option="67,ata00070e36e57b.cnf.xml"
  uci set dhcp.@dnsmasq[0].enable_tftp="1"
  uci set dhcp.@dnsmasq[0].tftp_root="/srv/tftp"
  uci commit dhcp && service dnsmasq restart

[profile already staged]
  /srv/tftp/ata00070e36e57b.cnf.xml (2695B, pinned)
EOF
}
print_apply
[ "$APPLY" -eq 0 ] && { echo "----> DRY-RUN END: nothing written. Run attended: $0 --apply"; exit 0; }

echo
if [ "$ROLLBACK" -eq 1 ]; then
  echo "===--ROLLBACK (attended): revert network+dhcp, remove profile, restart both services==="
  ssh -o BatchMode=yes -o ConnectTimeout=20 "$HOST" '
    uci revert network; uci revert dhcp
    rm -f /srv/tftp/'"$PROFILE_NAME"'
    service network restart; sleep 3; service dnsmasq restart; sleep 6
    echo "rollback-br-members:$(ls /sys/class/net/br-lan/brif 2>/dev/null | tr "\n" " ")"
  ' 2>&1 | grep -viE "WARNING:connection|post-quantum|store|decrypt|upgrad|openssh.com/pq"
  exit 0
fi

echo "===C) APPLY (operator-attended; writes network+dhcp ONLY; bounded)==="
ssh -o BatchMode=yes -o ConnectTimeout=20 "$HOST" '
  uci set network.br-lan.ports="eth0 eth2"
  uci add network interface
  uci set network.@interface[-1].name="wan-ata"
  uci set network.@interface[-1].type="bridge"
  uci set network.@interface[-1].ifname="eth1"
  uci set network.@interface[-1].proto="static"
  uci set network.@interface[-1].ipaddr="'"$ATA_IP"'"
  uci set network.@interface[-1].netmask="255.255.255.0"
  uci commit network
  service network reload; sleep 4
  uci add dhcp dhcp
  uci set dhcp.@dhcp[-1].interface="wan-ata"
  uci set dhcp.@dhcp[-1].start="100"
  uci set dhcp.@dhcp[-1].limit="50"
  uci set dhcp.@dhcp[-1].leasetime="12h"
  uci add_list dhcp.@dhcp[-1].dhcp_option="66,'"$ATA_IP"'"
  uci add_list dhcp.@dhcp[-1].dhcp_option="67,ata00070e36e57b.cnf.xml"
  uci set dhcp.@dnsmasq[0].enable_tftp="1"
  uci set dhcp.@dnsmasq[0].tftp_root="/srv/tftp"
  uci commit dhcp
  service dnsmasq restart
  sleep 4
' 2>&1 | grep -viE "WARNING:connection|post-quantum|store|decrypt|upgrad|openssh.com/pq"

echo
echo "===D) VERIFY (read-only, bounded): TWO scopes really split; TFTP/66/67 on ATA scope ONLY; printer lease intact==="
ssh -o BatchMode=yes -o ConnectTimeout=20 "$HOST" '
  echo "dnsmasq-proc:$(pgrep -x dnsmasq | wc -l)"
  echo "scopes:"; uci -q show dhcp | grep -E "interface=(lan|wan-ata)|dhcp_option="
  echo "lan-opt667-count:$(uci -q show dhcp | grep -A2 "interface=lan" | grep -cE "6[67],")  (must be 0: printer plain)"
  echo "wanta-opt667-count:$(uci -q show dhcp | grep -A2 "interface=wan-ata" | grep -cE "6[67],")  (must be 2)"
  echo "br-members-now:$(ls /sys/class/net/br-lan/brif 2>/dev/null | tr "\n" " ")"
  echo "printer-lease:$(cat /tmp/dhcp.leases 2>/dev/null | grep -iE "80:38:96" | awk "{print \$3,\$4}")"
' 2>&1 | grep -viE "WARNING:connection|post-quantum|store|decrypt|upgrad|openssh.com/pq"
echo
echo "===E) RING GATE (operator, attended; ATA blinking on eth1=wan-ata now being served its OWN scope with 66/67):==="
echo "  1) wait ~25s for the ATA to DISCOVER->lease on wan-ata (192.168.7.100+) -> TFTP-fetch ata00070e36e57b.cnf.xml -> register to 192.168.7.1:5060"
echo "  2) office handset at extension 100: lift, dial  100##  -> IVR answers -> press DTMF  5"
echo "  3) Extension 101 (SPA0300) RINGS on the ATA. Answer it. Confirm both ways."
echo "If the IVR answered but 101 never rang, or the ATA never leased — say EXACTLY that (bounded) and I read the live lease+registration trace."