# QEMU qualification, not yet executed

Reuse the printer OpenWrt24.10.8 x86/64 EFI harness after safety repairs; do not
infer that its older24.10.0 results qualify a new image. Current harness is one
guest NIC plus guest-loopback fake printer, not a segmented gateway replica.

Before launch: fresh netstat IPv4/IPv6 snapshots and scutil --nwi; numeric overlap
review, loopback-only forwards, explicit egress policy, bounded runtime and
cleanup. Compare these same snapshots after shutdown. Stop on host drift without
trying to repair routes. No physical ATA/printer/production VPN connection.

`run-qemu-tools.sh` is dry-run by default, passes QEMU options as an argument array,
rejects paths that can alter QEMU suboption syntax, caps console output, and has no
subnet-overlap override. Its apply path remains unexecuted.

Current permission baseline allows user-mode networking only. Multi-guest socket
links require separate explicit approval. Never bridge to office or device ports.

Gates: repeated apply/no drift, delayed DHCP, readdress/loss, three cold boots,
power kill/restart on same writable disk during jobs/calls/config stage, blank
image reconstruction, rollback, and concurrent management/print/call availability.
Do not confuse graceful shutdown with abrupt-power-loss testing. No inferred
hardware timing or analog-ring proof from QEMU.
