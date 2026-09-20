// SPDX-License-Identifier: BSD-3-Clause
// Validate the SIP packed-main runtime layout after headless import.
// Read-only: reports derived addresses and fails on stale/base-zero projects.

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSet;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceIterator;
import java.nio.charset.StandardCharsets;

public class ValidatePackedRuntime extends GhidraScript {
    private void require(boolean condition, String message) throws Exception {
        if (!condition) throw new Exception(message);
    }

    @Override
    public void run() throws Exception {
        long[][] expected = {
            { 0x100L, 0x26d0L, 0, 1 },
            { 0x26d0L, 0x2fbcL, 0, 1 },
            { 0x2fbcL, 0x7b84L, 0, 1 },
            { 0x7b84L, 0xc74cL, 0, 1 },
            { 0xc74cL, 0x686a0L, 1, 0 },
        };
        for (long[] item : expected) {
            MemoryBlock block = currentProgram.getMemory().getBlock(toAddr(item[0]));
            require(block != null, "missing runtime block");
            require(block.getStart().getOffset() == item[0]
                    && block.getEnd().getOffset() + 1 == item[1],
                    "runtime block boundary mismatch");
            require(block.isExecute() == (item[2] != 0)
                    && block.isWrite() == (item[3] != 0),
                    "runtime block permission mismatch");
        }

        byte[] expectedString = "ATA Config Update OK".getBytes(
            StandardCharsets.US_ASCII);
        byte[] actualString = getBytes(toAddr(0x534cL), expectedString.length);
        require(java.util.Arrays.equals(expectedString, actualString),
                "runtime string mismatch at 0x534c");

        Instruction instruction = getInstructionAt(toAddr(0x33c54L));
        byte[] instructionBytes = getBytes(toAddr(0x33c54L), 4);
        println(String.format("instruction_33c54=%02x%02x%02x%02x text=%s",
            instructionBytes[0] & 0xff, instructionBytes[1] & 0xff,
            instructionBytes[2] & 0xff, instructionBytes[3] & 0xff,
            instruction == null ? "<none>" : instruction.toString()));
        require(java.util.Arrays.equals(instructionBytes,
                    new byte[] {(byte) 0xe0, 0x0c, 0x53, 0x4c}),
                "runtime string materialization missing at 0x33c54");

        Address loggerAddress = toAddr(0x1c9b4L);
        Function logger = getFunctionAt(loggerAddress);
        require(logger != null && "maybe_log_event".equals(logger.getName()),
                "relocated logger function is missing");
        int calls = 0;
        ReferenceIterator references = currentProgram.getReferenceManager()
            .getReferencesTo(loggerAddress);
        while (references.hasNext()) {
            Reference reference = references.next();
            if (reference.getReferenceType().isCall()) calls++;
        }
        require(calls == 108, "unexpected unique logger call count: " + calls);
        Function emitter = getFunctionAt(toAddr(0x1cc0cL));
        Function handler = getFunctionAt(toAddr(0x33940L));
        require(emitter != null
                && "maybe_syslog_emit_class".equals(emitter.getName()),
                "syslog emitter name is missing");
        require(handler != null
                && "maybe_http_config_post_handler".equals(handler.getName()),
                "HTTP configuration handler name is missing");
        boolean messageReference = false;
        for (Reference reference : getReferencesFrom(toAddr(0x33c54L))) {
            if (reference.getToAddress().equals(toAddr(0x534cL))) {
                messageReference = true;
            }
        }
        require(messageReference, "configuration message reference is missing");
        Function materializationFunction = getFunctionAt(toAddr(0x33c54L));
        println("function_33c54=" + (materializationFunction == null
                ? "<none>" : materializationFunction.getName()));
        AddressSet bodies = new AddressSet();
        FunctionIterator functions = currentProgram.getFunctionManager()
            .getFunctions(true);
        int functionCount = 0;
        while (functions.hasNext()) {
            Function function = functions.next();
            require(!bodies.intersects(function.getBody()),
                    "overlapping function body at " + function.getEntryPoint());
            bodies.add(function.getBody());
            functionCount++;
        }
        require(functionCount == 808,
                "unexpected function count: " + functionCount);
        println("runtime_string=0x534c instruction=0x33c54");
        println("maybe_log_event=0x1c9b4 unique_calls=" + calls);
        println("syslog_emitter=0x1cc0c config_message_ref=0x33c54->0x534c");
        println("functions=" + functionCount + " overlapping_bodies=0");
        println("packed_runtime_validation=PASS");
    }
}
