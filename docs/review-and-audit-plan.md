# ATA firmware research: review, cleanup, and third-party audit plan

Audience: a third-party agentic auditor, and the project owner. Purpose: state honestly
what the firmware research has produced, what is **not** achieved, what is worth
pursuing, and a verifiable plan for an independent audit.

Everything here is from pinned, local artifacts; no device contact. Evidence level is
marked **[proven]** / **[inferred]** / **[open]**.

---

## 1. The actual goal (kept front and centre)

> Be able to debug a faulty ATA from a **syslog message**: find the message's source in the
> firmware and understand the **code emitted around the log line** (the state that produced it).

Measured against that goal, the current output is **not yet useful**: the readable C is
barely improved and the syslog message source is **not located**. This document explains why
and what would fix it.

---

## 2. What is real (verified)

| Artifact | Evidence |
| --- | --- |
| Bank reconstruction, single hash-asserted source | `firmware/zup_bank.py` + `firmware/mipsx_image.py`, pinned SHA-256 `ee2247ad…` [proven] |
| Corrected Ghidra MIPS-X module: register-arg ABI (`r4..`), return `r2`, real `return` for `jspci r31`, `SpecTo` for `psw`/`md` | `firmware/ghidra_module/` [proven] |
| Packed main decompiled: **3,026 functions**, `r23`/`r24` calls resolved (11,941 / 207, 0 unverified) | `firmware/ghidra_decompile_packed.py` [proven] |
| **206 syslog emit sites** in the packed main, with numeric codes (`0x60xx`, `0x7a44`, …) | `research/decompiled/named/packed_main_annotated.c` [proven] |
| Config format fully documented: text `#txt`, XML `<ATADev>`, binary TLV `#ata`, RC4 weak/strong, split profiles | `docs/ata-config-formats.md` [proven] |
| Config parser chain + descriptor schema at RAM `0x4024` (84 entries, 75/84 tags match `ptag.dat`) | `docs/ata-runtime-config-dispatch.md` [proven] |
| Dispatch structure: `g_dispatch_7580` (14 handlers), per-channel state machine (`0xbe98`, `0x1a8`-byte ctx), resident `g_event_table` (`0x2bc8`) | same doc [proven] |
| **Trace-message table** (the message source reference) | transition image, bank `0x2f000..0x79a00` [proven] |
| Deterministic C pipeline (`regenerate_readable_c.py`), evidence-backed names (`naming/packed_main.json`) | [proven] |

---

## 3. What is NOT achieved (honest)

1. **Readability barely improved.** Only **17 of 3,026** functions carry semantic names; the
   rest are `sub_XXXXXXXX`. Locals are `unaff_rNN` / `iRamNNNN` / `param_N`. This is why the
   owner "has not been able to see any improvement on the readable code".
2. **The syslog message source is not located.** The SIP firmware image — bank, packed main,
   and packed aux — contains **zero** trace-message strings (`Reg Resp`, `RTP`, `SIP/2.0`,
   `REGISTER`, `Error` all absent). Yet the live device emits text syslog
   (`[03]:ATA Config Update OK`, `[00]:ARP Update:…`). So the code→message mapping is
   **[open]**.
3. **Runtime tables not materialised.** `g_cfg_state` (`0x9d84`) and `g_event_table`
   (`0x2bc8`) are built at init; not dumped.
4. **The emulator chase was a detour.** Repeated attempts to reach the runtime state
   (entry mode, standalone packed-main emulation, hand-rolled boot, Ghidra p-code emulator)
   all hit the same launch/runtime-state wall. This was pursued well past the point of
   diminishing returns; the p-code emulator's only durable win is the `SpecTo` sleigh fix.

---

## 4. Root causes (why the readable C is not readable)

* **Naming is manual and tiny.** 17 functions were hand-named. At that rate the file will
  never be readable. Naming must be **generated** from evidence (the config schema, the log
  codes, cross-references), not typed by hand.
