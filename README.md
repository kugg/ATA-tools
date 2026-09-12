# ATA Tools

Source-readable tools and research for keeping Cisco ATA186 and ATA188 analog
telephone adapters useful.

The project can inspect legacy firmware, reconstruct and analyze its mapped flash
bank, convert legacy configuration profiles, simulate the firmware protocol, and
run one operator-attended DHCP and firmware-service window from Python. It does
not include Cisco firmware or support files.

> [!CAUTION]
> Firmware maintenance can permanently disable a device. Offline parsing and the
> complete firmware response stream are tested, but these Python tools have not
> yet flashed a physical ATA. No successful device reboot, SIP registration,
> ringing, or two-way audio result is claimed.

Modern Asterisk integration is a future project. The current repository creates a
maintainable path to that work; it is not an Asterisk distribution or a tested PBX
configuration.

## What Is Included

| Tool | Purpose |
| --- | --- |
| `ata_flash.py` | Experimental combined DHCP and firmware service for one directly connected ATA |
| `dhcp.py` | Bounded DHCP parser/responder used by `ata_flash.py`; direct invocation is inert |
| `refactor/sata186us.py` | Firmware inspection, KBOX protocol implementation, and loopback qualification |
| `refactor/ata_upgrade_client.py` | Loopback-only ATA firmware client simulator |
| `refactor/cfgfmt.py` | Offline conversion between legacy `#txt` and `#ata` configuration profiles |
| `refactor/zup_bank.py` | Validate a `+kxz` package map and reconstruct its 512 KiB bank |
| `refactor/zup_rebuild.py` | Rebuild a package from a validated template and reconstructed bank |
| `refactor/mipsx_dasm.py` | Bounded MIPS-X disassembly and control-transfer analysis |

The project deliberately does not provide:

- Cisco firmware, `ptag.dat`, configuration templates, or vendor executables
- A firmware catalog, signature service, or automatic upgrade-path selection
- Host address, route, DNS, firewall, or VPN configuration
- Automatic DTMF entry, retry, rollback, or recovery after an ambiguous transfer
- A general web-management client, TFTP provisioning server, or SIP registrar
- A guarantee that a rebuilt package is authentic, compatible, or safe to flash

## Requirements

