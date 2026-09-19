#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""Decompile a packed type-8 program with its indirect calls pre-resolved.

The SIP application is not the resident bank that
``sip_bank_named_readable.c`` covers; it is the packed main payload
(type-8 at bank ``0x479bc``), a distinct program loaded at ``0xc74c``.
Its indirect calls are of the form ``jspci rNN, disp`` with a known
byte-coordinate anchor (``r23 = 0x40000`` for mode-0 programs).  Ghidra
cannot see that anchor, so its decompiler prints unresolved
``(*(code *)(...))()`` calls.

This driver closes the gap without a new resolver:

1. expand the checked type-8 payload through refactor/zup_bank.py;
2. reuse refactor/mipsx_dasm.py to resolve the call targets;
3. create a Ghidra function at every resolved target and decompile.

It only reads the pinned package and writes a temporary payload/target
list plus the requested output C file.  It never opens a socket.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from refactor import mipsx_dasm, zup_bank
except ImportError:  # executed with refactor/ on sys.path
    import mipsx_dasm
    import zup_bank


GHIDRA_HEADLESS = "/usr/local/Cellar/ghidra/12.1.3/libexec/support/analyzeHeadless"
LANGUAGE = "MIPS-X:BE:32:ATA186"
DEFAULT_REG_BASE = "r23=0x40000"

# Creates a function at each resolved target, then decompiles every function.
GHIDRA_SCRIPT = """\
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.symbol.RefType;
import ghidra.program.model.symbol.SourceType;
import java.io.BufferedReader;
import java.io.FileReader;
import java.io.FileWriter;
import java.io.PrintWriter;
import java.util.ArrayList;
import java.util.List;

public class PackedDecompile extends GhidraScript {
    private List<long[]> readPairs(String path) throws Exception {
        List<long[]> out = new ArrayList<>();
        BufferedReader br = new BufferedReader(new FileReader(path));
        String line;
        while ((line = br.readLine()) != null) {
            line = line.trim();
            if (line.isEmpty()) continue;
            String[] parts = line.split("\\\\s+");
            if (parts.length < 1) continue;
            long a = Long.parseLong(parts[0], 16);
            long b = parts.length > 1 ? Long.parseLong(parts[1], 16) : 0;
            out.add(new long[] { a, b });
        }
        br.close();
        return out;
    }

    private List<String[]> readSites(String path) throws Exception {
        List<String[]> out = new ArrayList<>();
        BufferedReader br = new BufferedReader(new FileReader(path));
        String line;
        while ((line = br.readLine()) != null) {
            line = line.trim();
            if (line.isEmpty()) continue;
            String[] parts = line.split("\\\\s+");
            if (parts.length < 2) continue;
            String kind = parts.length > 2 ? parts[2] : "call";
            out.add(new String[] { parts[0], parts[1], kind });
        }
        br.close();
        return out;
    }

    @Override
    public void run() throws Exception {
        String sitesPath = getScriptArgs()[0];
        String startsPath = getScriptArgs()[1];
        String outPath = getScriptArgs()[2];
        List<String[]> sites = readSites(sitesPath);
        List<long[]> starts = readPairs(startsPath);

        // 1) linear-sweep so every word is an instruction before flows are built
        long limit = currentProgram.getMaxAddress().getOffset();
        for (long a = 0; a + 4 <= limit; a += 4) {
            Address ad = toAddr(a);
            if (getInstructionAt(ad) == null) disassemble(ad);
        }
        // 2) link each jspci site to its resolved target.  A tail transfer is a
        //    computed *jump*, so the callee's body is not merged into the caller.
        int linked = 0;
        for (String[] site : sites) {
            Address src = toAddr(Long.parseLong(site[0], 16));
            Address dst = toAddr(Long.parseLong(site[1], 16));
            Instruction ins = getInstructionAt(src);
            if (ins == null) continue;
            RefType type = "jump".equals(site[2])
                ? RefType.COMPUTED_JUMP : RefType.COMPUTED_CALL;
            try {
                currentProgram.getReferenceManager().addMemoryReference(
                    src, dst, type, SourceType.USER_DEFINED, -1);
                linked++;
            } catch (Exception e) {}
        }
        // 3) create a function at every candidate start so bodies follow calls
        int created = 0;
        for (long[] start : starts) {
            Address d = toAddr(start[0]);
            if (currentProgram.getMemory().getBlock(d) == null) continue;
            if (getFunctionAt(d) != null) continue;
            try {
                createFunction(d, String.format("sub_%08x", start[0]));
                created++;
            } catch (Exception e) {}
        }
        println("call_sites=" + sites.size() + " linked=" + linked
                + " function_starts=" + starts.size() + " created=" + created);

        PrintWriter pw = new PrintWriter(new FileWriter(outPath));
        DecompInterface decomp = new DecompInterface();
        decomp.openProgram(currentProgram);
        FunctionIterator funcs = currentProgram.getFunctionManager().getFunctions(true);
        int count = 0;
        while (funcs.hasNext() && !monitor.isCancelled()) {
            Function func = funcs.next();
            DecompileResults res = decomp.decompileFunction(func, 60, monitor);
            if (res.decompileCompleted()) {
                // A scalar return in r2 shows as undefined4; type it as int.
                ghidra.program.model.data.DataType rt = func.getReturnType();
                if (rt != null && "undefined4".equals(rt.getName())) {
                    try {
                        func.setReturnType(
                            ghidra.program.model.data.IntegerDataType.dataType,
                            SourceType.USER_DEFINED);
                        res = decomp.decompileFunction(func, 60, monitor);
                    } catch (Exception e) {}
                }
                pw.println("// === " + func.getName() + " @ " + func.getEntryPoint() + " ===");
                pw.println(res.getDecompiledFunction().getC());
                pw.println();
                count++;
            }
        }
        pw.flush();
        pw.close();
        decomp.dispose();
        println("decompiled_functions=" + count);
    }
}
"""


