// DashDecomp — Ghidra Headless Script: Extract all strings that look like
// C++ function names or class names from the DLP code.bin and export them
// along with their addresses in a format compatible with our symbol map.
//
// Usage (via ghidra-analyzeHeadless):
//   See tools/ghidra_extract_symbols.sh for the full command.
//
// Output: build/dlp_symbols.csv  (address,name)
//         build/dlp_strings.txt  (all printable strings with offsets)

import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.program.model.address.*;
import ghidra.program.model.data.*;
import ghidra.util.task.TaskMonitor;
import java.io.*;
import java.util.*;

public class ExtractSymbols extends GhidraScript {

    @Override
    public void run() throws Exception {
        println("=== DashDecomp: ExtractSymbols ===");

        // ── Export all user-defined and analysis-found symbols ──────────────
        File buildDir = new File(System.getProperty("user.dir"), "build");
        File symbolsOut = new File(buildDir, "dlp_symbols.csv");
        PrintWriter symWriter = new PrintWriter(new FileWriter(symbolsOut));
        symWriter.println("address,name,type,namespace");

        SymbolTable symTable = currentProgram.getSymbolTable();
        SymbolIterator iter = symTable.getDefinedSymbols();
        int count = 0;
        while (iter.hasNext()) {
            Symbol sym = iter.next();
            if (sym.getSymbolType() == SymbolType.FUNCTION ||
                sym.getSymbolType() == SymbolType.LABEL) {
                String name = sym.getName();
                String ns   = sym.getParentNamespace().getName(true);
                long addr   = sym.getAddress().getOffset();
                symWriter.printf("0x%08X,%s,%s,%s%n",
                    addr, name, sym.getSymbolType(), ns);
                count++;
            }
        }
        symWriter.close();
        println("Symbols written: " + count + " -> " + symbolsOut.getPath());

        // ── Export all strings found in .rodata / data sections ─────────────
        File stringsOut = new File(buildDir, "dlp_strings.txt");
        PrintWriter strWriter = new PrintWriter(new FileWriter(stringsOut));

        DataIterator dataIter = currentProgram.getListing().getDefinedData(true);
        int strCount = 0;
        while (dataIter.hasNext()) {
            Data data = dataIter.next();
            if (data.getDataType() instanceof StringDataType ||
                data.getDataType() instanceof TerminatedStringDataType ||
                data.getDataType() instanceof UnicodeDataType) {
                Object val = data.getValue();
                if (val != null) {
                    String s = val.toString();
                    if (s.length() >= 4) {
                        strWriter.printf("0x%08X\t%s%n",
                            data.getAddress().getOffset(), s);
                        strCount++;
                    }
                }
            }
        }
        strWriter.close();
        println("Strings written: " + strCount + " -> " + stringsOut.getPath());

        println("=== Done! ===");
    }
}
