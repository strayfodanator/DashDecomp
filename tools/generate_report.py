#!/usr/bin/env python3
"""
DashDecomp — Progress Report Generator
Generates a report.json compatible with decomp.dev's expected format.

This script scans the asm/ and src/ directories to determine:
  - NODECOMPILED: functions that only have .s stubs (not yet decompiled)
  - NONMATCHING:  functions with C++ written but not yet byte-identical
  - MATCHING:     functions that compile byte-identically to the original

Usage:
  python tools/generate_report.py [--output build/report.json]
"""

import argparse
import json
import os
import re
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────
ROOT       = Path(__file__).parent.parent
ASM_DIR    = ROOT / "asm"
SRC_DIR    = ROOT / "src"
BUILD_DIR  = ROOT / "build"

# ── Known total code size (decompressed code.bin) ────────────────────────────
# MD5 confirmed: 4b8320677e3311b14a75d2abb97772e8
TOTAL_CODE_SIZE = 5488 * 1024  # 5,488 KB in bytes

# ── Annotation markers used in .cpp files ────────────────────────────────────
MATCHING_MARKER    = "MATCHING"
NONMATCHING_MARKER = "NONMATCHING"

# ── Load functions size manifest ─────────────────────────────────────────────
FUNCTIONS_JSON = ASM_DIR / "functions.json"
SYMBOL_SIZES = {}
STUB_SIZES = {}

if FUNCTIONS_JSON.exists():
    try:
        import json as j
        manifest = j.loads(FUNCTIONS_JSON.read_text())
        for rel_path, size in manifest.items():
            STUB_SIZES[rel_path] = size
            symbol_name = Path(rel_path).stem
            SYMBOL_SIZES[symbol_name] = size
    except Exception as e:
        print(f"[WARN] Failed to load functions manifest: {e}")

def count_asm_stubs() -> list[dict]:
    """Scan asm/ for .s files — each represents a NODECOMPILED function."""
    stubs = []
    for s_file in sorted(ASM_DIR.rglob("*.s")):
        if s_file.name == "functions.json":
            continue
        rel = s_file.relative_to(ROOT)
        rel_str = str(rel)
        size = STUB_SIZES.get(rel_str, 4)  # fallback to 4 bytes if not in manifest
        stubs.append({
            "path":   rel_str,
            "status": "NODECOMPILED",
            "size":   size,
        })
    return stubs


def count_src_functions() -> list[dict]:
    """
    Scan src/ for .cpp files.
    Each function annotated with MATCHING or NONMATCHING is counted accordingly.
    Supports symbol tagging: e.g., '// MATCHING sub_00280000'
    """
    funcs = []
    for cpp_file in sorted(SRC_DIR.rglob("*.cpp")):
        rel = cpp_file.relative_to(ROOT)
        text = cpp_file.read_text(errors="ignore")

        # Find markers: MATCHING sub_XXXX or NONMATCHING sub_XXXX
        # e.g., "// MATCHING sub_00280000" or "// status: MATCHING"
        matches = re.finditer(r"\b(MATCHING|NONMATCHING)\b(?:\s*[:\-(\s]\s*)?(sub_[0-9A-Fa-f]{8})?", text)
        found_any = False

        for match in matches:
            found_any = True
            status = match.group(1)
            symbol = match.group(2)
            
            size = 100  # Default fallback size for C++ functions
            if symbol and symbol in SYMBOL_SIZES:
                size = SYMBOL_SIZES[symbol]
            elif not symbol:
                # Try to search the whole file for any sub_XXXXXXXX symbol to associate the size
                sub_match = re.search(r"\b(sub_[0-9A-Fa-f]{8})\b", text)
                if sub_match and sub_match.group(1) in SYMBOL_SIZES:
                    size = SYMBOL_SIZES[sub_match.group(1)]

            funcs.append({
                "path":   f"{rel}:{symbol or 'unknown'}",
                "status": status,
                "size":   size,
            })

        # If the file has no markers, check if it contains sub_XXXX to guess size, count as 1 NONMATCHING unit
        if not found_any:
            size = 100
            sub_match = re.search(r"\b(sub_[0-9A-Fa-f]{8})\b", text)
            if sub_match and sub_match.group(1) in SYMBOL_SIZES:
                size = SYMBOL_SIZES[sub_match.group(1)]
            
            funcs.append({
                "path":   str(rel),
                "status": "NONMATCHING",
                "size":   size,
            })

    return funcs


def build_report() -> dict:
    stubs    = count_asm_stubs()
    src_fns  = count_src_functions()

    # Calculate actual bytes instead of guessing proportionally
    total_code = sum(entry["size"] for entry in stubs + src_fns)
    matched_code = sum(entry["size"] for entry in src_fns if entry["status"] == "MATCHING")

    # If functions.json wasn't loaded or total size is 0, fallback to known total code size
    if total_code == 0:
        total_code = TOTAL_CODE_SIZE

    total_funcs = len(stubs) + len(src_fns)
    matched_funcs = sum(1 for f in src_fns if f["status"] == "MATCHING")

    matched_pct = (matched_code / total_code * 100.0) if total_code > 0 else 0.0

    # Build the units list in the objdiff report.json format
    units = []
    for entry in stubs + src_fns:
        is_matched = entry["status"] == "MATCHING"
        size = entry["size"]
        units.append({
            "name":     entry["path"],
            "metadata": {
                "progress_categories": [],
                "complete": is_matched,
            },
            "measures": {
                "fuzzy_match_percent":  100.0 if is_matched else 0.0,
                "total_code":           size,
                "matched_code":         size if is_matched else 0,
                "total_data":           0,
                "matched_data":         0,
                "total_functions":      1,
                "matched_functions":    1 if is_matched else 0,
            },
        })

    report = {
        "measures": {
            "fuzzy_match_percent":  matched_pct,
            "total_code":           total_code,
            "matched_code":         matched_code,
            "total_data":           0,
            "matched_data":         0,
            "total_functions":      total_funcs,
            "matched_functions":    matched_funcs,
        },
        "units": units,
    }

    return report


def main():
    parser = argparse.ArgumentParser(description="Generate decomp.dev-compatible report.json")
    parser.add_argument("--output", "-o", default="build/report.json",
                        help="Output path for the report JSON (default: build/report.json)")
    args = parser.parse_args()

    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)

    report = build_report()

    with open(output, "w") as f:
        json.dump(report, f, indent=2)

    m = report["measures"]
    total_fn  = m["total_functions"]
    match_fn  = m["matched_functions"]
    pct       = m["fuzzy_match_percent"]

    print(f"[OK]  Report written to {output}")
    print(f"      Functions: {match_fn}/{total_fn} matched")
    print(f"      Progress:  {pct:.2f}%")


if __name__ == "__main__":
    main()
