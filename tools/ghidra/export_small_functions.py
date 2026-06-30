# DashDecomp: Export small functions for decompilation
# @category: DashDecomp
# Run with: analyzeHeadless ... -postScript export_small_functions.py

import os
import sys

build_dir = os.path.join(os.getcwd(), "build")

# Get current program
program = getCurrentProgram()
listing = program.getListing()
memory = program.getMemory()

funcs = listing.getFunctions(True)

output_path = os.path.join(build_dir, "function_details_py.txt")
with open(output_path, "w") as f:
    count = 0
    for func in funcs:
        addr = func.getEntryPoint().getOffset()
        size = func.getBody().getNumAddresses()

        # Only small functions (<= 20 bytes) for now
        if size > 20 or size < 4:
            continue

        f.write("=== FUNCTION ===\n")
        f.write("ADDRESS: 0x%08X\n" % addr)
        f.write("SIZE: %d\n" % size)
        f.write("NAME: %s\n" % func.getName())

        # Raw bytes
        try:
            bytes_arr = bytearray(size)
            memory.getBytes(func.getEntryPoint(), bytes_arr)
            hex_str = "".join("%02X" % b for b in bytes_arr)
            f.write("BYTES: %s\n" % hex_str)
        except:
            f.write("BYTES: (error reading)\n")

        # Instructions
        f.write("DISASM:\n")
        inst_iter = listing.getInstructions(func.getBody(), True)
        for inst in inst_iter:
            f.write("  %s\n" % str(inst))

        # Decompiled C
        f.write("DECOMPILED:\n")
        try:
            decomp = DecompInterface()
            decomp.openProgram(program)
            results = decomp.decompileFunction(func, 0, monitor)
            if results and results.getDecompiledFunction():
                f.write(results.getDecompiledFunction().getC() + "\n")
        except:
            f.write("  (decompilation failed)\n")

        f.write("\n")
        count += 1
        if count >= 100:
            break

print("Exported %d small functions -> %s" % (count, output_path))
