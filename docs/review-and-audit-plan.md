# ATA firmware research: review, cleanup, and third-party audit plan

Audience: a third-party agentic auditor, and the project owner. Purpose: state honestly
what the firmware research has produced, what is **not** achieved, what is worth
pursuing, and a verifiable plan for an independent audit.

> [!WARNING]
> This plan has been superseded in material respects by
> [`firmware-re-audit-2026-09-20.md`](firmware-re-audit-2026-09-20.md). In
> particular, the SIP mode-1 payloads do contain the exact live syslog strings,
> and the 3,026/206 counts were candidate/decompiler-text counts rather than
> established function/emit-site counts. Post-audit runtime loading, conservative
> function recovery, and the initial syslog atlas are now complete; see
> [`ata-syslog-atlas.md`](ata-syslog-atlas.md).

Everything here is from pinned, local artifacts; no device contact. Evidence level is
marked **[proven]** / **[inferred]** / **[open]**.

---

## 1. The actual goal (kept front and centre)

> Be able to debug a faulty ATA from a **syslog message**: find the message's source in the
> firmware and understand the **code emitted around the log line** (the state that produced it).

Measured against that goal, the corrected output is now reliable enough for an
initial message-to-state atlas. It does not yet cover every message, runtime-built
table, or unresolved MIPS-X operation.

---

## 2. What is real (verified)

| Artifact | Evidence |
| --- | --- |
| Bank reconstruction, single hash-asserted source | `firmware/zup_bank.py` + `firmware/mipsx_image.py`, pinned SHA-256 `ee2247ad…` [proven] |
| Corrected Ghidra MIPS-X module: register-arg ABI (`r4..`), return `r2`, real `return` for `jspci r31`, `SpecTo` for `psw`/`md` | `firmware/ghidra_module/` [proven] |
| Runtime loader maps two initialized-data blocks, two zero-fill blocks, and code `0xc74c..0x686a0`; 807 entry/call-target seeds create with no containment failure and zero overlapping saved bodies | `firmware/ghidra_decompile_packed.py` + `ValidatePackedRuntime.java` [proven] |
| Correct runtime decode has 108 unique calls to relocated `maybe_log_event@0x1c9b4`; the stale base-zero project exposed only 104 | decoder + corrected Ghidra xrefs [proven] |
| Config format fully documented: text `#txt`, XML `<ATADev>`, binary TLV `#ata`, RC4 weak/strong, split profiles | `docs/ata-config-formats.md` [proven] |
| Config parser chain + descriptor schema at RAM `0x4024` (84 entries, 75/84 tags match `ptag.dat`) | `docs/ata-runtime-config-dispatch.md` [proven] |
| Dispatch structure: `g_dispatch_7580` (14 handlers), per-channel state machine (`0xbe98`, `0x1a8`-byte ctx), resident `g_event_table` (`0x2bc8`) | same doc [proven] |
| SIP trace-message strings in expanded mode-1 data (`0x100..0x26d0`, `0x2fbc..0x7b84`) | SIP type-8 payloads `0x6bb60`/`0x6cbcc` [proven] |
| Deterministic C pipeline (`regenerate_readable_c.py`), evidence-backed names (`naming/packed_main.json`) | [proven] |

---

## 3. What is NOT achieved (honest)

1. **Readability remains partial.** Nineteen entries carry semantic names and
   locals remain `unaff_rNN` / `iRamNNNN` / `param_N`. Overlapping function
   bodies are gone. One valid SIP function at runtime `0x21dcc` still triggers a
   Ghidra low-level address-space decompiler error.
2. **The earlier syslog scan was incomplete.** It omitted expanded mode-1 data. The SIP
   image contains `ATA Config Update OK` at runtime `0x534c` and `ARP Update...` at `0x3bc`;
   both are now mapped through class-gated emitter `0x1cc0c`; see the atlas.
3. **Runtime tables not materialised.** `g_cfg_state` (`0x9d84`) and `g_event_table`
   (`0x2bc8`) are built at init; not dumped.
4. **The emulator chase was a detour.** Repeated attempts to reach the runtime state
   (entry mode, standalone packed-main emulation, hand-rolled boot, Ghidra p-code emulator)
   all hit the same launch/runtime-state wall. This was pursued well past the point of
   diminishing returns; the p-code emulator's only durable win is the `SpecTo` sleigh fix.

---

## 4. Root causes (why the readable C is not readable)

* **Naming is manual and tiny.** 19 functions are evidence-named. At that rate the file will
  never be readable. Naming must be **generated** from evidence (the config schema, the log
  codes, cross-references), not typed by hand.
* **No type/struct recovery.** The decompiler emits `*(int *)(ctx + 0x108)` because no struct
  is defined. The per-channel context (`0x1a8` bytes) and the config state (`0xc`-stride) are
  known but not typed.
* **The function-pointer dispatch hides the call graph** from the decompiler; we substitute
  names post-hoc (`annotate_packed_c.py`), which is brittle.
* **Type and indirect-dispatch recovery remain limited.** The corrected runtime
  import supplies natural data xrefs and non-overlapping bodies, but it cannot
  infer runtime-built tables or source-level state names.

---

## 5. What is worth pursuing (the nuggets, prioritised)

