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

1. derive the runtime data/zero/code layout from the checked launch table;
2. expand the checked type-8 payloads through firmware/zup_bank.py;
3. reuse firmware/mipsx_dasm.py to resolve call and tail-transfer targets;
4. create functions only at the entry point and linked-call targets, then
   decompile. Tail targets remain basic blocks unless separately evidenced.

It only reads the pinned package and writes a temporary payload/target
list plus the requested output C file.  It never opens a socket.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from firmware import mipsx_dasm, zup_bank, zup_extract
except ImportError:  # executed with firmware/ on sys.path
    import mipsx_dasm
    import zup_bank
    import zup_extract


GHIDRA_HEADLESS = "/usr/local/Cellar/ghidra/12.1.3/libexec/support/analyzeHeadless"
LANGUAGE = "MIPS-X:BE:32:ATA186"
DEFAULT_REG_BASE = "r23=0x40000"
MAX_NAMING_ENTRIES = 5000
MAX_NAMING_FILE_BYTES = 2 * 1024 * 1024
GHIDRA_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


@dataclass(frozen=True)
class RuntimeRegion:
    """One non-overlapping runtime memory region derived from launch records."""

    name: str
    start: int
    size: int
    kind: str
    data: bytes | None = None

    @property
    def end(self) -> int:
        return self.start + self.size


def build_runtime_layout(bank: bytes, launch_header: int,
                         mode0_offset: int) -> tuple[RuntimeRegion, ...]:
    """Build the selected launch table's initialized, zero, and code regions."""
    table = zup_bank.parse_launch_table(bank, launch_header)
    type9 = [record for record in table.records if record.record_type == 9]
    if len(type9) != 1:
        raise ValueError("launch table must contain one type-9 code destination")
    code_start = type9[0].field1
    regions = []
    mode0 = None
    for record in table.records:
        if record.record_type == 1 and record.field2 < code_start:
            size = record.field3 * 4
            if not size or record.field2 + size > code_start \
                    or not zup_bank.RUNTIME_BANK_BASE <= record.field1 \
                    or record.field1 + size > \
                    zup_bank.RUNTIME_BANK_BASE + len(bank):
                raise ValueError("initialized-copy launch record is invalid")
            source = record.field1 - zup_bank.RUNTIME_BANK_BASE
            regions.append(RuntimeRegion(
                f"data_{record.field2:08x}", record.field2, size, "data",
                bank[source:source + size]))
        if record.record_type == 2:
            size = record.field2 * 4
            if not size:
                raise ValueError("zero-fill launch record is empty")
            regions.append(RuntimeRegion(
                f"zero_{record.field1:08x}", record.field1, size, "zero"))
        if record.record_type != 8:
            continue
        if not zup_bank.RUNTIME_BANK_BASE <= record.field1 \
                < zup_bank.RUNTIME_BANK_BASE + len(bank):
            raise ValueError("type-8 launch address is outside the bank")
        offset = record.field1 - zup_bank.RUNTIME_BANK_BASE
        payload = zup_bank.parse_type8_payload(bank, offset)
        if payload.mode == 0:
            if offset != mode0_offset or mode0 is not None:
                raise ValueError("launch table mode-0 payload is ambiguous")
            mode0 = payload
        else:
            regions.append(RuntimeRegion(
                f"data_{payload.field:08x}", payload.field,
                payload.output_size, "data", payload.data))
    if mode0 is None:
        raise ValueError("requested mode-0 payload is absent from launch table")
    regions.append(RuntimeRegion(
        "packed_main_code", code_start, mode0.output_size, "code", mode0.data))
    regions.sort(key=lambda region: region.start)
    for index, region in enumerate(regions):
        if region.start % 4 or region.size % 4 or region.end > zup_bank.BANK_BYTES:
            raise ValueError("runtime region is unaligned or out of bounds")
        if index and regions[index - 1].end != region.start:
            raise ValueError("runtime launch regions overlap or leave a gap")
    return tuple(regions)


def _bounded_naming_entries(naming: dict, key: str) -> list[dict]:
    entries = naming.get(key, [])
    if not isinstance(entries, list) or len(entries) > MAX_NAMING_ENTRIES \
            or not all(isinstance(entry, dict) for entry in entries):
        raise ValueError(f"naming map {key} entries are invalid")
    return entries


