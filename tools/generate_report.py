#!/usr/bin/env python3
"""
DashDecomp — Progress Report Generator
Generates a report.json compatible with decomp.dev's expected format.

Groups functions into Units by their directory in asm/,
so each Unit corresponds to a logical grouping of related functions
(e.g. Item/Enemy/AIRankGroupMiddle contains multiple functions).

Usage:
  python tools/generate_report.py [--output build/report.json]
"""

import argparse
import json
import re
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).parent.parent
ASM_DIR = ROOT / "asm"
SRC_DIR = ROOT / "src"
BUILD_DIR = ROOT / "build"

TOTAL_CODE_SIZE = 5488 * 1024

MATCHING_MARKER = "MATCHING"
NONMATCHING_MARKER = "NONMATCHING"

FUNCTIONS_JSON = ASM_DIR / "functions.json"
RETAIL_HASHES = BUILD_DIR / "retail_hashes.csv"

SYMBOL_SIZES = {}
STUB_SIZES = {}
ADDR_TO_SIZE: dict[int, int] = {}

# Load Ghidra retail function sizes (has 15110 entries with real sizes)
if RETAIL_HASHES.exists():
    try:
        with open(RETAIL_HASHES) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("address"):
                    continue
                parts = line.split(",")
                if len(parts) >= 3:
                    addr = int(parts[0], 16)
                    size = int(parts[2])
                    ADDR_TO_SIZE[addr] = size
    except Exception as e:
        print(f"[WARN] Failed to load retail_hashes.csv: {e}")

# Load functions.json as fallback
if FUNCTIONS_JSON.exists():
    try:
        manifest = json.loads(FUNCTIONS_JSON.read_text())
        for rel_path, size in manifest.items():
            STUB_SIZES[rel_path] = size
            symbol_name = Path(rel_path).stem
            SYMBOL_SIZES[symbol_name] = size
    except Exception as e:
        print(f"[WARN] Failed to load functions manifest: {e}")


def _get_size(path: str) -> int:
    """Look up function size: first by address from retail_hashes,
    then by path from functions.json, default 4."""
    # Try path from functions.json
    if path in STUB_SIZES:
        return STUB_SIZES[path]
    # Try extracting address from path/filename and look up in retail_hashes
    m = re.search(r"([0-9A-Fa-f]{8})", path)
    if m:
        addr = int(m.group(1), 16)
        if addr in ADDR_TO_SIZE:
            return ADDR_TO_SIZE[addr]
    return 4


def _addr_from_file(s_file: Path) -> int | None:
    """Extract virtual address from a .s file's metadata comment."""
    m = re.search(r"sub_([0-9A-Fa-f]{8})", s_file.name)
    if m:
        return int(m.group(1), 16)
    try:
        with open(s_file, "rb") as fh:
            head = fh.read(200)
        m = re.search(rb"Virtual Address:\s*0x([0-9A-Fa-f]{8})", head)
        if m:
            return int(m.group(1), 16)
        m = re.search(rb"0x([0-9A-Fa-f]{8})", s_file.name.encode())
        if m:
            return int(m.group(1), 16)
    except Exception:
        pass
    return None


def get_func_statuses() -> dict[str, dict]:
    statuses = {}

    for s_file in sorted(ASM_DIR.rglob("*.s")):
        rel = s_file.relative_to(ROOT)
        rel_str = str(rel)
        addr = _addr_from_file(s_file)
        size = _get_size(rel_str)
        if size == 4 and addr and addr in ADDR_TO_SIZE:
            size = ADDR_TO_SIZE[addr]
        statuses[rel_str] = {
            "path": rel_str,
            "status": "NODECOMPILED",
            "size": size,
        }

    for cpp_file in sorted(SRC_DIR.rglob("*.cpp")):
        text = cpp_file.read_text(errors="ignore")

        for match in re.finditer(
            r"\b(MATCHING|NONMATCHING)\b(?:\s*[:\-(\s]\s*)?(sub_[0-9A-Fa-f]{8})?",
            text,
        ):
            status = match.group(1)
            symbol = match.group(2)

            size = 100
            if symbol and symbol in SYMBOL_SIZES:
                size = SYMBOL_SIZES[symbol]
            elif not symbol:
                sub_match = re.search(r"\b(sub_[0-9A-Fa-f]{8})\b", text)
                if sub_match and sub_match.group(1) in SYMBOL_SIZES:
                    size = SYMBOL_SIZES[sub_match.group(1)]

            key = symbol or str(cpp_file.relative_to(ROOT))
            if key and key not in statuses:
                statuses[key] = {
                    "path": f"{cpp_file.relative_to(ROOT)}:{key}",
                    "status": status,
                    "size": size,
                }

    return statuses


CHUNK_SIZE = 50


def _func_label(path: str) -> str:
    m = re.match(r"^asm/[^/]+/(.+)", path)
    if m:
        return Path(m.group(1)).with_suffix("").as_posix()
    return Path(path).stem


