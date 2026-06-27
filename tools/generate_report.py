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

def count_asm_stubs() -> list[dict]:
    """Scan asm/ for .s files — each represents a NODECOMPILED function."""
    stubs = []
    for s_file in sorted(ASM_DIR.rglob("*.s")):
        rel = s_file.relative_to(ROOT)
        stubs.append({
            "path":   str(rel),
            "status": "NODECOMPILED",
        })
    return stubs


def count_src_functions() -> list[dict]:
    """
    Scan src/ for .cpp files.
    Each function annotated with MATCHING or NONMATCHING is counted accordingly.
    Any file with no annotations is treated as NONMATCHING.
    """
    funcs = []
    for cpp_file in sorted(SRC_DIR.rglob("*.cpp")):
        rel = cpp_file.relative_to(ROOT)
        text = cpp_file.read_text(errors="ignore")

        matching_count    = len(re.findall(r"\bMATCHING\b",    text))
        nonmatching_count = len(re.findall(r"\bNONMATCHING\b", text))

        for _ in range(matching_count):
            funcs.append({"path": str(rel), "status": "MATCHING"})
        for _ in range(nonmatching_count):
            funcs.append({"path": str(rel), "status": "NONMATCHING"})

        # If the file has no markers, count it as one NONMATCHING unit
        if matching_count == 0 and nonmatching_count == 0:
            funcs.append({"path": str(rel), "status": "NONMATCHING"})

    return funcs


def build_report() -> dict:
    stubs    = count_asm_stubs()
    src_fns  = count_src_functions()

    total_funcs     = len(stubs) + len(src_fns)
    matched_funcs   = sum(1 for f in src_fns if f["status"] == "MATCHING")
    total_code      = TOTAL_CODE_SIZE
    # Estimate matched code bytes proportionally from matched functions
    matched_code    = int((matched_funcs / total_funcs * total_code) if total_funcs > 0 else 0)

    matched_pct = (matched_code / total_code * 100.0) if total_code > 0 else 0.0

    # Build the units list in the objdiff report.json format
    units = []
    for entry in stubs + src_fns:
        is_matched = entry["status"] == "MATCHING"
        units.append({
            "name":     entry["path"],
            "metadata": {
                "progress_categories": [],
                "complete": is_matched,
            },
            "measures": {
                "fuzzy_match_percent":  100.0 if is_matched else 0.0,
                "total_code":           1,
                "matched_code":         1 if is_matched else 0,
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
