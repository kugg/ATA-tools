# ATA Firmware Static Analysis

This document records reproducible, offline observations about the reference
`ATA030100SIP040211A.zup` package. It does not authorize contacting an ATA,
serving firmware, executing the vendor utilities, or publishing the local Cisco
artifacts. Package reconstruction is not a physical-device readback.

## Evidence Boundary

The current evidence supports these separate statements:

- Two regions in the reconstructed bank are big-endian MIPS-X instructions.
- The main and auxiliary regions use `r24` as a shared indexed-call register.
  Its inferred byte-coordinate anchor is `0x00040a00`, corresponding to the
  documented architectural word-address value `r24=0x00010280`.
- The code makes 1000 calls through externally initialized `r23`, but no current
  record interpretation establishes its value or the absent resident targets.
- Final type-5 launch values independently encode the exact SIP and transition
  `r24` call-anchor word values. The resident dispatcher directly loads type-5
  field 1 into `r24`.
- Three launch type-8 mode-0 payloads expand to big-endian MIPS-X programs. Their
  mode-1 companions expand initialized data spans, not ZSP400 instructions.
- The four nested `+kbz` outputs validate structurally, but current content
  evidence is table-like and does not establish that any output is ZSP400 code.
- No direct source currently identifies the ATA186 physical CPU or proves that
  its hardware contains a ZSP400 core.

MAME is secondary implementation evidence. Its Linksys PAP2/ES3890F skeleton is
not evidence about the ATA186 board, and its MIPS-X CPU implementation currently
does not execute instructions.

## Pinned Inputs

| Item | Bytes | SHA-256 |
| --- | ---: | --- |
| `ATA030100SIP040211A.zup` | 319159 | `b8597657928905aea66924118889f0883bd38c0804ddf880e3be2c33ccf62eb5` |
| reconstructed 512 KiB bank | 524288 | `ee2247ad3b9cbd5d711f4985cbdce220359e6edff6555d8486e119e767c8f8c6` |
| `transition.zup` | 274436 | `9cf97b172f4d3422dfa54ad9708a5e110637130963d9f1bc1f1e70c1bbfcc278` |
| reconstructed transition bank | 524288 | `ad7abb7575a14885c171f4cf6a630f60547d2ccd03b47b55c04a279278332eee` |
| MIPS-X report, DTIC ADA181619 | 2845901 | `34080b1e651e6699fd7a089b088f2ae627786df54e6a31e8e64e5e97523d2b21` |
| ZSP400 architecture manual, DSA0093274 | 641348 | `66d1b83611a157f9e84e48d50222375ee8b754764add4f167a8a353bc2550257` |

The pinned package identifies platform `0x0301`, protocol `0x0400`, and version
`0x0301`. Its outer `kup1` and inner `+kxz` byte sums are both `0x02932f32`.
Those sums detect accidental damage but are not signatures or provenance proof.

## Bank Structure

The legacy `zupinfo.exe` was decompiled but never executed. Its hidden `xzup`
path creates an `0xff`-filled `0x80000` bank, copies four raw regions, and expands
seven raw-DEFLATE regions from the inner `+kxz` map. Independent reconstruction
produced two byte-identical bank files with the pinned bank hash above.

`firmware/zup_bank.py` now reproduces this process without vendor execution. It
requires a bounded regular no-symlink input, validates the declared inner length
and byte sum, bounds and de-overlaps every destination, requires exact raw-DEFLATE
EOF plus the little-endian CRC-32/ISIZE trailer, and only publishes complete new
mode-`0600` outputs. The SIP package has an optional `ATA4` word between its data
and map table; `transition.zup` has no gap. The decompiled extractor advances by
declared stored lengths and accepts both exact forms.

```sh
python3 -B firmware/zup_bank.py PATH_TO_ZUP
python3 -B firmware/zup_bank.py PATH_TO_ZUP --extract-bank NEW_PRIVATE_BANK
```

Key bank ranges are:

| Range or offset | Observation |
| --- | --- |
| `0x00000` | Main launch header `(0,0x0cfc0110,0x1b,0xd)` |
| `0x00a00..0x2c9d4` | Main MIPS-X executable region |
| `0x2c9d4` | First nested `+kbz` payload |
| `0x2ea0c` | Embedded `ZUP?ATA030100SIP040211A.zup` descriptor |
| `0x40000` | Six-word section header |
| `0x40100..0x402c0` | Repeated launch header followed by 27 records |
| `0x402c0` | Second nested `+kbz` payload |
| `0x479bc`, `0x70010` | Type-8 mode-0 compressed MIPS-X programs |
| `0x6bb60`, `0x6cbcc`, `0x76c20` | Type-8 mode-1 initialized-data payloads |
| `0x70000` | Auxiliary launch header pointing to 18 records at `0x76ee0` |
| `0x76ee0..0x77000` | 18 fixed 16-byte launch records |
| `0x77000` | Third nested `+kbz` payload |
| `0x78390` | Fourth nested `+kbz` payload |
| `0x7d000..0x7e968` | Auxiliary MIPS-X executable region |

The launch headers use the bank's runtime mapping base `0x0cf80000`: subtracting
that base from the second header word gives the first-record bank offset. The
main header points to `0x40110` and declares 27 records; the auxiliary header
points to `0x76ee0` and declares 18. Thus `0x0cfc0110` is a table pointer, not an
`r23` call anchor. Record types `1`, `2`, `3`, `4`, `5`, `6`, `7`, `8`, `9`,
`0xb`, `0xc`, and `0xd` are recognized by the resident dispatcher. The table
relationships and direct handler operations are recorded below; only the CPU meaning
of type 3's high PC tag and the purpose of type `0xd` remain unidentified.

All four nested `+kbz` records have validated header sums, raw-DEFLATE streams,
CRC-32 values, and uncompressed sizes:

| Offset | Output bytes | Output SHA-256 |
| --- | ---: | --- |
| `0x2c9d4` | `0x282c` | `03fcc7acca9747279297d8b5bc05ebe909f628b178733447b7e407a781136a00` |
| `0x402c0` | `0xc4a0` | `38166aad0a0bccb347d9f0246a4c0efd0fa8239ef2d187ccfaf0615c95d52251` |
| `0x77000` | `0x14a4` | `4662618a0ac730e8ff8c0c53104197425684be10540def69b18c8a6c7f812a6a` |
| `0x78390` | `0x24a4` | `d73cd25c5d4ad6e5e5b062dba4cdd1bdc5bb55fd2303f4357ce75d9cdb96076b` |

