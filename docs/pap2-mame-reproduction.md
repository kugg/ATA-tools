# PAP2 MAME Reproduction and Firmware Boundaries

This document separates two similarly named but technically distinct paths:

- **PAP2 MAME research** reproduces a bounded local emulator trace from an
  archived ROM dump. It does not flash a device.
- **Cisco ATA 186/188 maintenance** uses this repository's reviewed firmware
  service with a user-supplied, model-compatible `.zup` image. It does not
  apply to a Linksys PAP2.

The repository contains neither vendor firmware nor support files. Only work
on equipment and software that you are authorized to use.

## PAP2 MAME Research

### Provenance and Limits

The PAP2 image used for the local trace came from the third-party Internet
Archive MAME set, not Cisco or Linksys. MAME marks it `BAD_DUMP`, and the
original dumper is unknown. Matching the checksums below proves only that a
file matches this MAME reference; it does not prove authenticity, board
revision, update compatibility, or flashability.

| Artifact | Bytes | SHA-1 | Other digest |
| --- | ---: | --- | --- |
| `mame-0.272-pap2.7z` | 759993 | `26d518d32c12d75fc35fb90fc18641276457243c` | MD5 `1c069409effc1bc2152b328c6d3f9cc4` |
| `linksys-pap2-2.0.12-ls.u51` | 1048576 | `73b163b00a3709a14f7419283c8515dd91009598` | CRC-32 `4d0f1e5d` |

Sources:

- [MAME 0.272 merged-set metadata](https://archive.org/metadata/mame-0.272-romset-complete-merged)
- [PAP2 archive member](https://archive.org/download/mame-0.272-romset-complete-merged/mess/pap2.7z)
- [PAP2-NA user guide](https://archive.org/details/generalmanual_000073264)
- [Upstream MAME PAP2 skeleton](https://github.com/mamedev/mame/blob/master/src/mame/skeleton/pap2.cpp)

Do not upload, commit, mirror, or redistribute the archive or extracted ROM.
Do not flash it to a PAP2, PAP2T, ATA 186, ATA 188, or any other device.

### Reference Acquisition Check

If you are legally entitled to obtain the archive, verify it before using it.
The archive should contain exactly one file named
`linksys-pap2-2.0.12-ls.u51`.

```sh
shasum -a 1 mame-0.272-pap2.7z
7z t mame-0.272-pap2.7z
7z x mame-0.272-pap2.7z
shasum -a 1 linksys-pap2-2.0.12-ls.u51
```

For a normal MAME ROM-set check, place the extracted file at
`roms/pap2/linksys-pap2-2.0.12-ls.u51` and run:

```sh
mame -rompath "$PWD/roms" -verifyroms pap2
```

An expected `NEEDS REDUMP` warning is not evidence of a bad local checksum; it
is MAME's provenance warning for this known reference.

### Current Reproduction Boundary

Stock upstream MAME can validate the ROM set, but it cannot reproduce this
project's bounded trace by itself. That trace currently relies on local,
uncommitted MIPS-X execution work and two read-only ROM aliases. No finalized,
reviewed MAME patchset is published with this repository yet.

The local result reaches a real loader/parser path, one MD5-style compression
return at `0x0cfff834`, and the taken next-block range branch through the
increment boundary at `0x0cffeb5c`. It does not establish a PAP2 boot, flash
algorithm, ES3890F register map, Ethernet operation, FXS behavior, or physical
hardware behavior.

## Cisco ATA 186/188 Firmware Maintenance

This is a separate hardware family and workflow. Do not use PAP2 artifacts,
PAP2 filenames, or PAP2 MAME evidence with an ATA 186/188.

### Obtain the Right Image

- Confirm the exact model, installed protocol image, and firmware version using
  the ATA's local IVR before selecting an image.
- Obtain a `.zup` release only from a source from which you are legally entitled
  to receive and use it. The historical Cisco release notes say the software
  download required a Cisco login; this repository intentionally provides no
  binary download link or firmware copy.
- Confirm the required upgrade path. In particular, historical Cisco guidance
  requires an intermediate transition image for version 1.34 and earlier.
- Keep the image and a user-created `SHA256SUMS` manifest private and adjacent.
  Check the digest against an independent trusted value where available.

Historical references:

- [Cisco ATA 186/188 Release 3.1(0) notes](https://web.archive.org/web/20090704161416id_/http://www.cisco.com/en/US/docs/voice_ip_comm/cata/186_188/3_1_0/english/release/notes/atarn3_1.html)
- [Cisco ATA SIP configuration and upgrade guide](https://web.archive.org/web/20040221155736id_/http://www.cisco.com/univercd/cc/td/doc/product/voice/ata/ataadmn/sip30ad/sip88ch3.htm)

### Validate Before a Service Window

Use the offline checks before opening any sockets:

```sh
python3 -B firmware/sata186us.py --inspect firmware/IMAGE.zup
python3 -B firmware/zup_bank.py firmware/IMAGE.zup
```

Then follow the complete preflight in
[`ata-firmware-maintenance.md`](ata-firmware-maintenance.md). It requires one
owner-controlled ATA on an isolated cable, an already-configured host address,
no ambiguous routes, a known client identity where possible, and an identified
device recovery procedure. The tools assert this environment; they do not
create interfaces, routes, DNS configuration, packet-filter rules, or VPN
configuration.

### Perform One Controlled Attempt

Only after the checklist passes, use the reviewed coordinator form:

```sh
python3 -B ata_flash.py --apply \
  --interface IFACE \
  --address HOST_IPV4 \
  --client-address ATA_IPV4 \
  --client-mac ATA_MAC \
  --dhcp-timeout-seconds 600 \
  --duration-seconds 3600 \
  firmware/IMAGE.zup
```

Wait for its ready line, then manually enter the printed DTMF sequence once.
Do not pre-enter, script, automatically redial, or repeat a transfer after an
ambiguous result. `All firmware blocks were served` means only that the server
sent each unique block and completed its grace period. It does not prove that a
device accepted, wrote, selected, or booted the image.

After the process has exited, verify the reported version through `123#` and
then separately verify configuration, registration, calls, and audio. Keep any
rollback decision within the vendor-supported, model-specific recovery path;
this project provides no automatic rollback or universal recovery guarantee.

## Related Local Documentation

- [`ata-firmware-maintenance.md`](ata-firmware-maintenance.md): full
  operator-attended preflight and post-transfer checklist.
- [`../firmware/FLASHING.md`](../firmware/FLASHING.md): protocol validation,
  isolation checks, and completion semantics.
- [`getting-started.md`](getting-started.md): ATA 186/188 SIP configuration and
  provisioning after a separately verified update.
