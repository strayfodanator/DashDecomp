#!/usr/bin/env python3
"""
build_real_stubs.py — DashDecomp
Replaces NODECOMPILED stubs with real assembly extracted from Ghidra.
Reads all_functions_asm.txt (exported by Ghidra) and writes proper .s files.

Usage:
    python tools/build_real_stubs.py
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASM_DIR = ROOT / "asm"
FUNCTIONS_FILE = ROOT / "build" / "all_functions_asm.txt"
FUNCTIONS_JSON = ASM_DIR / "functions.json"

BASE_ADDR = 0x00100000

MODULES = [
    ("System",  0x00100000, 0x001DFFFF),
    ("Sead",    0x001E0000, 0x0027FFFF),
    ("Race",    0x00280000, 0x0037FFFF),
    ("Kart",    0x00380000, 0x0046FFFF),
    ("Item",    0x00470000, 0x0050FFFF),
    ("UI",      0x00510000, 0x0057FFFF),
    ("Sound",   0x00580000, 0x005BFFFF),
    ("Net",     0x005C0000, 0x005DFFFF),
]

STUB_TEMPLATE = """\
.section .text
.global {label}
.type   {label}, %function
{label}:
{asm}
"""


def va_to_module(va: int) -> str:
    for name, start, end in MODULES:
        if start <= va <= end:
            return name
    return "Misc"


def main():
    print("[INFO] Reading function data from Ghidra export...")

    funcs = {}
    with open(FUNCTIONS_FILE) as f:
        content = f.read()

    blocks = content.strip().split("\n\n")
    for block in blocks:
        lines = block.strip().split("\n")
        if not lines or not lines[0].startswith("FUNC:"):
            continue

        header = lines[0]
        parts = header.split(":", 3)
        if len(parts) < 4:
            continue
        _, addr_str, size_str, name = parts
        addr = int(addr_str, 16)
        size = int(size_str)

        bytes_hex = ""
        asm_lines = []
        in_asm = False
        for line in lines[1:]:
            if line.startswith("BYTES:"):
                bytes_hex = line[6:]
            elif line.startswith("ASM:"):
                asm_text = line[4:]
                if asm_text.strip():
                    asm_lines = [asm_text.strip()]
                in_asm = True
            elif in_asm:
                asm_lines.append(line)

        funcs[addr] = {
            "size": size,
            "name": name,
            "bytes": bytes_hex,
            "asm": asm_lines,
        }

    print(f"[INFO] Loaded {len(funcs)} functions")

    # Load existing functions.json metadata
    import json
    meta = {}
    if FUNCTIONS_JSON.exists():
        with open(FUNCTIONS_JSON) as f:
            meta = json.load(f)

    # Also load xmap for names
    xmap = {}
    xmap_path = ROOT / "build" / "dlp_symbols" / "USA" / "CTRDash.xmap"
    if xmap_path.exists():
        with open(xmap_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split(None, 1)
                if len(parts) == 2:
                    addr = int(parts[0], 16)
                    xmap[addr] = parts[1]

    written = 0
    functions_json = {}

    for addr, func in sorted(funcs.items()):
        module = va_to_module(addr)
        offset = addr - BASE_ADDR

        # Determine label and path
        xmap_name = xmap.get(addr)
        if xmap_name:
            label = xmap_name.split("(")[0].split("<")[0].strip()
            label = re.sub(r"[^a-zA-Z0-9_]", "_", label).strip("_")
            if not label:
                label = f"sub_{addr:08X}"
            else:
                # Use the xmap name as a path component
                ns_parts = label.split("_")
                # Build path: module/namespace/function
                stem = label
                subdir = ASM_DIR / module
                for p in ns_parts[:-1]:
                    if p and len(p) < 50:
                        subdir = subdir / p
                stub_path = subdir / f"{stem}.s"
        else:
            stem = f"sub_{addr:08X}"
            label = stem
            subdir = ASM_DIR / module
            stub_path = subdir / f"{stem}.s"

        # Check if this path already used (collision)
        rel = str(stub_path.relative_to(ROOT))
        if rel in functions_json:
            stem = f"{stem}_{addr:08X}"
            label = stem
            stub_path = subdir / f"{stem}.s"
            rel = str(stub_path.relative_to(ROOT))
        functions_json[rel] = func["size"]

        # Build assembly text
        asm_body = ""
        if func["asm"]:
            for line in func["asm"]:
                asm_body += f"    {line}\n"
        else:
            asm_body = "    bx lr\n"

        stub_text = STUB_TEMPLATE.format(label=label, asm=asm_body)

        stub_path.parent.mkdir(parents=True, exist_ok=True)
        stub_path.write_text(stub_text)
        written += 1

        if written % 1000 == 0:
            print(f"[PROGRESS] {written}/{len(funcs)} stubs written...")

    # Save functions.json
    with open(FUNCTIONS_JSON, "w") as f:
        json.dump(dict(sorted(functions_json.items())), f, indent=2)

    print(f"[OK] Wrote {written} stubs with real assembly code")
    print(f"[OK] Wrote {FUNCTIONS_JSON}")


if __name__ == "__main__":
    main()
