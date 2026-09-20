# ATA runtime: config struct → dispatch, and the deterministic C pipeline

Handoff note for a follow-on agent. Companion to
[ATA configuration formats](ata-config-formats.md) and
[the firmware analysis](firmware-analysis.md). Everything here is from the pinned
artifacts; names are evidence-backed and the generated C is reproducible.

## 0. Deterministic, evidence-backed readable C

The packed-main C is generated, not hand-edited:

```
python3 refactor/regenerate_readable_c.py            # temp project
python3 refactor/regenerate_readable_c.py --project ghidra-project-packed   # persistent (stop the MCP first)
```

Stages:

1. `refactor/ghidra_decompile_packed.py --names refactor/naming/packed_main.json`
   - expands the checked type-8 payload (`zup_bank`), resolves `jspci` call/tail targets
     (`mipsx_dasm`), imports into Ghidra (MIPS-X, corrected cspec/sleigh), linear-sweeps,
     links `COMPUTED_CALL`/`COMPUTED_JUMP`, creates functions, **applies the naming map**, and
     decompiles.
   - Output: `research/decompiled/named/packed_main_readable.c` (3,026 functions).
2. `refactor/annotate_packed_c.py --names …`
   - substitutes the resolved `r23` (in-payload) and `r24` (cross-module → resident) call
     targets, preferring the evidence-backed name over `sub_XXXXXXXX`, and normalises scalar
     `undefined4` to `int`.
   - Output: `research/decompiled/named/packed_main_annotated.c`.

**Naming policy.** `refactor/naming/packed_main.json` holds every function/global name with a
mandatory `evidence` string; the generator writes that evidence as a plate comment above the
definition. Names use the `ghidra-mcp-ng` `rules.yaml` prefixes (`guess_`/`maybe_`/`likely_`).
To rename, edit the JSON and re-run — never edit the generated C.

Current coverage: 3,026 functions, `r23` resolved 11,941 (0 unverified), `r24` 207, 379 named
call sites, 188 residual dynamic callbacks. Provenance of the tooling changes: WORKLOG
2026-09-18…2026-09-19.

## 1. The config parser and the config struct (packed main)

| Step | Name | Addr |
| --- | --- | --- |
| parse profile | `maybe_cfg_parse_profile` | `0x37a1c` |
| TLV loop | `maybe_cfg_apply_tlv_records` | `0x380c0` |
| store | `maybe_cfg_store_parameter` | `0x24688` |
| lookup | `maybe_cfg_lookup_parameter` → `maybe_cfg_find_tag_index` | `0x24aa8` → `0x24ae8` |
| apply | `maybe_cfg_apply_parameter` | `0x24064` |

- `maybe_cfg_parse_profile` requires header `tag == 0x7FFE && len == 4`, verifies the checksum
  (`maybe_cfg_checksum_verify`, `0xff7c`), then runs the TLV loop.
- `maybe_cfg_apply_tlv_records` reads `(tag,len)`; skips `tag < 0xff` unless `tag` is `1` or
  `0x12`; applies each via `maybe_cfg_store_parameter`; special-cases tags `0x23` and `0x66`;
  logs `0x60xx` codes via `maybe_log_event`.
- **`g_cfg_descriptors` at RAM `0x4024`** (stride `0x14`, 84 entries) is the static schema:
  byte 2 = TLV tag (75/84 match `ptag.dat`), +4 size, +6 runtime format, flags word at +0.
- **`g_cfg_state` at RAM `0x9d84`** (stride `0xc`) is the live per-parameter value struct —
  the "local config struct".
- `maybe_cfg_apply_parameter` reads the descriptor and the state, and branches on descriptor
  flag bits (`0x800` re-parse, `0x2000` reset/boolean, `0xa100` text path).

## 2. The dispatchers

- **Resident event dispatcher** `dispatcher_f82b38` (bank `0x2b38`): event code `0..0x4f` →
  `mem[g_event_table + code*4]` (`g_event_table` = `0x2bc8`). The table is **zeroed**
  (`sub_000068bc(0x2bc8,0x140)`) then **registration-populated** at run time.
- **Packed-main dispatch** is the ~188 residual `(*(code *)(*(int *)(ctx+off) << 2))()` calls —
  function pointers read from **context structs**.
- **Log path:** `maybe_log_event` → `maybe_log_dispatch` (`0x100e8`) → resident
  `dispatcher_f82b38` (only records whose first byte is `0x60`).

### 2.1 Data-span pointer tables are runtime addresses  [proven]

A pointer stored in a type-8 mode-1 data span is a **runtime** word address; the
payload-relative offset the decompiler uses is `value*4 - 0xc74c`. This resolves the
`g_dispatch_7580` table (called as `(*(code *)(*(int *)(idx*4 + 0x7580) << 2))()`):

```
[ 0] sub_00055c70   [ 1] sub_000562c8   [ 2] sub_00056568   [ 3] sub_00056ca4
[ 4] sub_00057968   [ 5] sub_000574b8   [ 6] sub_0005847c   [ 7] sub_00058064
[ 8] sub_00057968   [ 9] sub_00058338   [10] sub_000583f0   [11] sub_000570bc
[12] sub_000566b8   [13] sub_000585dc
```

All 14 resolve to function prologues. Reproduce with
`python3 refactor/resolve_data_tables.py` (deterministic, evidence-backed; the result is
recorded on `g_dispatch_7580` in `refactor/naming/packed_main.json`). The index is a runtime
value, so the call *sites* remain dynamic, but the handler set is now known.

Other callback families are context-relative and still dynamic: `unaff_r30 - 0x3c` (frame
slot, 17 sites), `*+0x108` (context field, ~11 sites), `param_1 + 0x68` (arg field). Their
targets depend on the runtime context struct, not a static table.

