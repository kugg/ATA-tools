// Emulate the resident bank with Ghidra's p-code emulator so control flow
// (two-delay-slot branches, jspci call/return) comes from the same SLEIGH that
// disassembles, instead of the hand-rolled interpreters.
//
// Usage (headless):
//   analyzeHeadless <proj> resident -import resident_bank.bin \
//     -processor MIPS-X:BE:32:ATA186 -cspec default -loader BinaryLoader \
//     -loader-baseAddr 0xcf80000 -noanalysis \
//     -postScript EmulateResident.java <stepLimit>
//
// Dumps the runtime tables (g_event_table 0x2bc8, g_cfg_state 0x9d84) after the
// run so they can be compared with the static analysis.

import ghidra.app.emulator.EmulatorHelper;
import ghidra.app.script.GhidraScript;
import ghidra.pcode.emulate.BreakCallBack;
import ghidra.pcode.pcoderaw.PcodeOpRaw;
import ghidra.program.model.address.Address;
import ghidra.program.model.mem.Memory;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.pcode.PcodeOp;

public class EmulateResident extends GhidraScript {

    // The SLEIGH models multiplier/coprocessor/xop/trap operations as CALLOTHER
    // userops (decode-only).  For emulation they are treated as no-ops so the
    // control flow can proceed; this is conservative, not device-accurate.
    private static final class NoOpCallOther extends BreakCallBack {
        @Override
        public boolean pcodeCallback(PcodeOpRaw op) {
            return op.getOpcode() == PcodeOp.CALLOTHER;
        }
    }

    private void ensureBlock(Memory mem, String name, long base, long size)
            throws Exception {
        Address a = toAddr(base);
        if (mem.getBlock(a) == null) {
            mem.createUninitializedBlock(name, a, size, false);
        }
    }

    private String words(EmulatorHelper emu, long base, int count) throws Exception {
        StringBuilder sb = new StringBuilder();
        byte[] b = emu.readMemory(toAddr(base), count * 4);
        for (int i = 0; i + 3 < b.length; i += 4) {
            long v = ((b[i] & 0xFFL) << 24) | ((b[i + 1] & 0xFFL) << 16)
                   | ((b[i + 2] & 0xFFL) << 8) | (b[i + 3] & 0xFFL);
            sb.append(String.format("%08x ", v));
        }
        return sb.toString().trim();
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        long limit = args.length > 0 ? Long.parseLong(args[0]) : 2_000_000L;

        Memory mem = currentProgram.getMemory();
        ensureBlock(mem, "sfr", 0x20000000L, 0x100000L);
        ensureBlock(mem, "win_1cf8", 0x1CF80000L, 0x80000L);
        ensureBlock(mem, "win_0d", 0x0D000000L, 0x80000L);
        ensureBlock(mem, "win_bit31", 0x80000000L, 0x80000L);

        // Low window: the reset tail (bank 0x7f400..0x80000) executes low; the rest
        // of low RAM starts zero and receives the runtime tables (0x2bc8, 0x9d84).
        // The bank itself stays at 0x0CF80000 for the launch header and main code.
        Address bankBase = toAddr(0x0CF80000L);
        MemoryBlock bankBlk = mem.getBlock(bankBase);
        Address low = toAddr(0x0L);
        if (mem.getBlock(low) == null) {
            mem.createInitializedBlock("ram_low", low, 0x80000L,
                    (byte) 0, monitor, false);
        }
        byte[] tail = new byte[0x80000 - 0x7f400];
        bankBlk.getBytes(toAddr(0x0CF80000L + 0x7f400L), tail);
        mem.setBytes(toAddr(0x7f400L), tail);

        EmulatorHelper emu = new EmulatorHelper(currentProgram);
        emu.registerDefaultCallOtherCallback(new NoOpCallOther());
        emu.writeRegister("pc", 0x7FF80L);   // low reset stub
        emu.writeRegister("r29", 0x7F800L);

        long steps = 0;
        while (steps < limit && !monitor.isCancelled()) {
            if (!emu.step(monitor)) {
                println("FAULT steps=" + steps + " at " + emu.getExecutionAddress()
                        + " : " + emu.getLastError());
                break;
            }
            steps++;
            if (steps % 2_000_000L == 0L) {
                println("steps=" + steps + " pc=" + emu.getExecutionAddress());
            }
        }
        println("STOP steps=" + steps + " pc=" + emu.getExecutionAddress()
                + " err=" + emu.getLastError());
        println("g_event_table[0x2bc8] = " + words(emu, 0x2bc8L, 16));
        println("g_cfg_state[0x9d84]   = " + words(emu, 0x9d84L, 16));
        emu.dispose();
    }
}
