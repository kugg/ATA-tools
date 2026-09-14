# ATA Tools

Source-readable tools and research for keeping Cisco ATA186 and ATA188 analog
telephone adapters useful.

The project can inspect legacy firmware, reconstruct and analyze its mapped flash
bank, convert legacy configuration profiles, serve a configuration profile over
TFTP, run one operator-attended DHCP and firmware-service window from Python, and
host a bounded bench SIP registrar/UAS that rings a phone and exchanges RTP media.
It does not include Cisco firmware or support files.

> [!CAUTION]
> Firmware maintenance can permanently disable a device. The transfer protocol has
> been proven against a physical ATA186: the KBOX selection and data dialogue were
> served, the device rebooted and reported SIP 3.1(0) via `123#`, a TFTP-served
> bench profile was applied, and registration, ringing, and two-way RTP audio were
> observed on an isolated bench. These are results for one specific device and
> profile, not a general guarantee. Keep modified firmware and modified profiles
> off production hardware until separately validated.

Modern Asterisk integration is the next project. The current repository provides
the proven bench SIP path (DHCP + TFTP profile provisioning + registrar/UAS plus
media) that an Asterisk endpoint will require; it is not yet an Asterisk
distribution or a tested PBX configuration.

## What Is Included

| Tool | Purpose |
| --- | --- |
| `dhcp.py` | Bounded DHCP parser/responder library also runnable directly: `dhcp.py --apply --interface NAME` |
| `telephony/tftp_profile.py` | Bounded RFC1350 TFTP server that serves one allow-listed profile to one peer |
| `telephony/sip_bench_proxy.py` | Bounded SIP registrar/UAS: REGISTER, INVITE with PCMU, streamed tone, inbound RTP counting |
| `telephony/ata_dev_post.py` | Bounded ATA `ATADev` XML snapshot reader and exact-field web POST for the bench ATA |
| `telephony/host_qualification.py` | Explicit loopback-only SCCP/IAX2/RTP qualification of the local host |
| `telephony/skinny_fixture.py`, `iax2_fixture.py`, `rtp_external_media.py`, `g711.py` | Bounded offline protocol/media fixtures and PCMU helpers |
| `ata_flash.py` | Experimental combined DHCP and firmware service for one directly connected ATA |
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
- A general web-management client, production TFTP provisioner, or production SIP registrar
- A guarantee that a rebuilt package or a modified profile is authentic, compatible, or safe to load

## Requirements

- Python 3.10 or newer
- A POSIX-like system for the secure file-output paths
- [Scapy 2.7.0](https://scapy.net/) for `ata_flash.py --apply` and `dhcp.py --apply`
- Packet-capture and layer-2-send access for the selected interface
- One ATA186/188 and an isolated Ethernet interface (or a protected network) for the live bench

Most offline and telephony tools use only the Python standard library. Set up the
optional live dependency with:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-bench.txt
```

The programs do not elevate privileges. Arrange the minimum BPF/raw-packet access
required by Scapy through normal operating-system administration.

## Telephony Bench

The bench is a single ATA186/188 on an isolated interface with a fixed private
topology (for example host `.2` and ATA `.10` on one `/24`). The host must own the
service address and the ATA must be reachable before any component binds.

Read-only route and NWI checks are always done before a live command. Never run
these tools on a shared, production, or Internet-facing network.

### DHCP (`dhcp.py`)

`dhcp.py` is a bounded single-lease responder. It derives its defaults from the
selected interface:

```sh
python3 -B dhcp.py --dry-run --interface NAME
python3 -B dhcp.py --apply --interface NAME [--client-address ATA_IPV4] \
  [--client-mac ATA_MAC] [--lease-seconds 600] [--timeout-seconds 3600]
```

The OFFER and ACK include the TFTP server options the ATA needs (`66` name and
`150` address) when provisioning over TFTP is used. Dry-run is the default and
opens no socket.

### TFTP profile provisioning (`telephony/tftp_profile.py`)

The ATA fetches its configuration from TFTP at boot when provisioning is enabled.
The server is bounded: it serves one allow-listed filename to one expected peer
for one bounded window:

```sh
python3 -B telephony/tftp_profile.py --apply \
  --profile /path/to/ata-profile \
  --allow-name atadefault.cfg \
  --expected-client ATA_IPV4 \
  --run-seconds 300
```

Build the profile from the device's own `/dev.xml` snapshot (see
`telephony/ata_dev_post.py`) or from a `#txt` text profile via
`refactor/cfgfmt.py`. Historical firmware requests a per-device name such as
`ata<mac-without-separators>` and may fall back to `atadefault.cfg`. Keep
device-specific profiles local.

### SIP registration and calls (`telephony/sip_bench_proxy.py`)

A bounded registrar/UAS that answers one fixed peer: REGISTER with `200 OK`, and
INVITE to a fixed extension with PCMU (RTP/AVP 0) plus a short generated PCMU
tone streamed to the peer. Inbound RTP is counted, never stored. One dialog at a
time, bounded call time and bounded run time.

```sh
python3 -B telephony/sip_bench_proxy.py --apply \
  --address HOST_IPV4 --expected-peer ATA_IPV4 \
  --run-seconds 1800 --call-seconds 90
```

The tone is a deliberate repeating pattern (for example 300 ms of 440 Hz then
silence) so it is distinguishable from voice; hearing it in the handset is the
media proof, not a rejection.

### Bench verification

With DHCP, TFTP, and the registrar running, power-cycle the ATA once. Expected at
boot: DHCP OFFER/ACK, a TFTP request for the profile, then REGISTER to the service
address, then a call to the extension with ringing plus the audible tone
(`rtp_tx`/`rtp_rx` counters prove media). The `/dev.xml` snapshot should show the
applied values (`GkOrProxy` and `SIPRegOn`).

Any ambiguity is a stop condition, never permission to redial, replay, or rerun.

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

### Building a bench profile

The smallest supported way to change a device is to read its current `ATADev` XML:

```sh
python3 -B telephony/ata_dev_post.py --apply \
  --url http://<ATA-IP>/dev --proxy 192.168.2.2 --reg-on 1
```

(Dry-run is the default; `--apply` performs the single POST.) The same snapshot can
be converted to a binary `#ata` profile with `refactor/cfgfmt.py` for TFTP
delivery. Keep device-specific profiles and passwords local.

## Offline Configuration Profiles

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
python3 -B -m unittest discover -s tests/unit -v

python3 -B -m unittest \
  refactor.tests.test_ata_upgrade_client \
  refactor.tests.test_cfgfmt \
  refactor.tests.test_mipsx_dasm \
  refactor.tests.test_sata186us \
  refactor.tests.test_zup_bank \
  refactor.tests.test_zup_rebuild -v
```

Host-loopback media qualification lives in `tests/host/` and is run only when
intentionally qualifying the local host:

```sh
python3 -B -m unittest discover -s tests/host -v
python3 -B -m telephony.host_qualification --run
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

- Modern Asterisk SIP registration, dial plan, and media interop for the provable
  bench SIP path
- Controlled inbound ringing, outbound calling, and codec negotiation beyond PCMU
- Version-specific backup, configuration, and recovery procedures
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