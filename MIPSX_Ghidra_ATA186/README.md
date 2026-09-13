# MIPS-X Ghidra processor module — ATA186 big-endian profile

This is a **starter Ghidra processor module for Stanford MIPS-X**, aimed at reverse-engineering Cisco ATA186/ATA188-family firmware and related MediaMatics/IIT-style implementations.

## What is modeled

- 32-bit, fixed-width, **big-endian** MIPS-X instructions.
- Byte-addressed RAM with the MIPS-X distinction that branch/jump quantities are word-oriented.
- Type-00 conditional branches with **two delay slots**, including the `SQ` (squash-on-not-taken) form.
- Core integer operations: `add`, `sub`, `subnc`, `and`, `bic`, `not`, `or`, `xor`.
- `asr`, `sh`, `rotlb`, `rotlcb`.
- `ld`, `ldt`, `st`, `stt`, `ldf`, `stf` as 32-bit memory accesses.
- `addi` and `jspci`; `jspci` scales its architectural word target to Ghidra's byte address space and models two delay slots.
- `movfrs` / `movtos` for the documented special-register encodings.
- Decode-only conservative treatment of `dstep`/multiply-step details, coprocessor transfers, trap/HSC, JPC/JPCRS, and uncertain ES3210/ES3890 type-2 opcodes.

The language ID is:

```text
MIPS-X:BE:32:ATA186
```

## Installation

The most predictable development install is to copy the `MIPSX` directory into your Ghidra tree as:

```text
<Ghidra>/Ghidra/Processors/MIPSX/
```

Then restart Ghidra. Ghidra normally compiles `data/languages/mipsx_be.slaspec` to `mipsx_be.sla` when the language is loaded. If your Ghidra installation directory is read-only, use a GhidraDev processor-module project instead and copy this module's `data/languages` directory into that project.

For a raw ATA firmware/code image, import it as **Raw Binary**, then choose `MIPS-X:BE:32:ATA186` manually. Set the image base to the byte address where the mapped code bank executes before disassembly. ATA-tools' bank reconstruction/mapping remains a separate preprocessing concern; this module is the CPU language layer.

## Important caveats

1. **This has not been run through Ghidra's `SleighCompile` in this build environment.** The XML files are schema-shaped and validated as well-formed, and the SLEIGH was checked structurally, but the final authority is your installed Ghidra's SLEIGH compiler. If it emits a line-specific error, that should be a small syntax/compatibility fix rather than an ISA redesign.
2. **r0 is architecturally hard-wired to zero.** The compiler/processor specs track it as zero at function entry, but a fully polished language should use operand tables that prevent arbitrary instructions from ever writing a mutable p-code varnode named `r0`.
3. **The ATA186 ABI is still provisional.** `r29` is set as stack pointer based on ATA-tools' prologue analysis; argument and return-register rules need to be learned from real firmware. The included cspec intentionally models arguments conservatively on the stack and uses `r1` only as a provisional scalar result.
4. **Type-2 opcodes 5 and 7 are deliberately conservative.** With `src1=0` they decode as standard MIPS-X coprocessor transfers. Nonzero-`src1` forms are shown as `xop5` / `xop7`, because ATA-tools/MAME flag them as possible ES3210/ES3890 byte operations.
5. **Exception-return pipeline operations are decode-only.** JPC/JPCRS operate on the hidden PC chain; pretending they are ordinary indirect jumps gives misleading nested-delay-slot p-code in Ghidra.
6. `ldf`/`stf` currently use the same 32-bit register operand field as ATA-tools/MAME for disassembly-oriented analysis. A future FPU-specific refinement can split out floating-point register storage if the ATA image actually uses it.

## Smoke-test words

`tests/mipsx_smoke.py` generates a few canonical instruction words in big-endian order and checks the field-level decoder used to sanity-check this module.

Known examples include:

```text
60000019    nop
cfc00000    hsc
e8000003    jpc
f8000003    jpcrs
```

## Sources used for the ISA decisions

- Stanford MIPS-X Instruction Set and Programmer's Manual (Paul Chow, 1986).
- `kugg/ATA-tools`, especially `refactor/mipsx_dasm.py`.
- MAME `src/devices/cpu/mipsx/mipsxdasm.cpp` as a secondary decoder reference.
- Ghidra's existing SLEIGH language definitions and compiler-spec documentation for module structure and p-code idioms.

This module is intended as a solid reversing baseline, not a claim that every ATA186 ASIC-specific extension has already been identified.
