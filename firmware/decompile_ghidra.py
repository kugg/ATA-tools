#!/usr/bin/env python3
"""Decompile all functions in a Ghidra program using PyGhidra."""

import sys
import os
import ghidra
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import TaskMonitor

def decompile_all(program_path, base_address, out_path):
    """Decompile all functions in the given program."""
    from ghidra.framework.model import DomainObject
    from ghidra.program.flat.flatapi import FlatProgramAPI
    from ghidra.app.script import GhidraScript

    # Open the program
    program = openProgram(program_path, "MIPS-X:BE:32:ATA186", "default", base_address)
    if program is None:
        print("Failed to open program")
        return False

    try:
        decomp = DecompInterface()
        decomp.openProgram(program)

        with open(out_path, "w") as pw:
            count = 0
            for func in program.getFunctionManager().getFunctions(True):
                res = decomp.decompileFunction(func, 60, TaskMonitor.DUMMY)
                if res.decompileCompleted():
                    pw.write("// === %s @ %s ===\n" % (func.getName(), func.getEntryPoint()))
                    pw.write(res.getDecompiledFunction().getC())
                    pw.write("\n")
                    count += 1

            print("Decompiled %d functions to %s" % (count, out_path))

        decomp.dispose()
        return True
    finally:
        program.release(this)

if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: decompile_ghidra.py <binary> <base_address> <output.c>")
        sys.exit(1)

    binary_path = sys.argv[1]
    base_address = sys.argv[2]
    out_path = sys.argv[3]

    success = decompile_all(binary_path, base_address, out_path)
    sys.exit(0 if success else 1)
