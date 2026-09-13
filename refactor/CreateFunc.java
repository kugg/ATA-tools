// Minimal script to create a function and disassemble from a known address
// @category GhidraTools

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionManager;

public class CreateFunc extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args == null || args.length < 1) {
            println("Usage: CreateFunc.java <hex_address>");
            return;
        }

        String addrStr = args[0];
        Address addr = currentProgram.getAddressFactory().getAddress(addrStr);
        if (addr == null) {
            println("Invalid address: " + addrStr);
            return;
        }

        // Try to disassemble from this address
        DisassembleCommand cmd = new DisassembleCommand(addr, null, true);
        boolean ok = cmd.applyTo(currentProgram);
        println("Disassemble " + addr + ": " + (ok ? "OK" : "FAILED"));

        // Check if functions were created
        FunctionManager funcMgr = currentProgram.getFunctionManager();
        int count = funcMgr.getFunctionCount();
        println("Total functions now: " + count);

        // List first 10 functions
        int shown = 0;
        for (Function f : funcMgr.getFunctions(true)) {
            println("  " + f.getEntryPoint() + " " + f.getName());
            if (++shown >= 10) break;
        }
    }
}
