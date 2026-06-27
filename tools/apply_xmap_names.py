#!/usr/bin/env python3
"""
apply_xmap_names.py — Match xmap named symbols to retail functions
by cross-referencing DLP and retail function hashes.

Strategy:
  1. Load xmap proper names → DLP address
  2. Load DLP hashes (address → hash)  
  3. Load retail hashes (hash → address)
  4. For each xmap name: DLP addr → DLP hash → retail addr → rename stub

Usage:
  python tools/apply_xmap_names.py [--dry-run]
"""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASM_DIR = ROOT / "asm"
FUNCTIONS_JSON = ASM_DIR / "functions.json"
XMAP = ROOT / "build/dlp_symbols/USA/CTRDash.xmap"
DLP_HASHES = ROOT / "build/dlp_hashes.csv"
RETAIL_HASHES = ROOT / "build/retail_hashes.csv"

SKIP_RE = re.compile(
    r"^(FUN_|DAT_|LAB_|switchD|caseD_|default|switchdata|thunk_)"
)


def load_xmap(path: Path) -> dict[int, str]:
    syms: dict[int, str] = {}
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
            if not SKIP_RE.match(name) and 0x00100000 <= addr <= 0x005FFFFF:
                syms[addr] = name
    return syms


def load_csv_by_addr(path: Path) -> dict[int, tuple[str, int]]:
    """Load CSV by address (address,hash,size,...) → (hash, size)."""
    result: dict[int, tuple[str, int]] = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("address"):
                continue
            parts = line.split(",")
            if len(parts) >= 3:
                result[int(parts[0], 16)] = (parts[1].strip(), int(parts[2]))
    return result


def load_csv_by_hash(path: Path) -> dict[str, tuple[int, int]]:
    """Load CSV by hash (address,hash,size,...) → (address, size)."""
    result: dict[str, tuple[int, int]] = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("address"):
                continue
            parts = line.split(",")
            if len(parts) >= 3:
                result[parts[1].strip()] = (int(parts[0], 16), int(parts[2]))
    return result


