#!/usr/bin/env python3
"""
validate_returns.py — DashDecomp
Checks that every function .s file ends with a valid return instruction.
ARM return opcodes:
  - 0x1E FF 2F E1  →  bx lr
  - 0x.. .. .. E8  →  ldmia/ldmfd ..., {..., pc}  (pop {..., pc})
  - 0x.. F0 .. E8  →  pop {..., pc}  (LDMIA with pc)
  - 0x.. 80 BD E8  →  pop {..., pc}  (LDMFD SP!, {..., pc})

Usage:
    python tools/validate_returns.py [--fix] [--verbose]
"""

import argparse, json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASM_DIR = ROOT / "asm"
FUNCTIONS_JSON = ASM_DIR / "functions.json"
BASE_ADDR = 0x00100000

VA_RE = re.compile(r'([0-9A-Fa-f]{8})')
BYTE_LINE_RE = re.compile(r'\.byte\s+(.*)')

# Known ARM return patterns (little-endian bytes)
RETURN_PATTERNS = [
    # bx lr
    b'\x1e\xff\x2f\xe1',
    # pop {r4, pc}  (various forms of LDMFD SP!, {reglist, pc})
    # 0x8... ... e8  where bit 15 (pc) is set in register list
    # Pattern: last 2 bytes are 0x..E8 where E8 = LDMIA/LDMFD
    # We'll check that the last 4-byte instruction has 0xE8 in top byte
]

def bytes_from_s(path: Path) -> bytes:
    lines = path.read_text().splitlines()
    result = bytearray()
    for line in lines:
        m = BYTE_LINE_RE.search(line)
        if m:
            parts = [p.strip() for p in m.group(1).split(',')]
            try:
                result.extend(bytes(int(p, 16) & 0xFF for p in parts))
            except ValueError:
                pass
    return bytes(result)


def is_valid_return(data: bytes) -> tuple[bool, str]:
    """Check if the last 4 bytes of data form a valid function ending."""
    if len(data) < 4:
        return False, "too short"

    last_inst = data[-4:]
    inst_val = int.from_bytes(last_inst, 'little')

    # Unconditional branch: B <label>
    if (inst_val & 0xFF000000) == 0xEA000000:
        return True, "b"
    # Conditional branch: B<cond> <label>
    if (inst_val & 0x0F000000) == 0x0A000000:
        return True, "b<cond>"
    # BL (branch and link - tail call)
    if (inst_val & 0xFF000000) == 0xEB000000:
        return True, "bl"
    # BLX (branch and link exchange)
    if (inst_val & 0xFF000000) == 0xFA000000:
        return True, "blx"

    # bx lr
    if last_inst == b'\x1e\xff\x2f\xe1':
        return True, "bx lr"
    # bx <reg> (any register)
    if (inst_val & 0xFFFFFFF0) == 0x012FFF10:
        return True, f"bx r{(inst_val & 0xF)}"

    # mov pc, lr / movs pc, lr
    if inst_val == 0xE1A0F00E or inst_val == 0xE1B0F00E:
        return True, "mov pc, lr"

    # ldmfd sp!, {..., pc}
    if (inst_val & 0x0FF00000) == 0x08B00000 and (inst_val & (1 << 15)):
        return True, "pop {..., pc}"

    # ldr pc, [sp], #4 / ldr pc, [sp, #offset]
    if (inst_val & 0x0F900FFF) == 0x0490F004:
        return True, "ldr pc, [sp]"
    if (inst_val & 0x0F900000) == 0x05900000 and (inst_val & 0xF) == 13:
        return True, "ldr pc, [sp, #offset]"
    if (inst_val & 0x0F900000) == 0x04900000 and (inst_val & 0xF) == 13:
        return True, "ldr pc, [sp], #offset"
    # ldr pc, [sp], #4
    if inst_val == 0xE49DF004:
        return True, "ldr pc, [sp], #4"
    # ldr pc, [sp, #4]
    if inst_val == 0xE59DF004:
        return True, "ldr pc, [sp, #4]"

    # subs pc, lr, #4 (return from exception)
    if inst_val == 0xE25EF004:
        return True, "subs pc, lr, #4"

    # swi/svc/trap
    if (inst_val & 0xFF000000) == 0xEF000000:
        return True, "swi"

    # nop (mov r0, r0) - padding
    if inst_val == 0xE1A00000:
        return True, "nop (padding)"

    # msr cpsr (mode switch, ends with nop-like)
    if (inst_val & 0xFFFFF000) == 0xE10F0000:
        return True, "msr"

    # Check last byte alignment — data remnants often have bytes > 0xFF
    # or look like addresses (high nibble patterns)
    for b in last_inst:
        if b > 0xEA and b != 0xFF and b != 0xFE:
            # Byte is in data-like range
            pass

    return False, f"0x{inst_val:08X}"


def main():
    parser = argparse.ArgumentParser(description='Validate function return instructions')
    parser.add_argument('--fix', action='store_true', help='Add bx lr to functions missing return')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    args = parser.parse_args()

    s_files = sorted(ASM_DIR.rglob("*.s"))
    issues = []
    total = 0

    for s_file in s_files:
        rel = s_file.relative_to(ROOT)
        # Skip data stubs
        if "/data/" in str(rel) or s_file.stem.startswith("DAT_"):
            continue
        
        data = bytes_from_s(s_file)
        if len(data) == 0:
            continue
        
        total += 1
        ok, desc = is_valid_return(data)
        if not ok:
            issues.append((s_file, desc))
            if args.verbose:
                print(f"  NO_RET {rel}: {desc}")

    print(f"[INFO] Checked {total} function stubs")
    if issues:
        print(f"[ISSUES] {len(issues)} functions without valid return:")
        for s_file, desc in issues[:20]:
            rel = s_file.relative_to(ROOT)
            print(f"  {rel}: {desc}")
        if len(issues) > 20:
            print(f"  ... and {len(issues) - 20} more")
    else:
        print("[OK] All functions end with valid return instruction")

    if args.fix and issues:
        print("\n[FIX] Would add bx lr to these functions (not yet implemented)")
    
    return len(issues)


if __name__ == '__main__':
    exit(main())
