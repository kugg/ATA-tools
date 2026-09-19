# ATA 186/188 configuration formats — research notes

Handoff document for a follow-on agent. Everything here is derived from the pinned,
local artifacts in this repository (no device contact, no network). It records the
**configuration file formats** used by the Cisco ATA 186/188 SIP firmware
`ata_03_01_00_sip_040211_1` (SW 3.1.0), the vendor tools that read/write them, and the
Python reimplementations in `refactor/`.

Evidence levels are marked:

* **[proven]** — reproduced from a pinned artifact, a passing test, or the vendor tool text.
* **[inferred]** — reverse-engineered behaviour encoded in `refactor/cfgfmt.py`; plausible
  but not independently confirmed against a device.
* **[open]** — unresolved; listed in "Open questions" for the next agent.

> Secrets: this document contains **no** keys, passwords, or device credentials. The example
> profiles in `telephony/` are local test values.

---

## 0. Artifact inventory

All under `ata_03_01_00_sip_040211_1/` unless noted.

| File | Role | Evidence |
| --- | --- | --- |
| `ptag.dat` | **Parameter tag descriptor table** (plain text, CRLF) used by `cfgfmt` | [proven] |
| `cfgfmt.exe` / `.linux` / `.sun` | Text→binary (and reverse) profile compiler, v2.3 | [proven] |
| `cfgfmt.txt` | `cfgfmt` usage text | [proven] |
| `sip_example.txt` | Example **text** profile (`#txt`), release 2.16 | [proven] |
| `sip_factory.html` | Sample web page of **factory defaults** (SIP) | [proven] |
| `sata186us.*` / `sata186us.txt` | Firmware **upgrade server** (`.zup`/`.kup`), v3.1 | [proven] |
| `prserv.*` / `prserv.txt` | Debug **log server** (NPRINTF), v2.0 | [proven] |
| `zupinfo.*` / `zupinfo.txt` | Extract image name/version from a `.zup` | [proven] |
| `bitaid.*` / `bitaid.txt` | Bitmap (bit-field) helper for hex config values | [proven] |
| `atapost.pl` / `atapost_readme.txt` | HTTP POST of parameter/value pairs, v2.0 | [proven] |
| `cptones.txt` | Per-country call-progress tone config | [proven] |
| `telephony/ata00070e36e57b.txt` | Local working **text** profile | [proven] |
| `telephony/ATA00070E36E57B.cnf.xml` | Local **XML** config for the same device | [proven] |
| `refactor/cfgfmt.py` | Bounded Python reimplementation of `cfgfmt` + tests | [inferred] |
| `refactor/prserv.py` | Bounded loopback observer of the debug UDP channel | [inferred] |
| `refactor/sata186us.py` | Python upgrade-server model | [inferred] |

Pinned digests live in `docs/firmware-analysis.md` ("Pinned Inputs"). The package
`ATA030100SIP040211A.zup` SHA-256 is `b8597657…`; the reconstructed 512 KiB bank is
`ee2247ad…`.

---

## 1. Configuration representations

The ATA accepts the **same logical configuration** in four encodings:

1. **Text profile** (`#txt`) — human-authored, one `Name:Value` per line. Compiled locally
   by `cfgfmt` into (2).
2. **Binary TLV profile** (`#ata`) — what the ATA downloads over TFTP and stores in flash.
   This is the canonical wire format.
3. **XML config** (`<ATADev>`) — Cisco Unified CM / TFTP XML delivery, one
   `<Tag value="…"/>` element per parameter. Served as `<MAC>.cnf.xml`.