Their exact six-word big-endian header is now implemented by
`zup_bank.py --nested-payload OFFSET`: magic `+kbz`, version `2`, stored-byte
sum, stored length, output-byte sum, and output length. The stored length includes
one raw-DEFLATE stream followed by its eight-byte little-endian CRC-32/ISIZE
trailer. Aggregate requested output is capped at 512 KiB and nothing is written.

No extracted payload or reconstructed bank belongs in Git.

## Disassembly Availability

`firmware/mipsx_dasm.py` can emit a complete linear disassembly for every confirmed
MIPS-X program. Each line contains the selected byte-coordinate address, raw 32-bit
word, and decoded instruction. Optional modes add resolved xrefs, register-base
inference, and delay-slot-aware transfer summaries. This is reproducible disassembly,
not decompiled pseudocode, recovered source symbols, or a complete control-flow graph.

The confirmed program inventory is:

| Image | Stored or resident location | Disassembly size | Coordinate note |
| --- | --- | ---: | --- |
| SIP resident main | Bank `0x00a00..0x2c9d4` | 45,045 words | Bank byte offsets |
| SIP inflate helper | Bank `0x7d000..0x7e968` | 1,626 words | Bank byte offsets |
| SIP reset/dispatcher tail | Bank `0x7f400..0x80000` | 768 words | Mixed code, copied validator, and fixed tail data |
| SIP packed main | Type-8 at bank `0x479bc` | 94,165 words | Output-relative; loaded at `0xc74c..0x686a0` |
| SIP packed auxiliary | Type-8 at bank `0x70010` | 17,275 words | Output-relative; loaded at `0x3000..0x13dec` |
| Transition resident main | Bank `0x00020..0x2aa60` | 43,664 words | Bank byte offsets |
| Transition inflate helper | Bank `0x79af8..0x7b460` | 1,626 words | Bank byte offsets |
| Transition dispatcher fragment | Bank `0x7fd20..0x7fed4` | 109 words | Shared prefix only; the package tail is incomplete |
| Transition packed main | Type-8 at bank `0x4f368` | 91,034 words | Output-relative; loaded at `0xf41c..0x68284` |

For type-8 mode-0 payloads, the direct-package command expands the checked stream in
memory and prints addresses relative to the start of its output. Add the documented
type-9 code start to obtain its loaded byte coordinate. The `r23=0x40000` argument is
therefore the corresponding output-relative linkage anchor. Bank-resident ranges use
bank byte offsets directly.

The following commands emit all confirmed SIP disassembly. Output paths must remain
private and outside the repository because the text includes raw proprietary
instruction words:

```sh
umask 077
python3 -B firmware/zup_bank.py \
  firmware/ATA030100SIP040211A.zup \
  --extract-bank "$PRIVATE_OUT/sip-bank.bin"
python3 -B firmware/mipsx_dasm.py "$PRIVATE_OUT/sip-bank.bin" \
  --region 0xa00:0x2c9d4 --region 0x7d000:0x7e968 \
  --region 0x7f400:0x80000 --reg-base r24=0x40a00 \
  > "$PRIVATE_OUT/sip-resident.mipsx.txt"
python3 -B firmware/mipsx_dasm.py \
  firmware/ATA030100SIP040211A.zup \
  --type8-payload 0x479bc --reg-base r23=0x40000 \
  --reg-base r24=0x40a00 > "$PRIVATE_OUT/sip-packed-main.mipsx.txt"
python3 -B firmware/mipsx_dasm.py \
  firmware/ATA030100SIP040211A.zup \
  --type8-payload 0x70010 --reg-base r23=0x40000 \
  > "$PRIVATE_OUT/sip-packed-auxiliary.mipsx.txt"
```

The corresponding transition commands are:

```sh
umask 077
python3 -B firmware/zup_bank.py \
  firmware/transition.zup \
  --extract-bank "$PRIVATE_OUT/transition-bank.bin"
python3 -B firmware/mipsx_dasm.py "$PRIVATE_OUT/transition-bank.bin" \
  --region 0x20:0x2aa60 --region 0x79af8:0x7b460 \
  --region 0x7fd20:0x7fed4 --reg-base r24=0x40020 \
  > "$PRIVATE_OUT/transition-resident.mipsx.txt"
python3 -B firmware/mipsx_dasm.py \
  firmware/transition.zup \
  --type8-payload 0x4f368 --reg-base r23=0x40000 \
  --reg-base r24=0x40020 > "$PRIVATE_OUT/transition-packed-main.mipsx.txt"
```

Mode-1 type-8 outputs are initialized data, not programs. The four nested `+kbz`
outputs are table-like and have no justified processor assignment, so no disassembly
is claimed for either class. Generated bank and disassembly files remain ignored local
evidence; Git retains the decoder, tests, hashes, scalar findings, and commands only.

## Reversible Package Rebuilding

`firmware/zup_rebuild.py` rebuilds one new package from a validated template and an
exact 512 KiB bank. It is an offline structural tool, not a signing, flashing, or
device-qualification path:

```sh
python3 -B firmware/zup_rebuild.py \
  PATH_TO_TEMPLATE.zup PATH_TO_BANK NEW_PRIVATE_PACKAGE
```

The builder first applies the same strict map validation as `zup_bank.py` and rejects
an empty or control-character outer package name. Raw regions are copied from the
requested bank. By default, each compressed region whose decoded bytes are unchanged
retains its original encoded bytes exactly; a changed region is regenerated as raw
DEFLATE followed by little-endian CRC-32 and ISIZE. The original 24-byte outer header
and any validated `ATA4` map gap are preserved, while the descriptor table, inner
lengths, and additive checksum are regenerated. Any bank change outside a mapped
destination is rejected. Finally, the complete result is parsed again and must
reconstruct the requested bank byte-for-byte before a mode-`0600`, no-replace output
is published.

