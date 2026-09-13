// Seed disassembly at known MIPS-X code regions in the SIP bank.
// @category GhidraTools

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.util.exception.CancelledException;

public class SeedDisassembly extends GhidraScript {

    // Known code regions from MAME disassembly analysis
    // Format: (start, length) in bytes, relative to image base
    private static final long[][] CODE_REGIONS = {
        {0x0a00, 0x1000},   // Main code block starting at cf80a00
        {0x1a00, 0x800},    // Additional code region
        {0x2600, 0x1000},   // Code around cf82600
        {0x3600, 0x1000},   // Code around cf83600
        {0x4a00, 0x1000},   // Code around cf84a00
        {0x5a00, 0x1000},   // Code around cf85a00
        {0x6a00, 0x1000},   // Code around cf86a00
        {0x7a00, 0x1000},   // Code around cf87a00
        {0x8a00, 0x1000},   // Code around cf88a00
        {0x9a00, 0x1000},   // Code around cf89a00
        {0xaa00, 0x1000},   // Code around cf8aa00
        {0xba00, 0x1000},   // Code around cf8ba00
        {0xca00, 0x1000},   // Code around cf8ca00
        {0xda00, 0x1000},   // Code around cf8da00
        {0xea00, 0x1000},   // Code around cf8ea00
        {0xfa00, 0x1000},   // Code around cf8fa00
        {0x10a00, 0x1000},  // Code around cf90a00
        {0x11a00, 0x1000},  // Code around cf91a00
        {0x12a00, 0x1000},  // Code around cf92a00
        {0x13a00, 0x1000},  // Code around cf93a00
        {0x14a00, 0x1000},  // Code around cf94a00
        {0x15a00, 0x1000},  // Code around cf95a00
        {0x16a00, 0x1000},  // Code around cf96a00
        {0x17a00, 0x1000},  // Code around cf97a00
        {0x18a00, 0x1000},  // Code around cf88a00
        {0x19a00, 0x1000},  // Code around cf99a00
        {0x1aa00, 0x1000},  // Code around cf9aa00
        {0x1ba00, 0x1000},  // Code around cf9ba00
        {0x1ca00, 0x1000},  // Code around cf9ca00
        {0x1da00, 0x1000},  // Code around cf9da00
        {0x1ea00, 0x1000},  // Code around cf9ea00
        {0x1fa00, 0x1000},  // Code around cf9fa00
        {0x20a00, 0x1000},  // Code around cfa0a00
        {0x21a00, 0x1000},  // Code around cfa1a00
        {0x22a00, 0x1000},  // Code around cfa2a00
        {0x23a00, 0x1000},  // Code around cfa3a00
        {0x24a00, 0x1000},  // Code around cfa4a00
        {0x25a00, 0x1000},  // Code around cfa5a00
        {0x26a00, 0x1000},  // Code around cfa6a00
        {0x27a00, 0x1000},  // Code around cfa7a00
        {0x28a00, 0x1000},  // Code around cfa8a00
        {0x29a00, 0x1000},  // Code around cfa9a00
        {0x2aa00, 0x1000},  // Code around cfaaa00
        {0x2ba00, 0x1000},  // Code around cfaba00
        {0x2ca00, 0x1000},  // Code around cfaca00
        {0x2da00, 0x1000},  // Code around cfada00
        {0x2ea00, 0x1000},  // Code around cfaea00
        {0x2fa00, 0x1000},  // Code around cfafa00
        {0x30a00, 0x1000},  // Code around cfb0a00
        {0x31a00, 0x1000},  // Code around cfb1a00
        {0x32a00, 0x1000},  // Code around cfb2a00
        {0x33a00, 0x1000},  // Code around cfb3a00
        {0x34a00, 0x1000},  // Code around cfb4a00
        {0x35a00, 0x1000},  // Code around cfb5a00
        {0x36a00, 0x1000},  // Code around cfb6a00
        {0x37a00, 0x1000},  // Code around cfb7a00
        {0x38a00, 0x1000},  // Code around cfb8a00
        {0x39a00, 0x1000},  // Code around cfb9a00
        {0x3aa00, 0x1000},  // Code around cfbaa00
        {0x3ba00, 0x1000},  // Code around cfbba00
        {0x3ca00, 0x1000},  // Code around cfcca00
        {0x3da00, 0x1000},  // Code around cfcda00
        {0x3ea00, 0x1000},  // Code around cfcea00
        {0x3fa00, 0x1000},  // Code around cfcfa00
        {0x40a00, 0x1000},  // Code around cfd0a00
        {0x41a00, 0x1000},  // Code around cfd1a00
        {0x42a00, 0x1000},  // Code around cfd2a00
        {0x43a00, 0x1000},  // Code around cfd3a00
        {0x44a00, 0x1000},  // Code around cfd4a00
        {0x45a00, 0x1000},  // Code around cfd5a00
        {0x46a00, 0x1000},  // Code around cfd6a00
        {0x47a00, 0x1000},  // Code around cfd7a00
        {0x48a00, 0x1000},  // Code around cfd8a00
        {0x49a00, 0x1000},  // Code around cfd9a00
        {0x4aa00, 0x1000},  // Code around cfdaa00
        {0x4ba00, 0x1000},  // Code around cfdba00
        {0x4ca00, 0x1000},  // Code around cfdca00
        {0x4da00, 0x1000},  // Code around cfdda00
        {0x4ea00, 0x1000},  // Code around cfdea00
        {0x4fa00, 0x1000},  // Code around cfdfa00
        {0x50a00, 0x1000},  // Code around cfe0a00
        {0x51a00, 0x1000},  // Code around cfe1a00
        {0x52a00, 0x1000},  // Code around cfe2a00
        {0x53a00, 0x1000},  // Code around cfe3a00
        {0x54a00, 0x1000},  // Code around cfe4a00
        {0x55a00, 0x1000},  // Code around cfe5a00
        {0x56a00, 0x1000},  // Code around cfe6a00
        {0x57a00, 0x1000},  // Code around cfe7a00
        {0x58a00, 0x1000},  // Code around cfe8a00
        {0x59a00, 0x1000},  // Code around cfe9a00
        {0x5aa00, 0x1000},  // Code around cfeaa00
        {0x5ba00, 0x1000},  // Code around cfeba00
        {0x5ca00, 0x1000},  // Code around cfeca00
        {0x5da00, 0x1000},  // Code around cfeda00
        {0x5ea00, 0x1000},  // Code around cfeea00
        {0x5fa00, 0x1000},  // Code around cfefa00
        {0x60a00, 0x1000},  // Code around cff0a00
        {0x61a00, 0x1000},  // Code around cff1a00
        {0x62a00, 0x1000},  // Code around cff2a00
        {0x63a00, 0x1000},  // Code around cff3a00
        {0x64a00, 0x1000},  // Code around cff4a00
        {0x65a00, 0x1000},  // Code around cff5a00
        {0x66a00, 0x1000},  // Code around cff6a00
        {0x67a00, 0x1000},  // Code around cff7a00
        {0x68a00, 0x1000},  // Code around cff8a00
        {0x69a00, 0x1000},  // Code around cff9a00
        {0x6aa00, 0x1000},  // Code around cffaa00
        {0x6ba00, 0x1000},  // Code around cffba00
        {0x6ca00, 0x1000},  // Code around cffca00
        {0x6da00, 0x1000},  // Code around cffda00
        {0x6ea00, 0x1000},  // Code around cffea00
        {0x6fa00, 0x1000},  // Code around cfffa00
    };

    @Override
    public void run() throws Exception {
        int disassembled = 0;
        int failed = 0;

        for (long[] region : CODE_REGIONS) {
            long offset = region[0];
            long length = region[1];

            Address startAddr = currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(offset);
            Address endAddr = startAddr.add(length);

            // Check if this address is in a valid memory block
            if (currentProgram.getMemory().contains(startAddr)) {
                DisassembleCommand cmd = new DisassembleCommand(startAddr, null, true);
                cmd.applyTo(currentProgram);
                disassembled++;
            } else {
                failed++;
            }
        }

        // Also try to find functions by looking for known patterns
        FunctionManager funcMgr = currentProgram.getFunctionManager();
        int funcCount = funcMgr.getFunctionCount();

        println("Disassembly seeded at " + disassembled + " regions (" + failed + " skipped)");
        println("Functions found: " + funcCount);
    }
}
