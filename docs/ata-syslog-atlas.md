# ATA SIP syslog atlas

This atlas maps observed text to exact runtime instructions. Addresses are not
interchangeable: packed payload offsets are relocated by `0xc74c`; resident bank
offsets are mapped at `0x0cf80000`; mode-1 data remains in low runtime memory.

The checked-in atlas can be searched without vendor firmware:

```sh
python3 firmware/syslog_lookup.py "RTP Rx"
python3 firmware/syslog_lookup.py 0x33c4c
python3 firmware/syslog_lookup.py --list
```

With a locally supplied package, verify the complete packed inventory, message
bytes, and argument-producing instructions:

```sh
python3 firmware/syslog_lookup.py --verify-package \
  ata_03_01_00_sip_040211_1/ATA030100SIP040211A.zup
```

## Shared emitter

Packed payload function offset `0x104c0`, runtime `0x1cc0c`, is provisionally
named `maybe_syslog_emit_class`. There are 27 static calls to it. Its first
argument indexes an eight-byte class descriptor at low runtime `0x39dc`; output
continues only when the supplied mask intersects that class's enabled mask. It
uses PRI format string `%s<%d>%s %s [%02d]:%s` at `0x3a43` and dispatches the
formatted output. This is the class gate shared by the entries below.

The separate packed function formerly named `maybe_log_event` is payload offset
`0x10268`, runtime `0x1c9b4`. Correct runtime disassembly finds 108 unique calls,
not the 104 visible in the stale base-zero project.

## Packed message map

These are all 27 direct packed-main calls to runtime emitter `0x1cc0c`. `Exact`
means the call appears in the conservative function body. `Nearest` means the
arguments and call are exact but the non-overlapping Ghidra model leaves the
block detached from useful decompiled control flow. The JSON atlas records the
exact class/mode/message instruction addresses for every row.

| Call | Class/mode | Message | Owning path | Confidence |
| --- | --- | --- | --- | --- |
| `0x1e198` | 1/2 | `DHCP's ip: %u.%u.%u.%u` | `sub_0001e018@0x1e018` | Exact |
| `0x1e1d4` | 1/2 | `DHCP's sm: %u.%u.%u.%u` | `sub_0001e018@0x1e018` | Exact |
| `0x1e210` | 1/2 | `DHCP's rt: %u.%u.%u.%u` | `sub_0001e018@0x1e018` | Exact |
| `0x1e42c` | 2/0 | `TFTP upgrade failed` | `sub_0001e3a4@0x1e3a4` | Exact |
| `0x20558` | 4/0 | `Reboot from %s (%s:%d)` | `sub_0001ff2c@0x1ff2c` | Nearest |
| `0x33c4c` | 3/0 | `ATA Config Update OK` | `maybe_http_response_dispatch@0x33940` | Exact detached arm |
| `0x36044` | 6/1 | `[%d]DTMF %c , insum:%d` | `sub_00035b8c@0x35b8c` | Nearest |
| `0x44b48` | 2/0 | `Rx TFTP file:%s(%d) ok` | `maybe_tftp_get_coordinator@0x44ac4` | Nearest |
| `0x44be8` | 2/0 | `Rx TFTP file:%s fail` | `maybe_tftp_get_coordinator@0x44ac4` | Nearest |
| `0x49524` | 8/0 | `[%d]RTP Rx dur:%d, pkt:%d, byte:%d, latePkt:%d lostPkt:%d avgJitter:%d` | `sub_0004948c@0x4948c` | Exact |
| `0x495c4` | 8/0 | `[%d]RTP Tx dur:%d, pkt:%d, byte:%d` | `sub_00049550@0x49550` | Exact |
| `0x4a4b0` | 7/1 | `[%d]Tx MPT PT=%d NSE pkt %08x` | `sub_0004a400@0x4a400` | Exact |
| `0x4a4f4` | 7/1 | `[%d]codec: %d => %d` | `sub_0004a400@0x4a400` | Exact |
| `0x4a5bc` | 7/1 | `[%d]Tx MPT PT=%d NSE pkt %08x` | `sub_0004a53c@0x4a53c` | Exact |
| `0x4cad0` | 7/1 | `[%d]Fax Pass Thru TX Rdn` | `sub_0004c40c@0x4c40c` | Nearest |
| `0x4d8bc` | 7/1 | `[%d]MPT mode %d` | `sub_0004d784@0x4d784` | Exact |
| `0x4da78` | inherited or 7 / 1 | `[%d]Rx MPT PT=%d NSE pkt %08x` | `sub_0004d924@0x4d924` | Conditional class |
| `0x4db44` | 7/1 | `[%d]codec: %d => %d` | `sub_0004d924@0x4d924` | Exact |
| `0x4dc68` | 7/1 | `[%d]codec: %d => %d` | `sub_0004d924@0x4d924` | Exact |
| `0x4df38` | 7/1 | `[%d]Fax Pass Thru RX Rdn` | `sub_0004dd84@0x4dd84` | Exact |
| `0x627c4` | 6/0 | `[%d]CLI%c %s` | `sub_00062728@0x62728` | Exact |
| `0x62fa8` | 6/0 | `[%d]CLI%c %s` | `sub_00062cb4@0x62cb4` | Nearest |
| `0x63190` | 7/1 | `SCC: Enable fax mode` | `sub_00062cb4@0x62cb4` | Nearest |
| `0x64668` | 7/1 | `[%d:%d]Mdm PassThru` | `sub_000640b4@0x640b4` | Nearest |
| `0x64700` | 7/1 | `[%d:%d]%s FAX` | `sub_000640b4@0x640b4` | Exact |
| `0x6502c` | 6/0 | `[%d]%sHOOK` | `sub_00064f3c@0x64f3c` | Exact |
| `0x67910` | 7/1 | `Enable fax` | `sub_000672a4@0x672a4` | Nearest |