def _metadata_text(value: object, description: str,
                   identifier: bool = False) -> str:
    if not isinstance(value, str) or not value \
            or any(character in value for character in "\t\r\n") \
            or (identifier and GHIDRA_NAME.fullmatch(value) is None):
        raise ValueError(f"naming map {description} is invalid")
    return value


def _hex_address(value: object, description: str,
                 low: int, high: int) -> int:
    if not isinstance(value, str):
        raise ValueError(f"naming map {description} is invalid")
    try:
        address = int(value, 16)
    except ValueError as exc:
        raise ValueError(f"naming map {description} is invalid") from exc
    if address < low or address >= high:
        raise ValueError(f"naming map {description} is outside mapped memory")
    return address


RUNTIME_LAYOUT_SCRIPT = """\
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.mem.Memory;
import ghidra.program.model.mem.MemoryBlock;
import java.io.BufferedReader;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileReader;
import java.io.InputStream;

public class PackedRuntimeLayout extends GhidraScript {
    @Override
    public void run() throws Exception {
        BufferedReader reader = new BufferedReader(
            new FileReader(getScriptArgs()[0]));
        Memory memory = currentProgram.getMemory();
        String line;
        int count = 0;
        while ((line = reader.readLine()) != null) {
            String[] fields = line.split("\\t", -1);
            if (fields.length != 5) throw new Exception("invalid layout row");
            String name = fields[0];
            long start = Long.parseLong(fields[1], 16);
            long size = Long.parseLong(fields[2], 16);
            String kind = fields[3];
            Address address = toAddr(start);
            MemoryBlock block;
            if ("code".equals(kind)) {
                block = memory.getBlock(address);
                if (block == null || !block.getStart().equals(address)
                        || block.getSize() != size) {
                    throw new Exception("imported code block does not match layout");
                }
                block.setName(name);
                block.setPermissions(true, false, true);
            } else if ("data".equals(kind)) {
                File file = new File(fields[4]);
                if (file.length() != size || memory.getBlock(address) != null) {
                    throw new Exception("initialized data block does not match layout");
                }
                InputStream input = new FileInputStream(file);
                try {
                    block = createMemoryBlock(name, address, input, size, false);
                } finally {
                    input.close();
                }
                block.setPermissions(true, true, false);
            } else if ("zero".equals(kind)) {
                if (memory.getBlock(address) != null) {
                    throw new Exception("zero block overlaps existing memory");
                }
                block = memory.createInitializedBlock(
                    name, address, size, (byte) 0, monitor, false);
                block.setPermissions(true, true, false);
            } else {
                throw new Exception("unknown runtime block kind");
            }
            println(String.format(
                "runtime_block=%s start=0x%x end=0x%x kind=%s",
                name, start, start + size, kind));
            count++;
        }
        reader.close();
        println("runtime_blocks=" + count);
    }
}
"""