- Python 3.10 or newer
- A POSIX-like system for the secure file-output paths
- [Scapy 2.7.0](https://scapy.net/) for `ata_flash.py --apply`
- Packet-capture and layer-2-send access for the selected interface

Most offline tools use only the Python standard library. Set up the optional live
dependency with:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-bench.txt
```

The program does not elevate privileges. Arrange the minimum BPF/raw-packet access
required by Scapy through normal operating-system administration.

## Firmware Files

Firmware is not distributed here. Obtain firmware and matching support files only
from a source from which you are legally entitled to receive and use them. Keep
firmware, configuration exports, passwords, keys, and generated banks out of Git.

The repository ignores `firmware/`, `vendor/`, `analysis/`, `optimized/`, `*.zup`,
and common private runtime artifacts. An ignore rule is not a secret scanner.

### Create `SHA256SUMS`

`ata_flash.py` requires an operator-controlled checksum manifest. Put the image in
a private directory and create the manifest there:

```sh
mkdir -p firmware
chmod 700 firmware

(
    umask 077
    cd firmware
    shasum -a 256 IMAGE.zup > SHA256SUMS
    shasum -a 256 -c SHA256SUMS
)
```

Use `sha256sum` and `sha256sum -c` on systems that provide the GNU commands.

The tool accepts exactly one valid manifest entry whose filename exactly matches
the selected image basename. Unrelated entries are ignored. The manifest is
bounded and may not be a symlink.

A matching SHA-256 proves that the selected bytes match the manifest. It does not
prove Cisco provenance, legal entitlement, model compatibility, an appropriate
upgrade path, or a vendor signature. Compare against an independent trusted digest
when one exists.

### Inspect Before Use

```sh
python3 -B refactor/sata186us.py --inspect firmware/IMAGE.zup
python3 -B refactor/zup_bank.py firmware/IMAGE.zup
```

The first command reports the whole-file SHA-256 and outer metadata. For a mapped
`+kxz` image, both commands validate the declared inner length and checksum, map
bounds, destination overlap, raw-DEFLATE termination, CRC-32, and ISIZE before
reconstructing the bank in memory.

The live path currently accepts only deeply validated `kup1` / `+kxz` packages.
Other historical envelope variants need equivalent structural validation before
they can be considered for live service.

## Experimental Firmware Service

`ata_flash.py` does not write flash memory directly. It temporarily answers DHCP
for one client and serves firmware blocks only when the ATA requests them. The ATA
controls storage, reboot, and boot selection.

### Preconditions

1. Connect one ATA to a dedicated Ethernet interface or otherwise isolated cable.
2. Keep that interface disconnected from household, office, production, VPN, and
   Internet-facing networks.
3. Assign the host interface one suitable IPv4 address outside this project.
4. Review current IPv4 and IPv6 routing. The selected interface must have no
   default, split-default, or gateway route, and its subnet must not overlap a route
   owned by another interface or VPN.
5. Prefer supplying the ATA MAC address. If it is omitted, the responder locks the
   first coherent DHCP client it sees.
6. Verify the image manifest, inspect the package, confirm the intended model and
   upgrade path, and keep any available configuration and recovery material private.
7. Keep both devices powered and have a human ready to enter one DTMF sequence.

Bare invocation is inert:

```sh
python3 -B ata_flash.py
```

Start one bounded attempt with values appropriate to the isolated cable:

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

`--interface` and `IMAGE` are required. The remaining network options behave as
follows:

- `--address` asserts an address already assigned to `IFACE`; it never configures
  the address. It is required when the interface has multiple IPv4 addresses.
- Without `--client-address`, host number 10 in the selected subnet is offered.
- Without `--client-mac`, the first valid DHCP DISCOVER selects the client.
- `--sha256sums PATH` selects a non-default manifest; otherwise `SHA256SUMS` beside
  the image is used.
- The DHCP deadline defaults to 600 seconds. The firmware window starts after ACK
  and defaults to 3600 seconds.
- The default completion grace is 120 quiet seconds after every block has been
  served. Retransmissions remain available during that grace period.

Before replying, the coordinator:

- validates the image and manifest before opening network sockets;
- reloads all IPv4 addresses and routes rather than trusting an interface's first
  address;
- rejects another-interface subnet overlap and selected-interface gateway or
  default-equivalent routes;
- reserves UDP ports 8000 and 8500 before DHCP;
- binds the exact host address and, where supported, the selected interface;
- uses nonblocking firmware sockets and clears any packets queued before readiness;
- ties DHCP ACK to the selected client and transaction;
- rechecks interface ownership and the effective direct client route before every
  firmware response.

The responder offers no gateway or DNS. The firmware server accepts only the
leased client IP, but source UDP ports may change because the vintage client does
that. These checks are not cryptographic authentication. Datagram sizes and parsing
are bounded; request counts are not artificially capped because real ATA transfers
may be slow or retransmit extensively. The wall-clock deadline remains the resource
limit.

### Trigger and Verify

Wait for the exact ready message. The program then prints a sequence of this form:

```text
100#A*B*C*D*8000#
```

Manually enter it once on the telephone attached to the ATA, where `A.B.C.D` is the
printed service address. Do not enter it before readiness and do not automatically
repeat it after an uncertain result.

`Python firmware response stream complete` means the server successfully sent each
unique payload block at least once. It does not prove that the ATA received, stored,
accepted, booted, or retained the image. After the service window ends, use the ATA
IVR version code:

```text
123#
```

Record the device-reported version, then perform the intended protocol and call
tests. No transfer, a partial stream, interruption, route change, early firmware
traffic, or an unexpected peer is a failed or ambiguous attempt. Stop and inspect;
never redial or rerun automatically.

## Configuring an ATA for SIP

Configuration details vary by firmware. Use the Cisco administrator guide for the
exact installed release and record the original values privately before changing
anything. A unit running SCCP, H.323, or MGCP firmware does not become a SIP endpoint
merely by entering SIP fields.

### Web Interface

For a small, manually managed installation:

1. Connect a telephone to Phone 1, enter the ATA voice menu, and use `21#` to hear
   the current IPv4 address.
2. From the same trusted local network, open `http://<ATA-IP>/dev`.
3. Choose one configuration authority. If TFTP provisioning remains enabled, a
   later refresh can replace values entered through the web or voice menu.
4. Enter only values supplied by your SIP deployment.

Common SIP parameters include:

| Purpose | ATA parameter |
| --- | --- |
| Registrar or proxy | `GkOrProxy` |
| Enable registration | `SIPRegOn=1` |
| Phone 1 registration identity | `UID0` |
| Phone 1 secret | `PWD0` |
| Separate authentication identity | `UseLoginID=1` and `LoginID0` |
| Registration renewal | `SIPRegInterval` |
| Outbound proxy, when required | `SipOutBoundProxy` |
| Codec preference | `LBRCodec` and related audio fields |
| Explicitly designed NAT traversal | `NATIP`, `NatServer`, and related flags |

There are no universal values for these fields. Do not copy addresses, credentials,
NAT settings, dial plans, or codec choices from an unrelated deployment.

Use the page's apply action to save and refresh configuration. The historical web
interface also exposes `/refresh`, while `/reset` power-cycles the ATA and is not
needed for every configuration change. A factory reset is not a routine rollback.

Verify progressively:

- Check `/stats/` for the expected proxy and recent successful registration.
- Confirm the matching active binding on the SIP server.
- Test dial tone, one controlled outbound call, one controlled inbound ring, and
  intelligible two-way audio.
- Use `/rtps` during a call for packet counters, but do not substitute counters for
  an audible media test.

The ATA web interface is legacy HTTP. Use it only on a trusted isolated management
network and never reuse a valuable password.

Archived Cisco references:

- [ATA 186/188 SIP configuration guide](https://web.archive.org/web/20040221155736id_/http://www.cisco.com/univercd/cc/td/doc/product/voice/ata/ataadmn/sip30ad/sip88ch3.htm)
- [ATA 186/188 SIP services](https://web.archive.org/web/20040222045655id_/http://www.cisco.com/univercd/cc/td/doc/product/voice/ata/ataadmn/sip30ad/sip88ch4.htm)
- [ATA 186/188 troubleshooting](https://web.archive.org/web/20040222045655id_/http://www.cisco.com/univercd/cc/td/doc/product/voice/ata/ataadmn/sip30ad/sip88ch5.htm)
- [Cisco ATA186/188 3.1 release notes](https://web.archive.org/web/20090704161416id_/http://www.cisco.com/en/US/docs/voice_ip_comm/cata/186_188/3_1_0/english/release/notes/atarn3_1.html)

### Offline Configuration Profiles

`refactor/cfgfmt.py` converts legacy text and binary profiles. It does not contact
an ATA or run a TFTP service. Use the `ptag.dat` and template from the exact firmware
support package; they are not interchangeable across arbitrary releases.

```sh
PTAG=/lawful/private/path/ptag.dat

# Text profile to an unencrypted binary profile, retaining SIP fields only.
python3 -B refactor/cfgfmt.py "-t$PTAG" -sip profile.txt ata-profile

# Binary profile back to reviewable text.
python3 -B refactor/cfgfmt.py "-t$PTAG" -sip ata-profile decoded.txt
```

Text input begins with `#txt`; an unencrypted binary profile begins with `#ata`.
Filters are available for `-sip`, `-h323`, `-mgcp`, and `-sccp`. `-split` requests
the legacy base/extended output split. `-g` omits fields marked sensitive by
`ptag.dat`; it is not a comprehensive secret scrubber.

Outputs are new mode-`0600` files and existing paths are never replaced. Includes
are confined to the source directory and nesting is bounded. Fixed-size values are
zero-padded rather than reproducing the vintage converter's stale-buffer behavior.

Historical RC4-compatible profiles can be processed only with bounded owner-only
key files:

```sh
chmod 600 profile.key
python3 -B refactor/cfgfmt.py "-t$PTAG" \
  --key-file=profile.key profile.txt ata-profile
```

Inline command-line keys are rejected. RC4 exists for migration compatibility and
is not modern configuration security. Treat every generated or decoded profile as
sensitive.

For TFTP provisioning, historical firmware generally requests a per-device profile
named `ata<mac-address-without-separators>` and may use `atadefault.cfg` as a
fallback. Stronger legacy-key mode uses an `.x` profile. Confirm naming and behavior
in the guide for the installed release, isolate the TFTP service, and do not mix it
with web-managed values accidentally.

## ZUP Format Research

The implementation and [firmware analysis](docs/firmware-analysis.md) establish the
following for the two analyzed ATA packages.

### Outer and Mapped Package

- The file begins with a 24-byte big-endian `kup1` header.
- The header carries an eight-byte name plus base type, platform, protocol, and
  version fields.
- The analyzed firmware payload uses a `+kxz` inner package. Its 16-byte header
  contains the magic, additive byte checksum, complete inner length, and map offset.
- A version-2 map table describes raw regions and compressed regions. The table must
  end exactly at the package boundary.
- Reconstruction starts with a 512 KiB bank filled with `0xff`, then copies or
  inflates non-overlapping regions into bounded destinations.
- Compressed regions contain raw DEFLATE followed by a little-endian CRC-32 and
  ISIZE trailer. The parser requires exact stream EOF, output size, CRC, and ISIZE.
- One analyzed image contains an `ATA4` word before its map; the transition image
  uses the otherwise identical mapped form without that gap.

The additive checksums detect accidental damage. They are not digital signatures.

### Nested and Launch Payloads

- Bank-embedded `+kbz` records use a six-word big-endian header with stored and
  output byte sums and lengths. Their bodies use the same raw-DEFLATE plus
  CRC-32/ISIZE form.
- Launch type-8 records point to another packed form with a mode-dependent
  big-endian header, raw DEFLATE, and a following little-endian CRC-32.
- Mode 0 expands executable content; mode 1 expands initialized data into a bounded
  destination. Bytes following the checked CRC are not fully interpreted.
- Three analyzed mode-0 outputs decode coherently as big-endian MIPS-X programs.
  This identifies instruction content, not the ATA186's physical CPU or SoC.
- Several launch-record roles and a shared inflate helper are strongly supported by
  cross-image evidence. Some record flags and exact source provenance remain open.

### Firmware Service Protocol

- UDP port 8000 handles KBOX image selection.
- UDP port 8500 handles stream hello and indexed 1,024-byte block requests.
- A KBOX request contains `kbox`, protocol version 1, bounded metadata, and an
  additive checksum. A successful response advertises the data-channel URL.
- The hello response carries the exact payload length and block size.
- A block response carries checksum, index, size, and a zero-padded 1,024-byte block.
- Only bytes after the outer 24-byte `kup1` header are streamed.

For the analyzed SIP image, the Python loopback service delivered 312 blocks and
319,135 payload bytes and matched response identities recorded from the vintage i386
server:

```text
image_sha256=b8597657928905aea66924118889f0883bd38c0804ddf880e3be2c33ccf62eb5
data_wire_sha256=158a9e2d5736f253cddcd1c4662b83792f996e0edd78b9eb5b6b1f34a279c7f2
selection_normalized_sha256=6beddb21fc08c6518a8f1f3375030c3d5a56b3171c5ee7cb29e686a2fd9282f0
```

That proves software-stream equivalence for those exact bytes. It does not prove
physical receipt, flash writes, reboot behavior, or bootability.

## Offline Analysis Commands

Create outputs in an owner-only directory:

```sh
mkdir -m 700 analysis

# Validate and summarize a mapped package.
python3 -B refactor/zup_bank.py firmware/IMAGE.zup

# Reconstruct one new private 512 KiB bank.
python3 -B refactor/zup_bank.py firmware/IMAGE.zup \
  --extract-bank analysis/bank.bin

# Inspect package-specific nested or type-8 payloads.
python3 -B refactor/zup_bank.py firmware/IMAGE.zup --nested-payload OFFSET
python3 -B refactor/zup_bank.py firmware/IMAGE.zup --type8-payload OFFSET

# Rebuild into a new package; never offer experimental output to hardware.
python3 -B refactor/zup_rebuild.py \
  firmware/TEMPLATE.zup analysis/bank.bin analysis/rebuilt.zup

# Analyze a selected MIPS-X region.
python3 -B refactor/mipsx_dasm.py analysis/bank.bin \
  --region START:END --stats
```

An unchanged analyzed bank round-trips byte-for-byte because unchanged compressed
streams are retained. Changed regions are recompressed with the local zlib. A
successful structural round trip does not prove compatibility with Cisco's historic
compressor or inflater, and modified packages must not be treated as flashable.

For the exact reference SIP image only, run the complete loopback transfer:

```sh
python3 -B refactor/sata186us.py --qualify \
  firmware/ATA030100SIP040211A.zup
```

This uses ephemeral `127.0.0.1` UDP sockets and a synthetic client. It does not
contact hardware and requires no QEMU or vendor executable.

## Tests

The public test set is offline except for bounded ephemeral loopback sockets:

```sh
python3 -B -m unittest \
  tests.unit.test_ata_flash \
  tests.unit.test_dhcp -v

python3 -B -m unittest \
  refactor.tests.test_ata_upgrade_client \
  refactor.tests.test_cfgfmt \
  refactor.tests.test_mipsx_dasm \
  refactor.tests.test_sata186us \
  refactor.tests.test_zup_bank \
  refactor.tests.test_zup_rebuild -v
```

Synthetic tests run in a clean checkout. Optional compatibility tests use local
vendor artifacts when this environment variable points at a private directory:

```sh
ATA186_TEST_ARTIFACT_DIR=/private/path/to/support-files \
  python3 -B -m unittest \
    refactor.tests.test_cfgfmt \
    refactor.tests.test_mipsx_dasm \
    refactor.tests.test_sata186us \
    refactor.tests.test_zup_bank \
    refactor.tests.test_zup_rebuild -v
```

Review skip counts. A green clean-checkout run does not imply that optional vendor
artifact vectors ran.

## Roadmap

- Operator-attended validation on physical ATA186 hardware
- Version-specific backup, configuration, and recovery procedures
- Modern Asterisk SIP registration and authentication
- Controlled inbound ringing, outbound calling, codec negotiation, and two-way audio
- Remaining launch-record semantics and component provenance
- Further authenticity and recovery analysis before any modified-image experiment

## License and Trademarks

Original project code and documentation are available under the BSD 3-Clause
License; see `LICENSE`. `refactor/mipsx_dasm.py` incorporates a BSD-3-Clause MAME
decode-table adaptation whose pinned source and notice are in
`THIRD_PARTY_NOTICES.md`.

Cisco, ATA186, and ATA188 are trademarks or product names of their respective
owner. This independent preservation project is not affiliated with or endorsed by
Cisco Systems, Inc. Cisco firmware and support-package files are not redistributed.

See [the detailed firmware analysis](docs/firmware-analysis.md),
[the maintenance checklist](docs/ata-firmware-maintenance.md), and
[the protocol notes](refactor/FLASHING.md).
