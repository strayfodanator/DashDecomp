#!/usr/bin/env python3
"""
DashDecomp - Mario Kart 7 Decompilation Project
check_matching.py: Scans src/ for function status and prints a progress report.

States:
  MATCHING     - C++ compiles byte-for-byte to the original  (🟢)
  NONMATCHING  - C++ written but output doesn't match yet    (🟡)
  NODECOMPILED - Only raw assembly exists in asm/            (🔴)

Usage:
    python tools/check_matching.py [--json] [--module MODULE]
"""

import os
import re
import json
import argparse
from pathlib import Path
from collections import defaultdict

ROOT    = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "src"
ASM_DIR = ROOT / "asm"

# ── Colors ───────────────────────────────────────────────────────────────────
RED    = "\033[31m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
BLUE   = "\033[34m"
GREY   = "\033[90m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

# Regex to detect function status annotations in source files
RE_MATCHING    = re.compile(r'//\s*STATUS:\s*MATCHING',    re.IGNORECASE)
RE_NONMATCHING = re.compile(r'//\s*STATUS:\s*NONMATCHING', re.IGNORECASE)

MODULES = ["Race", "Kart", "Item", "System", "UI", "Sound", "Net", "Sead"]


def scan_module(module: str):
    """
    Scan a module directory for function status.
    Returns a dict: { "matching": int, "nonmatching": int, "nodecompiled": int }
    """
    counts = defaultdict(int)

    src_module = SRC_DIR / module
    asm_module = ASM_DIR / module

    # Count .s files in asm/ that are NOT yet in src/
    asm_files = set()
    if asm_module.exists():
        asm_files = {f.stem for f in asm_module.rglob("*.s")}

    src_files = set()
    if src_module.exists():
        for cpp_file in src_module.rglob("*.cpp"):
            src_files.add(cpp_file.stem)
            content = cpp_file.read_text(encoding="utf-8", errors="ignore")
            # Count individual functions by STATUS annotations
            matching_count    = len(RE_MATCHING.findall(content))
            nonmatching_count = len(RE_NONMATCHING.findall(content))
            counts["matching"]    += matching_count
            counts["nonmatching"] += nonmatching_count

    # Files only in asm/ (not yet touched) are nodecompiled
    nodecompiled = asm_files - src_files
    counts["nodecompiled"] += len(nodecompiled)

    return dict(counts)


def progress_bar(done: int, total: int, width: int = 30) -> str:
    if total == 0:
        return f"[{'─' * width}] n/a"
    pct    = done / total
    filled = int(pct * width)
    bar    = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {pct*100:5.1f}%"


def print_report(results: dict, module_filter=None):
    print(f"\n{BOLD}{'─'*65}")
    print(f"  DashDecomp — Matching Progress Report")
    print(f"{'─'*65}{RESET}\n")
    print(f"  {'Module':<14} {'🟢 matching':>12} {'🟡 nonmatch':>12} {'🔴 nodecomp':>12}   Progress")
    print(f"  {'─'*14} {'─'*12} {'─'*12} {'─'*12}   {'─'*38}")

    total_m  = 0
    total_nm = 0
    total_nd = 0

    for module, counts in sorted(results.items()):
        if module_filter and module.lower() != module_filter.lower():
            continue

        m  = counts.get("matching",    0)
        nm = counts.get("nonmatching", 0)
        nd = counts.get("nodecompiled",0)
        total = m + nm + nd

        total_m  += m
        total_nm += nm
        total_nd += nd

        bar = progress_bar(m, total)

        m_str  = f"{GREEN}{m:>12}{RESET}"
        nm_str = f"{YELLOW}{nm:>12}{RESET}"
        nd_str = f"{RED}{nd:>12}{RESET}"

        print(f"  {module:<14} {m_str} {nm_str} {nd_str}   {bar}")

    grand_total = total_m + total_nm + total_nd
    print(f"\n  {'─'*65}")
    print(f"  {'TOTAL':<14} {total_m:>12} {total_nm:>12} {total_nd:>12}   {progress_bar(total_m, grand_total)}")
    print()

    if grand_total == 0:
        print(f"  {GREY}No functions found yet. Run `make extract` first.{RESET}\n")


def main():
    parser = argparse.ArgumentParser(description="DashDecomp matching progress report")
    parser.add_argument("--json",   action="store_true", help="Output as JSON")
    parser.add_argument("--module", type=str,            help="Filter to a specific module")
    args = parser.parse_args()

    results = {}
    for module in MODULES:
        results[module] = scan_module(module)

    if args.json:
        print(json.dumps(results, indent=2))
        return

    print_report(results, module_filter=args.module)


if __name__ == "__main__":
    main()