4. **Web UI form** (HTML) — the browser configuration page. `sip_factory.html` is the ATA 188
   (SIP) **factory settings** page; fields are named by the same parameter names and POST to
   the `dev` endpoint (matches `atapost.pl`'s HTTP path).

The parameter **names and value encodings are shared** across all four; only the container
differs.

---

## 2. `ptag.dat` — the parameter tag descriptor table  [proven]

Plain-text, CRLF, one descriptor per line. Header comment (verbatim structure):

```
tag,tagFmtBit,nameStr,size,context
```

* `tag` — integer TLV tag for the parameter.
* `tagFmtBit` — bitmap of the value's format (see below).
* `nameStr` — the parameter name used in text/XML profiles.
* `size` — length in bytes of the encoded value.
* `context` — protocol applicability bitmap.

### 2.1 Format bits (`tagFmtBit`)

| Bit | Meaning |
| --- | --- |
| `0x0002` | IPv4 address |
| `0x0004` | 32-bit integer |
| `0x0008` | digits (0-9 and dot) |
| `0x0010` | alphabetic characters |
| `0x0020` | boolean |
| `0x0040` | array of shorts (2-byte values) |
| `0x0080` | extended IP address (`IP.PORT`) |
| `0x0100` | tone frequency format (obsolete) |
| `0x0200` | unsigned integer / hex bitmap |
| `0x4000` | **sensitive**: omitted from `ata<mac>` when `-g` is given |
| `0x8000` | **v3.0 extended-profile** member (split when profile > ~2000 bytes) |

Note the `0x000C` used by many tags = `0x0004 | 0x0008` (integer/digits); `0x0006` =
`0x0002 | 0x0004` (IP as integer); `0x020C` = hex/unsigned integer; `0x0010|0x4000` =
sensitive string.

### 2.2 Context bits (`context`)

| Bit | Protocol |
| --- | --- |
| `0x1` | H.323 |
| `0x2` | SIP |
| `0x4` | MGCP |
| `0x8` | SCCP |

`0xF` = all protocols. The `cfgfmt` protocol filters (`-sip`, `-h323`, `-mgcp`, `-sccp`)
select descriptors by this field.

### 2.3 Aliases / obsoleted names

Several tags have multiple names (the *last matching line wins* on lookup — see
`_lookup_by_tag`, `refactor/cfgfmt.py:1088`). Examples: `RxCodec`/`PrfCodec` (tag 7),
`UseSIP`/`UseMGCP` (18), `UID0`/`CA0UID` (25), `GkOrProxy`/`CA0orCM0` (29),
`DialTone`/`DialToneFreq` (36). A follow-on agent should treat the first name as canonical
for SIP.

### 2.4 Full descriptor list

See **Appendix A** (all 110 descriptors, verbatim).

---

## 3. Text profile format (`#txt`)  [proven]

From `sip_example.txt` (header comment) and `refactor/cfgfmt.py:747` (`parse_text_profile`):

* **Must begin with `#txt`** for `cfgfmt` to treat the file as text.
* Lines beginning with `#` are comments.
* Parameter/value pairs are `Name:Value` (one per line; all optional).
* Value types:
  * alphanumeric string — `SIP-4-Ever$#, 1234`
  * numeric digit string — `593, 960135`
  * comma-separated array of shorts — `395,65534,20,32768`
  * IPv4 — `192.168.2.170`
  * extended IPv4 (IP.PORT) — `192.168.2.170.9001`
  * boolean — `0`/`1`
  * bitmap / unsigned hex — `0x00060400`
  * 32-bit integer — `2147483647`
* `#include`-style includes are parsed relative to the source directory and are
  path-confined (`_safe_include_path`, `refactor/cfgfmt.py:726`) — the original followed
  arbitrary includes; the reimplementation refuses escapes.

### 3.1 Pseudo parameters (not in `ptag.dat`)  [inferred]

Handled specially in `parse_text_profile` / `_store_pseudo`:

| Tag | Text name | Encoding |
| --- | --- | --- |
| `0x1100` | `UpgradeCode` | `n,a,b,c,ip,port,f,string` (8 fields) |
| `0x1101` | `UpgradeLang` | same shape as `UpgradeCode` |
| `0x1102` | (`TftpURL2`) | NUL-terminated string |
| `0x1103` | `UpgradeLogo` | `a,ip,string` |
| `0x1104` | (`UpgradeXml`) | `a,ip,string` |
| `0x1105` | `EncryptKeyEx` | `key[ sep]mac` → `mac(6) || key(32)`; see §4.5 |
| `0x4000` | — | extended-file pointer (split profiles) |
| `0x7FFE` | — | profile header (checksum + length) |

---

## 4. Binary TLV profile format (`#ata`)  [inferred, from `refactor/cfgfmt.py`]

The binary format is byte-oriented and big-endian. Build path: `build_records`
(`refactor/cfgfmt.py:930`), `_header_block` (`:963`), `_write_one_file` (`:1035`).

### 4.1 Overall layout (unencrypted, unsplit)

```
"#ata"                        4-byte magic
header                        TLV tag 0x7FFE
payload                       sequence of TLVs
```

### 4.2 Header block

`_header_block(payload, strong)`:

```
encode_varint(0x7FFE)         header tag
encode_varint(4)              header length
uint16  checksum              checksum of payload
uint16  length                payload length
```

* `strong == False` → `checksum_simple` = 16-bit sum of payload bytes (`sum & 0xFFFF`).
* `strong == True` → `checksum_internet` = one's-complement 16-bit checksum (RFC 1071 style),
  with odd trailing byte added directly.

### 4.3 TLV records

Each record is `varint(tag) || varint(len) || value`.

Varint (`encode_varint`/`decode_varint`, `:248`): values `< 0x80` are one byte; otherwise two
bytes `0x80|((v>>8)&0x7F), v&0xFF`. Max representable 0x7FFF.

### 4.4 Splitting into an extended profile

* Threshold: estimated size ≥ `SPLIT_THRESHOLD = 0x7D1` (2001) bytes (`:40`).
* Two files are produced: the base profile and `<output>.ex`.
* A record with format bit `0x8000` goes **only** into `.ex`; all others go into the base.
* The base file ends with a pointer record: `varint(0x4000) || varint(len+1) || "<name>.ex\0"`.
* `-split` forces splitting; the original also reports "output binary file too big".

### 4.5 Encryption

Two independent mechanisms (both keyed from the **profile text**, not the CLI, unless a
private key file is supplied):

1. **Weak / legacy** (`EncryptKey`, CLI `-eRc4Passwd`):
   `output = RC4(hex_key).crypt(entire "#ata"+header+payload)`.
2. **Strong** (`EncryptKeyEx`, CLI `-xRc4Passwd`, must be hex):
   ```
   rand8    = 8 random bytes
   masked   = (header || payload) XOR rand8   # byte i XOR rand8[i & 7]; no "#ata"
   output   = RC4(strong_key).crypt(masked || rand8)
   ```
   Strong output has **no `#ata` magic**. When both passes run, the strong file is written to
   `<output>.x` / `<output>.xex`.

`EncryptKeyEx` text form is `key[ / | space | tab ]mac` (delimiters are **not** comma). The
key is 32 hex chars (16 bytes); the MAC is 6 bytes (or zeros).

RC4 matches the firmware's KSA/PRGA (`FUN_08048d08`, `FUN_08048be4`); see
`_ksa_from_key_bytes` / `_ksa_from_hex_string` (`refactor/cfgfmt.py:173`). Non-hex key
characters trigger a strength warning.

### 4.6 Special tag `0x1105`

`_wrap_1105` (`:922`): the 0x26-byte inner value is checksummed (internet), prefixed with a
fixed 4-byte blob, and the tail is RC4-encrypted with a fixed 16-byte key derived from a
`.data` blob at `0x0804ed60` (`_fixed_1105_material`, `:295`, referencing `FUN_0804a60c`).

### 4.7 Decode direction

`binary_to_text` (`:1158`) emits `#txt` then walks the TLV stream, resolving tags through
`ptag.dat` (`_lookup_by_tag`) and printing `Name:Value`. Unknown tags are rendered by
`decode_pseudo` (`:1135`). This is the tool's `-d`/reverse path and is useful for turning a
captured device profile back into readable text.

---

## 5. XML configuration format (`<ATADev>`)  [proven]

`telephony/ATA00070E36E57B.cnf.xml` is the local example. Structure:

```xml
<ATADev>
  <UseTftp value="1"/>
  <TftpURL value="0"/>
  <CfgInterval value="3600"/>
  <EncryptKey value="0"/>
  <EncryptKeyEx value="000…00"/>
  <Dhcp value="1"/>
  <StaticIP value="0.0.0.0"/>
  <GkOrProxy value="192.168.2.2"/>
  <SIPPort value="5060"/>
  <UID0 value="100"/> <PWD0 value="0"/>
  <DialPlan value="*St4-|#St4-|…"/>
  <Version value="v3.1.0 atasip"/>
  <MAC value="00070e36e57b"/>
</ATADev>
```

* One element per parameter; the element name is the `ptag.dat` `nameStr`; `value` is the
  same text encoding as `#txt`.
* Delivered over TFTP as `<MAC>.cnf.xml` (CUCM-style). See TODO item "Harden … retain
  version-specific evidence and statically limit the initial XML configuration to 4096
  bytes".
* The XML and text profiles in `telephony/` are the **same 73 parameters** — a direct
  name↔name correspondence, useful as a Rosetta stone.
* Cisco bug `CSCsd44357` (TODO.md) concerns ATA186 CUCM/TFTP XML configuration.

---

## 6. Provisioning and delivery paths  [proven]

* **TFTP profile download**: ATA is a TFTP client (`UseTftp`, `TftpURL`, `AltTftpURL`,
  `CfgInterval`). The binary profile is fetched periodically (bench: `CfgInterval:3600`).
  Firmware-side strings: `tftp(0x%08x,%s)`, `tftpGet` (`docs/ata-sip-firmware-services.md`).
* **Profile-driven reset**: applying a fetched profile that reports `cfgNeedReboot` triggers
  an immediate reset (see `docs/ata-sip-firmware-services.md`, "profile-driven reset").
* **HTTP POST**: `atapost.pl <ip> -field=value` (v2.0+) and `-xml` (v3.0+) — requires the
  web interface enabled (`OpFlags` bit 7 clear).
* **IVR voice menu**: numeric access codes (e.g. `7387277` for `UIPassword`, `81#` for
  `NPrintf`); `*` enters the dot in IP addresses.
* **PC upgrade server**: `sata186us` serves `.zup` (software) / `.kup` (language) images on
  port 8000; the phone is told `100#<pc_ip>*8000#` (software) or `101#…` (language).

---

## 7. Debug / log channel  [proven]

* Parameter `NPrintf` = `<ip>.<port>` (extended-IP format); the ATA sends diagnostic text to
  that UDP endpoint. Bench profile uses `NPrintf:0.0.0.0.0` (disabled).
* `prserv` (v2.0) receives it, default UDP port **9001**, writes `<port>.log`; `-t` prefixes
  local timestamps. `refactor/prserv.py` is a bounded loopback observer (never persists packet
  contents) — useful for offline inspection without contacting a device.
* This channel is the natural place to look for runtime config traces (the "strings
  debugging" angle). `TraceFlags` / `SyslogIP` / `SyslogCtrl` control related logging.

---

## 8. Where the config code lives in the firmware  [partially resolved]

### 8.1 The config/UI strings are in the **transition** image, not the SIP bank

Direct string search over both reconstructed banks:

| Needle | SIP bank (`ATA030100SIP040211A.zup`) | Transition bank (`transition.zup`) |
| --- | ---: | ---: |
| `#ata` (profile magic) | 0 | 1 (bank `0x7471c`) |
| `StaticIP`, `UIPassword`, `DialPlan`, `CfgInterval` | 0 | present |
| `<html>`, `HTTP/1.1`, `Content-Type` | 0 | present |
| `<td bgcolor=…` (web form generator) | 0 | present (`0x73c40`) |
| `ATA186` / `Cisco ATA 186` | 0 | present (`0x73b28`) |
| `Komodo` (build codename) | 0 | present (`0x73af1`) |

Concrete locations in the **transition bank**:

* **Parameter-name table** (NUL-separated, the ordered list the web UI iterates):
  bank `0x73837`–`0x73a97` — `CallCmd, OutBoundProxy, DialPlan, UDPTOS, MediaPort, SIPPort,
  NATIP, AltGk, EncryptKey, RingOnOffTime, AlertTone, CallWaitTone, RingBackTone, ReorderTone,
  BusyTone, DialTone, PServer, NPrintf, TftpURL, … UID0/PWD0/UID1/PWD1 … StaticIP, MAC`.
* **`UIPassword` special table** at `0x733ca` (name followed by a 40-byte small-value array).
* **Web form generator** format string at `0x73c40`:
  `<td bgcolor=%s>%s: <td><input size=20 type=%s name="%s" Value="%s"><br>`; HTTP response
  strings `0x73c8c`–`0x73fb1`; `Version: %s (Build %s)` at `0x73f2f`.
* **`#ata` magic** at `0x7471c`; `tftp %d %d %d` / `nextTftp %d` / `TFTP` nearby.
* `0x73b60` `dev`, `0x73b64` `admsip`, `0x73b6b` `admh323`, `0x73b73` `adv40c9` — web endpoints.

**Consequence:** the config parser and web UI code for this package is in the **transition
firmware**, not the SIP 3.1.0 bank. The SIP bank and its packed main/aux contain none of these
strings. The SIP 3.1.0 config path is therefore still unresolved — it may live in a component
outside this reconstructed bank, or use a non-string (compact) encoding. This is a genuine
open question, not an artifact of the reconstruction (the SIP bank is byte-identical to the
pinned digest).

### 8.2 The `cfgfmt.py` function addresses

`refactor/cfgfmt.py` cites functions it reproduces:

| Address | Role (comment in `cfgfmt.py`) |
| --- | --- |
| `FUN_08048d08` | RC4 KSA |
| `FUN_08048be4` | RC4 PRGA |
| `FUN_08049184` / `FUN_080491f0` | varint encode/decode |
| `FUN_08049274` / `FUN_080492b4` | checksums (simple / internet) |
| `FUN_0804a60c` | tag `0x1105` wrapping (fixed `.data` blob at `0x0804ed60`) |
| `FUN_0804ab4c` | text profile parsing |
| `FUN_0804b79c` | binary building |
| `FUN_0804c70c` / `FUN_0804a728` | binary decoding |

These are in the `0x0804xxxx` range and appear **nowhere** in the repo except `cfgfmt.py`'s
comments; the disassembly dumps and Ghidra projects are all `0x0CF8xxxx`. A quick test of the
obvious base hypothesis (`0x08000000 + offset` → transition bank offset `0x48d08`) found
**data, not code**, so that base is wrong. The base these addresses belong to is still
unresolved.

### 8.3 Recommended next step

Disassemble the **transition bank** around the name table (`0x73000`–`0x74800`) to recover the
actual config/web logic (name table iteration, form generation, `#ata` handling) and to locate
the RC4/varint/checksum routines the reimplementation models. This uses the reversed firmware
directly and would let `docs/ata-config-formats.md` stop relying on `cfgfmt.py`'s comments.

### 8.4 The config parser and dispatcher in the packed main  [proven from the decompiled C]

The SIP **application** (packed main, base 0, decompiled in `ghidra-project-packed`) does the
profile parsing with numeric constants — there are no strings and no C `switch`; the dispatch
is table/pointer based, matching the working hypothesis that config drives function-pointer
selection.

Chain recovered from the annotated C (`research/decompiled/named/packed_main_annotated.c`):

| Function | Role |
| --- | --- |
| `sub_00037a1c` | **Profile parser.** Reads varints (`sub_00010dfc`), checks header `tag == 0x7FFE && len == 4`, verifies checksum (`sub_0000ff7c`), then calls the TLV processor. Error paths log `0x60xx` codes via `sub_000381e4`. |
| `sub_000380c0` | **TLV record loop.** For each `(tag,len)`: skips `tag < 0xff` unless `tag == 1` or `0x12`; applies via `sub_00024688`; special-cases tags `0x23` and `0x66`; logs `0x6048/0x6088/0x609c` via `sub_00010268`. |
| `sub_00024688` | **Tag setter** = `store(lookup(tag), value)`. |
| `sub_00024aa8` → `sub_00024ae8` | **Tag lookup**: linear search of a descriptor table at RAM **`0x4026 + i*0x10`** (16-byte stride) for the tag word. |
| `sub_00024064` | **Apply**: index-bounded `1..0x54`; reads a **0x14-byte descriptor at RAM `0x4024 + index*0x14`** and a **0xc-byte state entry at RAM `0x9d84 + index*0xc`**. This is the "config struct" the settings are loaded into. |
| `sub_00010268` | **Logger/trace**: `sub_0000bb60` (format) → `sub_000100e8`. |
| `sub_000100e8` | **Log dispatcher**: only records whose first byte is `0x60`; calls the **resident** `dispatcher_f82b38(param, ..., 0)` and manages log state (`iRam00008390`). |
| `sub_000381e8` / `sub_000381e4` | Completion / error-report tail targets (event codes `0x60xx`). |

**Cross-module evidence:** `sub_000100e8` calls `dispatcher_f82b38`, a **resident** function
name from `signatures.json`, and `sub_000380c0` calls `func_0cf80f8c`. These are exactly the
`r24` cross-module calls resolved in §"r24" above — the packed main drives resident
dispatchers. This supports the hypothesis: config state selects which dispatched task runs, and
the trace/syslog path (`sub_00010268` → `dispatcher_f82b38`) fires after each dispatched task.

**Tables to recover next** (all in packed-main RAM, base 0):

* `0x4024`, stride `0x14`, indices `1..0x54` — the parameter descriptor table (likely
  tag/format/size/current-value, cf. `ptag.dat`).
* `0x9d84`, stride `0xc` — per-parameter runtime state.
* `0x4026`, stride `0x10` — tag→index lookup table.

Dump these tables from the decompiled data or the emulator and they become the firmware-side
counterpart of `ptag.dat`.

### 8.5 The `.linux` tools are i386 ELF (for format mapping)

`cfgfmt.linux` (stripped), `prserv.linux` and `sata186us.linux` (both **not stripped**, e.g.
`BigNumAdd` in `sata186us.linux`) are 32-bit i386 ELF, dynamically linked. They implement the
PC-side format exactly and are the authoritative reference for the TLV/RC4/varint/checksum
behaviour `refactor/cfgfmt.py` models. Import them into Ghidra (i386 has first-class analysis)
to confirm the format rather than trusting the reimplementation — this is the recommended way
to close the `FUN_0804xxxx` question.

---

## 9. Working commands

Two practical gotchas:

* The text profile **must begin with `#txt`**. The local
  `telephony/ata00070e36e57b.txt` does **not** (it starts at `UseTftp:1`), so it must be
  prepended before compiling, or `cfgfmt` treats it as binary and fails with
  `unknown or encrypted input file`.
* `cfgfmt.py`'s default tag table is `ptag.dat` **in the current directory**; the file lives
  under `ata_03_01_00_sip_040211_1/`, so pass `-t<path>` (no space).

Direction is **auto-detected from the input magic**, not a flag: input starting with `#txt`
is compiled to binary; anything else is decoded back to text. Inline `-e`/`-x` keys are
**rejected** — encryption keys must come from a private mode-0600 key file.

```bash
P=ata_03_01_00_sip_040211_1/ptag.dat

# text profile -> binary TLV profile (prepend the required #txt magic)
{ printf '#txt\n'; cat telephony/ata00070e36e57b.txt; } > /tmp/profile.txt
python3 refactor/cfgfmt.py -t$P /tmp/profile.txt /tmp/out.bin

# binary profile -> text (auto-detected; input must not begin with "#txt")
python3 refactor/cfgfmt.py -t$P /tmp/out.bin /tmp/recovered.txt

# protocol-filtered build (only SIP-context descriptors)
python3 refactor/cfgfmt.py -t$P -sip /tmp/profile.txt /tmp/sip.bin

# encryption: weak (RC4 hex key) or strong, from private key files only
python3 refactor/cfgfmt.py -t$P --key-file=/path/mode0600.key  /tmp/profile.txt /tmp/out.bin
python3 refactor/cfgfmt.py -t$P --xkey-file=/path/mode0600.xkey /tmp/profile.txt /tmp/out.bin

# Offline observer of the NPrintf debug channel (loopback only)
python3 refactor/prserv.py 9001

# Tests
python3 -m unittest refactor.tests.test_cfgfmt
```

Verified locally: the compile produced a `#ata` file (791 bytes) whose header is
`fffe 04 <csum16> <len16>`; decoding it back yielded 75 `#txt` lines with
`#EncryptKeyEx:<secret>` redacted by the tool. Compiling the working profile emits
`warning: unknown attribute at line 27` because `OutBoundProxy` is not a `ptag.dat` name (the
tag is `SipOutBoundProxy`, tag 75) — a real inconsistency in the local profile worth fixing.

Flags (from `parse_options`, `refactor/cfgfmt.py:1196`): `-v` verbose, `-g` omit sensitive
(`0x4000`) parameters, `-t<file>` tag table, `-split` force split, `-sip`/`-h323`/`-mgcp`/
`-sccp` protocol filters, `--key-file=`/`--xkey-file=` private keys. The positional arguments
are exactly `input output`.

---

## 10. Open questions for the next agent

1. **Dump the packed-main config tables** (§8.4): `0x4024` (stride `0x14`, indices `1..0x54`),
   `0x9d84` (stride `0xc`), `0x4026` (stride `0x10`). These are the firmware-side counterpart of
   `ptag.dat`; recovering them maps TLV tag → internal index → descriptor/state.
2. **Map the resident log/dispatch path**: `dispatcher_f82b38` (called from `sub_000100e8`) and
   the other `r24` cross-module targets; this is the syslog-after-dispatch family.
3. **Confirm the binary/encryption format** by importing the i386 ELF tools (`cfgfmt.linux`
   etc., §8.5) into Ghidra, closing the `FUN_0804xxxx` question directly instead of trusting
   `refactor/cfgfmt.py`.
4. **Confirm the split/extended mechanics** against a device profile >2000 bytes: file naming
   (`<out>` + `<out>.ex`, and `.x`/`.xex` for the strong pass) and the `0x4000` pointer.
5. **RC4 key handling**: exact KSA variants for the hex-string (`-e`) vs byte (`-x`) keys, and
   whether `EncryptKey`/`EncryptKeyEx` in a served profile are *configuration data* or also
   select output encryption (the reimplementation treats them as data).
6. **XML field completeness**: is the `<ATADev>` element set identical to the `ptag.dat` names,
   and does CUCM add/rename any?
7. **`bitaid`**: reconstruct the exact bit-range semantics for the bitmap parameters
   (`OpFlags`, `CallFeatures`, `VLANSetting`, …).
8. **Tones**: `cptones.txt` per-country tables vs the `DialTone`/`BusyTone` array encoding
   (`tone_pair`, `refactor/cfgfmt.py:484`).
9. **Provisioning security**: the profile is RC4-protected, not authenticated; document the
   threat model before any live use (see `docs/security.md`).

---

## Appendix A — `ptag.dat` descriptors (verbatim, 110 lines)

```
tag      fmt     name                size  context
3        0x0006  StaticIP            4     0xF
4        0x0006  StaticRoute         4     0xF
5        0x0006  StaticNetMask       4     0xF
7        0x000C  RxCodec             4     0x3
7        0x000C  PrfCodec            4     0xC
8        0x000C  TxCodec             4     0x3
9        0x0006  DNS1IP              4     0xF
10       0x0006  DNS2IP              4     0xF
11       0x000C  NumTxFrames         4     0xF
12       0x020C  AutMethod           4     0x1
13       0x000C  SIPRegInterval      4     0x2
14       0x000C  MaxRedirect         4     0x2
15       0x0028  Dhcp                1     0xF
17       0x0028  IPDialTone          1     0x3
18       0x0028  UseSIP              1     0x3
18       0x0028  UseMGCP             1     0xC
19       0x0028  SIPRegOn            1     0x2
20       0x0028  UseTftp             1     0xF
21       0x0028  UseLoginID          1     0x3
21       0x0028  UseH323ID           1     0x1
23       0x4008  UIPassword          10    0xF
24       0x0006  NTPIP               4     0x3
25       0x4010  UID0                32    0x3
25       0x4010  CA0UID              32    0xC
26       0x4010  PWD0                32    0x3
27       0x4010  UID1                32    0x3
27       0x4010  CA1UID              32    0xC
28       0x4010  PWD1                32    0x3
29       0x0010  GkOrProxy           32    0x3
29       0x0010  CA0orCM0            32    0xC
30       0x0010  Gateway             32    0x1
31       0x0010  GkId                32    0x3
32       0x0010  TftpURL             32    0xF
35       0x0080  NPrintf             6     0xF
36       0x0150  DialToneFreq        18    0xF
36       0x0050  DialTone            22    0xF
37       0x0150  BusyToneFreq        18    0xF
37       0x0050  BusyTone            22    0xF
38       0x0150  ReorderToneFreq     18    0xF
38       0x0050  ReorderTone         34    0xF
39       0x0150  RingBackToneFreq    18    0xF
39       0x0050  RingBackTone        22    0xF
40       0x0150  CallWaitToneFreq    18    0xF
40       0x0050  CallWaitTone        22    0xF
41       0x0010  DialPlan            200   0x3
43       0x0050  DialTone2           22    0xF
44       0x4010  LoginID0            52    0x3
44       0x4010  H323id0             52    0x1
44       0x0010  EPID0orSID0         52    0xC
45       0x4010  LoginID1            52    0x3
45       0x4010  H323id1             52    0x1
45       0x0010  EPID1orSID1         52    0xC
47       0x0150  AlertToneFreq       18    0xF
47       0x0050  AlertTone           22    0xF
47       0x0050  ConfirmTone         22    0xF
48       0x0050  SITone              34    0x2
49       0x0028  ToConfig            1     0xF
50       0x000C  CfgInterval         4     0xF
52       0x000C  IPDialPlan          4     0x3
54       0x000C  LBRCodec            4     0xF
55       0x020C  Polarity            4     0xF
56       0x000C  TimeZone            4     0x3
57       0x020C  ConnectMode         4     0xF
58       0x020C  AudioMode           4     0xF
59       0x020C  TraceFlags          4     0xF
60       0x0050  RingOnOffTime       6     0x3
60       0x0050  RingCadence         6     0xC
61       0x0010  EncryptKey          9     0xF
62       0x020C  CallFeatures        4     0x3
63       0x0010  CallCmd             248   0x3
64       0x020C  PaidFeatures        4     0x3
65       0x020C  CallerIdMethod      4     0xF
66       0x0010  AltTftpURL          32    0x8
67       0x0010  AltGk               32    0x3
67       0x0010  CA1orCM1            32    0xC
68       0x0006  NATIP               4     0x2
69       0x000C  SIPPort             4     0x2
70       0x000C  MediaPort           4     0xF
71       0x000C  GkTimeToLive        4     0x1
72       0x020C  TOS                 4     0xF
72       0x020C  UDPTOS              4     0xF
74       0x000C  AltGkTimeOut        4     0x3
75       0x0010  SipOutBoundProxy    32    0x2
76       0x020C  SigTimer            4     0xF
77       0x020C  OpFlags             4     0xF
78       0x0006  AltNTPIP            4     0x3
90       0x0010  CodecName           248   0x4
91       0x000C  MGCPPort            4     0x4
92       0x000C  RetxLim             4     0x4
93       0x000C  RetxIntvl           4     0x4
94       0x0010  MGCPVer             32    0x4
95       0x020C  VLANSetting         4     0xF
97       0x0010  NatServer           48    0x2
98       0x020C  NatTimer            4     0x2
99       0x0010  Domain              32    0xC
100      0x020C  FeatureTimer        4     0x3
101      0x020C  CFGID               4     0x3
102      0x0080  SyslogIP            6     0xF
103      0x020C  SyslogCtrl          4     0xF
129      0x8010  DialPlanEx          500   0x3
130      0x8010  DisplayName0        32    0x2
131      0x8010  DisplayName1        32    0x2
160      0x020C  FeatureTimer2       4     0x3
161      0x020C  MsgRetryLimits      4     0x2
162      0x020C  SessionTimer        4     0x2
163      0x000C  SessionInterval     4     0x2
164      0x000C  MinSessionInterval  4     0x2
170      0x000C  FXSInputLevel       4     0xF
171      0x000C  FXSOutputLevel      4     0xF
0x2001   0x020C  RegMode             4     0x8
```

(Comments in the source mark some as obsoleted aliases and some as v3.0-only; those were
preserved in the extraction but trimmed here for width — consult the file for the exact
annotations.)
