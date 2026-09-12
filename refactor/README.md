# ATA Format and Protocol Tools

This directory contains source-readable implementations of selected Cisco ATA186
and ATA188 file formats and firmware-service behavior. The implementations preserve
interoperability where it is understood while deliberately removing unsafe behavior
from the vintage utilities.

Cisco firmware, support files, and executables are not part of this repository.
Obtain them only from a source from which you are legally entitled to receive and
use them.

## Tools

| Tool | Behavior |
| --- | --- |
| `cfgfmt.py` | Bounded offline `#txt`/`#ata` profile converter |
| `sata186us.py` | Inert by default; local image inspection and pinned loopback qualification |
| `ata_upgrade_client.py` | Synthetic loopback client used by qualification tests |
| `zup_bank.py` | Deep `+kxz` map validation, bank reconstruction, and nested-payload inspection |
| `zup_rebuild.py` | Checked offline package rebuilding into a new private file |
| `mipsx_dasm.py` | Bounded offline MIPS-X disassembly and control-transfer analysis |

Live DHCP and firmware service exists only in the top-level `ata_flash.py`. None of
the tools in this directory has a live-device mode.

## Safe Defaults

These commands do not open a firmware-service socket:

```sh
python3 -B refactor/sata186us.py
python3 -B refactor/sata186us.py --inspect firmware/IMAGE.zup
python3 -B refactor/zup_bank.py firmware/IMAGE.zup
```

`sata186us.py` without a mode performs no file or socket I/O. `--inspect` reads one
bounded regular image and reports validated metadata. For `+kxz` images it also runs
the complete bank-structure validator.

## Loopback Qualification

The qualifier is intentionally limited to the exact analyzed SIP reference image:

```sh
python3 -B refactor/sata186us.py --qualify \
  firmware/ATA030100SIP040211A.zup
```

It uses ephemeral IPv4 loopback sockets and the synthetic ATA client. No QEMU,
vendor executable, physical interface, DTMF, or ATA is involved. The expected image
and wire identities are:

```text
image_sha256=b8597657928905aea66924118889f0883bd38c0804ddf880e3be2c33ccf62eb5
data_wire_sha256=158a9e2d5736f253cddcd1c4662b83792f996e0edd78b9eb5b6b1f34a279c7f2
selection_normalized_sha256=6beddb21fc08c6518a8f1f3375030c3d5a56b3171c5ee7cb29e686a2fd9282f0
blocks=312
payload_bytes=319135
```

These values establish software-response equivalence for those exact bytes. They do
not establish image provenance, ATA receipt, flash writes, bootability, or successful
operation after reboot.

## Configuration Profiles

Use the `ptag.dat` and text template supplied with the exact firmware release. They
are intentionally absent from a clean checkout.

```sh
PTAG=/lawful/private/path/ptag.dat

# Text to binary.
python3 -B refactor/cfgfmt.py "-t$PTAG" -sip profile.txt ata-profile

# Binary to text.
python3 -B refactor/cfgfmt.py "-t$PTAG" -sip ata-profile decoded.txt
```

The converter provides protocol filters (`-sip`, `-h323`, `-mgcp`, and `-sccp`),
legacy split output (`-split`), and sensitive-tag omission according to `ptag.dat`
(`-g`). It confines includes to the input directory, bounds include depth and all
input/output sizes, creates only new mode-`0600` outputs, and never replaces an
existing path.

Compatibility encryption keys must come from owner-only bounded files:

```sh
python3 -B refactor/cfgfmt.py "-t$PTAG" \
  --key-file=profile.key profile.txt ata-profile
```

`--xkey-file=PATH` handles the longer legacy key form. Inline keys are rejected so
they do not enter process arguments. RC4 is retained only for migration compatibility
and is not modern configuration security.

Fixed-size values are zero-padded. This intentionally differs from the vintage
converter, which could retain stale bytes from a previous value in the same scratch
buffer.

## Package Analysis

```sh
# Validate and summarize a +kxz package.
python3 -B refactor/zup_bank.py firmware/IMAGE.zup

# Create one new private reconstructed bank.
python3 -B refactor/zup_bank.py firmware/IMAGE.zup \
  --extract-bank analysis/bank.bin

# Print a checked launch table or inspect nested payloads.
python3 -B refactor/zup_bank.py firmware/IMAGE.zup --launch-header OFFSET
python3 -B refactor/zup_bank.py firmware/IMAGE.zup --nested-payload OFFSET
python3 -B refactor/zup_bank.py firmware/IMAGE.zup --type8-payload OFFSET

# Rebuild a new package from a validated template and exact 512 KiB bank.
python3 -B refactor/zup_rebuild.py \
  firmware/TEMPLATE.zup analysis/bank.bin analysis/rebuilt.zup

# Decode a selected bank region.
python3 -B refactor/mipsx_dasm.py analysis/bank.bin \
  --region START:END --stats
```

`zup_bank.py` validates all destination spans before expansion and requires exact
raw-DEFLATE EOF, output size, CRC-32, and ISIZE. Nested and type-8 requested output is
independently bounded. Optional output is atomic, private, and no-replace.

`zup_rebuild.py` rejects changes outside mapped destinations and reconstructs the
result to verify the requested bank before publishing it. It preserves unchanged
compressed streams and recompresses only changed regions by default. Structural
round-trip success is not a signature, provenance check, vintage-zlib compatibility
claim, or authorization to flash a modified package.

`mipsx_dasm.py` bounds regions, inference dimensions, retained transfer records,
cross references, and text output. It provides linear disassembly and a delay-slot-
aware transfer summary, not recovered source code or a complete control-flow graph.
Its MAME-derived decode table and BSD-3-Clause terms are recorded in
`../THIRD_PARTY_NOTICES.md`.

## Tests

```sh
python3 -B -m unittest \
  refactor.tests.test_ata_upgrade_client \
  refactor.tests.test_cfgfmt \
  refactor.tests.test_mipsx_dasm \
  refactor.tests.test_sata186us \
  refactor.tests.test_zup_bank \
  refactor.tests.test_zup_rebuild -v
```

Optional compatibility vectors are selected with `ATA186_TEST_ARTIFACT_DIR` and are
skipped when lawful local artifacts are absent. Review skip counts before claiming
that those vectors ran.

See `../README.md` for the complete project guide, `FLASHING.md` for protocol and
live-service boundaries, and `../docs/firmware-analysis.md` for reproducible static
analysis.