Unchanged reconstruction is byte-identical:

| Package | Original/rebuilt bytes | Original/rebuilt SHA-256 |
| --- | ---: | --- |
| SIP | 319159 | `b8597657928905aea66924118889f0883bd38c0804ddf880e3be2c33ccf62eb5` |
| Transition | 274436 | `9cf97b172f4d3422dfa54ad9708a5e110637130963d9f1bc1f1e70c1bbfcc278` |

The explicit `--recompress-all` control demonstrates the distinction between decoded
identity and historical encoded identity:

| Package | Fully rebuilt bytes | Fully rebuilt SHA-256 |
| --- | ---: | --- |
| SIP | 316355 | `a8df7719dae512d709c8a2f0aebfe659f6fd2d03ad88a36aecbd78ae8235f772` |
| Transition | 269861 | `dc67af22825d1eeda46d5ed67d3015bad0bfeb521035a0df752a1a45f5f5e910` |

Both fully recompressed packages reconstruct their original bank hashes, but current
zlib levels `0..9` and default, filtered, Huffman-only, RLE, and fixed strategies did
not reproduce most original SIP streams or any transition stream. These results used
Python linked at runtime to zlib `1.2.12` (compile headers `1.2.11`). Output for changed
streams is therefore not established as byte-stable across zlib versions or compatible
with the vintage device inflater. The package checksums are not cryptographic
authentication, and no rebuilt or modified package has been offered to hardware.

## Launch Type-8 Payloads

Type-8 launch records point to a second bounded compression form. An eight-byte
big-endian header contains a mode and one mode-dependent field, followed by one
raw-DEFLATE stream and a little-endian CRC-32 of its output. Stream EOF determines
the compressed size. Bytes after the CRC do not consistently contain a complete
ISIZE and remain uninterpreted; the parser neither consumes nor assigns them.

```sh
python3 -B firmware/zup_bank.py PATH_TO_ZUP --type8-payload OFFSET
```

`firmware/zup_bank.py` accepts modes 0 and 1, caps both per-payload and aggregate
requested output at 512 KiB, and checks a mode-1 destination span against that same
bound. The pinned outputs are:

| Image/offset | Mode/field | Compressed | Output | CRC-32 | Output SHA-256 |
| --- | --- | ---: | ---: | ---: | --- |
| SIP `0x479bc` | `0 / 0x483bd241` | `0x24195` | `0x5bf54` | `0x379482a8` | `7b1770759a2f1849aef92d7b434b001c55925432cbf0eb24cc31bbff1ae85df9` |
| SIP `0x6bb60` | `1 / 0x100` | `0x105f` | `0x25d0` | `0x0fced7cf` | `e26fbef2176d195b2abb3aae028f60a6d503dfb2b4f517ea6831cfe17a9911be` |
| SIP `0x6cbcc` | `1 / 0x2fbc` | `0x265c` | `0x4bc8` | `0x17db033d` | `a91e14977a36f8d167003028a43b5cd8bdb64d8043035a1af4570785bd4797f8` |
| SIP `0x70010` | `0 / 0x483bd241` | `0x6c02` | `0x10dec` | `0xe70ae33a` | `fd180b04f2a81a2bac363a8aff8f0eb2324d70750e9f3af562050865603c783f` |
| SIP `0x76c20` | `1 / 0x100` | `0x29a` | `0x590` | `0xbc1aa614` | `6edec1b620431c99cc69c23b79f273c1b92c47db3c5df48a3acdb57d1bacf5e8` |
| Transition `0x4f368` | `0 / 0x483bd241` | `0x20aea` | `0x58e68` | `0x613cd603` | `b928d27d00fcda84769ce7dcb21e07ba3142c3cdee4da1c49ec3685cdf01c270` |

All three mode-0 outputs start with the same coherent MIPS-X setup sequence. The
first two instructions construct `0x70000`, after which the positive 17-bit
`addi r29,+0xffe0,r29` produces initial stack pointer `0x7ffe0`, 32 bytes below
the `0x80000` bank end. Complete big-endian scans produce the following contrast;
every decoded big-endian direct branch remains in its output range:

```sh
python3 -B firmware/mipsx_dasm.py PATH_TO_ZUP \
  --type8-payload MODE_ZERO_OFFSET --stats
```

| Program | Words | Big-endian unknown | Big-endian NOP | Little-endian unknown |
| --- | ---: | ---: | ---: | ---: |
| SIP main | 94165 | 44 | 15354 | 44486 |
| SIP auxiliary | 17275 | 37 | 3376 | 7392 |
| Transition | 91034 | 44 | 15513 | 41390 |

This establishes the mode-0 processor content as big-endian MIPS-X without
identifying the physical chip. Mode 1 supplies initialized data at its field value:

- SIP main: `0x100..0x26d0`, then type-2 zero fill to `0x2fbc`; initialized
  `0x2fbc..0x7b84`, then type-2 zero fill to terminal value `0xc74c`.
- SIP auxiliary: `0x100..0x690`, followed by type-2 zero fill to `0x1c28`.
- Transition uses type-1 copies for analogous initialized spans at
  `0x100..0x2568` and `0x3ce4..0xb514`, with type-2 records filling the gaps and
  tail through `0xf41c`.

The first program instructions load their data context from `0x2fbc`, `0x100`,
and `0x3ce4`, respectively, matching those initialized spans. With byte-coordinate
anchor `0x40000`, all mode-0 `r23` calls resolve inside their program: 3466 calls to
806 targets for SIP main, 796 to 202 for SIP auxiliary, and 3358 to 757 for
transition.

The terminal-record algebra and those program-relative calls support the following
loaded layout:

| Program | Type-9 code start | Code bytes | Code end | Type-7 `r23` word value | Type-3 value |
| --- | ---: | ---: | ---: | ---: | ---: |
| SIP main | `0xc74c` | `0x5bf54` | `0x686a0` | `0x131d3` | `0x400031d3` |
| SIP auxiliary | `0x3000` | `0x10dec` | `0x13dec` | `0x10c00` | `0x40000c00` |
| Transition | `0xf41c` | `0x58e68` | `0x68284` | `0x13d07` | `0x40003d07` |

