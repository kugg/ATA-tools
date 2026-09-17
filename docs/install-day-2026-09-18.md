# APU2 install day (2026-09-18) -- office ATA bench twin, operator-attended

Purpose: flash the exact twin closure onto the office APU2/APU3, leave it
powered, and the handset must work (IVR 100#/101# + RTP audio both ways).
This page is the operator run-sheet. It is NOT an alarm, no production
device: the APU2 is the physical copy of the gate-passed twin.

## Space you need (measured, see docs/apu2-disk-budget-24.10.8.md)

- Image (flashed leaf, APU2 = non-EFI SeaBIOS combined): **120.24 MiB**
- Overlay (installed 65-ipk closure + twin payload): **37.44 MiB**
- Total persistent footprint: **~158 MiB = 0.15 GiB**
- Any mSATA >= 512 MiB works; recommend **>= 4 GiB** (34 days of logs/CDR +
  recordings headroom at measured ~120 MiB/day). Do NOT need to shrink feeds.

## Image to write on the APU2 disk (APU2 uses SeaBIOS, NOT EFI)

- `openwrt-24.10.8-x86-64-generic-squashfs-combined.img` (non-EFI) -- already
  downloaded, SHA256-verified, staged in the twin download dir. The EFI
  image (120.28 MiB) is only the T491/EFI reference; do not flash it here.

## Operator actions tomorrow (in order)

1. Have the SHA256 of the exact file we wrote (we stage it on the bench
   storage or via serial/scp helper) and the disk to be flashed.
2. Flash: `dd`/bmaptool the non-EFI combined image to the mSATA (>= 4 GiB).
   Verify the written image bytes vs staged digest BEFORE boot.
3. Attach APU2 serial console (115200 8N1), power on; expect U-Boot/coreboot
   -> kernel -> dropbear ssh on LAN (br-lan 10.0.2.15 default in twin).
4. Provide operator-configured LAN/static/DNS per office as needed (twin uses
   slirp defaults; on APU2 set real LAN): confirm Asterisk binds + RTP/UDP.
5. Operator gate (same as twin): dial `100#` -> IVR prompt; `5` (DTMF) ->
   confirmation; `101#` -> clean AudioSocket tone. Then operator confirms
   to the harness/records that the phone works.
6. Leave powered; gather `opkg manifest` + `df` + `asterisk -rx core show
   uptime` snapshot -> record in WORKLOG/handoff.

## Fields only operator can decide (please answer on install day)

- mSATA size / model actually installed.
- LAN interface name + static IP/DNS on the office network (or DHCP).
- Names/number plan for the office ATA lines (tenant/DID, agent extension).
- Whether to keep prompts/recordings on this disk (grows overlay).

## What we still owe (records / next actions)

- SDK from-source rebuild (30+ min container compile) -- NOT a blocker for
  tomorrow; starts when Docker daemon is up using tests/openwrt/sdk-build-container.sh.
- Any private office configs (IPs, creds, number plan) stay OUT of git
  (AGENTS.md security rule); record only redacted placeholders.
