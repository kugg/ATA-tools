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
2. **Recover the `g_event_table` (`0x2bc8`) registration.** Only the zeroing `sub_000068bc` is
   located; find the writers and check whether registration is config-gated → maps *config →
   enabled event handlers*.
3. **Trace the callback context structs.** For each `(*(code *)(*(int *)(ctx+off) << 2))()` site,
   find where `ctx+off` is written and whether it derives from `g_cfg_state`. If so, those 188
   sites become resolvable and config→callback is direct.
4. **Annotate the apply code** with the decoded flag semantics (edit
   `refactor/naming/packed_main.json` + comments, regenerate).

## 5. Honest status

* Proven: the config parser chain, `g_cfg_descriptors` schema, the existence and layout of
  `g_cfg_state`, the ABI, and the `jspci` dispatch families.
* Runtime-built (not statically dumpable): `g_cfg_state` and `g_event_table` — both live in
  type-2 zero-fill gaps and are filled at init; standalone emulation of the packed main
  diverges into the data span without reaching the init.
* Highest-value next step is (1)/(2)/(3) above; all are the same "execute the launch sequence"
  problem that has bounded this effort.