In all three groups, `type7 * 4 = type9 + 0x40000` and
`type3 = 0x40000000 | (type9 / 4)`. Subtracting the proposed code start from the
type-7 byte value gives the independently recovered `r23` anchor exactly. Each
program also ends below its initial `0x7ffe0` stack pointer. These equalities strongly
identify type 9 as the code load offset after the data extent and type 7 as the
program's word-addressed `r23` value. The dispatcher loads type-3 field 1 unchanged
and performs terminal `jspci r13,0,r0`; only the CPU/platform meaning of its preserved
`0x40000000` PC tag remains unknown. The common mode-0 header field `0x483bd241` is also the
second instruction word in every output. The helper's squash branch does not load
that field in mode 0, and no other consumer is established.

The initialized data also provides component-identification clues, not provenance:
SIP main contains model strings for ATA186 and ATA188 plus build token `040211A`;
the auxiliary data contains `Cisco IP Phone 7905`, `LDR0203`, and recovery filename
`ata18xr.zup`. Transition data contains extensive H.323/H.245 strings including
`H323Dispatcher` and `admh323`, alongside ATA186 and SIP strings. These establish
shared/recovery code and the transition image's protocol content, but do not identify
a compiler, source release, signing chain, or physical chip.

The SIP web interface lives as `printf`-style HTML templates inside the mode-1
initialized span, not as separate files: the type-8 payload at bank `0x6cbcc`
(mode 1, field `0x2fbc`, output `0x4bc8`) expands into the `0x2fbc..0x7b84`
span and contains `<html>`, `<form method="post">`, `<input>` field templates,
and links to `/dev` and `/rtps`. The transition bank carries the same template
markers at `0x73ce2` and `0x73e42`, further shared-UI evidence. No other HTML,
CGI, or filesystem structure was found; the raw bank itself has only 1390
short printable runs, of which the sole meaningful ASCII outside code noise is
the NUL-terminated recovery filename slot `ZUP?ATA030100SIP040211A.zup` at bank
`0x2ea0c` (28 used bytes of its `0xf4` raw region, remainder `0xff`).

Mapped-vs-fill layout of the SIP bank is now explicit. Never-mapped `0xff`
fill totals roughly 90 KiB: `0x100..0xa00`, a `0x11500`-byte hole at
`0x2eb00..0x40000`, `0x6f300..0x70000`, `0x7a400..0x7d000`, and
`0x7ef00..0x7f400`. The helper output `0x7d000..0x7ef00` ends with 984 `0xff`
bytes past its `0x7eb28` module end, i.e. padded initialized output. The reset
tail's fixed data at `0x7f520`/`0x7f55f` holds dial-plan-like digit-map text
(`911`, `St4` alternatives) and feature-code-like vectors (`*67`, `#90`
forms); these are described, not quoted, and their consumer is unidentified.
The nested `+kbz` output at `0x2c9d4` holds call-control-like error text
(`Call Leg/Transaction Does Not Exist`) with tone-script-like vectors, while
the other three nested outputs are numeric table data. There is still no
recovered archive, object, or filesystem container: component boundaries rest
on launch spans, payload headers, and these string markers only.

### Shared Inflate Helper

Every type-8 operation is followed by type 6, type `0xb`, type `0xc`, type 5, and
type 4 setup records. The type-4 value maps to a 6504-byte MIPS-X helper and its
preceding type-5 value maps exactly `0x40000` bytes beyond the helper start:

| Image | Helper code | Type-4 value | Type-5 `r24` byte anchor |
| --- | --- | ---: | ---: |
| SIP | `0x7d000..0x7e968` | `0x033ff400` | `0xbd000` |
| Transition | `0x79af8..0x7b460` | `0x033fe6be` | `0xb9af8` |

The code ranges are byte-identical, with SHA-256
`fa18fed20b1904f8c26c1758cfb303e6d6bfc9ee2097979cda07847c11566221`.
Each contains 1626 completely decoded big-endian MIPS-X words. Independent `r24`
inference makes the recorded type-5 value the leading candidate in both images:
all 45 calls resolve to nine local stack prologues. This identifies the code as a
relocated module, type 4 as its entry-address form, and type 5 as its word-addressed
linkage anchor. The resident dispatcher independently proves that type 4 performs a
linked call to field 1 and type 5 loads field 1 into `r24`.

Each helper is followed by the same 448-byte initialized block, SHA-256
`be2bca1bec4b43f1fa729e77af4f0abd8912b64803f87a7b39e7c9c5323103b3`.
The repeated type-1 record copies that block to `0x7fc00`, which is also the type-6
value. Its layout contains the canonical mask, bit-length order, copy-length,
length-extra, distance, and distance-extra tables used by the standalone Mark
Adler/gzip inflate core, including its `99` invalid-code marker. Together with the
checked raw-DEFLATE outputs, this identifies the module as a customized inflate
helper rather than an unrelated executable region. A stable comparative source is
`lib/inflate.c` Git blob `75e7d303c72ed9faf1501cac47e562edd28e9552` in Linux
commit `9ee1c939d1cb936b1f98e8d81aeffab57bae46ab`; its header identifies Mark
Adler's c10p1 (10 January 1993) and gzip-1.0.3 ancestry. That later Linux snapshot
establishes algorithm lineage, not the firmware's exact source release,
modifications, compiler, or license provenance.

The helper entry exposes a consistent launch ABI. `r4` points at the type-8 header;
the entry reads its mode and advances `r4` to the raw stream. For mode 1, a
`bnesq` taken-only delay slot loads the header field into output pointer `r5`. For
mode 0 the squash rule suppresses that load, retaining the caller's type-9-derived
`r5` code destination. This independently explains the mode-dependent header field
and type-9 code-start relationship.

The same entry stores incoming `r19` at `r25+0x18`. The Huffman-table builder later
reads that cursor, advances it by eight bytes per allocated table entry, and stores
it back, matching the standalone inflate core's arena allocation. The dispatcher
directly loads type `0xc` field 1 into `r19`; helper behavior establishes its arena-
cursor role. All helper `r25` accesses fall within offsets `0x0..0x140` of the copied
block, while the dispatcher directly loads type-6 field 1 into `r25`, establishing
the context/table assignment. The dispatcher likewise loads type-`0xb` field 1 into
`r29`; the invariant value `0x7f800` and the helper's downward-growing stack establish
the initial-stack role.

