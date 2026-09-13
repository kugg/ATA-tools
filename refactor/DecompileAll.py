# Ghidra Jython script to decompile all functions
# @category GhidraTools

import csv
import os
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import TaskMonitor

out_path = os.path.join(os.path.dirname(os.path.abspath(getScriptArgs()[0])), "decompiled.c") if len(getScriptArgs()) > 0 else "/tmp/decompiled.c"

decomp = DecompInterface()
decomp.openProgram(currentProgram)

pw = open(out_path, "w")
count = 0

for func in currentProgram.getFunctionManager().getFunctions(True):
    res = decomp.decompileFunction(func, 60, TaskMonitor.DUMMY)
    if res.decompileCompleted():
        pw.write("// === %s @ %s ===\n" % (func.getName(), func.getEntryPoint()))
        pw.write(res.getDecompiledFunction().getC())
        pw.write("\n")
        count += 1

pw.flush()
pw.close()
decomp.dispose()
print("Decompiled %d functions to %s" % (count, out_path))
