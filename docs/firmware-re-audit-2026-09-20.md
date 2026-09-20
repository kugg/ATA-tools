# ATA firmware reverse-engineering re-audit (2026-09-20)

This is an independent audit of the prior model's `.zup`, bank, MIPS-X,
decompilation, and emulator claims. It is offline and read-only with respect to
the ATA and production systems.

## Verdict

Continue the work, but reset the decompilation phase before drawing more semantic
conclusions.

The package and bank work is valuable and substantially reproducible. The current
Ghidra C and emulator are not reliable enough to support the claimed function
count or syslog-site count. Most importantly, the prior conclusion that the SIP
firmware contains no trace strings is false: the scan omitted the mode-1
initialized-data payloads, which contain the exact live messages.

## Proven and worthwhile

The artifact-backed suite passed 83/83 tests with no skips when invoked with the
artifact directory explicitly. Independent reconstruction reproduced the pinned
package/bank identities, launch maps, checked nested payloads, type-8 payloads,
and unchanged package round trips.

The following remain high-confidence results:

- `.zup` outer `kup1` / inner `+kxz` parsing and the bounded 512 KiB bank map.
- Raw and raw-DEFLATE region reconstruction with CRC-32/ISIZE checks.
- Counted launch records and the directly decoded record operations.
- Type-8 mode-0 MIPS-X programs and mode-1 initialized-data spans.
- Big-endian MIPS-X identification and the `r23`/`r24` linkage arithmetic.
- The config-format tooling and the imported vintage x86 support tools.
- The custom Ghidra language as the best available static-analysis platform.

## Corrections to prior claims

### 1. SIP trace strings are present

The prior review scanned the reconstructed bank and mode-0 programs, but omitted
the expanded mode-1 payloads. The SIP payloads contain the exact strings needed
for syslog analysis:

| Type-8 payload | Runtime span | Examples |
| --- | --- | --- |
| `0x6bb60` | `0x100..0x26d0` | `ARP Update...` at `0x3bc`, registration/SIP/RTP/DHCP strings |
| `0x6cbcc` | `0x2fbc..0x7b84` | `ATA Config Update OK` at `0x534c`, PRI format at `0x3a43`, config/UI/RTP strings |
| `0x76c20` | `0x100..0x690` | auxiliary initialized data |

The packed main has a direct materialization of `0x534c` at runtime instruction
address `0x33c54` (mode-0 offset `0x27508`). Its surrounding instructions set up
the live `ATA Config Update OK` path. Therefore syslog-to-source analysis is
statically tractable from the SIP package itself; the transition image is useful
for comparison, but is not the missing message source.

### 2. `3,026 functions` is a candidate-start count, not a proven function count

`firmware/ghidra_decompile_packed.py` creates a function at every resolved call
target, every tail-transfer target, and every negative `r29` adjustment. That
splits real functions at internal stack adjustments. For example, Ghidra has both
`maybe_log_event` at `0x10268` and a false function `sub_00010278` at the stack
adjustment inside its prologue.

For the SIP main, the seeder currently reports:

```text
resolved sites: 5823 (3466 linked calls, 2357 tails)
linked-call targets: 806
tail targets: 1854
prologue-only candidates: 369
combined candidate starts: 3027
```

These are useful candidates, not 3,027 established functions. The generated C
contains overlapping and truncated bodies; semantic review must not count each
body as an independent function.

Resolved after the audit: the runtime loader seeds only the image entry and 806
unique linked-call targets, in descending order. Calls are linked before body
creation and tail jumps afterward. All 807 seeds create without containment or
creation failure; the saved project has no overlapping bodies. Ghidra decompiles
806; valid function `0x21dcc` retains one low-level address-space error.

### 3. `206 syslog emit sites` is not established

The generated annotated C had 206 lines containing `maybe_log_event(`, while the
stale base-zero Ghidra graph exposed 104 computed-call sites to payload offset
`0x10268`. Correct runtime loading relocates that function to `0x1c9b4` and
exposes 108 unique call instructions; the prior project had four disassembly
holes. Use unique decoded instruction addresses, not C-text occurrences.

### 4. The runtime alias model remains a hypothesis