The final host type-5 values separately encode the outer program's inferred `r24`
anchor exactly:

- SIP: `0x033f0280 * 4 - 0x0cf80000 = 0x40a00`.
- Transition: `0x033f0008 * 4 - 0x0cf80000 = 0x40020`.

The packed SIP-main program makes 97 `r24` calls through the first value, all to 43
resident stack prologues. The transition program makes 129 calls through the second,
all into resident text: 128 reach 47 prologues and the remaining target at `0x24784`
is a resident `r24` tail thunk. SIP auxiliary has no terminal type-5 record and makes
no `r24` calls. These independent consumers identify final type 5 as the packed
program's resident `r24` linkage value, consistent with the now-recovered direct
type-5 dispatcher load.

## MIPS-X Identification

The primary architecture report states that memory is byte-addressed, memory
offsets are byte offsets, branch/jump displacements are word displacements, and
addressing is consistently big-endian. It also documents two delay slots for
branches and jumps, the canonical `nop` word `0x60000019`, and `jspci` as a
17-bit signed word displacement added to a source register.

`firmware/mipsx_dasm.py` is a bounded offline decoder and scanner. Its decode
table follows MAME's BSD-3-Clause `mipsxdasm.cpp` at commit
`844b0763d46e1fbd2f21aea9528316a7b0cab7da`; redistribution terms are retained
in `THIRD_PARTY_NOTICES.md`. The decoder retains an explicit warning around
type-2 op5/op7. MAME names these operations `movfrc`/`movtoc`, but notes that
nonstandard ES3210/ES3890 variants may use related forms for byte operations.

Run both executable regions with a private reconstructed bank path:

```sh
python3 -B firmware/mipsx_dasm.py PATH_TO_BANK \
  --region 0xa00:0x2c9d4 \
  --region 0x7d000:0x7e968 \
  --reg-base r24=0x40a00 \
  --stats --xref-summary 12
```

Expected combined counts are:

```text
words=46671
branch=3466
compute=17190
jump=4193
memory=12762
nop=9060
branch_in_range=3466
jump_in_range=2747
jump_unresolved=1446
resolved_xrefs=6213
unique_targets=3647
```

There are no unknown big-endian words in either selected region. The equivalent
little-endian control has `19113` unknown words out of `46671`, plus `5533`
out-of-range apparent branches:

```sh
python3 -B firmware/mipsx_dasm.py PATH_TO_BANK \
  --region 0xa00:0x2c9d4 \
  --region 0x7d000:0x7e968 \
  --byte-order little --stats
```

This complete coverage, branch coherence, primary-manual byte order, and the
canonical NOP density jointly identify the regions as big-endian MIPS-X. It is
not merely a zero-filled-data effect and does not identify a chip package.

## Register-Base Inference

The base scanner is exhaustive over the selected regions rather than seeded
with `0x40a00`. It collects every `jspci r24,displacement,link` call and every
negative `addi r29,immediate,r29` stack-frame prologue. Each possible pairing
votes for `base = prologue_address - displacement`, weighted by call-reference
count. The reported base is a byte-coordinate call anchor because the file and
disassembler PCs use byte offsets. The architecture report specifies word PC
addresses, so the corresponding raw register value is `base / 4`. Every
candidate is then scored for calls landing within selected code and for
`addi`-materialized function pointers landing on stack prologues.

```sh
python3 -B firmware/mipsx_dasm.py PATH_TO_BANK \
  --region 0xa00:0x2c9d4 \
  --region 0x7d000:0x7e968 \
  --infer-base r24 --candidate-limit 10
```

The leading results begin:

```text
register=r24 call_references=1523 unique_displacements=360
byte_anchor=0x00040a00 raw_word_value=0x00010280 prologue_references=1478 prologue_targets=351 in_range_references=1523 in_range_targets=360 addi_prologue_references=33 addi_prologue_targets=16
byte_anchor=0x00042108 raw_word_value=0x00010842 prologue_references=182 prologue_targets=13 in_range_references=1485 in_range_targets=351 addi_prologue_references=11 addi_prologue_targets=2
byte_anchor=0x00040f58 raw_word_value=0x000103d6 prologue_references=172 prologue_targets=8 in_range_references=1521 in_range_targets=359 addi_prologue_references=1 addi_prologue_targets=1
byte_anchor=0x00040b2c raw_word_value=0x000102cb prologue_references=152 prologue_targets=8 in_range_references=1523 in_range_targets=360 addi_prologue_references=0 addi_prologue_targets=0
```

The first candidate has more than eight times the weighted prologue score of
the runner-up, covers 351 distinct prologue targets rather than 13, and resolves
all 1523 calls into selected code. Independently, all 33 `addi` uses of raw
`r24=0x00010280` materialize 16 distinct local stack-prologue addresses; the next
candidate covers only 11 references across two prologues. This is high-confidence static evidence for
the byte-coordinate anchor `0x00040a00` and raw architectural register value
`0x00010280`, but there is no static write that shows how startup establishes it.

## Delay-Slot-Aware Transfer Summary

The primary manual specifies two delay slots after every branch and jump. Jump
slots always execute. Ordinary branch slots execute on both outcomes, while a
squash branch suppresses both slots when the branch is not taken. `jspci` stores
the return location after both slots. The bounded control-transfer summary exposes those
rules rather than applying conventional single-slot MIPS behavior:

```sh
python3 -B firmware/mipsx_dasm.py PATH_TO_BANK \
  --region 0xa00:0x2c9d4 --region 0x7d000:0x7e968 \
  --reg-base r24=0x40a00 --cfg-summary 100
```

For the SIP regions this reports 7659 control transfers and 360 resolved local
call targets. Transition reports 7248 transfers and 569 local targets with
`r24=0x40020`. The full scan retains only the requested `N` transfer records and
fails closed above 65,536 unique local call targets. Each retained transfer
identifies both architectural slot addresses, how many are present in the selected
regions, whether slots always execute or are taken-only, the taken/call target when
known, and the post-slot continuation for conditional branches and calls. Labels
such as `sub_00001d58` name resolved local call targets only; they do not claim a
full CFG, recovered function boundaries, or assignments for unresolved `r23` calls.