* **No type/struct recovery.** The decompiler emits `*(int *)(ctx + 0x108)` because no struct
  is defined. The per-channel context (`0x1a8` bytes) and the config state (`0xc`-stride) are
  known but not typed.
* **The function-pointer dispatch hides the call graph** from the decompiler; we substitute
  names post-hoc (`annotate_packed_c.py`), which is brittle.
* **The interesting strings are not in the image**, so a strings-driven approach cannot anchor
  the SIP syslog work.

---

## 5. What is worth pursuing (the nuggets, prioritised)

**N1 — Locate the syslog message source (highest value; directly the goal).**
The emit sites and codes are known (206 sites). The message **texts** exist in the
transition image (a rich table: `[%d]Reg Resp %s`, `RTP Rx Init: %d, %d`,
`Call waiting`, `Failed to extract UID from RxMsg`, …). Two questions to answer, both static:
* Does the SIP firmware share the resident code that carries those messages (i.e. is the
  message table copied into the SIP image at boot, or is the SIP syslog actually emitted by a
  shared resident)? If yes, the transition table is the SIP message source.
* If not, where does the SIP device get the text? (language file `.kup`? host-side mapping?
  a copied/compressed region?) This must be answered before any "syslog → code" tool can work.

**N2 — Build the code→message→state index.**
For each log code, record: the emit function, the neighbouring calls/branches, and (once N1
resolves) the message text. Output: a table `code → function → message → state`. This is the
artifact that makes syslog debugging possible, and it is **static**.

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

**Objective.** Independently confirm or refute the claims in §2, and assess whether §5's
plan (especially N1) is sound. The auditor must be able to reproduce every claim from the
pinned artifacts and reject anything that is not reproducible.

**Method.** Offline, read-only; no device, no network. Work from the pinned `.zup`
(SHA-256 `b8597657…`) and the reconstructed bank (`ee2247ad…`).

**Checks (each with an explicit accept/reject):**

1. **Image integrity.** Rebuild the bank with `firmware/zup_bank.py`; confirm
   `ee2247ad…`. *Reject if the digest differs.*
2. **Decompilation.** Run `firmware/regenerate_readable_c.py` (temp project); confirm
   ~3,026 functions and the resolved-call counts. *Reject if it does not reproduce.*
3. **Naming policy.** Every name in `firmware/naming/packed_main.json` has a non-empty
   `evidence` string, and the generated C shows it as a plate comment. *Reject any name
   without evidence.*
4. **Config schema.** Independently decode the `0x4024` table (base `0x4024`, stride `0x14`,
   byte 2 = TLV tag) and confirm the 75/84 match against `ptag.dat`. *Reject the claim if the
   match rate or layout differs.*
5. **Dispatch claims.** Confirm `g_dispatch_7580` resolves to the listed 14 functions via
   `firmware/resolve_data_tables.py`, and that `g_event_table`/`g_cfg_state` are zero-filled
   gaps (type-2). *Reject if any target is not a function prologue.*
6. **Syslog strings claim (critical).** Independently scan the SIP bank, packed main, and
   packed aux for the trace fragments; confirm **zero** hits, and confirm the transition image
   **does** contain them. *Reject the SIP-syslog conclusion if any fragment is found in SIP.*
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

**Deliverable.** A short report: per-check accept/reject, the exact command and result, and a
verdict on whether **N1** can be answered from the available artifacts (and if not, what single
piece of evidence is missing — most likely the `.kup` language file or a captured SIP syslog
with its class/code fields).

---

## 8. Bottom line

The **static config/dispatch research is solid and publishable**. The **readable C is not
usable yet** because naming and typing were not automated. The **syslog-debug goal is
unblocked only if the message-source question (N1) is answered** — and the single most useful
next artifact is the transition message table mapped against the packed main's 206 log emit
codes. Execution/emulation is not on the critical path and should be retired.