**N1 — Correct SIP runtime image (completed).**
Mode-1 data is loaded at `0x100`/`0x2fbc`, documented gaps are zero-filled,
and mode-0 code is loaded at `0xc74c`. The validator confirms natural references
to the exact live strings without relying on the transition image.

**N2 — Extend the code→message→state index.**
The initial atlas records the two observed priority messages, unique instruction
addresses, owning paths, class gate, and neighbouring state branches. Extend the
same static method to the remaining message table.

**N3 — Generated, evidence-backed naming at scale.**
Derive names from: `ptag.dat` tag names (config setters/getters), the log codes (log helpers),
the `g_dispatch_7580` handler set, and string/table references. Every name carries its
evidence (already the policy in `naming/packed_main.json`).

**N4 — Struct/type recovery.**
Define the per-channel context (`0x1a8`) and the config state entry (`0xc`) as Ghidra structs
so the C reads `ctx->cb_108` / `cfg->value`, and the decompiler's call resolution improves.

**N5 — Retire the emulators.**
Keep the Ghidra p-code emulator as the only execution engine (or drop execution entirely);
remove the hand-rolled ones to end the recurring delay-slot/aliasing class of bug.

---

## 6. Cleanup

Safe, owner-scoped cleanup (do **not** touch other agents' files):

* Retire `research/boot_run.py`, `research/dispatch_resolve.py`, `research/main_run.py`,
  `firmware/mipsx_boot_trace.py` (superseded; keep as `.archive/` if desired).
* Keep: `firmware/{zup_bank,mipsx_image,mipsx_dasm,ghidra_decompile_packed,annotate_packed_c,
  resolve_data_tables,regenerate_readable_c,cfgfmt}.py`, `firmware/naming/`,
  `firmware/ghidra_module/`, `firmware/ghidra_scripts/EmulateResident.java`.
* Remove generated/scratch: `extract_resolved.txt` (superseded by the named C), stale
  `/tmp` outputs, `refactor/DIR/`.
* Consolidate docs: `docs/ata-config-formats.md` + `docs/ata-runtime-config-dispatch.md` are
  the two research docs; this review is the third.
* **Do not** delete or edit `WORKLOG.md`, `TODO.md`, `docs/handoff.md` (local, gitignored,
  another agent's).

---

## 7. Audit plan for a third-party agentic auditor

**Objective.** Independently confirm or refute the claims in §2 and the completed
N1/N2 evidence. The auditor must be able to reproduce every claim from the
pinned artifacts and reject anything that is not reproducible.

**Method.** Offline, read-only; no device, no network. Work from the pinned `.zup`
(SHA-256 `b8597657…`) and the reconstructed bank (`ee2247ad…`).

**Checks (each with an explicit accept/reject):**

1. **Image integrity.** Rebuild the bank with `firmware/zup_bank.py`; confirm
   `ee2247ad…`. *Reject if the digest differs.*
2. **Decompilation.** Run `firmware/regenerate_readable_c.py` (temp project);
   confirm 807 conservative seeds, 806 decompilations, the recorded `0x21dcc`
   error, and no overlapping saved bodies.
3. **Naming policy.** Every name in `firmware/naming/packed_main.json` has a non-empty
   `evidence` string, and the generated C shows it as a plate comment. *Reject any name
   without evidence.*
4. **Config schema.** Independently decode the `0x4024` table (base `0x4024`, stride `0x14`,
   byte 2 = TLV tag) and confirm the 75/84 match against `ptag.dat`. *Reject the claim if the
   match rate or layout differs.*
5. **Dispatch claims.** Confirm `g_dispatch_7580` resolves to the listed 14 functions via
   `firmware/resolve_data_tables.py`, and that `g_event_table`/`g_cfg_state` are zero-filled
   gaps (type-2). *Reject if any target is not a function prologue.*
6. **Syslog strings claim (critical).** Expand all SIP mode-1 type-8 payloads and confirm the
   live strings and runtime destinations above. Confirm the `0x33c54 -> 0x534c` reference.
7. **Format doc.** Spot-check `cfgfmt.py` against the transition/tool behaviour for at least:
   the `#ata` header (`0x7FFE`/len 4/checksum), weak vs strong RC4, and the split threshold
   `0x7D1`. *Reject any divergence not documented as an intentional safety deviation.*
8. **No fabrication.** Confirm no claim relies on emulation that did not actually run, and
   that the p-code emulator's limits are stated (it does not reach the config init).

**Red flags the auditor should raise:**
* Any name or message mapping presented without evidence.
* Any "resolved" call that is a heuristic, not a decoded target.
* Any claim that a mock/emulator proves hardware behaviour.
* Any leaked credential/private path in committed material.

**Deliverable.** A short report: per-check accept/reject, the exact command and
result, and a verdict on whether the two initial atlas rows follow from the
pinned artifacts without emulation or device assumptions.

---

## 8. Bottom line

The **static config/dispatch research and corrected runtime image are useful and
reproducible**. Conservative boundaries remove the prior overlap, but naming,
typing, runtime-built tables, and one decompiler failure still limit readability.
The initial syslog-debug goal is demonstrated by the two-row atlas; expansion is
static follow-on work. Execution/emulation is not on the critical path.
