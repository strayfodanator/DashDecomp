#!/usr/bin/env python3
"""
DashDecomp — Symbol Importer
Takes the extracted DLP symbols/strings and maps them to our retail binary stubs.

Strategy:
  1. Parse the Ghidra-exported dlp_symbols.csv for known function addresses in DLP
  2. Parse dlp_strings.txt for RTTI class names / source paths / function names
  3. Use byte-pattern matching to find the same functions in the retail binary
  4. Rename the corresponding sub_XXXXXXXX.s stubs to their real names
  5. Regenerate asm/functions.json and build/report.json

Usage:
  python tools/import_symbols.py \\
      --symbols build/dlp_symbols.csv \\
      --strings build/dlp_strings.txt \\
      --retail  build/code.dec.bin \\
      --dlp     build/dlp_exefs/code.bin
"""

import argparse
import csv
import json
import os
import re
import shutil
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT    = Path(__file__).parent.parent
ASM_DIR = ROOT / "asm"

BASE_ADDR = 0x00100000
DLP_BASE  = 0x00100000

# ── Pattern window for byte-matching between DLP and retail binary ─────────────
MATCH_WINDOW = 32   # bytes to read from function start for fingerprint
MIN_MATCH    = 20   # minimum matching bytes to consider a match


def load_symbols(path: Path) -> list[dict]:
    """Load symbols from either CSV or XMAP format."""
    symbols = []
    if not path.exists():
        print(f"[WARN] Symbols file not found: {path}")
        return symbols
    if path.suffix == ".xmap":
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split(None, 1)
                if len(parts) == 2:
                    addr_str = "0x" + parts[0]
                    name = parts[1]
                    symbols.append({
                        "address": addr_str,
                        "name": name,
                        "type": "Function",
                        "namespace": ""
                    })
        print(f"[INFO] Loaded {len(symbols)} symbols from XMAP: {path.name}")
    else:
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                symbols.append(row)
        print(f"[INFO] Loaded {len(symbols)} symbols from CSV: {path.name}")
    return symbols


def load_strings_txt(path: Path) -> list[tuple[int, str]]:
    """Load strings with addresses from dlp_strings.txt."""
    entries = []
    if not path.exists():
        print(f"[WARN] Strings file not found: {path}")
        return entries
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t", 1)
            if len(parts) == 2:
                try:
                    addr = int(parts[0], 16)
                    entries.append((addr, parts[1]))
                except ValueError:
                    continue
    print(f"[INFO] Loaded {len(entries)} strings from {path.name}")
    return entries


def fingerprint(data: bytes, offset: int, window: int = MATCH_WINDOW) -> bytes:
    """Extract a byte fingerprint from the binary starting at offset."""
    end = min(offset + window, len(data))
    return data[offset:end]


def find_in_retail(dlp_fp: bytes, retail_data: bytes, search_start: int = 0) -> int:
    """
    Find a DLP function fingerprint in the retail binary.
    Returns the offset in retail_data, or -1 if not found.
    """
    # Try exact match first (functions often compile identically)
    idx = retail_data.find(dlp_fp[:MIN_MATCH], search_start)
    if idx != -1 and idx % 2 == 0:   # Thumb functions must be 2-byte aligned
        return idx

    return -1