# Creates a function at each resolved target, then decompiles every function.
GHIDRA_SCRIPT = """\
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.mem.MemoryBlock;
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
        String namesPath = getScriptArgs()[2];
        String outPath = getScriptArgs()[3];
        List<String[]> sites = readSites(sitesPath);
        List<long[]> starts = readPairs(startsPath);

        // 1) linear-sweep executable blocks only.  Data and zero-fill blocks
        //    must remain data rather than becoming plausible MIPS-X instructions.
        for (MemoryBlock block : currentProgram.getMemory().getBlocks()) {
            if (!block.isExecute()) continue;
            long first = block.getStart().getOffset();
            long end = block.getEnd().getOffset();
            for (long a = first; a + 3 <= end; a += 4) {
                Address ad = toAddr(a);
                if (getInstructionAt(ad) == null) disassemble(ad);
            }
        }
        // 2) Link calls before creating functions.  Tail references are delayed:
        //    if present during body construction Ghidra follows the jump and
        //    absorbs the callee into the caller despite the callee also having
        //    independent call-entry evidence.
        int linkedCalls = 0, linkedJumps = 0;
        for (String[] site : sites) {
            if ("jump".equals(site[2])) continue;
            Address src = toAddr(Long.parseLong(site[0], 16));
            Address dst = toAddr(Long.parseLong(site[1], 16));
            Instruction ins = getInstructionAt(src);
            if (ins == null) continue;
            try {
                currentProgram.getReferenceManager().addMemoryReference(
                    src, dst, RefType.COMPUTED_CALL,
                    SourceType.USER_DEFINED, -1);
                linkedCalls++;
            } catch (Exception e) {}
        }
        // 3) create a function at every candidate start so bodies follow calls
        int created = 0, contained = 0, failed = 0;
        for (long[] start : starts) {
            Address d = toAddr(start[0]);
            if (currentProgram.getMemory().getBlock(d) == null) continue;
            if (getFunctionAt(d) != null) continue;
            Function owner = getFunctionContaining(d);
            if (owner != null) {
                println("contained_start=" + d + " owner="
                        + owner.getEntryPoint());
                contained++;
                continue;
            }
            try {
                createFunction(d, String.format("sub_%08x", start[0]));
                created++;
            } catch (Exception e) { failed++; }
        }
        // 4) Now annotate tail transfers without allowing them to influence the
        //    already-established function bodies.
        for (String[] site : sites) {
            if (!"jump".equals(site[2])) continue;
            Address src = toAddr(Long.parseLong(site[0], 16));
            Address dst = toAddr(Long.parseLong(site[1], 16));
            if (getInstructionAt(src) == null) continue;
            try {
                currentProgram.getReferenceManager().addMemoryReference(
                    src, dst, RefType.COMPUTED_JUMP,
                    SourceType.USER_DEFINED, -1);
                linkedJumps++;
            } catch (Exception e) {}
        }
        println("call_sites=" + sites.size() + " linked_calls=" + linkedCalls
                + " linked_jumps=" + linkedJumps + " function_starts="
                + starts.size() + " created=" + created + " contained="
                + contained + " failed=" + failed);

        // 5) apply the deterministic, evidence-backed naming map.  Every name
        //    carries its evidence as a plate comment so the generated C is
        //    reproducible and auditable.
        int named = 0, nameSkipped = 0;
        BufferedReader nb = new BufferedReader(new FileReader(namesPath));
        String nline;
        while ((nline = nb.readLine()) != null) {
            nline = nline.trim();
            if (nline.isEmpty()) continue;
            String[] p = nline.split("\\t");
            if (p.length < 3) continue;
            Address a = toAddr(Long.parseLong(p[1], 16));
            String kind = p[0];
            String nm = p[2];
            String ev = p.length > 3 ? p[3] : "";
            if ("f".equals(kind)) {
                Function f = getFunctionAt(a);
                if (f == null) { nameSkipped++; continue; }
                try {
                    f.setName(nm, SourceType.USER_DEFINED);
                    setPlateComment(a, "evidence: " + ev);
                    named++;
                } catch (Exception e) { nameSkipped++; }
            } else if ("g".equals(kind)) {
                try {
                    createLabel(a, nm, true);
                    setPlateComment(a, "evidence: " + ev);
                    named++;
                } catch (Exception e) { nameSkipped++; }
            } else if ("r".equals(kind)) {
                try {
                    Address target = toAddr(Long.parseLong(nm, 16));
                    currentProgram.getReferenceManager().addMemoryReference(
                        a, target, RefType.DATA, SourceType.USER_DEFINED, -1);
                    setEOLComment(a, "evidence: " + ev);
                    named++;
                } catch (Exception e) { nameSkipped++; }
            }
        }
        nb.close();
        println("names_applied=" + named + " names_skipped=" + nameSkipped);

        PrintWriter pw = new PrintWriter(new FileWriter(outPath));
        DecompInterface decomp = new DecompInterface();
        decomp.openProgram(currentProgram);
        FunctionIterator funcs = currentProgram.getFunctionManager().getFunctions(true);
        int count = 0, decompileFailed = 0;
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
            } else {
                println("decompile_failed=" + func.getEntryPoint());
                decompileFailed++;
            }
        }
        pw.flush();
        pw.close();
        decomp.dispose();
        println("decompiled_functions=" + count
                + " decompile_failed=" + decompileFailed);
    }
}
"""