`firmware/mipsx_image.py` accurately gates the reconstructed bank hash, but its
address folding is a working emulator model rather than proven hardware mapping.
Its own tests assert the chosen aliases; they do not independently establish
them. The worklog also records that low RAM versus bank aliases remain unresolved.

### 5. The p-code emulator is not device-accurate

The SLEIGH module deliberately leaves multiply/divide-step, coprocessor,
exception, trap, and uncertain OP5/OP7 operations as userops.
`EmulateResident.java` treats every `CALLOTHER` as a no-op. That is useful for
limited control-flow experiments but cannot validate a full boot or initialized
runtime state.

## Correctness defects in the current tools

### Resolved high: edited banks did not repair the launch checksum

The audited implementation modified launch records and compressed payloads but
did not recompute the XOR checksum stored at bank `0x40004`. The resident
validator uses this checksum to select the main or auxiliary launch header. A
one-bit record edit changed the calculated value from `0x61f0752a` to
`0x65f0752a` while leaving the stored value unchanged.

Resolved after the audit: composition now recomputes, stores, and revalidates the
section checksum after edits. A pinned edited-bank integration test passes the C
validator and selects the intended main header at bank `0x40100`.

### Resolved high: extraction manifests were not bound to source inventory

The audited implementation did not verify `bank_sha256` and trusted
manifest-controlled table and payload offsets. Duplicate headers that reference
the same table were processed independently. Changing a payload and updating its
manifest digest could make the composer treat it as unchanged.

Resolved after the audit: composition binds the exact source bank hash, parsed
header/table metadata, record offsets, and parsed payload metadata to the
manifest. It rejects omitted, added, moved, or altered inventory and conflicting
duplicate-table proposals. Replacement contents remain separate payload files.

### Medium: decoder and SLEIGH disagree on special moves

The Python decoder's `(function & 0xffe) != 0` check accepts special code 1 but
rejects codes 2 and 4, while the SLEIGH defines `md=2` and `pcm4/pcml=4`. Add a
manual-derived opcode conformance suite shared by the Python decoder, SLEIGH,
and MAME disassembler.

### Medium: memory word accesses can exceed the flat window

`Memory.store(0xfffff, ...)` grows the nominal 1 MiB bytearray by three bytes.
Require `offset + 4 <= FLAT_BYTES` for loads and stores and test every boundary.

### Medium: artifact-backed tests skip silently without an environment variable

Most tests search `$ATA186_TEST_ARTIFACT_DIR` or `vendor/`, while the local files
are under `ata_03_01_00_sip_040211_1/`. Release evidence must report skip counts,
or all artifact-backed tests should use the same candidate search logic.

## Best avenue forward

### Phase 1: make a correct runtime-image loader

Build a Ghidra program with separate blocks at their actual runtime addresses:

- initialized data `0x100..0x26d0` from type-8 `0x6bb60`;
- zero-fill `0x26d0..0x2fbc`;
- initialized data `0x2fbc..0x7b84` from type-8 `0x6cbcc`;
- zero-fill `0x7b84..0xc74c`;
- packed main code `0xc74c..0x686a0` from type-8 `0x479bc`;
- resident ROM/code in its separately justified high mapping.

The current base-zero code import overlays the address range used by real low
data and prevents natural string/data references. A correct loader should make
`0x33c54 -> 0x534c` an ordinary reference visible to Ghidra.

Completed after the audit: the launch-derived loader creates the five exact SIP
blocks above and the corresponding transition layout. The runtime validator
confirms block boundaries/permissions and the ordinary message reference.

### Phase 2: recover conservative function boundaries

Seed only linked-call targets as definite entries. Treat tail targets as basic
blocks unless they independently match a validated entry pattern. Recover the
compiler's real prologue forms, including argument stores before the stack
adjustment. Reject overlapping functions and report candidate confidence.

Completed after the audit: 807 SIP entry/call-target seeds create without
containment failure and saved bodies do not overlap. Ghidra decompiles 806;
`0x21dcc` retains one isolated low-level address-space error.

### Phase 3: build the syslog atlas from instruction addresses

Start with the two live messages:

- `ATA Config Update OK` at runtime data `0x534c`, directly referenced at
  runtime code `0x33c54`;
