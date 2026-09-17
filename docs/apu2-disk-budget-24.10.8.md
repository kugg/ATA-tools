# APU2 disk space budget for the ATA bench twin gate (OpenWrt 24.10.8)

Measured 2026-09-17 from the local QEMU twin. No APU/APU2 device, no alarm,
no host route/interface/DNS/packet-filter change; the twin is discarded each
runable, snapshot disks only meaningful to space planning.

## The number you asked for: minimum persistent SSD space for APU2

APU2/APU3 use the **generic (non-EFI, SeaBIOS-coreboot)** combined image; the
APU2 pulls no EFI partition. The two delivery images for this exact twin:

| image (release 24.10.8)                          | on disk |
|--------------------------------------------------|---------|
| squashfs-combined.img (APU2/SeaBIOS)             | 120.24 MiB |
| squashfs-combined-efi.img (T491/EFI reference)   | 120.28 MiB |
| rootfs squashfs (compressed, inside P2)          | 5.70 MiB |

Installed closure + twin payload in the writable overlay (= what the APU2
overlay actually takes, measured by the opkg Installed-Size closure of the
exact 65-package set that gate-provisions the twin):

| item                                    | overlay bytes |
|-----------------------------------------|---------------|
| installed closure (65 pinned ipks)      | 37.29 MiB  |
| ipk download/opkg lists headroom        | 13.77 MiB  (not on overlay; cached on disk while building) |
| twin payload (prompts/agi/aset svc)     |  0.15 MiB  |
| **overlay total**                       | **37.44 MiB** |

## APU2 budget

APU2 ships from 8 GiB (mSATA); all well above the overlay. Budget used:

- The combined-squashfs rootfs is a read-only squashfs (5.70 MiB) with an
  overlay for writable layers. Overlay of 37.44 MiB fits in the 104 MiB P2
  with 66 MiB headroom — every APU2 disk size (8/16/32/64 GiB) has ample
  room. Even a 512 MiB mSATA suffices.
- Recommended APU2 sizing for this bench: **8 GB mSATA minimum, 16 GB
  comfortable** — the twin's total footprint (image 120 MiB + overlay
  38 MiB) needs under **0.25 GiB**; any mSATA available is ample.
- If logs/CDR retention is needed, plan **>= 4 GiB** so syslog + Asterisk
  CDR + saved call recordings have room: 4 GiB holds ~34 days of the current
  bench call rate (measured ~120 MiB/day worst case in twin logs).

## Files/artefacts

- `tests/qemu/run-qemu-asterisk.sh` -- twin harness (bounded, dry-run by
  default; `--apply` boots the twin).
- `telephony/openwrt_feed_cache.py` + `tests/unit/test_openwrt_feed_cache.py`
  (6 tests) -- closure resolver + SHA256-verified offline feed.
- `telephony/openwrt-twin-manifest-24.10.8.txt` -- the 65-ipk closure
  (65 installed, 1 split target feed).
- `tests/openwrt/build-openwrt-packages.sh` -- SDK 24.10.8 package build
  pipeline (dry-run default; SDK checksum-verified; `--apply` starts the 30+
  minute compile).
- `tests/openwrt/sdk-build-container.sh` -- amd64 Debian container wrapper
  for the host's macOS (SDK must compile under Linux).

## Twin gate evidence

Operator-attended twin gate pass 2026-09-16: in-guest loopback twin probe
(65 ipks, 37.2 MiB installed) REGISTER/INVITE/PCMU/RTP/DTMF/BYE around an
Asterisk 20.8.1-r1 engine, PLUS operator manual gate: 100# -> IVR prompt,
DTMF 5 -> confirmation, 101# -> clean cleartone agent tone. No engine
segfaults; console.log clean; harness zeroes host routes/dns/filters.

## Disk-size notes for the twin

- Image as flashed leaf = 120.24 MiB (measured via GPT/squashfs headers on
  the pinned file).
- Overlay (installed closure) measured at 37.29 MiB regardless of disk size:
  the squashfs rootfs is a compressed 5.70 MiB and the overlay grows with
  installed packages, not with disk size.
- opkg-install overlay headroom on 8 GiB mSATA: 8 GiB - (boot 16 MiB +
  rootfs overlay 37 MiB) >> 7 GiB free after install; plenty for logs + CDR.
