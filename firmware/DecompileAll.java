// Decompile all functions in the current program
// @category GhidraTools

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
        String[] args = getScriptArgs();
        String outPath = (args != null && args.length > 0) ? args[0] : "/tmp/decompiled.c";

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