def demangle(name: str) -> str:
    result = subprocess.run(
        ["c++filt"], input=name, capture_output=True, text=True, timeout=10
    )
    return result.stdout.strip() if result.returncode == 0 else name


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
    if "--restore" in sys.argv:
        _restore_backup()
        return

    print("[INFO] Loading xmap named symbols...")
    xmap = load_xmap(XMAP)
    print(f"[INFO] {len(xmap)} named symbols loaded")

    print("[INFO] Loading DLP hashes (address → hash)...")
    dlp_addr_to_hash = load_csv_by_addr(DLP_HASHES)
    print(f"[INFO] {len(dlp_addr_to_hash)} DLP hashes loaded")

    print("[INFO] Loading retail hashes (hash → address)...")
    retail_hash_to_addr = load_csv_by_hash(RETAIL_HASHES)
    print(f"[INFO] {len(retail_hash_to_addr)} retail hashes loaded")

    # Match: xmap name → DLP addr → DLP hash → retail addr
    print("[INFO] Matching xmap names to retail functions by hash...")
    matched: dict[int, str] = {}
    no_dlp_hash = 0
    no_retail_match = 0
    for dlp_addr, raw_name in xmap.items():
        if dlp_addr not in dlp_addr_to_hash:
            no_dlp_hash += 1
            continue
        h, _ = dlp_addr_to_hash[dlp_addr]
        if h not in retail_hash_to_addr:
            no_retail_match += 1
            continue
        retail_addr, _ = retail_hash_to_addr[h]
        matched[retail_addr] = raw_name

    print(f"[INFO] Matched {len(matched)} symbols (hash match)")
    print(f"[INFO]   No DLP hash entry: {no_dlp_hash}")
    print(f"[INFO]   No retail hash match: {no_retail_match}")

    # ── Phase 2: Address-match exact ──────────────────────────────────────
    # For xmap entries that didn't hash-match, check if the DLP address
    # exists at the same address in retail_hashes.csv
    print("[INFO] Phase 2: Exact address matching...")
    retail_addr_to_hash = load_csv_by_addr(RETAIL_HASHES)
    addr_matched: dict[int, str] = {}
    for dlp_addr, raw_name in xmap.items():
        if dlp_addr in matched.values():
            continue
        if dlp_addr in matched:
            continue
        if dlp_addr in retail_addr_to_hash:
            h2, _ = retail_addr_to_hash[dlp_addr]
            if h2 not in retail_hash_to_addr:
                continue
            raddr, _ = retail_hash_to_addr[h2]
            if raddr == dlp_addr and raddr not in matched:
                addr_matched[raddr] = raw_name

    print(f"[INFO] Address-matched: {len(addr_matched)}")
    matched.update(addr_matched)

    # ── Phase 3: Segment-sequential matching ──────────────────────────────
    # Use hash-matched functions as anchors; within each segment,
    # match retail unmatched to DLP unmatched (with xmap names)
    # sequentially by similar size.
    print("[INFO] Phase 3: Segment-sequential matching...")

    all_retail: list[tuple[int, str, int]] = []
    with open(RETAIL_HASHES) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("address"):
                continue
            parts = line.split(",")
            if len(parts) >= 3:
                all_retail.append(
                    (int(parts[0], 16), parts[1].strip(), int(parts[2]))
                )
    all_retail.sort(key=lambda x: x[0])

    all_dlp: list[tuple[int, str]] = []
    with open(DLP_HASHES) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("address"):
                continue
            parts = line.split(",")
            if len(parts) >= 2:
                all_dlp.append((int(parts[0], 16), parts[1].strip()))
    all_dlp.sort(key=lambda x: x[0])

    dlp_hash_to_retail = {h: a for a, (h, s) in retail_addr_to_hash.items()}

    # Build anchor pairs from hash-matched functions: (retail_addr, dlp_addr)
    # These are ground-truth correspondences between the two binaries
    dlp_hash_to_addr = {h: a for a, h in all_dlp}
    anchor_set: set[tuple[int, int]] = set()
    for ra, rh, rs in all_retail:
        if rh in dlp_hash_to_addr:
            da = dlp_hash_to_addr[rh]
            if da in xmap:
                anchor_set.add((ra, da))
    anchor_pairs = sorted(anchor_set, key=lambda x: x[0])
    print(f"[INFO] Anchor pairs (hash ground truth): {len(anchor_pairs)}")

    matched_addrs = set(matched.keys())

    # Identify unmatched retail (FUN_*) and unmatched DLP (addrs in xmap)
    retail_unmatched_list = [
        (a, h, s) for a, h, s in all_retail
        if a not in matched_addrs
    ]
    dlp_xmap_addrs = set(xmap.keys())
    dlp_unmatched_list = [
        (a, h) for a, h in all_dlp
        if a in dlp_xmap_addrs and h not in dlp_hash_to_retail
    ]

    print(f"[INFO] Retail unmatched after hash+addr: {len(retail_unmatched_list)}")
    print(f"[INFO] DLP unmatched with xmap name: {len(dlp_unmatched_list)}")

    # DLP address → size mapping
    dlp_addr_to_size: dict[int, int] = {}
    with open(DLP_HASHES) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("address"):
                continue
            parts = line.split(",")
            if len(parts) >= 3:
                dlp_addr_to_size[int(parts[0], 16)] = int(parts[2])

    # Segment-sequential matching
    seq_matched: dict[int, str] = {}

    def match_segment(ra_start, ra_end, da_start, da_end):
        r_seg = [(a, h, s) for a, h, s in retail_unmatched_list if ra_start < a < ra_end]
        d_seg = [(a, h) for a, h in dlp_unmatched_list if da_start < a < da_end]
        ri, di = 0, 0
        seg_matches = 0
        while ri < len(r_seg) and di < len(d_seg):
            ra, rh, rs = r_seg[ri]
            da, dh = d_seg[di]
            ds = dlp_addr_to_size.get(da, 0)
            if abs(rs - ds) / max(rs, ds, 1) <= 0.3:
                name = xmap.get(da, "")
                if name and ra not in matched and ra not in seq_matched:
                    seq_matched[ra] = name
                    seg_matches += 1
                ri += 1
                di += 1
            elif rs < ds:
                ri += 1
            else:
                di += 1
        return seg_matches

    total_seg = 0
    for i in range(len(anchor_pairs) - 1):
        total_seg += match_segment(
            anchor_pairs[i][0], anchor_pairs[i + 1][0],
            anchor_pairs[i][1], anchor_pairs[i + 1][1],
        )
    # Head and tail
    if anchor_pairs:
        total_seg += match_segment(0, anchor_pairs[0][0], 0, anchor_pairs[0][1])
        total_seg += match_segment(anchor_pairs[-1][0], 0xFFFFFFFF, anchor_pairs[-1][1], 0xFFFFFFFF)

    print(f"[INFO] Segment-sequential matches: {total_seg}")
    matched.update(seq_matched)

    total_matched = len(matched)
    print(f"[INFO] Total matched (all phases): {total_matched}")

    # Load current stubs
    stubs: dict[str, int] = {}
    for s_file in sorted(ASM_DIR.rglob("*.s")):
        rel = str(s_file.relative_to(ROOT))
        m = re.search(r"sub_([0-9A-Fa-f]{8})", s_file.name)
        if not m:
            try:
                with open(s_file, "rb") as fh:
                    head = fh.read(200)
                m = re.search(rb"sub_([0-9A-Fa-f]{8})", head)
            except Exception:
                pass
        if m:
            addr = int(m.group(1), 16)
            stubs[rel] = addr

    print(f"[INFO] sub_ stubs in asm/: {len(stubs)}")

    # Find which stubs can be renamed
    rename_ops: list[tuple[str, int, str]] = []
    for rel_path, addr in stubs.items():
        if addr in matched:
            rename_ops.append((rel_path, addr, matched[addr]))

    print(f"[INFO] Stubs to rename: {len(rename_ops)}")

    if not rename_ops:
        print("[RESULT] Nothing to rename.")
        return

    # Batch demangle
    print(f"[INFO] Demangling {len(rename_ops)} names...")
    all_names = [op[2] for op in rename_ops]
    demangled = []
    for i in range(0, len(all_names), 500):
        batch = all_names[i : i + 500]
        result = subprocess.run(
            ["c++filt"],
            input="\n".join(batch),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.stdout.strip():
            demangled.extend(result.stdout.strip().split("\n"))
        else:
            demangled.extend(batch)

    # Build rename plan: avoid collisions
    final_ops: list[tuple[Path, Path, str, str]] = []
    used_targets: set[Path] = set()

    for (rel_path, addr, raw_name), demangled_str in zip(rename_ops, demangled):
        parts = name_to_path_parts(demangled_str)
        if not parts:
            continue
        func_name = parts[-1]
        subdir_parts = parts[:-1]
        mod_match = re.match(r"asm/([^/]+)", rel_path)
        module = mod_match.group(1) if mod_match else "System"

        old_path = ROOT / rel_path
        if not old_path.exists():
            continue

        while subdir_parts and subdir_parts[0].lower() == module.lower():
            subdir_parts = subdir_parts[1:]

        new_dir = ASM_DIR / module
        for part in subdir_parts:
            new_dir = new_dir / part
        new_path = new_dir / f"{func_name}.s"

        # Avoid name collision: skip if target already used by another rename
        if new_path in used_targets or new_path == old_path:
            continue
        used_targets.add(new_path)

        final_ops.append((old_path, new_path, raw_name, demangled_str))

    renamed = 0
    for old_path, new_path, raw_name, demangled_str in final_ops:
        if dry_run:
            print(
                f"  [DRY]  {old_path.relative_to(ASM_DIR)}  →  {new_path.relative_to(ASM_DIR)}"
            )
            renamed += 1
            continue

        new_path.parent.mkdir(parents=True, exist_ok=True)
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

    print(f"\n[RESULT] Renamed stubs: {renamed}")

    if renamed > 0 and not dry_run:
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


def _restore_backup():
    """Restore sub_ stubs from git (revert rename)."""
    result = subprocess.run(
        ["git", "status", "--porcelain", "asm/"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        status, path = line[:2], line[3:].strip()
        if status == "??" and path.endswith(".s"):
            Path(path).unlink()
        elif status == " D" and "sub_" in path:
            subprocess.run(
                ["git", "checkout", "--", path],
                capture_output=True,
                cwd=ROOT,
            )
    print("[OK]  Restored sub_ stubs from git.")


if __name__ == "__main__":
    main()
