// Seed disassembly and create functions at known MIPS-X entry points
// @category GhidraTools

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.program.model.listing.*;
import ghidra.util.task.TaskMonitor;

public class SeedDisasm extends GhidraScript {
    @Override
    public void run() throws Exception {
        // Try disassembly at first code address
        Address start = toAddr(0xcf80a00);
        println("Trying disassembly at " + start);

        DisassembleCommand cmd = new DisassembleCommand(start, null, true);
        boolean ok = cmd.applyTo(currentProgram, TaskMonitor.DUMMY);
        println("Disassemble result: " + ok);

        FunctionManager fm = currentProgram.getFunctionManager();
        int count = fm.getFunctionCount();
        println("Functions after disassemble: " + count);

        if (count > 0) {
            int shown = 0;
            for (Function f : fm.getFunctions(true)) {
                println("  " + f.getEntryPoint() + " " + f.getName());
                if (++shown >= 10) break;
            }
        }

        // Try creating a function explicitly
        println("Creating function at " + start);
        Listing listing = currentProgram.getListing();
        if (listing.getCodeUnitAt(start) != null) {
            println("  Code unit exists at " + start + ": " + listing.getCodeUnitAt(start));
        } else {
            println("  No code unit at " + start);
        }
    }
}