Across both regions, all 2747 `r24` calls and tails resolve to aligned addresses
in the main code region. The main region also has 1000 calls through `r23`, with
105 unique displacements. Earlier analysis provisionally used the repeated type-1
record field `0x0cffe968` as its byte-coordinate anchor. The transition table now
shows that analogous type-1 values are source-address fields and differ from
other plausible linkage values, so that provisional assignment is withdrawn.
Outer `r23` targets remain unresolved pending earlier bootstrap state or resident
symbols.

The two firmware versions nevertheless permit relative inference without an
absolute `r23` value. Equal resident call targets imply
`second_base - first_base = first_displacement - second_displacement`:

```sh
python3 -B firmware/mipsx_dasm.py SIP_BANK \
  --region 0xa00:0x2c9d4 --region 0x7d000:0x7e968 \
  --compare-image TRANSITION_BANK --compare-region 0x20:0x2aa60 \
  --infer-shared-delta r23 --candidate-limit 5
```

The leading candidate is `transition_base - SIP_base = -0x14c`, aligning 10
distinct displacement targets with 49 weighted references. The next candidates
align only five distinct targets (`+0x290` with 26 weighted references and
`-0xa8` with seven). This supports a relative linkage change but still does not
establish either absolute base.

The auxiliary region uses `r25` as a memory base 133 times: 82 loads and 51
stores, and 18 `addi` uses derive context offsets from `+0x1c` through `+0x140`.
Neither executable region statically writes `r23`, `r24`, or `r25`. The packed
mode-0 programs now supply direct consumers that validate the final type-5 `r24`
value, but the initial outer `r23`/`r25` values remain in an unavailable bootstrap or
earlier launch context.

## Resident Launch Dispatcher

The SIP reset tail at bank `0x7f400..0x80000` contains the complete validator and
launch dispatcher. It copies 63 words from `0x7f9fc..0x7faf8` to low RAM byte address
`0x7fe00`, then calls the relocated copy at architectural word PC `0x1ff80`. The
validator XORs every big-endian word selected by the four descriptors in the staged
section header at `0x40000`, then XORs `0xdeadbeef`. The checked result and stored word
are both `0x61f0752a`.

A checksum match returns header runtime address `0x0cfc0100`, bank `0x40100`, whose
table pointer/count are `0x0cfc0110` and 27. A final checksum mismatch returns
`0x0cff0000`, bank `0x70000`, whose table pointer/count are `0x0cff6ee0` and 18.
The duplicate main header at bank zero has the same 27 records as `0x40100`. A marker
mismatch branches around part of this calculation with an incoming register value
that is not statically established, so only the checksum match/mismatch selection is
claimed.

The selector at `0x7fd20..0x7fddc` dispatches fixed 16-byte records to these handlers:

| Type | Directly decoded operation |
| ---: | --- |
| `1` | Copy field 3 32-bit words from field 1 to field 2 |
| `2` | Store zero for field 2 32-bit words starting at field 1 |
| `3` | Load field 1 into `r13`, then terminal unlinked `jspci r13,0,r0` |
| `4` | Linked call to field 1 through `r13`, preserving dispatcher state |
| `5` | Load field 1 into `r24` |
| `6` | Load field 1 into `r25` |
| `7` | Load field 1 into `r23` |
| `8` | Load field 1 into `r4` |
| `9` | Load field 1 into `r5` |
| `0xa` | Load field 1 into `r28` |
| `0xb` | Load field 1 into `r29` |
| `0xc` | Load field 1 into `r19` |
| `0xd` | Read four field-2-length blocks at 16-byte strides; purpose unknown |

The register loads occur in the first always-executed delay slot of each branch back
to the dispatcher continuation. Type 4 calls with link register `r31`, saves and
restores `r6`, `r7`, `r10`, and `r11`, then resumes record dispatch. For type `0xd`,
if `B=field1`, `L=field2`, and `N=floor(L/16)`, the exact read addresses are
`B+16*i`, `B+L+16*i`, `B+2*L+16*i`, and `B+3*L+16*i` for `0 <= i < N`; no known
table invokes this handler, and a cache-related purpose remains only a hypothesis.

All three known tables contain type 3 only as their final record, at `0x402b0`,
`0x76ff0`, and transition `0x7b700`. Normal count exhaustion would fall through into
the type-1 handler with a one-past-end record pointer, so the terminal type-3 jump is
part of the table contract. Its field is passed to the PC unchanged. The low word-PC
portion maps exactly to the type-9 code start; software does not mask the
`0x40000000` tag. An untagged `jspci` separately executes the validator in low RAM,
so the tag is not a universal RAM selector. Its CPU/platform address-space or cache
meaning remains unknown and it is not established as a user-mode switch.

Transition independently contains the byte-identical selector and handlers through
the type-3 field load over bank `0x7fd20..0x7fed4`, SHA-256
`80d37f8c13ffdd054562b8106419445c3df9cf439c28d5428e88d708127b50bd`.
Its remaining bank tail is `0xff`, so the transition package alone does not contain
the terminal `jspci` or complete type-4 handler; it may rely on an already resident
suffix, which remains a runtime hypothesis.

## Launch-Record Clues

`firmware/zup_bank.py --launch-header OFFSET` validates and prints one launch
header and its counted records directly from the reconstructed in-memory bank.
It does not assign names to unknown record types. For the SIP package, offsets
`0` and `0x70000` select the main and auxiliary tables; transition uses offset
`0`.

The transition table establishes the strongest record invariants:

- Runtime source addresses map to bank offsets by subtracting `0x0cf80000`.
- Type 1 has the shape `(source,destination,word_count)`. Its derived byte span
  is `word_count * 4`. Source `0x0cfefe60` maps to bank `0x6fe60`; adding
  `0x91a * 4` reaches the next source exactly at `0x722c8`.
- The same type-1 records place `0x2468` initialized bytes at `0x100..0x2568`
  and `0x7830` bytes at `0x3ce4..0xb514`.
