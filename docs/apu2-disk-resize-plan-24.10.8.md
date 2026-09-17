# APU2/APU3 mSATA disk resize plan (gate data-expand), release 24.10.8

Measured 2026-09-17 read-only on the live office APU2 (root@10.47.11.97):
no block device was written, no fs resized, no reboot, no package installed,
no egress. This is the plan; the operator-run `--apply` is a SEPARATE,
attended, gated action (see docs/install-day-2026-09-18.md section 5).

## Why `df` looked wrong (measured, not guessed)

| block | size | comment |
|-------|------|---------|
| sda (SeaBIOS APU2) | 14.9 GiB | 31277232 sectors |
| sda1 | 16 MiB | boot leaf (SeaBIOS, non-EFI) |
| sda2 | 104 MiB | root squashfs + as-overlay on loop0 |
| loop0 (/overlay) | 86.6 MiB | 46.7M used / 33.0M free |
| **unallocated tail** | **~14.6 GiB** | free GPT sectors, currently unused |

OpenWrt 24.10.8 x86_64 generic does NOT grow P2 on first boot; the combined
image ships P2=104M. Everything past 104M on the mSATA is unallocated.

## Target layout

- Keep sda1/sda2 exactly as installed (boot + overlay unchanged; the twin
  overlay closure of 37.29 MiB fits today with 33.0M free).
- Add sda3 = the unallocated tail (129 refs: first free sector after sda2;
  measured start = LBA 246784+1, last = 31277231) as ext4.
- Mount sda3 at /data; bind-mount the write-heavy paths onto it via /etc/
  rc.local entries or an init.d script (bounded, recorded): opkg cache/feeds,
  CDR, recordings, AGI working dir. The running overlay / engine is untouched
  and the phone keeps working during the operation.

## Safety gates

- The expand is NOT a first-boot action: it runs after the operator gate
  (`100#` IVR + DTMF 5, `101#` tone) confirms the phone works.
- Script is dry-run by default; writes only under `--apply`.
- sda3 create + mkfs is the ONLY write; sda1/sda2 never rewritten.
- Rollback: unmount /data, delete sda3 GPT entry (recorded), reboot; overlay
  and phone unaffected.

## Files

- Operator-attended runbook: docs/install-day-2026-09-18.md
- Space budget evidence: docs/apu2-disk-budget-24.10.8.md
- The expand script (dry-run default): tests/apu2/apu2-expand-data.sh
