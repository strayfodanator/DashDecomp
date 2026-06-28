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

    # ── Phase 3: Multi-pass segment matching ─────────────────────────────
    # Use hash-matched functions as anchors; within and across segments,
    # match unmatched retail to unmatched DLP (with xmap names) using:
    #   Pass A: Sequential greedy (size threshold 30%)
    #   Pass B: Exhaustive exact-size within segments
    #   Pass C: Closest-size within segments (50%)
    #   Pass D: Cross-segment exact-size
    #   Pass E: Cross-segment closest-size (50%)
    print("[INFO] Phase 3: Multi-pass segment matching...")

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
    # Build reverse: DLP address → retail address from hash-matched pairs
    dlp_to_retail: dict[int, int] = {}
    for dlp_a, (h, _) in dlp_addr_to_hash.items():
        if h in retail_hash_to_addr:
            ra = retail_hash_to_addr[h][0]
            if ra in matched_addrs:
                dlp_to_retail[dlp_a] = ra
    matched_dlp_addrs = set(dlp_to_retail.keys())

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

    # Build lists of unmatched, with sizes
    r_unmatched = [(a, h, s) for a, h, s in all_retail if a not in matched_addrs]
    d_unmatched = [(a, h) for a, h in all_dlp if a in xmap and a not in matched_dlp_addrs]
    print(f"[INFO] Retail unmatched after hash+addr: {len(r_unmatched)}")
    print(f"[INFO] DLP unmatched with xmap name: {len(d_unmatched)}")

    pmid: dict[int, str] = {}
    r_m = set()
    d_m = set()

    def get_segments(rl, dl):
        segs = []
        for i in range(len(anchor_pairs) - 1):
            ra_s, da_s = anchor_pairs[i]; ra_e, da_e = anchor_pairs[i + 1]
            segs.append((
                [(a, h, s) for a, h, s in rl if ra_s < a < ra_e],
                [(a, h) for a, h in dl if da_s < a < da_e],
            ))
        if anchor_pairs:
            segs.insert(0, (
                [(a, h, s) for a, h, s in rl if a < anchor_pairs[0][0]],
                [(a, h) for a, h in dl if a < anchor_pairs[0][1]],
            ))
            segs.append((
                [(a, h, s) for a, h, s in rl if a > anchor_pairs[-1][0]],
                [(a, h) for a, h in dl if a > anchor_pairs[-1][1]],
            ))
        return segs

    # ── Pass A: Sequential greedy ──
    segs = get_segments(r_unmatched, d_unmatched)
    for r_seg, d_seg in segs:
        ri, di = 0, 0
        while ri < len(r_seg) and di < len(d_seg):
            ra, rh, rs = r_seg[ri]
            da, dh = d_seg[di]
            ds = dlp_addr_to_size.get(da, 0)
            if abs(rs - ds) / max(rs, ds, 1) <= 0.3:
                name = xmap.get(da, "")
                if name and ra not in r_m:
                    pmid[ra] = name; r_m.add(ra); d_m.add(da)
                ri += 1; di += 1
            elif rs < ds: ri += 1
            else: di += 1
    print(f"[INFO]   Pass A (sequential): {len(pmid)}")

    # ── Pass B: Exhaustive exact-size within segments ──
    r2 = [(a, h, s) for a, h, s in r_unmatched if a not in r_m]
    d2 = [(a, h) for a, h in d_unmatched if a not in d_m]
    segs = get_segments(r2, d2)
    b_count = 0
    for r_seg, d_seg in segs:
        from collections import defaultdict
        r_bs = defaultdict(list)
        for ra, rh, rs in r_seg: r_bs[rs].append(ra)
        for da, dh in d_seg:
            ds = dlp_addr_to_size.get(da, 0)
            if ds in r_bs and r_bs[ds]:
                ra = r_bs[ds].pop(0)
                if da in xmap and ra not in r_m:
                    name = xmap[da]
                    pmid[ra] = name; r_m.add(ra); d_m.add(da); b_count += 1
    print(f"[INFO]   Pass B (exact-size within seg): {b_count}")

    # ── Pass C: Closest-size within segments (50%) ──
    r3 = [(a, h, s) for a, h, s in r_unmatched if a not in r_m]
    d3 = [(a, h) for a, h in d_unmatched if a not in d_m]
    segs = get_segments(r3, d3)
    c_count = 0
    for r_seg, d_seg in segs:
        ra_list = list(r_seg)
        for da, dh in d_seg:
            ds = dlp_addr_to_size.get(da, 0)
            best_ra = None; best_d = float('inf'); best_i = -1
            for i, (ra, rh, rs) in enumerate(ra_list):
                if rs == 0: continue
                d = abs(rs - ds) / max(rs, ds)
                if d < best_d and d <= 0.5:
                    best_d = d; best_ra = ra; best_i = i
            if best_ra is not None and da in xmap:
                name = xmap[da]
                pmid[best_ra] = name; r_m.add(best_ra); d_m.add(da)
                ra_list.pop(best_i); c_count += 1
    print(f"[INFO]   Pass C (closest-size within seg): {c_count}")

    # ── Pass D: Cross-segment exact-size ──
    r4 = [(a, h, s) for a, h, s in r_unmatched if a not in r_m]
    d4 = [(a, h) for a, h in d_unmatched if a not in d_m]
    from collections import defaultdict
    r_bs_all = defaultdict(list)
    for ra, rh, rs in r4: r_bs_all[rs].append(ra)
    d_count = 0
    for da, dh in d4:
        ds = dlp_addr_to_size.get(da, 0)
        if ds in r_bs_all and r_bs_all[ds]:
            ra = r_bs_all[ds].pop(0)
            if da in xmap and ra not in r_m:
                name = xmap[da]
                pmid[ra] = name; r_m.add(ra); d_m.add(da); d_count += 1
    print(f"[INFO]   Pass D (cross-seg exact-size): {d_count}")

    # ── Pass E: Cross-segment closest-size (50%) ──
    r5 = [(a, h, s) for a, h, s in r_unmatched if a not in r_m]
    d5 = [(a, h) for a, h in d_unmatched if a not in d_m]
    ra_all = list(r5)
    e_count = 0
    for da, dh in d5:
        ds = dlp_addr_to_size.get(da, 0)
        best_ra = None; best_d = float('inf'); best_i = -1
        for i, (ra, rh, rs) in enumerate(ra_all):
            if rs == 0: continue
            d = abs(rs - ds) / max(rs, ds)
            if d < best_d and d <= 0.5:
                best_d = d; best_ra = ra; best_i = i
        if best_ra is not None and da in xmap:
            name = xmap[da]
            pmid[best_ra] = name; r_m.add(best_ra); d_m.add(da)
            ra_all.pop(best_i); e_count += 1
    print(f"[INFO]   Pass E (cross-seg closest-size): {e_count}")

    total_new = len(pmid)
    print(f"[INFO] Phase 3 total new matches: {total_new}")
    matched.update(pmid)

    # ── Phase 4: Forced address match ───────────────────────────────────────
    # For each unmatched sub_*, check if its retail address has an xmap entry
    # (same address in DLP binary). This is like Phase 2 but without the
    # hash-collision constraint.
    print("[INFO] Phase 4: Forced address matching...")
    unmatched_retail_addrs = {
        a for a, h, s in all_retail if a not in matched
    }
    f_addr_count = 0
    for ra in sorted(unmatched_retail_addrs):
        if ra in xmap:
            name = xmap[ra]
            if ra not in matched:
                matched[ra] = name
                f_addr_count += 1
    print(f"[INFO]   Pass F (forced address): {f_addr_count}")

    # ── Phase 5: Containing DLP function match ──────────────────────────────
    # For each remaining sub_* that lies INSIDE a DLP function body (whose
    # start address has an xmap name), assign the containing function's name
    # with a _subN suffix.
    print("[INFO] Phase 5: Containing DLP function matching...")

    # Build DLP function ranges: addr → (size, name)
    dlp_range: dict[int, tuple[int, str]] = {}
    for da, (dh, ds) in load_csv_by_addr(DLP_HASHES).items():
        if da in xmap:
            dlp_range[da] = (ds, xmap[da])

    dlp_starts = sorted(dlp_range.keys())

    from bisect import bisect_left

    # For each unmatched retail addr, find containing DLP function
    # and group by DLP function
    from collections import defaultdict
    contained_in_dlp: dict[int, list[int]] = defaultdict(list)
    for ra in sorted(unmatched_retail_addrs):
        idx = bisect_left(dlp_starts, ra)
        if idx > 0:
            prev_da = dlp_starts[idx - 1]
            prev_ds, prev_name = dlp_range[prev_da]
            if ra < prev_da + prev_ds:
                contained_in_dlp[prev_da].append(ra)

    g_count = 0
    for dlp_a, ra_list in sorted(contained_in_dlp.items()):
        _, name = dlp_range[dlp_a]
        demangled_name = demangle(name)
        parts = name_to_path_parts(demangled_name)
        if not parts:
            continue
        for i, ra in enumerate(ra_list):
            if ra in matched:
                continue
            if len(ra_list) == 1:
                suffix_name = name
            else:
                suffix_name = f"{name}::sub__{i+1}"
            matched[ra] = suffix_name
            g_count += 1

    print(f"[INFO]   Pass G (containing DLP func): {g_count}")

    total_matched = len(matched)
    print(f"[INFO] Total matched (all phases): {total_matched}")

    # Load current stubs — only match by FILENAME (not content)
    # so we don't re-rename files already matched in previous runs.
    stubs: dict[str, int] = {}
    for s_file in sorted(ASM_DIR.rglob("*.s")):
        m = re.search(r"sub_([0-9A-Fa-f]{8})", s_file.name)
        if m:
            rel = str(s_file.relative_to(ROOT))
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
