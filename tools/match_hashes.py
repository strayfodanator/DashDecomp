#!/usr/bin/env python3
"""
match_hashes.py — DashDecomp
Match DLP function hashes against retail function hashes.
Uses the DLP xmap to assign names to matched functions,
then renames corresponding assembly stubs.

Usage:
    python tools/match_hashes.py [--dry-run] [--verbose]
"""
import csv, re, os, sys
from pathlib import Path

ROOT     = Path(__file__).resolve().parent.parent
ASM_DIR  = ROOT / "asm"
BUILD    = ROOT / "build"

DLP_HASHES  = BUILD / "dlp_hashes.csv"
RETAIL_HASHES = BUILD / "retail_hashes.csv"
DLP_XMAP    = BUILD / "dlp_symbols/USA/CTRDash.xmap"

# ── Helpers ────────────────────────────────────────────────────────────────────

def load_hashes(path: Path) -> dict[int, dict]:
    """Load a hash CSV produced by ExportFunctionHashes.java.
    Returns {hash -> {addr, size, name}} — keyed by hash value.
    When multiple functions share the same hash, the entry is None (ambiguous).
    """
    by_hash: dict[int, dict | None] = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            h = int(row["hash"])
            entry = {"addr": int(row["address"], 16), "size": int(row["size"]), "name": row["name"]}
            if h in by_hash:
                by_hash[h] = None   # collision → skip this hash
            else:
                by_hash[h] = entry
    return by_hash


def load_xmap(path: Path) -> dict[int, str]:
    """Load DLP xmap: {dlp_va -> symbol_name}"""
    syms: dict[int, str] = {}
    skip_re = re.compile(r'^(FUN_|DAT_|LAB_|switchD|caseD_|default|switchdata)')
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(None, 1)
            if len(parts) != 2:
                continue
            addr = int(parts[0], 16)
            name = parts[1]
            if not skip_re.match(name):
                syms[addr] = name
    return syms


def sanitize_filename(name: str) -> str:
    """Convert a C++ symbol to a safe filename stem."""
    name = name.replace("::", "_")
    name = re.sub(r"<[^>]*>", "", name)
    name = re.sub(r"\(.*\)", "", name)
    name = re.sub(r"\b(void|bool|int|float|const|static|virtual|inline|unsigned|char)\b\s*", "", name)
    name = name.strip("_ ")
    name = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    name = re.sub(r"__+", "_", name)
    return name[:80]


def find_stub(retail_va: int) -> Path | None:
    """Look up a stub file by its virtual address."""
    stem = f"sub_{retail_va:08X}"
    for candidate in ASM_DIR.rglob(f"{stem}.s"):
        return candidate
    return None


def rename_stub(stub: Path, retail_va: int, new_name: str, dry_run: bool) -> bool:
    """Rename a stub file and update its contents."""
    old_stem = stub.stem
    safe_name = sanitize_filename(new_name)
    if not safe_name or safe_name == old_stem:
        return False

    new_path = stub.parent / f"{safe_name}.s"
    if new_path.exists() and new_path != stub:
        new_path = stub.parent / f"{safe_name}_{retail_va:08X}.s"

    if dry_run:
        print(f"  [DRY]  {stub.name}  ->  {new_path.name}")
        return True

    content = stub.read_text()
    content = content.replace(f"* Function: {old_stem}", f"* Function: {new_name} [{old_stem}]")
    content = content.replace(f".global {old_stem}", f".global {safe_name}")
    content = content.replace(f".type   {old_stem},", f".type   {safe_name},")
    content = content.replace(f"{old_stem}:\n", f"{safe_name}:  @ was {old_stem}\n")

    new_path.write_text(content)
    if new_path != stub:
        stub.rename(new_path)
    return True


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Match DLP/retail Ghidra hashes and rename stubs")
    parser.add_argument("--dry-run",  action="store_true")
    parser.add_argument("--verbose",  action="store_true")
    args = parser.parse_args()

    for p, label in [(DLP_HASHES, "dlp_hashes.csv"), (RETAIL_HASHES, "retail_hashes.csv"), (DLP_XMAP, "CTRDash.xmap")]:
        if not p.exists():
            print(f"[ERR] Missing: {p}"); sys.exit(1)

    print("[INFO] Loading hash tables...")
    dlp_by_hash    = load_hashes(DLP_HASHES)
    retail_by_hash = load_hashes(RETAIL_HASHES)

    dlp_unique    = sum(1 for v in dlp_by_hash.values() if v)
    retail_unique = sum(1 for v in retail_by_hash.values() if v)
    print(f"[INFO] DLP unique hashes:    {dlp_unique:,}")
    print(f"[INFO] Retail unique hashes: {retail_unique:,}")

    print("[INFO] Loading DLP xmap symbols...")
    xmap = load_xmap(DLP_XMAP)
    print(f"[INFO] Named DLP symbols: {len(xmap):,}")

    print("[INFO] Building existing stub index...")
    stubs: dict[int, Path] = {}
    for s in ASM_DIR.rglob("*.s"):
        if s.stem.startswith("sub_"):
            try:
                stubs[int(s.stem[4:], 16)] = s
            except ValueError:
                pass
    print(f"[INFO] Stubs found: {len(stubs):,}")
    print()

    matched = renamed = no_stub = no_name = collisions = 0

    # For each DLP hash that's unambiguous, look it up in the retail hash table
    for h, dlp_entry in dlp_by_hash.items():
        if dlp_entry is None:
            collisions += 1
            continue

        dlp_va = dlp_entry["addr"]

        # Get symbol name from xmap
        name = xmap.get(dlp_va)
        if not name:
            no_name += 1
            if args.verbose:
                print(f"  [UNNAMED]  DLP:0x{dlp_va:08X}")
            continue

        # Look up same hash in retail
        retail_entry = retail_by_hash.get(h)
        if retail_entry is None:
            continue  # not found or collision in retail

        retail_va = retail_entry["addr"]

        # Check if we have a stub for this retail address
        stub = stubs.get(retail_va)
        if not stub:
            no_stub += 1
            if args.verbose:
                print(f"  [NO STUB]  retail:0x{retail_va:08X}  {name}")
            continue

        matched += 1
        ok = rename_stub(stub, retail_va, name, dry_run=args.dry_run)
        if ok:
            renamed += 1
            print(f"  [{'DRY' if args.dry_run else 'OK '}]  0x{retail_va:08X}  {name}")

    print()
    print(f"[RESULT] Hash-matched stubs:        {matched}")
    print(f"         Renamed:                   {renamed}")
    print(f"         No retail stub for match:  {no_stub}")
    print(f"         DLP symbols without name:  {no_name}")
    print(f"         Ambiguous hashes skipped:  {collisions}")

    if renamed > 0 and not args.dry_run:
        print()
        print("[INFO] Regenerating functions.json...")
        os.system(f"cd '{ROOT}' && python tools/create_stubs.py --update-json-only 2>/dev/null || true")
        print("[OK]  Commit the renamed stubs to update decomp.dev!")


if __name__ == "__main__":
    main()
