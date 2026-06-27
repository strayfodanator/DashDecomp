#!/usr/bin/env python3
"""
Move root-level sub_*.s files into namespace subdirectories.
Uses nearest-xmap-namespace lookup (same logic as generate_report.py).
"""

import bisect
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent.parent
ASM_DIR = ROOT / "asm"
XMAP_PATH = ROOT / "build/dlp_symbols/USA/CTRDash.xmap"

def sanitize(name: str) -> str:
    out = re.sub(r'[<>(){} ,]', '_', name)
    out = re.sub(r'_+', '_', out)
    out = out.strip('_')
    return out or "_global"

# Load xmap
XMAP_ADDRS: list[int] = []
XMAP_NS: list[str] = []
with open(XMAP_PATH) as f:
    for line in f:
        line = line.strip()
        if not line or "\t" not in line:
            continue
        addr_s, name = line.split("\t", 1)
        addr = int(addr_s, 16)
        XMAP_ADDRS.append(addr)
        ns = name.split("::")[0] if "::" in name else "_global"
        XMAP_NS.append(ns)

total_moved = 0
total_dirs_created = 0

for mod_dir in sorted(ASM_DIR.iterdir()):
    if not mod_dir.is_dir():
        continue

    for f in sorted(mod_dir.glob("sub_*.s")):
        m = re.search(r"sub_([0-9A-Fa-f]{8})", f.name)
        if not m:
            continue
        addr = int(m.group(1), 16)

        # Find nearest namespace
        idx = bisect.bisect_left(XMAP_ADDRS, addr)
        if idx == 0:
            ns = XMAP_NS[0]
        elif idx >= len(XMAP_ADDRS):
            ns = XMAP_NS[-1]
        else:
            d_prev = addr - XMAP_ADDRS[idx - 1]
            d_next = XMAP_ADDRS[idx] - addr
            ns = XMAP_NS[idx - 1] if d_prev <= d_next else XMAP_NS[idx]

        safe = sanitize(ns)
        target_dir = mod_dir / safe
        target_dir.mkdir(parents=True, exist_ok=True)
        if target_dir.is_dir() and not any(target_dir.iterdir()):
            pass  # was just created

        target = target_dir / f.name
        if target.exists():
            print(f"SKIP {target} (already exists)")
            continue

        subprocess.run(["git", "mv", str(f), str(target)], check=True)
        total_moved += 1

print(f"\nDone. Moved {total_moved} files.")
