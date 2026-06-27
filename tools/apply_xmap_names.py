#!/usr/bin/env python3
"""
apply_xmap_names.py — Match xmap named symbols to retail functions
by address range and rename stubs accordingly.

Usage:
  python tools/apply_xmap_names.py [--dry-run]
"""

import bisect
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASM_DIR = ROOT / "asm"
FUNCTIONS_JSON = ASM_DIR / "functions.json"
XMAP = ROOT / "build/dlp_symbols/USA/CTRDash.xmap"
RETAIL_HASHES = ROOT / "build/retail_hashes.csv"


def load_xmap(path: Path) -> dict[int, str]:
    syms: dict[int, str] = {}
    skip = re.compile(r"^(FUN_|DAT_|LAB_|switchD|caseD_|default|switchdata|thunk_)")
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(None, 1)
            if len(parts) != 2:
                continue
            try:
                addr = int(parts[0], 16)
            except ValueError:
                continue
            name = parts[1]
            if not skip.match(name):
                syms[addr] = name
    return syms


def load_retail_functions(path: Path) -> tuple[list[int], list[int]]:
    starts: list[int] = []
    ends: list[int] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("address"):
                continue
            parts = line.split(",")
            if len(parts) >= 3:
                try:
                    addr = int(parts[0], 16)
                    size = int(parts[2])
                    starts.append(addr)
                    ends.append(addr + size)
                except ValueError:
                    continue
    return starts, ends


def batch_demangle(names: list[str]) -> list[str]:
    result = subprocess.run(
        ["c++filt"], input="\n".join(names), capture_output=True, text=True, timeout=30
    )
    return result.stdout.strip().split("\n") if result.stdout.strip() else names


def name_to_path_parts(name: str) -> list[str]:
    s = re.sub(r"\b(static|virtual|inline|const)\b\s*", "", name)
    s = re.sub(r"<[^<>]*>", "", s)
    s = re.sub(r"\(.*", "", s).strip()
    parts = [p.strip() for p in s.split("::") if p.strip()]
    safe = []
    for p in parts:
        p = re.sub(r"[^a-zA-Z0-9_]", "_", p)
        p = re.sub(r"__+", "_", p)
        safe.append(p.strip("_")[:80])
    return [p for p in safe if p]


def main():
    dry_run = "--dry-run" in sys.argv

    print("[INFO] Loading xmap named symbols...")
    xmap = load_xmap(XMAP)
    print(f"[INFO] {len(xmap)} named symbols loaded")

    print("[INFO] Loading retail function boundaries...")
    starts, ends = load_retail_functions(RETAIL_HASHES)
    print(f"[INFO] {len(starts)} retail functions loaded")

    print("[INFO] Matching xmap symbols to retail functions...")
    matched: dict[int, str] = {}
    for xaddr, xname in xmap.items():
        idx = bisect.bisect_right(starts, xaddr) - 1
        if idx >= 0 and xaddr < ends[idx]:
            matched[starts[idx]] = xname

    print(f"[INFO] Matched {len(matched)} named symbols to retail functions")

    with open(FUNCTIONS_JSON) as f:
        functions = json.load(f)

    # Prepare rename list
    rename_ops: list[tuple] = []
    for func_path in functions:
        m = re.search(r"sub_([0-9A-Fa-f]{8})", func_path)
        if not m:
            continue
        addr = int(m.group(1), 16)
        if addr not in matched:
            continue
        rename_ops.append((func_path, addr, matched[addr]))

    print(f"[INFO] Batch-demangling {len(rename_ops)} names...")
    if rename_ops:
        raw_names = [op[2] for op in rename_ops]
        demangled = batch_demangle(raw_names)
    else:
        demangled = []

    renamed = 0
    for (func_path, addr, raw_name), demangled_str in zip(rename_ops, demangled):
        parts = name_to_path_parts(demangled_str)
        if not parts:
            continue
        func_name = parts[-1]
        subdir_parts = parts[:-1]
        mod_match = re.match(r"asm/([^/]+)", func_path)
        module = mod_match.group(1) if mod_match else "System"

        old_path = ROOT / func_path
        if not old_path.exists():
            continue

        while subdir_parts and subdir_parts[0].lower() == module.lower():
            subdir_parts = subdir_parts[1:]

        new_dir = ASM_DIR / module
        for part in subdir_parts:
            new_dir = new_dir / part
        new_path = new_dir / f"{func_name}.s"

        if old_path == new_path:
            continue

        if dry_run:
            print(
                f"  [DRY]  {old_path.relative_to(ASM_DIR)}  →  {new_path.relative_to(ASM_DIR)}"
            )
            renamed += 1
            continue

        new_dir.mkdir(parents=True, exist_ok=True)
        content = old_path.read_text()
        content = content.replace(
            f"* Function: {old_path.stem}",
            f"* Function: {demangled_str} [{old_path.stem}]",
        )
        content = content.replace(f".global {old_path.stem}", f".global {func_name}")
        content = content.replace(
            f".type   {old_path.stem}", f".type   {func_name}"
        )
        content = content.replace(
            f"{old_path.stem}:\n", f"{func_name}:  @ was {old_path.stem}\n"
        )
        new_path.write_text(content)
        old_path.unlink()
        renamed += 1

    print(f"\n[RESULT] Renamed stubs: {renamed} ({len(matched)} total matched)")

    if renamed > 0 and not dry_run:
        print("[INFO] Regenerating functions.json...")
        subprocess.run(
            [sys.executable, str(ROOT / "tools/create_stubs.py"), "--regen"],
            cwd=ROOT,
            capture_output=True,
        )
        print("[INFO] Regenerating report.json...")
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools/generate_report.py"),
                "--output",
                "build/report.json",
            ],
            cwd=ROOT,
        )
        print("[OK]  Done! Commit changes to update decomp.dev.")


if __name__ == "__main__":
    main()