- `ARP Update...` at runtime data `0x3bc`.

For each string, follow data references to formatter calls, class-mask gates,
and callers. Record unique instruction addresses, not decompiled-text counts.
Then expand to registration, DHCP, SIP, and RTP messages.

Completed for the class-gated emitter after the audit: the checked-in atlas and
`firmware/syslog_lookup.py` cover all 27 packed direct calls with exact call,
message, class/mode argument instructions, and owner confidence. Package-backed
verification checks every row. `0x4da78` deliberately remains inherited-class
or class 7 based on its two mask branches. The separate 108-call logger path is
the next atlas scope.

### Phase 4: cross-version matching

Once both programs have sound function boundaries and comparable runtime memory
maps, use Ghidra Version Tracking or BinDiff's Ghidra BinExport support to match
SIP and transition functions. Ghidra's documentation explicitly requires mostly
correct disassembly, function definitions, and similar memory maps first, so it
must follow phases 1 and 2 rather than precede them.

## Tool assessment

- **Ghidra:** keep as the primary platform. The existing custom MIPS-X module is
  the largest project-specific asset.
- **Ghidra Version Tracking / BinDiff:** currently missed, high-value after
  function-boundary repair. Use for SIP/transition and firmware-version matching.
- **MAME:** real MIPS-X disassembler and PAP2 skeleton, but `execute_run()` only
  advances PC. Use as an independent decode oracle, not an emulator.
- **Binwalk:** installed, but detected no signatures in either `.zup`; the custom
  parser is materially better. Retain only as an independent generic check.
- **Kaitai Struct:** useful for publishing a declarative format specification,
  not for discovering semantics or replacing the hardened parser.
- **Binary Ninja / IDA / rizin:** no native MIPS-X support. A new architecture
  plugin would duplicate the existing SLEIGH effort.
- **QEMU / Unicorn / angr native MIPS / PANDA / Renode:** conventional MIPS is
  not MIPS-X. None is a shortcut; each needs a new CPU/lifter backend.
- **angr p-code:** potentially useful later for small symbolic checks through
  Ghidra p-code, but not before SLEIGH conformance and memory mapping are fixed.
- **Hardware RAM/JTAG:** potentially decisive for runtime-built tables, but only
  after board-level identification and a separately approved non-destructive
  electrical plan. It is not the first step for syslog mapping.

## Go/no-go

- **Go:** package/bank format research, runtime-image construction, static string
  xrefs, config mapping, and cross-version comparison.
- **Repair first:** function boundaries, decoder conformance, and evidence labels
  in the current review. The editable rebuild pipeline defects above are fixed
  and artifact-backed, but this does not establish vendor authenticity.
- **No-go for now:** modified firmware on hardware, full boot claims from the
  no-op p-code model, implementing a MAME CPU core, or porting MIPS-X to another
  framework before the static path is exhausted.

## Verification performed

```sh
ATA186_TEST_ARTIFACT_DIR="$PWD/ata_03_01_00_sip_040211_1" \
python3 -B -m unittest \
  firmware.tests.test_zup_bank \
  firmware.tests.test_zup_extract \
  firmware.tests.test_zup_rebuild \
  firmware.tests.test_mipsx_image \
  firmware.tests.test_mipsx_dasm -v
# Initial audit: ran 83 tests, OK, no skips
```

Additional direct checks reproduced the launch-checksum defect, the 1 MiB memory
boundary growth, the special-register decoder mismatch, the stale 104-call Ghidra
logger calls, and the SIP mode-1 string/runtime-address table above. Plain
`binwalk` scans identified no generic signatures in either package.

Post-audit pipeline repair verification added the C launch-trace suite to the
command above and ran 110 tests with no skips. It covers source-bank and payload
inventory tampering, conflicting duplicate headers, checksum regeneration,
pinned SIP edit/rebuild/reparse, and intended main-header selection.

Final post-audit discovery with the explicit artifact directory ran 292 firmware
tests successfully. The sole skip is the optional Swedish config vector. Six
syslog lookup tests include exact 27-call/package/message/argument verification,
bounded atlas validation, symlink and duplicate-call rejection, and lookup output.
