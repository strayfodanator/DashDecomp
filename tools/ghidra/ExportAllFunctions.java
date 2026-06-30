import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.program.model.address.*;
import ghidra.program.model.lang.*;
import ghidra.program.model.util.*;
import java.io.*;
import java.util.*;

public class ExportAllFunctions extends GhidraScript {

    @Override
    public void run() throws Exception {
        println("=== DashDecomp: ExportAllFunctions ===");

        File buildDir = new File(System.getProperty("user.dir"), "build");
        PrintWriter pw = new PrintWriter(new FileWriter(new File(buildDir, "all_functions_asm.txt")));

        FunctionIterator funcs = currentProgram.getListing().getFunctions(true);
        int count = 0;
        while (funcs.hasNext()) {
            Function f = funcs.next();
            long addr = f.getEntryPoint().getOffset();
            long size = f.getBody().getNumAddresses();

            if (size < 4) continue;

            pw.printf("FUNC:0x%08X:%d:%s%n", addr, size, f.getName());

            // Raw bytes
            byte[] bytes = new byte[(int) size];
            currentProgram.getMemory().getBytes(f.getEntryPoint(), bytes);
            StringBuilder sb = new StringBuilder();
            for (byte b : bytes) {
                sb.append(String.format("%02X", b & 0xFF));
            }
            pw.println("BYTES:" + sb.toString());

            // Instructions
            InstructionIterator insts = currentProgram.getListing().getInstructions(f.getBody(), true);
            StringBuilder asm = new StringBuilder();
            while (insts.hasNext()) {
                Instruction inst = insts.next();
                String addrStr = Long.toHexString(inst.getAddress().getOffset());
                String mnem = inst.getMnemonicString();
                String ops = inst.getDefaultOperandRepresentation(0);
                if (inst.getNumOperands() > 1) {
                    for (int i = 1; i < inst.getNumOperands(); i++) {
                        ops += ", " + inst.getDefaultOperandRepresentation(i);
                    }
                }
                asm.append(String.format("  %s %s%n", mnem, ops));
            }
            pw.println("ASM:" + asm.toString().trim());
            pw.println();
            count++;
        }
        pw.close();
        println("Exported " + count + " functions -> all_functions_asm.txt");
        println("=== Done! ===");
    }
}
