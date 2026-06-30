import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.program.model.address.*;
import ghidra.program.model.lang.*;
import ghidra.app.decompiler.*;
import ghidra.util.task.TaskMonitor;
import java.io.*;
import java.util.*;

public class ExportFunctionDetails extends GhidraScript {

    @Override
    public void run() throws Exception {
        println("=== DashDecomp: ExportFunctionDetails ===");

        File buildDir = new File(System.getProperty("user.dir"), "build");
        PrintWriter pw = new PrintWriter(new FileWriter(new File(buildDir, "function_details.txt")));

        FunctionIterator funcs = currentProgram.getListing().getFunctions(true);
        int count = 0;
        while (funcs.hasNext()) {
            Function f = funcs.next();
            long addr = f.getEntryPoint().getOffset();
            long size = f.getBody().getNumAddresses();

            // Skip very large functions for now
            if (size > 50) continue;

            pw.println("=== FUNCTION ===");
            pw.printf("ADDRESS: 0x%08X%n", addr);
            pw.printf("SIZE: %d%n", size);
            pw.printf("NAME: %s%n", f.getName());

            // Get raw bytes
            byte[] bytes = new byte[(int) size];
            currentProgram.getMemory().getBytes(f.getEntryPoint(), bytes);
            StringBuilder sb = new StringBuilder();
            for (byte b : bytes) {
                sb.append(String.format("%02X", b & 0xFF));
            }
            pw.printf("BYTES: %s%n", sb.toString());

            // Get assembly instructions
            pw.println("DISASM:");
            InstructionIterator insts = currentProgram.getListing().getInstructions(f.getBody(), true);
            while (insts.hasNext()) {
                Instruction inst = insts.next();
                pw.printf("  %s%n", inst.toString());
            }

            // Get decompiled C code
            pw.println("DECOMPILED:");
            try {
                DecompInterface decompiler = new DecompInterface();
                decompiler.openProgram(currentProgram);
                DecompileResults res = decompiler.decompileFunction(f, 0, monitor);
                if (res != null && res.getDecompiledFunction() != null) {
                    String decompiled = res.getDecompiledFunction().getC();
                    pw.println(decompiled);
                }
            } catch (Exception e) {
                pw.println("  (decompilation failed: " + e.getMessage() + ")");
            }

            pw.println();
            count++;
            if (count >= 200) break;
        }
        pw.close();
        println("Exported " + count + " functions -> function_details.txt");
        println("=== Done! ===");
    }
}