- Type 2 has the shape `(destination,word_count,0)` and fills the intervening
  spans: `0x2568 + 0x5df * 4 = 0x3ce4` and
  `0xb514 + 0xfc2 * 4 = 0xf41c`.
- The initialized and zero-filled spans therefore cover one contiguous
  `0x100..0xf41c` layout. The terminal `0xf41c` equals its type-9 value.
- Type 8 points into compressed raw-map inputs. Transition's `0x0cfcf368` maps to
  raw destination `0x4f368`; SIP values map exactly to `0x479bc`, `0x6bb60`,
  `0x6cbcc`, `0x70010`, and `0x76c20`.

The first type-1 transition source also maps to `0x7b460`, and its `0x70` words
end exactly at the record table at `0x7b620`. The analogous SIP source
`0x0cffe968` maps to bank offset `0x7e968`; this confirms it as a bank-backed
source field and invalidates its earlier use as direct evidence for `r23`.

The type-8 source bytes are compressed rather than direct MIPS-X text. Their
raw-DEFLATE outputs, mode/data relationships, and CRC-32 values are now established
above. Their dispatcher register setup is now established; bytes following each CRC
remain unknown.

The outer `r24` word value has a simple linker-like form:
`0x00010280 = 0x10000 + (0xa00 / 4)`. Thus a signed 17-bit word displacement can
reach the main text beginning at byte offset `0xa00`. The terminal record groups
contain a related three-way encoding of the data-terminal/code-start quantity:

| Group | Byte quantity | Biased word quantity | Flagged word quantity |
| --- | ---: | ---: | ---: |
| Main | type 9: `0x0000c74c` | type 7: `0x000131d3` | type 3: `0x400031d3` |
| Auxiliary | type 9: `0x00003000` | type 7: `0x00010c00` | type 3: `0x40000c00` |

For the main group, `0xc74c = 4 * 0x31d3` and
`0x131d3 = 0x10000 + 0x31d3`. For the auxiliary group,
`0x3000 = 4 * 0xc00` and `0x10c00 = 0x10000 + 0xc00`. This proves that the
records encode the same per-group quantity in byte, `r23`-biased-word, and
flagged-word forms. Mode-1/type-1 initialized data plus type-2 zero fill reaches the
type-9 value exactly for SIP main and transition. The mode-0 size and call-anchor
checks independently identify that same value as the following code start. SIP
auxiliary reaches only `0x1c28` of its `0x3000` extent through currently understood
records, so the remaining reservation semantics stay open.

Every SIP image group also contains the type-1 copy
`(0x0cffe968,0x0007fc00,0x70)`, and every group repeats `0x0007fc00` in a type-6
record. That now-identified inflate helper's `r25` references cover 16 fields at
offsets `0x0..0x18` and `0x11c..0x13c`, while its derived pointers cover eight
offsets through `0x140`. The resident dispatcher directly loads type-6 field 1
into `r25`, establishing the context/table assignment for `r25=0x0007fc00`.
Only the initial outer/pre-launch `r25` value remains in the unavailable
bootstrap context. The bounded `firmware/zup_launch_trace.c` model traces this
assignment without executing guest code.

## Transition Differential

The independently reconstructed `transition.zup` bank provides a second image
from the same format family:

- Its outer map has one raw and four compressed regions and no `ATA4` map gap.
- Its main MIPS-X text is exactly `0x20..0x2aa60`: 43664 big-endian words, no
  unknown decodes, and all 2512 direct branches remain in range.
- Exhaustive `r24` inference selects byte anchor `0x00040020`, exactly
  `text_start + 0x40000`, corresponding to raw word value `0x00010008`.
- That anchor sends all 2364 `r24` calls to 569 local targets; 2352 references
  reach 568 stack prologues. All 22 `addi r24,...` references materialize 18
  local stack-prologue addresses.
- The next call-anchor candidate has only 282 weighted prologue references and
  no `addi` prologue matches.
- A 15-record table at `0x7b620` uses the same types as the SIP tables. Its
  type-1 entries have the shape `(source,destination,size)`, including
  `(0x0cffb460,0x0007fc00,0x70)`, `(0x0cfefe60,0x100,0x91a)`, and
  `(0x0cff22c8,0x3ce4,0x1e0c)`.
- Its launch header at bank offset zero maps `0x0cffb620` back to table offset
  `0x7b620` and declares exactly 15 records.
- The transition code makes 681 unresolved `r23` calls to 88 displacements, but
  it also contains no static `r23` initialization.

The exact `text_start + 0x40000` result independently confirms the signed
17-bit word-displacement linkage convention used by the SIP image. Conversely,
the transition records demonstrate that a type-1 source address alone is not
enough to assign `r23`. Neither image identifies the physical chip or contains
the external resident image.

## Nested Payloads

The prior claim that the payload at bank offset `0x77000` was the strongest
ZSP400 candidate is withdrawn. Interpreting its output as big-endian 16-bit words
does find nine adjacent same-register values matching the `movl`/`movh` opcode
forms, but the nine pair starts are isolated rather than part of instruction-like
runs. Their surrounding words are smoothly varying numeric vectors, consistent
with coefficient or lookup-table data. Other payload/byte-order combinations
contain zero to three such incidental pairs.

The ZSP400 architecture manual confirms fixed-width 16-bit instructions,
instruction-addressed `%pc`, reset `%pc=0xf800`, and no architecturally visible
delay slots. Its coding tables identify `0xbf01` as `nop` and `0xbf02` as `idle`,
not return instructions. Neither marker occurs in any of the four outputs under
either 16-bit byte order. This absence cannot prove that no code is present, but
the current marker and context checks do not justify a ZSP400 disassembly or CFG.

This workstream remains separate from the host MIPS-X result. Incidental opcode
matches do not identify executable boundaries, processor ownership, or a physical
ZSP400 core in the ATA186.

## External ZSP400 Tool Leads

The public `latchdevel/LSIUtil` repository was checked at recursive tree
`62788df5eb2b017b9a8b49811fd06b993eb70b89`. It contains LSI Fusion-MPT HBA source,
headers, documentation, and host binaries for SCSI, Fibre Channel, and SAS/SATA
controllers. Its own description says those controller chipsets use ARM or PowerPC.
No ZSP400 simulator, assembler, opcode table, or ATA186-specific source was identified,
so the shared LSI name is not evidence of a technical relationship to these payloads.

