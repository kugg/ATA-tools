// SPDX-License-Identifier: BSD-3-Clause
// Report one packed-main decompiler result without changing the program.

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;

public class InspectPackedFunction extends GhidraScript {
    @Override
    public void run() throws Exception {
        if (getScriptArgs().length != 1) {
            throw new Exception("usage: InspectPackedFunction.java ADDRESS");
        }
        long offset = Long.decode(getScriptArgs()[0]);
        if (offset < 0 || offset > 0xffffffffL) {
            throw new Exception("address is outside the 32-bit program space");
        }
        Function function = getFunctionAt(toAddr(offset));
        if (function == null) throw new Exception("function is absent");
        DecompInterface decompiler = new DecompInterface();
        decompiler.openProgram(currentProgram);
        DecompileResults result = decompiler.decompileFunction(
            function, 120, monitor);
        println("function=" + function.getEntryPoint()
                + " completed=" + result.decompileCompleted()
                + " error=" + result.getErrorMessage());
        decompiler.dispose();
    }
}