def demangle_simple(name: str) -> str:
    """
    Simple C++ name demangler for common patterns.
    Handles basic _ZN...E patterns without needing c++filt.
    """
    if not name.startswith("_Z"):
        return name

    # Try using c++filt if available
    import subprocess
    try:
        result = subprocess.run(
            ["c++filt", name], capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass

    return name


def sanitize_filename(name: str) -> str:
    """Convert a C++ symbol name to a safe filename."""
    # Replace :: with _
    name = name.replace("::", "_")
    # Remove template parameters
    name = re.sub(r"<[^>]*>", "", name)
    # Remove function signatures
    name = re.sub(r"\(.*\)", "", name)
    # Remove return types and other keywords
    name = re.sub(r"\b(void|bool|int|float|const|static|virtual|inline)\b\s*", "", name)
    # Remove leading/trailing underscores or spaces
    name = name.strip("_ ")
    # Replace any remaining unsafe chars
    name = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    # Collapse multiple underscores
    name = re.sub(r"__+", "_", name)
    return name[:80]  # cap length


def rename_stub(old_va: int, new_name: str, module: str, dry_run: bool = False) -> bool:
    """
    Rename a sub_XXXXXXXX.s stub file to the real name.
    Returns True if the rename succeeded.
    """
    old_stem = f"sub_{old_va:08X}"
    safe_name = sanitize_filename(new_name)

    if not safe_name or safe_name == old_stem:
        return False

    # Search for the old stub file in the module's directory
    old_path = ASM_DIR / module / f"{old_stem}.s"
    if not old_path.exists():
        # Try all module directories
        for candidate in ASM_DIR.rglob(f"{old_stem}.s"):
            old_path = candidate
            break
        else:
            return False

    new_path = old_path.parent / f"{safe_name}.s"

    # Avoid overwriting existing files
    if new_path.exists() and new_path != old_path:
        new_path = old_path.parent / f"{safe_name}_{old_va:08X}.s"

    if dry_run:
        print(f"  [DRY]  {old_path.name}  ->  {new_path.name}")
        return True

    # Update stub content with real name
    content = old_path.read_text()
    content = content.replace(f"* Function: {old_stem}", f"* Function: {new_name} [{old_stem}]")
    content = content.replace(f".global {old_stem}", f".global {safe_name}")
    content = content.replace(f".type   {old_stem},", f".type   {safe_name},")
    content = content.replace(f"{old_stem}:\n", f"{safe_name}:  @ was {old_stem}\n")

    new_path.write_text(content)
    old_path.rename(new_path) if new_path != old_path else None

    return True


def main():
    parser = argparse.ArgumentParser(description="Import DLP symbols into DashDecomp stubs")
    parser.add_argument("--symbols", default="build/dlp_symbols/USA/CTRDash.xmap")
    parser.add_argument("--retail",  default="build/code.dec.bin")
    parser.add_argument("--dlp",     default="build/dlp_exefs/code.bin")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    symbols_path = ROOT / args.symbols

    # ── Load symbols ───────────────────────────────────────────────────────────
    symbols = load_symbols(symbols_path)

    print(f"[INFO] Strategy: direct address mapping (DLP USA == retail USA v1.0 addresses)")
    print()

    # ── Build a quick lookup of all existing stub VAs ──────────────────────────
    existing_stubs: dict[int, Path] = {}
    for stub in ASM_DIR.rglob("*.s"):
        stem = stub.stem
        if stem.startswith("sub_"):
            try:
                va = int(stem[4:], 16)
                existing_stubs[va] = stub
            except ValueError:
                continue

    print(f"[INFO] Stubs in asm/: {len(existing_stubs)}")
    print()

    matched   = 0
    renamed   = 0
    no_stub   = 0
    skipped   = 0
    total     = len(symbols)

    for sym in symbols:
        name     = sym.get("name", "").strip()
        addr_str = sym.get("address", "").strip()

        # Skip unnamed or auto-named entries
        if not name or not addr_str:
            skipped += 1
            continue

        # Skip Ghidra auto-generated names
        if re.match(r'^(FUN_|DAT_|LAB_|switchD|caseD_|default|switchdata)', name):
            skipped += 1
            continue

        try:
            dlp_va = int(addr_str, 16)
        except ValueError:
            skipped += 1
            continue

        # The retail v1.0 USA shares the same load address (0x00100000) and
        # the DLP binary is compiled from the same source → addresses match.
        retail_va = dlp_va

        if retail_va not in existing_stubs:
            no_stub += 1
            if args.verbose:
                print(f"  [MISS]  0x{retail_va:08X}  {name}")
            continue

        matched += 1
        real_name = demangle_simple(name)

        # Determine module from namespace/name
        module = "System"
        for mod in ["Race", "Kart", "Item", "UI", "Sound", "Net", "Sead"]:
            if mod.lower() in real_name.lower():
                module = mod
                break

        if rename_stub(retail_va, real_name, module, dry_run=args.dry_run):
            renamed += 1
            print(f"  [{'DRY' if args.dry_run else 'OK '}]  0x{retail_va:08X}  {name}")

    print()
    print(f"[RESULT] Total symbols:      {total}")
    print(f"         Stub matches:       {matched}")
    print(f"         Renamed stubs:      {renamed}")
    print(f"         No stub (ARM32/missing): {no_stub}")
    print(f"         Skipped (auto-names):    {skipped}")

    if renamed > 0 and not args.dry_run:
        print()
        print("[INFO] Regenerating functions.json and report.json...")
        os.system(f"cd '{ROOT}' && python tools/create_stubs.py 2>/dev/null")
        os.system(f"cd '{ROOT}' && python tools/generate_report.py --output build/report.json")
        print("[OK]  Done! Commit the renamed stubs to update decomp.dev.")


if __name__ == "__main__":
    main()