def _unit_name_for_path(path: str) -> str:
    """Derive the unit name from a .s file path.
    Named functions use their leaf directory as the unit.
    Root sub_ functions are grouped by module for later chunking.
    """
    m = re.match(r"^asm/([^/]+)/", path)
    mod = m.group(1) if m else "_"

    # Has subdirectory beyond module root?
    rest = path[len(f"asm/{mod}/"):]
    parent = Path(rest).parent.as_posix()
    if parent != "." and parent != "":
        return f"{mod}/{parent}"
    return None  # root-level function → will be chunked


def _func_sort_key(info: dict) -> int:
    path = info["path"]
    m = re.search(r"([0-9A-Fa-f]{8})", path)
    return int(m.group(1), 16) if m else 0


CHUNK_SIZE = 50


def _chunk_list(lst: list, size: int):
    for i in range(0, len(lst), size):
        yield lst[i : i + size]


def _make_unit(name: str, funcs: list[dict]) -> dict:
    total_code = sum(f["size"] for f in funcs)
    matched_code = sum(f["size"] for f in funcs if f["status"] == "MATCHING")
    total_fns = len(funcs)
    matched_fns = sum(1 for f in funcs if f["status"] == "MATCHING")
    fuzzy_pct = (matched_code / total_code * 100.0) if total_code > 0 else 0.0
    complete = matched_fns == total_fns

    return {
        "name": name,
        "metadata": {"progress_categories": [], "complete": complete},
        "measures": {
            "fuzzy_match_percent": fuzzy_pct,
            "total_code": total_code,
            "matched_code": matched_code,
            "total_data": 0,
            "matched_data": 0,
            "total_functions": total_fns,
            "matched_functions": matched_fns,
        },
        "functions": [
            {
                "name": _func_label(f["path"]),
                "size": f["size"],
                "fuzzy_match_percent": 100.0 if f["status"] == "MATCHING" else 0.0,
                "metadata": {"virtual_address": 0},
            }
            for f in funcs
        ],
    }


def group_funcs_into_units(
    statuses: dict[str, dict],
) -> list[dict]:
    # Separate named (subdirectory) vs root (sub_*) functions
    named_groups: dict[str, list[dict]] = defaultdict(list)
    root_funcs: dict[str, list[dict]] = defaultdict(list)

    for stem, info in statuses.items():
        unit = _unit_name_for_path(info["path"])
        if unit:
            named_groups[unit].append(info)
        else:
            m = re.match(r"^asm/([^/]+)", info["path"])
            mod = m.group(1) if m else "_"
            root_funcs[mod].append(info)

    units = []

    # Named groups → one unit per directory
    for unit_name, funcs in sorted(named_groups.items()):
        funcs.sort(key=_func_sort_key)
        units.append(_make_unit(unit_name, funcs))

    # Root-level sub_* functions → chunked
    for mod in sorted(root_funcs):
        funcs = root_funcs[mod]
        funcs.sort(key=_func_sort_key)
        for idx, chunk in enumerate(_chunk_list(funcs, CHUNK_SIZE)):
            units.append(_make_unit(f"{mod}/part_{idx:02d}", chunk))

    return units


def build_report() -> dict:
    statuses = get_func_statuses()
    units = group_funcs_into_units(statuses)

    total_code = sum(u["measures"]["total_code"] for u in units)
    total_fns = sum(u["measures"]["total_functions"] for u in units)
    matched_code = sum(u["measures"]["matched_code"] for u in units)
    matched_fns = sum(u["measures"]["matched_functions"] for u in units)

    if total_code == 0:
        total_code = TOTAL_CODE_SIZE

    matched_pct = (matched_code / total_code * 100.0) if total_code > 0 else 0.0

    report = {
        "measures": {
            "fuzzy_match_percent": matched_pct,
            "total_code": total_code,
            "matched_code": matched_code,
            "total_data": 0,
            "matched_data": 0,
            "total_functions": total_fns,
            "matched_functions": matched_fns,
            "total_units": len(units),
            "complete_units": sum(1 for u in units if u["metadata"]["complete"]),
        },
        "units": units,
    }

    return report


def main():
    parser = argparse.ArgumentParser(
        description="Generate decomp.dev-compatible report.json"
    )
    parser.add_argument(
        "--output",
        "-o",
        default="build/report.json",
        help="Output path for the report JSON (default: build/report.json)",
    )
    args = parser.parse_args()

    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)

    report = build_report()

    with open(output, "w") as f:
        json.dump(report, f, indent=2)

    m = report["measures"]
    total_fn = m["total_functions"]
    match_fn = m["matched_functions"]
    total_units = m["total_units"]
    pct = m["fuzzy_match_percent"]

    print(f"[OK]  Report written to {output}")
    print(f"      Units:     {total_units}")
    print(f"      Functions: {match_fn}/{total_fn} matched")
    print(f"      Progress:  {pct:.2f}%")


if __name__ == "__main__":
    main()
