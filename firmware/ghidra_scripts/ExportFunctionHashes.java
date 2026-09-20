// SPDX-License-Identifier: BSD-3-Clause
// Export address-independent SHA-256 fingerprints for non-overlapping functions.

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressRange;
import ghidra.program.model.address.AddressRangeIterator;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import java.io.PrintWriter;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;

public class ExportFunctionHashes extends GhidraScript {
    private String hex(byte[] bytes) {
        StringBuilder output = new StringBuilder();
        for (byte value : bytes) output.append(String.format("%02x", value));
        return output.toString();
    }

    @Override
    public void run() throws Exception {
        if (getScriptArgs().length != 1) {
            throw new Exception("usage: ExportFunctionHashes.java OUTPUT");
        }
        Path outputPath = Paths.get(getScriptArgs()[0]);
        PrintWriter output = new PrintWriter(Files.newBufferedWriter(
            outputPath, StandardOpenOption.CREATE_NEW,
            StandardOpenOption.WRITE));
        FunctionIterator functions = currentProgram.getFunctionManager()
            .getFunctions(true);
        int count = 0;
        while (functions.hasNext()) {
            Function function = functions.next();
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            long size = 0;
            AddressRangeIterator ranges = function.getBody().getAddressRanges();
            while (ranges.hasNext()) {
                AddressRange range = ranges.next();
                Address address = range.getMinAddress();
                long remaining = range.getLength();
                while (remaining > 0) {
                    int amount = (int) Math.min(remaining, 4096L);
                    byte[] bytes = getBytes(address, amount);
                    digest.update(bytes);
                    address = address.add(amount);
                    remaining -= amount;
                    size += amount;
                }
            }
            output.println(String.format("%x\t%x\t%s",
                function.getEntryPoint().getOffset(), size,
                hex(digest.digest())));
            count++;
        }
        output.close();
        println("function_hashes=" + count + " output=" + getScriptArgs()[0]);
    }
}