### 2.2 The `+0x108` callbacks belong to a per-channel state machine, not config  [proven]

Tracing the `*+0x108` family:

* A table of context pointers lives at RAM **`0xbe98`** (in the type-2 zero-fill gap, so built
  at run time), indexed by a channel/call number.
* `sub_000068bc(0x1a8)` allocates a **`0x1a8`-byte context**; the allocator (`sub_00058dd4` /
  `sub_00058df4`) stores the pointer at `0xbe98 + index*4`, sets `*ctx = index`, and clears
  `ctx+0xdc` / `ctx+0x104`.
* Each context holds records at **stride `0x6c`**; a record's `+8` is the **`g_dispatch_7580`
  handler index** (`sub_…` at line 118525 returns `*(int*)(*(int*)(index*4+0xbe98) + rec*0x6c + 8)`).
* `sub_00058f60(index, callback)` sets `ctx+0x108`; the dispatcher `sub_00059310` calls
  `table[handler_index](context, …)`, and handlers invoke `(*(code*)(*(int*)(ctx+0x108)<<2))()`.

So `+0x108` is a **per-channel state-machine callback**, allocated and set during call setup —
**not** the config struct. The config→callback hypothesis is therefore not satisfied through
this family; the config struct (`g_cfg_state`, `0x9d84`) remains a separate, gating input.

### 2.3 `g_event_table` (`0x2bc8`) is runtime-populated  [proven]

The resident event table is not statically initialised:

* It is zeroed by `sub_000068bc(0x2bc8, 0x140)` (0x50 entries) inside `func_0cf81e58`
  (bank `0x1e58`) — which is itself a dispatch state machine, not a plain init.
* `dispatcher_f82b38` reads `mem[0x2bc8 + code*4]` and, when non-zero, calls `0x26f0` with it;
  `0x26f0` performs list/queue manipulation (`ld [r8],r2; ld [r2+8],r8; st [r3+8],r8; …`), so an
  entry is a **pointer to a per-event structure**, not a bare function pointer.
* The resident C contains **no writes** to `mem[0x2bc8 + code*4]`, and a scan of the bank found
  **no static table** of ≥12 consecutive resident function pointers. The entries are therefore
  allocated and linked at run time.

Same conclusion as `g_cfg_state`: the dispatch tables are materialised during the launch
sequence; only the config **schema** (`g_cfg_descriptors`) and the `g_dispatch_7580` handler set
are statically recoverable.

## 3. Does the config struct drive the dispatcher?

Two facts bound the answer:

1. The **resident never reads `0x9d84`** (0 references) — the config struct is packed-main only.
2. **No code-pointer load reads `0x9d84`/`0x9d90`** — the config state is not itself a
   function-pointer table.

So the relationship is **gating/selection**, not identity: config descriptor flags and state
values select which apply/handler path runs; the dispatch tables are `g_event_table` (resident
events) and the context-struct callbacks (packed main). The config→dispatch insight is real
but indirect.

## 4. Using the insight to understand the runtime

Because the config vocabulary is now decoded, the config-apply code is readable and the
settings that gate features are identifiable (`OpFlags`, `CallFeatures`, `TraceFlags`,
`VLANSetting`, `SyslogCtrl`, …). To close the loop:

1. **Materialise `g_cfg_state` (`0x9d84`).** It is built by `sub_0002854c` per parameter from
   `g_cfg_descriptors`. Needs the init sequence (boot emulator) or a synthetic environment that
   stubs the resident globals the init reads. Then name the fields from `ptag.dat`.
2. **Recover the `g_event_table` (`0x2bc8`) registration.** Done (§2.3): it is
   runtime-populated; no static source.
3. **Trace the callback context structs.** Done (§2.2): the `+0x108` family is a per-channel
   state machine, not config-derived.
4. **Annotate the apply code** with the decoded flag semantics (edit
   `refactor/naming/packed_main.json` + comments, regenerate).

## 5. Boot emulator attempt (option c)  [blocked]

Running the resident from the reset stub (`0x7ff80`) with the correct byte pc (`mipsx_boot_trace`
takes a byte, not a word — an earlier stall was a caller bug) reaches the launch-record walk at
`0x7fd24..0x7fdcc` and loops forever:

* the walk dispatches on each record's first word (`ld [r10],r3`, a chain of `beq r2,r3`), stride
  `0x10`;
* in the emulator `r10` is set once to a garbage value and the record count `r11` is **never
  initialised (0)**, so `bne r7,r11` never exits; it reads `0xffffffff` records indefinitely.

The launch header lives at bank `0` (`table_address 0x0CFC0110`, 27 records of `0x10` bytes; the
first record word is `0x1`), but the reset path does not materialise `r10`/`r11` from it in the
model. So boot mode cannot reach the config init: the launch-header read / device state is not
modelled. This is the concrete blocker for materialising `g_cfg_state` and `g_event_table`.

## 6. Honest status

* **Statically recovered:** the config parser chain, `g_cfg_descriptors` schema (75/84 tags),
  the `g_dispatch_7580` handler set (14), the ABI, and the `jspci` dispatch families; plus the
  negative results that `g_event_table` and the `+0x108` callbacks are runtime/per-channel, not
  config-derived.
* **Runtime-built (not statically dumpable):** `g_cfg_state` (`0x9d84`) and `g_event_table`
  (`0x2bc8`). Both need the launch sequence.
* **Blocker:** the boot emulator does not apply the launch header (r10/r11 unset), so it never
  reaches the config init. Next work is to model the launch-header read (a bounded, concrete
  target) rather than the whole device.