def resolve_call_sites(payload: bytes, byte_order: str,
                       register_bases: dict[int, int],
                       image_base: int = 0) -> list[tuple[int, int, str]]:
    """Resolved (site, target, kind) triples, reusing mipsx_dasm.

    ``kind`` is "call" (link register != r0) or "jump" (tail transfer).  The
    distinction matters: a tail transfer is a jump, so it must be linked with
    a computed *jump* reference, otherwise Ghidra merges the callee's body
    into the caller and never creates a separate function.
    """
    regions = mipsx_dasm.validate_regions(
        [(0, len(payload) - (len(payload) % 4))], len(payload))
    sites: list[tuple[int, int, str]] = []
    for offset, word in mipsx_dasm.iter_words(payload, regions, byte_order):
        address = image_base + offset
        instruction = mipsx_dasm.decode(word, address, register_bases)
        if instruction.kind == "jump" and instruction.target is not None:
            kind = "call" if instruction.role == "call" else "jump"
            sites.append((address, instruction.target, kind))
    return sites


def resolve_function_starts(payload: bytes, byte_order: str,
                            register_bases: dict[int, int],
                            image_base: int = 0) -> list[int]:
    """Conservative starts: image entry plus in-image linked-call targets.

    Stack adjustments are not starts: real functions can save arguments before
    adjusting r29. Tail transfers are basic-block evidence, not function-entry
    evidence. Descending order lets Ghidra stop a lower function at already-known
    higher callees instead of allowing an early low function to absorb them.
    """
    runtime_regions = [
        (image_base, image_base + len(payload) - (len(payload) % 4))]
    starts = {image_base}
    for _, target, kind in resolve_call_sites(
            payload, byte_order, register_bases, image_base):
        if kind == "call" and mipsx_dasm.address_in_regions(
                target, runtime_regions):
            starts.add(target)
    return sorted(starts, reverse=True)


