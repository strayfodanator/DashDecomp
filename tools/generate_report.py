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
import bisect
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).parent.parent
ASM_DIR = ROOT / "asm"
SRC_DIR = ROOT / "src"
BUILD_DIR = ROOT / "build"

TOTAL_CODE_SIZE = 5488 * 1024

MATCHING_MARKER = "MATCHING"
NONMATCHING_MARKER = "NONMATCHING"

RETAIL_HASHES = BUILD_DIR / "retail_hashes.csv"
XMAP_PATH = BUILD_DIR / "dlp_symbols/USA/CTRDash.xmap"

# Load xmap for nearest-namespace resolution
XMAP_ADDRS: list[int] = []
XMAP_NS: list[str] = []
if XMAP_PATH.exists():
    try:
        with open(XMAP_PATH) as f:
            for line in f:
                line = line.strip()
                if not line or "\t" not in line:
                    continue
                addr_s, name = line.split("\t", 1)
                addr = int(addr_s, 16)
                XMAP_ADDRS.append(addr)
                if "::" in name:
                    ns = name.split("::")[0]
                else:
                    ns = "<global>"
                XMAP_NS.append(ns)
    except Exception as e:
        print(f"[WARN] Failed to load xmap: {e}")

SYMBOL_SIZES = {}
ADDR_TO_SIZE: dict[int, int] = {}
GHIDRA_TOTAL_CODE = 0

# Load Ghidra retail function sizes (authoritative source)
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
                    GHIDRA_TOTAL_CODE += size
                    name = parts[3] if len(parts) > 3 else ""
                    if name:
                        SYMBOL_SIZES[name] = size
    except Exception as e:
        print(f"[WARN] Failed to load retail_hashes.csv: {e}")


def _get_size(path: str, addr: int | None = None) -> int:
    """Look up function size from Ghidra retail_hashes by address."""
    if addr is not None and addr in ADDR_TO_SIZE:
        return ADDR_TO_SIZE[addr]
    m = re.search(r"([0-9A-Fa-f]{8})", path)
    if m:
        addr2 = int(m.group(1), 16)
        if addr2 in ADDR_TO_SIZE:
            return ADDR_TO_SIZE[addr2]
    return 4


def _addr_from_path(path: str) -> int | None:
    m = re.search(r"sub_([0-9A-Fa-f]{8})", path)
    if m:
        return int(m.group(1), 16)
    return None


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
        size = _get_size(rel_str, addr)
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


def _name_to_ns(name: str) -> str:
    if "::" in name:
        return name.split("::")[0]
    return "<global>"


def _unit_name_for_path(path: str, addr: int | None = None) -> str | None:
    """Derive the unit name from a .s file path.
    Named functions use first-level directory as the unit.
    Root sub_ functions use nearest xmap namespace.
    Named root-level files use their own stem as unit name.
    """
    m = re.match(r"^asm/([^/]+)/", path)
    mod = m.group(1) if m else "_"
    rest = path[len(f"asm/{mod}/"):]
    parts = Path(rest).parts
    if len(parts) > 1:
        return f"{mod}/{parts[0]}"

    stem = Path(rest).stem

    # Named function at module root — use its name as unit
    if not stem.startswith("sub_"):
        return f"{mod}/{stem}"

    # Root-level sub_* — find nearest xmap namespace by address
    if addr is not None and XMAP_ADDRS:
        idx = bisect.bisect_left(XMAP_ADDRS, addr)
        if idx == 0:
            ns = XMAP_NS[0]
        elif idx >= len(XMAP_ADDRS):
            ns = XMAP_NS[-1]
        else:
            d_prev = addr - XMAP_ADDRS[idx - 1]
            d_next = XMAP_ADDRS[idx] - addr
            ns = XMAP_NS[idx - 1] if d_prev <= d_next else XMAP_NS[idx]
        return f"{mod}/{ns}"

    return None


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
        addr = _addr_from_path(info["path"])
        unit = _unit_name_for_path(info["path"], addr)
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
