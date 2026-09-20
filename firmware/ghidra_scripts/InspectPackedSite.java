// SPDX-License-Identifier: BSD-3-Clause
// Print bounded function and instruction context for one packed-main site.

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceIterator;
import java.util.HashSet;

public class InspectPackedSite extends GhidraScript {
    @Override
    public void run() throws Exception {
        if (getScriptArgs().length != 1) {
            throw new Exception("usage: InspectPackedSite.java ADDRESS");
        }
        long offset = Long.decode(getScriptArgs()[0]);
        if (offset < 0 || offset > 0xffffffffL) {
            throw new Exception("address is outside the 32-bit program space");
        }
        Address site = toAddr(offset);
        Function function = getFunctionContaining(site);
        println("site=" + site + " function=" + (function == null
                ? "<none>" : function.getName() + "@"
                    + function.getEntryPoint()));
        if (function == null) return;

        HashSet<Long> callers = new HashSet<>();
        ReferenceIterator references = currentProgram.getReferenceManager()
            .getReferencesTo(function.getEntryPoint());
        while (references.hasNext()) {
            Reference reference = references.next();
            if (reference.getReferenceType().isCall()) {
                callers.add(reference.getFromAddress().getOffset());
            }
        }
        println("callers=" + callers.size() + " body="
                + function.getBody().getMinAddress() + ".."
                + function.getBody().getMaxAddress());
        long first = Math.max(function.getBody().getMinAddress().getOffset(),
                              offset - 0x40L);
        long last = Math.min(function.getBody().getMaxAddress().getOffset(),
                             offset + 0x40L);
        for (long address = first; address <= last; address += 4) {
            Instruction instruction = getInstructionAt(toAddr(address));
            if (instruction != null) {
                println(instruction.getAddress() + " " + instruction);
            }
        }

        DecompInterface decompiler = new DecompInterface();
        decompiler.openProgram(currentProgram);
        DecompileResults result = decompiler.decompileFunction(
            function, 120, monitor);
        if (result.decompileCompleted()) {
            String c = result.getDecompiledFunction().getC();
            println("decompile_begin");
            println(c.length() > 12000 ? c.substring(0, 12000) : c);
            println("decompile_end");
        } else {
            println("decompile_error=" + result.getErrorMessage());
        }
        decompiler.dispose();
    }
}