def resolve_call_sites(payload: bytes, byte_order: str,
                       register_bases: dict[int, int]) -> list[tuple[int, int, str]]:
    """Resolved (site, target, kind) triples, reusing mipsx_dasm.

    ``kind`` is "call" (link register != r0) or "jump" (tail transfer).  The
    distinction matters: a tail transfer is a jump, so it must be linked with
    a computed *jump* reference, otherwise Ghidra merges the callee's body
    into the caller and never creates a separate function.
    """
    regions = mipsx_dasm.validate_regions(
        [(0, len(payload) - (len(payload) % 4))], len(payload))
    sites: list[tuple[int, int, str]] = []
    for address, word in mipsx_dasm.iter_words(payload, regions, byte_order):
        instruction = mipsx_dasm.decode(word, address, register_bases)
        if instruction.kind == "jump" and instruction.target is not None:
            kind = "call" if instruction.role == "call" else "jump"
            sites.append((address, instruction.target, kind))
    return sites


def resolve_function_starts(payload: bytes, byte_order: str,
                            register_bases: dict[int, int]) -> list[int]:
    """Candidate function starts: jspci targets (call or tail) plus r29 prologues.

    Reuses mipsx_dasm's prologue test and decoder; not a second ISA model.
    """
    regions = mipsx_dasm.validate_regions(
        [(0, len(payload) - (len(payload) % 4))], len(payload))
    starts: set[int] = set()
    for address, word in mipsx_dasm.iter_words(payload, regions, byte_order):
        if mipsx_dasm.is_stack_prologue(word):
            starts.add(address)
        instruction = mipsx_dasm.decode(word, address, register_bases)
        # A resolved jspci target is a function entry whether it is a call
        # (link != r0) or a tail transfer (link r0); include both.
        if instruction.kind == "jump" and instruction.target is not None \
                and mipsx_dasm.address_in_regions(instruction.target, regions):
            starts.add(instruction.target)
    return sorted(starts)