The conference paper "A simulator support for LSI logic ZSP400 instruction set" by
Ling Gan and Zhenjiang Ding, DOI `10.1109/3CA.2010.5533884`, was published at 3CA 2010,
pages 10-13. Crossref confirms that it cites the 2001 ZSP400 architecture manual.
OpenAlex record `W2065156030` supplies an abstract describing a Windows C++ simulator
based on the target-machine architecture that executes assembler output and claims
support for 95 percent of the instruction set. OpenAlex marks the paper closed, with
no repository full text or PDF; no released simulator implementation was located in
the bounded public search. This is useful historical context, not ATA186 processor or
firmware evidence.

## Ghidra Decomilation with MCP

### Prerequisites

- Ghidra 12.1.3+ with `ghidra-mcp-ng` extension installed
- Custom MIPS-X processor module at `MIPSX_Ghidra_ATA186/` (installed to Ghidra's Processors directory)
- Python 3.8+ for the MCP bridge

### Setup

1. Install the MIPS-X processor module:
   ```sh
   cp -r MIPSX_Ghidra_ATA186/MIPSX /usr/local/Cellar/ghidra/12.1.3/libexec/Ghidra/Processors/
   ```

2. Start Ghidra headless MCP server:
   ```sh
   python3 start.py --ghidra /usr/local/Cellar/ghidra/12.1.3/libexec \
     --project /Users/user/devel/ata/ghidra-project/ATA \
     --rules /Users/user/devel/ghidra-mcp-ng/rules.yaml
   ```

3. Start the MCP bridge:
   ```sh
   python3 bridge.py --url http://127.0.0.1:8192
   ```

4. Configure OpenCode (`~/.config/opencode/opencode.jsonc`):
   ```json
   "mcp": {
     "ghidra": {
       "type": "local",
       "command": ["python3", "/path/to/bridge.py", "--url", "http://127.0.0.1:8192"]
     }
   }
   ```

### Bank Decompilation Workflow

The bank binary is a container with multiple sections, not a flat executable. The extracted payloads are the actual MIPS-X programs.

1. **Extract and import the bank**:
   ```sh
   python3 -B firmware/zup_extract.py firmware/ATA030100SIP040211A.zup \
     --out /tmp/sip_extract --disasm
   ```

2. **Import into Ghidra via MCP** (the bank needs functions seeded):
   ```json
   {"program": "bank.bin", "project_dir": "sip_bank", "language_id": "MIPS-X:BE:32:ATA186", "base_address": "0xcf80000"}
   ```

3. **Seed functions from known entry points** (Ghidra auto-analyzer doesn't find MIPS-X functions):
   - Run `SeedAllFunctions.java` via Ghidra headless, OR
   - Use `CreateFunc.java` to create functions at specific addresses

4. **Decompile via MCP**:
   ```json
   {"program": "/sip_bank/bank.bin", "name_or_address": "0xcf80a00"}
   ```

### Known Issues

- **add_script/delete_script ClassCastException**: The ghidra-mcp-ng extension has a bug where adding/deleting scripts via MCP fails. Workaround: copy scripts directly to Ghidra's script directories.
  - Bug documented in `/Users/user/devel/ghidra-mcp-ng/BUG_ADD_SCRIPT_CLASSCAST.md`
- **Auto-analyzer finds 0 functions**: MIPS-X has no standard function prologue pattern. Must seed functions manually from known entry points (addresses with `addi r29` prologues).

### Processor Module Details

The MIPS-X processor module (`MIPSX_Ghidra_ATA186/`) provides:
- Language ID: `MIPS-X:BE:32:ATA186`
- SLEIGH specification for instruction decoding
- Compiler spec (`mipsx.cspec`) with conservative ABI model
- Processor spec (`mipsx.pspec`) with r29 as stack pointer

## Open Questions

- What earlier bootstrap state initializes outer resident `r23`/`r25`?
- What CPU/platform meaning does type 3's preserved `0x40000000` PC tag have, and
  what is the purpose of type `0xd`'s four-range read pattern?
- Which code performs `+kbz` expansion, and where are the outputs loaded?
- Are the main and auxiliary ranges loaded simultaneously or as overlays?
- What physical CPU/SoC is fitted to the ATA186 board?
- Does any nested output contain executable code, and can loader, object-format,
  or debugger evidence establish its processor, boundaries, byte order, and
  branch base?
- Can authoritative release/source material map the embedded `LDR0203`, 7905,
  ATA186/188, SIP, and H.323 identifiers to exact original component versions?

## Sources

- MIPS-X architecture report: <https://archive.org/download/DTIC_ADA181619/DTIC_ADA181619.pdf>
- MAME MIPS-X disassembler: <https://github.com/mamedev/mame/blob/844b0763d46e1fbd2f21aea9528316a7b0cab7da/src/devices/cpu/mipsx/mipsxdasm.cpp>
- MAME MIPS-X CPU stub: <https://github.com/mamedev/mame/blob/master/src/devices/cpu/mipsx/mipsx.cpp>
- MAME PAP2 skeleton: <https://github.com/mamedev/mame/blob/master/src/mame/skeleton/pap2.cpp>
- Relevant MAME change: <https://github.com/mamedev/mame/commit/844b0763d46e1fbd2f21aea9528316a7b0cab7da>
- ZSP400 architecture manual DSA0093274: <https://datasheet.datasheetarchive.com/originals/library/Datasheet-06/DSA0093274.pdf>
- LSIUtil tree reviewed: <https://github.com/latchdevel/LSIUtil/tree/62788df5eb2b017b9a8b49811fd06b993eb70b89>
- ZSP400 simulator paper: <https://doi.org/10.1109/3CA.2010.5533884>
- OpenAlex paper metadata and abstract: <https://api.openalex.org/works/W2065156030>
- Comparative standalone inflate source: <https://github.com/torvalds/linux/blob/9ee1c939d1cb936b1f98e8d81aeffab57bae46ab/lib/inflate.c>