def resolve_call_targets(payload: bytes, byte_order: str,
                         register_bases: dict[int, int],
                         image_base: int = 0) -> list[int]:
    """Unique resolved local call targets for one payload."""
    return sorted({target for _, target, _ in
                   resolve_call_sites(
                       payload, byte_order, register_bases, image_base)})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", help="pinned .zup package (read-only)")
    parser.add_argument("--type8-payload", required=True,
                        type=lambda v: int(v, 0),
                        help="bank offset of the type-8 payload (SIP main: 0x479bc)")
    parser.add_argument("--reg-base", action="append", default=[],
                        type=mipsx_dasm.parse_register_base,
                        help=f"call anchor, e.g. {DEFAULT_REG_BASE}")
    parser.add_argument("--launch-header", type=lambda v: int(v, 0), default=0,
                        help="bank offset of the selected launch header (default 0)")
    parser.add_argument("--byte-order", choices=("big", "little"), default="big")
    parser.add_argument("--out", default=None,
                        help="output C file (default research/decompiled/named/)")
    parser.add_argument("--project", default=None,
                        help="persistent Ghidra project dir to create/keep "
                             "(for an MCP server); default is a temp project")
    parser.add_argument("--names", default=None,
                        help="evidence-backed naming map (JSON); applied "
                             "deterministically so the C is regenerable")
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args(argv)

    relative_register_bases = dict(args.reg_base) if args.reg_base \
        else {23: 0x40000}

    out_path = args.out or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "research", "decompiled", "named",
        f"packed_{args.type8_payload:x}_readable.c")
    out_path = os.path.abspath(out_path)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    package = zup_bank.read_package(args.package)
    bank = zup_bank.build_bank(package)
    layout = build_runtime_layout(
        bank.data, args.launch_header, args.type8_payload)
    code = next(region for region in layout if region.kind == "code")
    payload = code.data
    register_bases = {
        register: code.start + value
        for register, value in relative_register_bases.items()
    }
    print(f"payload_offset=0x{args.type8_payload:x} bytes={len(payload)} "
          f"words={len(payload)//4} runtime=0x{code.start:x}..0x{code.end:x}")

    targets = resolve_call_targets(
        payload, args.byte_order, register_bases, code.start)
    sites = resolve_call_sites(
        payload, args.byte_order, register_bases, code.start)
    starts = resolve_function_starts(
        payload, args.byte_order, register_bases, code.start)
    print(f"reg_base={{{', '.join(f'r{r}=0x{v:x}' for r, v in register_bases.items())}}} "
          f"call_sites={len(sites)} unique_targets={len(targets)} starts={len(starts)}")

    work = tempfile.mkdtemp(prefix="packed_ghidra_")
    try:
        image_name = "sip_main_code.bin" if args.type8_payload == 0x479BC \
            else f"packed_{args.type8_payload:x}_code.bin"
        payload_path = os.path.join(work, image_name)
        layout_path = os.path.join(work, "layout.tsv")
        sites_path = os.path.join(work, "sites.txt")
        starts_path = os.path.join(work, "starts.txt")
        script_dir = os.path.join(work, "scripts")
        os.makedirs(script_dir, exist_ok=True)
        with open(payload_path, "wb") as handle:
            handle.write(payload)
        with open(layout_path, "w") as handle:
            for index, region in enumerate(layout):
                region_path = ""
                if region.kind == "data":
                    region_path = os.path.join(work, f"region_{index}.bin")
                    with open(region_path, "wb") as region_file:
                        region_file.write(region.data)
                handle.write(
                    f"{region.name}\t{region.start:x}\t{region.size:x}\t"
                    f"{region.kind}\t{region_path}\n")
        with open(sites_path, "w") as handle:
            for source, target, kind in sites:
                handle.write(f"{source:x} {target:x} {kind}\n")
        with open(starts_path, "w") as handle:
            for start in starts:
                handle.write(f"{start:x}\n")
        layout_script_path = os.path.join(script_dir, "PackedRuntimeLayout.java")
        with open(layout_script_path, "w") as handle:
            handle.write(RUNTIME_LAYOUT_SCRIPT)
        script_path = os.path.join(script_dir, "PackedDecompile.java")
        with open(script_path, "w") as handle:
            handle.write(GHIDRA_SCRIPT)

        # Deterministic, evidence-backed naming map (optional).  Format:
        # kind<TAB>address<TAB>name<TAB>evidence  (kind = f function | g global)
        names_path = os.path.join(work, "names.tsv")
        with open(names_path, "w") as handle:
            if args.names:
                naming = json.loads(zup_extract._read_regular_file(
                    args.names, MAX_NAMING_FILE_BYTES,
                    "naming map").decode("utf-8"))
                if not isinstance(naming, dict):
                    raise ValueError("naming map root is invalid")
                if naming.get("function_addresses") != "payload-relative" \
                        or naming.get("global_addresses") != "runtime":
                    raise ValueError("naming map address spaces are unsupported")
                mapped_end = layout[-1].end
                mapped_start = layout[0].start
                for item in _bounded_naming_entries(naming, "functions"):
                    address = _hex_address(
                        item.get("address"), "function address", 0, code.size)
                    handle.write("f\t{:x}\t{}\t{}\n".format(
                        code.start + address,
                        _metadata_text(item.get("name"), "function name", True),
                        _metadata_text(item.get("evidence"), "evidence")))
                for item in _bounded_naming_entries(naming, "globals"):
                    handle.write("g\t{:x}\t{}\t{}\n".format(
                        _hex_address(item.get("address"), "global address",
                                     mapped_start, mapped_end),
                        _metadata_text(item.get("name"), "global name", True),
                        _metadata_text(item.get("evidence"), "evidence")))
                for item in _bounded_naming_entries(naming, "references"):
                    handle.write("r\t{:x}\t{:x}\t{}\n".format(
                        _hex_address(item.get("source"), "reference source",
                                     code.start, code.end),
                        _hex_address(item.get("target"), "reference target",
                                     mapped_start, mapped_end),
                        _metadata_text(item.get("evidence"), "evidence")))

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
            "-loader-baseAddr", hex(code.start),
            "-analysisTimeoutPerFile", str(args.timeout),
            "-postScript", "PackedRuntimeLayout.java", layout_path,
            "-postScript", "PackedDecompile.java",
            sites_path, starts_path, names_path, out_path,
        ] + delete_flag
        print("running Ghidra headless...")
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=args.timeout + 300)
        for stream in (result.stdout, result.stderr):
            for wanted in ("runtime_block=", "runtime_blocks=", "call_sites=",
                           "contained_start=", "decompiled_functions=",
                           "decompile_failed="):
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
