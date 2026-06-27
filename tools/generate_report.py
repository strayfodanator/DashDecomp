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

SYMBOL_SIZES = {}
STUB_SIZES = {}

if FUNCTIONS_JSON.exists():
    try:
        manifest = json.loads(FUNCTIONS_JSON.read_text())
        for rel_path, size in manifest.items():
            STUB_SIZES[rel_path] = size
            symbol_name = Path(rel_path).stem
            SYMBOL_SIZES[symbol_name] = size
    except Exception as e:
        print(f"[WARN] Failed to load functions manifest: {e}")


def get_func_statuses() -> dict[str, dict]:
    """
    Scan asm/ and src/ and return a dict mapping function path stem → status info.
      status: "MATCHING" | "NONMATCHING" | "NODECOMPILED"
    """
    statuses = {}

    for s_file in sorted(ASM_DIR.rglob("*.s")):
        rel = s_file.relative_to(ROOT)
        rel_str = str(rel)
        size = STUB_SIZES.get(rel_str, 4)
        stem = s_file.stem
        statuses[stem] = {
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

            key = symbol or cpp_file.stem
            if key and key not in statuses:
                statuses[key] = {
                    "path": f"{cpp_file.relative_to(ROOT)}:{key}",
                    "status": status,
                    "size": size,
                }

    return statuses


CHUNK_SIZE = 50


def _func_label(path: str) -> str:
    """Extract display name from an asm path.
    e.g. asm/Item/Enemy/AIRankGroupMiddle/getGroupKind.s → Enemy/AIRankGroupMiddle/getGroupKind
         asm/Item/sub_00470030.s                          → sub_00470030
    """
    stem = Path(path).stem
    m = re.match(r"^asm/[^/]+/(.+)", path)
    if m:
        return Path(m.group(1)).with_suffix("").as_posix()
    return stem


def _extract_sub_addr(path: str) -> int | None:
    """Extract address from a sub_XXXXXXXX path like asm/Item/sub_00470030.s → 0x00470030"""
    m = re.search(r"sub_([0-9A-Fa-f]{8})", path)
    return int(m.group(1), 16) if m else None


def _is_root_func(path: str) -> bool:
    """True if the .s file sits directly in the module root."""
    return bool(re.match(r"^asm/[^/]+/sub_", path))


def _chunk_list(lst: list, size: int):
    """Yield successive chunks of `size` from lst."""
    for i in range(0, len(lst), size):
        yield lst[i : i + size]


def group_funcs_into_units(
    statuses: dict[str, dict],
) -> list[dict]:
    """
    Group functions into Units.

    - Functions in subdirectories → grouped by leaf directory
      (e.g. Item/Enemy/AIRankGroupMiddle)
    - Root-level unnamed functions → chunked into groups of CHUNK_SIZE
      (e.g. Item/_unk_000, Item/_unk_001, …)
    """
    # Separate root vs subdirectory functions
    subdir_funcs: dict[str, list[dict]] = defaultdict(list)
    root_funcs: dict[str, list[dict]] = defaultdict(list)

    for stem, info in statuses.items():
        path = info["path"]
        m = re.match(r"^asm/([^/]+)", path)
        mod = m.group(1) if m else "_"

        if _is_root_func(path):
            root_funcs[mod].append(info)
        else:
            # Use leaf directory as unit name
            m2 = re.match(r"^asm/(.+)/[^/]+$", path)
            unit_name = m2.group(1) if m2 else stem
            subdir_funcs[unit_name].append(info)

    units = []

    # ── Build subdirectory units ──────────────────────────────────────────
    for unit_name, funcs in sorted(subdir_funcs.items()):
        total_code = sum(f["size"] for f in funcs)
        matched_code = sum(f["size"] for f in funcs if f["status"] == "MATCHING")
        total_fns = len(funcs)
        matched_fns = sum(1 for f in funcs if f["status"] == "MATCHING")
        fuzzy_pct = (matched_code / total_code * 100.0) if total_code > 0 else 0.0
        complete = matched_fns == total_fns

        functions_list = [
            {
                "name": _func_label(f["path"]),
                "size": f["size"],
                "fuzzy_match_percent": 100.0 if f["status"] == "MATCHING" else 0.0,
                "metadata": {"virtual_address": 0},
            }
            for f in funcs
        ]

        units.append({
            "name": unit_name,
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
            "functions": functions_list,
        })

    # ── Build root-level chunked units ────────────────────────────────────
    for mod in sorted(root_funcs):
        funcs = root_funcs[mod]
        # Sort by the sub_ address so chunks are contiguous
        funcs.sort(key=lambda f: f["path"])
        for idx, chunk in enumerate(_chunk_list(funcs, CHUNK_SIZE)):
            # Use address range for chunk name
            first_addr = _extract_sub_addr(chunk[0]["path"])
            last_addr = _extract_sub_addr(chunk[-1]["path"]) + chunk[-1]["size"] - 1
            if first_addr and last_addr:
                chunk_name = f"{mod}/{first_addr:08X}_{last_addr:08X}"
            else:
                chunk_name = f"{mod}/_unk_{idx:03d}"
            total_code = sum(f["size"] for f in chunk)
            matched_code = sum(f["size"] for f in chunk if f["status"] == "MATCHING")
            total_fns = len(chunk)
            matched_fns = sum(1 for f in chunk if f["status"] == "MATCHING")
            fuzzy_pct = (matched_code / total_code * 100.0) if total_code > 0 else 0.0
            complete = matched_fns == total_fns

            functions_list = [
                {
                    "name": _func_label(f["path"]),
                    "size": f["size"],
                    "fuzzy_match_percent": 100.0 if f["status"] == "MATCHING" else 0.0,
                    "metadata": {"virtual_address": 0},
                }
                for f in chunk
            ]

            units.append({
                "name": chunk_name,
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
                "functions": functions_list,
            })

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