At `0x4da78`, mode 1 and message `0x6d6c` are exact. Class is deliberately
not collapsed to one value: `r16` saves the incoming `r4` at `0x4d94c`; the
branch at `0x4da20` can skip the explicit class-7 assignment at `0x4da28`, while
the second mask path reaches the call with class 7. The verifier checks those
instructions and preserves the uncertainty.

## Resident message map

The resident ARP call is separate from the 27 packed-main calls:

| Message | Data | Argument instruction | Emitter call | Class/mode | Owning path |
| --- | --- | --- | --- | --- | --- |
| `ARP Update:MAC:%02x%02x%02x%02x%02x%02x, IP:%d.%d.%d.%d` | low runtime `0x3bc` | resident runtime `0x0cf80bad4` (`addi r0,0x3bc,r6`) | resident runtime `0x0cf80bacc` -> packed runtime `0x1cc0c` | class 0, mode 0 | resident ARP-update formatter, bank offset `0xb8a4`, runtime `0x0cf80b8a4` |

## ATA configuration path

The containing packed handler constructs HTTP response strings from
`0x515c..0x53df`, including `Configured Successfully` at `0x52c0` and validation
errors at `0x5362`. In the successful branch, runtime `0x33c48` loads class 3;
the emitter call is at `0x33c4c`; its two delay slots load mode 0 and message
`0x534c`. A local saved value loaded immediately before the call is tested for
zero at runtime `0x33c3c`; zero skips this syslog call. Its exact source-level
meaning is not yet proven, so it is recorded as a nonzero success-path gate,
not labeled as a reboot or changed-entry flag.

Ghidra does not assign the call block itself to a conservative function body:
it lies in a switch/tail-controlled arm using the frame established at runtime
`0x33940`. The shared frame and HTTP strings establish the owning handler, while
the detached block remains explicit rather than forcing an overlapping function.

## ARP path

Resident function bank `0xb8a4`/runtime `0x0cf80b8a4` receives IP and MAC
pointers. Before the emitter call it expands six bytes from the second pointer
and four bytes from the first pointer onto the stack, then loads class 0, mode 0,
and format `0x3bc`. Three resident call sites are statically resolved:

| Caller instruction | Arguments | Nearby gate |
| --- | --- | --- |
| `0x0cf80b280` | `r4=r18+0xe`, `r5=r18+8` | calls when low runtime word `0x3ac` is zero |
| `0x0cf80b33c` | same | calls when low runtime word `0x3ac` is zero |
| `0x0cf80b3a0` | same | calls when low runtime word `0x3ac` is nonzero on a separate update path |

The first pointer therefore supplies the four IP octets and the second supplies
the six MAC octets. The semantic purpose of state word `0x3ac` is not yet proven;
the atlas records its observed branch polarity without naming it.

## Separate packed log-event path

The packed function `maybe_log_event` (payload offset `0x10268`, runtime
`0x1c9b4`) is a second, larger logging path: the corrected runtime disassembly
finds **108 unique call instructions** to it, not the 104 visible in the stale
base-zero project. It is not the syslog class emitter and carries **no class or
mode argument**: it receives a message address in `r4` plus up to four further
arguments, formats into a local buffer, and forwards the record through
`maybe_log_dispatch` (runtime `0x1c834`) to the resident event dispatcher.
The only connection to the class gate is the forwarding call `0x1cc58` inside
`maybe_syslog_emit_class`, which passes `"%s"` and the already-formatted
record, so it inherits the emitter's class.

The complete atlas is searchable and package-verifiable without vendor
firmware:

```sh
python3 firmware/event_lookup.py "Close RTPRX"
python3 firmware/event_lookup.py 0x44ac4
python3 firmware/event_lookup.py --list
python3 firmware/event_lookup.py --verify-package \
  ata_03_01_00_sip_040211_1/ATA030100SIP040211A.zup
```

Package verification re-resolves all 108 calls, re-decodes every recorded
argument-producing instruction, and compares every recorded message string
against the rebuilt runtime layout.

Coverage: 108/108 calls have an exact message recovered from `r4`; 11 have all
arguments materialized as constants and 97 have at least one explicitly
recorded dynamic argument (register move, struct load, global load, or other
producer). Each entry records its owning function, direct callers, subsystem
owner (call-control, RTP media, config apply, TFTP, sockets, tones, DTMF, FXS
hook/ring/CID, codec, provisioning, startup, and so on), and whether an
argument's producing write may be conditionally skipped (69 entries carry that
warning).

One useful layout observation: the packed config error/event calls pass
`0x60xx` values that are simultaneously the documented event code and the
message address, because the config message table is located at runtime
`0x6000` (`0x6008` "e: cfg < 8", `0x6019` "e: #ata", `0x6022` "e: s/l %d %d",
`0x6030` "e: bad len", `0x603c` "e: bad sum", `0x6070` "e: eex sum",
`0x6088` "i: modified? %d %d", `0x609c` "i: cfgNeedReboot %d", `0x60b8`
"i: waiting to reset", `0x60cd` "i: reset").

## Evidence boundary

This is static, artifact-backed evidence. It establishes message, instruction,
module, emitter, class, and nearby state gates. It does not establish runtime
frequency, delivery reliability, or the meaning of unnamed state fields. No
modified firmware or device interaction was used.
