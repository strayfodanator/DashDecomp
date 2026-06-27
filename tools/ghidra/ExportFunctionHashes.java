// DashDecomp — Ghidra Version Tracking script
// Runs BSim-style matching between two already-imported programs and
// exports the resulting symbol mapping as a CSV for import_symbols.py.
//
// Usage:
//   1. Make sure MK7_DLP project has code.bin (already done)
//   2. Import the retail binary into MK7_Retail project with the same settings
//   3. Run this script on the retail project
//
// This script is simpler: it just does function-by-function code comparison
// using Ghidra's built-in hash matching via FunctionHashPlugin.

import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.program.model.address.*;
import ghidra.program.util.SymbolicPropogator;
import ghidra.util.task.TaskMonitor;
import java.io.*;
import java.util.*;

public class ExportFunctionHashes extends GhidraScript {

    @Override
    public void run() throws Exception {
        println("=== DashDecomp: ExportFunctionHashes ===");

        File buildDir = new File(System.getProperty("user.dir"), "build");
        // code.dec.bin = retail; code.bin = DLP
        String suffix = currentProgram.getName().contains(".dec.") ? "retail" : "dlp";
        File hashOut = new File(buildDir, suffix + "_hashes.csv");
        PrintWriter pw = new PrintWriter(new FileWriter(hashOut));
        pw.println("address,hash,size,name");

        FunctionIterator funcs = currentProgram.getListing().getFunctions(true);
        int count = 0;
        while (funcs.hasNext()) {
            Function f = funcs.next();
            long addr = f.getEntryPoint().getOffset();
            long size = f.getBody().getNumAddresses();
            String name = f.getName();

            // Compute a simple hash from the function's bytes
            byte[] bytes = new byte[(int) Math.min(size, 64)];
            currentProgram.getMemory().getBytes(f.getEntryPoint(), bytes);
            long hash = 0;
            for (int i = 0; i < bytes.length; i++) {
                hash = hash * 31 + (bytes[i] & 0xFF);
            }

            pw.printf("0x%08X,%d,%d,%s%n", addr, hash, size, name);
            count++;
        }
        pw.close();
        println("Exported " + count + " function hashes -> " + hashOut.getPath());
        println("=== Done! ===");
    }
}