def resolve_call_targets(payload: bytes, byte_order: str,
                         register_bases: dict[int, int]) -> list[int]:
    """Unique resolved local call targets for one payload."""
    return sorted({target for _, target, _ in
                   resolve_call_sites(payload, byte_order, register_bases)})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", help="pinned .zup package (read-only)")
    parser.add_argument("--type8-payload", required=True,
                        type=lambda v: int(v, 0),
                        help="bank offset of the type-8 payload (SIP main: 0x479bc)")
    parser.add_argument("--reg-base", action="append", default=[],
                        type=mipsx_dasm.parse_register_base,
                        help=f"call anchor, e.g. {DEFAULT_REG_BASE}")
    parser.add_argument("--base", type=lambda v: int(v, 0), default=0,
                        help="Ghidra image base for the payload (default 0)")
    parser.add_argument("--byte-order", choices=("big", "little"), default="big")
    parser.add_argument("--out", default=None,
                        help="output C file (default research/decompiled/named/)")
    parser.add_argument("--project", default=None,
                        help="persistent Ghidra project dir to create/keep "
                             "(for an MCP server); default is a temp project")
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args(argv)

    register_bases = dict(args.reg_base) if args.reg_base \
        else {23: 0x40000}

    out_path = args.out or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "research", "decompiled", "named",
        f"packed_{args.type8_payload:x}_readable.c")
    out_path = os.path.abspath(out_path)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    package = zup_bank.read_package(args.package)
    bank = zup_bank.build_bank(package)
    payload = zup_bank.parse_type8_payload(bank.data, args.type8_payload).data
    print(f"payload_offset=0x{args.type8_payload:x} bytes={len(payload)} "
          f"words={len(payload)//4}")

    targets = resolve_call_targets(payload, args.byte_order, register_bases)
    sites = resolve_call_sites(payload, args.byte_order, register_bases)
    starts = resolve_function_starts(payload, args.byte_order, register_bases)
    print(f"reg_base={{{', '.join(f'r{r}=0x{v:x}' for r, v in register_bases.items())}}} "
          f"call_sites={len(sites)} unique_targets={len(targets)} starts={len(starts)}")

    work = tempfile.mkdtemp(prefix="packed_ghidra_")
    try:
        payload_path = os.path.join(work, "payload.bin")
        sites_path = os.path.join(work, "sites.txt")
        starts_path = os.path.join(work, "starts.txt")
        script_dir = os.path.join(work, "scripts")
        os.makedirs(script_dir, exist_ok=True)
        with open(payload_path, "wb") as handle:
            handle.write(payload)
        with open(sites_path, "w") as handle:
            for source, target, kind in sites:
                handle.write(f"{args.base + source:x} {args.base + target:x} {kind}\n")
        with open(starts_path, "w") as handle:
            for start in starts:
                handle.write(f"{args.base + start:x}\n")
        script_path = os.path.join(script_dir, "PackedDecompile.java")
        with open(script_path, "w") as handle:
            handle.write(GHIDRA_SCRIPT)

        project_dir = os.path.abspath(args.project) if args.project \
            else os.path.join(work, "project")
        os.makedirs(project_dir, exist_ok=True)
        delete_flag = [] if args.project else ["-deleteProject"]
        command = [
            GHIDRA_HEADLESS, project_dir, "packed",
            "-scriptPath", script_dir,
            "-import", payload_path,
            "-processor", LANGUAGE,
            "-cspec", "default",
            "-loader", "BinaryLoader",
            "-loader-baseAddr", hex(args.base),
            "-analysisTimeoutPerFile", str(args.timeout),
            "-postScript", "PackedDecompile.java", sites_path, starts_path, out_path,
        ] + delete_flag
        print("running Ghidra headless...")
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=args.timeout + 300)
        for stream in (result.stdout, result.stderr):
            for wanted in ("call_sites=", "decompiled_functions="):
                for line in stream.splitlines():
                    if wanted in line:
                        print(line.strip())
        if result.returncode != 0:
            print("Ghidra failed:", file=sys.stderr)
            print(result.stdout[-2000:], file=sys.stderr)
            print(result.stderr[-2000:], file=sys.stderr)
            return 1
        if not os.path.isfile(out_path):
            print("error: output C file not created", file=sys.stderr)
            print("--- Ghidra stdout (tail) ---", file=sys.stderr)
            print(result.stdout[-3000:], file=sys.stderr)
            print("--- Ghidra stderr (tail) ---", file=sys.stderr)
            print(result.stderr[-3000:], file=sys.stderr)
            return 1
        print(f"output={out_path} bytes={os.path.getsize(out_path)}")
        return 0
    except subprocess.TimeoutExpired:
        print("error: Ghidra timed out", file=sys.stderr)
        return 1
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
