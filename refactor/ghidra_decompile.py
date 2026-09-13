#!/usr/bin/env python3
"""Decompile a raw binary using Ghidra headless with MIPS-X processor."""

import argparse
import os
import subprocess
import sys
import tempfile
import shutil

GHIDRA_HEADLESS = "/usr/local/Cellar/ghidra/12.1.3/libexec/support/analyzeHeadless"
LANGUAGE = "MIPS-X:BE:32:ATA186"
DEFAULT_BASE_ADDRESS = "0xcf80000"

DECOMPILE_SCRIPT = """\
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import java.io.FileWriter;
import java.io.PrintWriter;

public class DecompileAll extends GhidraScript {
    @Override
    public void run() throws Exception {
        String outPath = getScriptArgs()[0];
        PrintWriter pw = new PrintWriter(new FileWriter(outPath));
        DecompInterface decomp = new DecompInterface();
        decomp.openProgram(currentProgram);

        FunctionIterator funcs = currentProgram.getFunctionManager().getFunctions(true);
        int count = 0;
        while (funcs.hasNext() && !monitor.isCancelled()) {
            Function func = funcs.next();
            DecompileResults res = decomp.decompileFunction(func, 60, monitor);
            if (res.decompileCompleted()) {
                pw.println("// === " + func.getName() + " @ " + func.getEntryPoint() + " ===");
                pw.println(res.getDecompiledFunction().getC());
                pw.println();
                count++;
            }
        }
        pw.flush();
        pw.close();
        decomp.dispose();
        println("Decompiled " + count + " functions to " + outPath);
    }
}
"""


def main():
    parser = argparse.ArgumentParser(description="Decompile binary via Ghidra headless")
    parser.add_argument("binary", help="Raw binary to decompile")
    parser.add_argument("--base", default=DEFAULT_BASE_ADDRESS,
                        help="Base address (default: 0xcf80000)")
    parser.add_argument("--out", default="decompiled.c",
                        help="Output C file (default: decompiled.c)")
    parser.add_argument("--timeout", type=int, default=600,
                        help="Timeout in seconds (default: 600)")
    args = parser.parse_args()

    if not os.path.isfile(args.binary):
        print(f"error: binary not found: {args.binary}", file=sys.stderr)
        return 1

    project_dir = tempfile.mkdtemp(prefix="ghidra_project_")
    script_dir = tempfile.mkdtemp(prefix="ghidra_scripts_")
    out_path = os.path.abspath(args.out)

    try:
        script_path = os.path.join(script_dir, "DecompileAll.java")
        with open(script_path, "w") as f:
            f.write(DECOMPILE_SCRIPT)

        project_name = "ata_analysis"
        bin_name = os.path.basename(args.binary)

        cmd = [
            GHIDRA_HEADLESS,
            project_dir,
            project_name,
            "-import", os.path.abspath(args.binary),
            "-processor", LANGUAGE,
            "-cspec", "default",
            "-loader", "BinaryLoader",
            "-loader-baseAddr", args.base,
            "-analysisTimeoutPerFile", str(args.timeout),
            "-postScript", script_path, out_path,
            "-deleteProject",
        ]

        print(f"Running Ghidra headless...")
        print(f"  Binary: {args.binary}")
        print(f"  Language: {LANGUAGE}")
        print(f"  Base: {args.base}")
        print(f"  Output: {out_path}")

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=args.timeout + 120)

        if result.returncode != 0:
            print("Ghidra stderr:", file=sys.stderr)
            print(result.stderr[-2000:], file=sys.stderr)
            return 1

        if os.path.isfile(out_path):
            size = os.path.getsize(out_path)
            print(f"Success: {out_path} ({size} bytes)")
            return 0
        else:
            print("error: output file not created", file=sys.stderr)
            print("Ghidra stdout:", file=sys.stderr)
            print(result.stdout[-2000:], file=sys.stderr)
            return 1

    except subprocess.TimeoutExpired:
        print("error: Ghidra timed out", file=sys.stderr)
        return 1
    finally:
        shutil.rmtree(project_dir, ignore_errors=True)
        shutil.rmtree(script_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
