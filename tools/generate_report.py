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

RETAIL_HASHES = BUILD_DIR / "retail_hashes.csv"

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


def _is_data_like(s_file: Path) -> bool:
    """Detect if a .s file is data (jump table, constant pool, vtable) masquerading as code.
    Checks if the last 4 bytes don't form a valid return instruction and no return exists
    in the last 10 instructions."""
    try:
        lines = s_file.read_text().splitlines()
    except Exception:
        return False
    byte_re = re.compile(r'\.byte\s+(.*)')
    data = bytearray()
    for line in lines:
        m = byte_re.search(line)
        if m:
            parts = [p.strip() for p in m.group(1).split(',')]
            try:
                data.extend(bytes(int(p, 16) & 0xFF for p in parts))
            except ValueError:
                pass
    if len(data) < 4:
        return False
    inst = data[-4:]
    v = int.from_bytes(inst, 'little')
    # Check if last instruction is a valid return
    if (v & 0x0FFFFFF0) == 0x012FFF10: return False       # bx rN (any condition)
    if (v & 0x0FFFFFF0) == 0x012FFF30: return False       # blx rN (any condition)
    if (v & 0x0E000000) == 0x0A000000: return False       # B/BL/BLX imm (any condition)
    if (v & 0x0FFFF000) == 0x01A0F000: return False       # mov pc, rN (any condition)
    if (v & 0x0FFFF000) == 0x01B0F000: return False       # movs pc, rN (any condition)
    if (v & 0x0FF00000) == 0x08B00000 and (v & (1 << 15)): return False  # pop {..pc}
    if (v & 0x0FF00000) == 0x08F00000 and (v & (1 << 15)): return False  # pop {..pc}^ (S=1)
    if v == 0xE1A00000: return False                       # nop (uncond)
    # ldr pc, [sp], #imm / [sp, #imm] (any W flag)
    if ((v >> 12) & 0xF) == 15 and ((v >> 16) & 0xF) == 13:
        if (v & 0x0F900000) == 0x04900000: return False   # post-indexed W=0
        if (v & 0x0F900000) == 0x04D00000: return False   # post-indexed W=1
        if (v & 0x0F900000) == 0x05900000: return False   # pre-indexed W=0
        if (v & 0x0F900000) == 0x05D00000: return False   # pre-indexed W=1
    if v == 0xE25EF004: return False                       # subs pc, lr, #4
    if (v & 0xFF000000) == 0xEF000000: return False        # swi
    # Check backwards for return (literal pool after code)
    for off in range(4, min(40, len(data)), 4):
        chunk = data[-off-4:-off] if off+4 <= len(data) else data[:4]
        if len(chunk) != 4: continue
        cv = int.from_bytes(chunk, 'little')
        if (cv & 0x0FFFFFF0) == 0x012FFF10: return False
        if (cv & 0x0E000000) == 0x0A000000: return False
        if (cv & 0x0FFFF000) == 0x01A0F000: return False
    # Last resort: top byte outside typical ARM instruction range
    b3 = inst[3]
    if b3 >= 0x70 or b3 <= 0x02:
        return True
    return True


def _size_from_file(s_file: Path) -> int | None:
    """Extract size from the .s file header 'Size (bytes):' comment."""
    try:
        with open(s_file, "rb") as fh:
            head = fh.read(4096)
        m = re.search(rb"Size \(bytes\):\s*(\d+)", head)
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return None


def _addr_from_file(s_file: Path) -> int | None:
    """Extract virtual address from a .s file's metadata comment."""
    m = re.search(r"sub_([0-9A-Fa-f]{8})", s_file.name)
    if m:
        return int(m.group(1), 16)
    try:
        with open(s_file, "rb") as fh:
            head = fh.read(4096)
        m = re.search(rb"Virtual Address:\s*0x([0-9A-Fa-f]{8})", head)
        if m:
            return int(m.group(1), 16)
        m = re.search(rb"sub_([0-9A-Fa-f]{8})", head)
        if m:
            return int(m.group(1), 16)
    except Exception:
        pass
    return None


def get_func_statuses() -> dict[str, dict]:
    statuses = {}

    for cpp_file in sorted(SRC_DIR.rglob("*.cpp")):
        text = cpp_file.read_text(errors="ignore")

        for match in re.finditer(
            r"\b(MATCHING|NONMATCHING)\b(?:\s*[:\-(\s]\s*)?([A-Za-z_][A-Za-z0-9_]*_[0-9A-Fa-f]{8})?",
            text,
        ):
            status = match.group(1)
            symbol = match.group(2)

            size = 100
            if symbol and symbol in SYMBOL_SIZES:
                size = SYMBOL_SIZES[symbol]
            elif not symbol:
                sub_match = re.search(r"\b([A-Za-z_][A-Za-z0-9_]*_[0-9A-Fa-f]{8})\b", text)
                if sub_match and sub_match.group(1) in SYMBOL_SIZES:
                    size = SYMBOL_SIZES[sub_match.group(1)]

            key = symbol or str(cpp_file.relative_to(ROOT))
            if key and key not in statuses:
                statuses[key] = {
                    "path": f"{cpp_file.relative_to(ROOT)}:{key}",
                    "status": status,
                    "size": size,
                }

    for s_file in sorted(ASM_DIR.rglob("*.s")):
        rel = s_file.relative_to(ROOT)
        rel_str = str(rel)
        if "/data/" in rel_str or s_file.stem.startswith("DAT_"):
            continue
        if _is_data_like(s_file):
            continue
        addr = _addr_from_file(s_file)
        size = _size_from_file(s_file)
        if size is None:
            size = _get_size(rel_str, addr)
        key = s_file.stem
        if key not in statuses:
            statuses[key] = {
                "path": rel_str,
                "status": "NODECOMPILED",
                "size": size,
                "addr": addr or 0,
            }

    return statuses


def _func_label(path: str) -> str:
    path = path.split(":")[0]
    stem = Path(path).stem
    m = re.match(r"^(.+?)_([0-9A-Fa-f]{8})$", stem)
    if m and m.group(1) != "sub":
        return m.group(1)
    return stem


def _unit_name(path: str) -> str:
    path = path.split(":")[0]
    m = re.match(r"^(?:asm|src)/([^/]+)/", path)
    mod = m.group(1) if m else "_"
    prefix = f"asm/{mod}/" if path.startswith("asm/") else f"src/{mod}/"
    rest = path[len(prefix):]
    parts = Path(rest).parts
    if len(parts) > 1:
        unit = f"{mod}/{parts[0]}"
    else:
        unit = mod
    return unit.replace("<", "_").replace(">", "_")


def _func_sort_key(info: dict) -> int:
    path = info["path"]
    m = re.search(r"([0-9A-Fa-f]{8})", path)
    return int(m.group(1), 16) if m else 0


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
                "metadata": {"virtual_address": f.get("addr", 0)},
            }
            for f in funcs
        ],
    }


def group_funcs_into_units(statuses: dict[str, dict]) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for stem, info in statuses.items():
        unit = _unit_name(info["path"])
        groups[unit].append(info)

    units = []
    for unit_name, funcs in sorted(groups.items()):
        funcs.sort(key=_func_sort_key)
        units.append(_make_unit(unit_name, funcs))
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
