#!/usr/bin/env python3
"""
resolve_overlaps.py — DashDecomp
Truncates parent function .s files + updates functions.json so the non_overlap
filter includes all individual sub-functions split by Ghidra.

Overlaps happen when Ghidra reports a large function (e.g. 3456 bytes) that
actually contains many smaller named functions. The parent .s file has all the
bytes; child .s files have correct per-function subsets. This tool truncates the
parent .s file to end just before the first child, so the linker places both.

Usage:
    python tools/resolve_overlaps.py [--dry-run] [--verbose]
"""

import argparse, json, re, struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASM_DIR = ROOT / "asm"
FUNCTIONS_JSON = ASM_DIR / "functions.json"
BASE_ADDR = 0x00100000

VA_RE = re.compile(r'([0-9A-Fa-f]{8})')
BYTE_LINE_RE = re.compile(r'\.byte\s+(.*)')

HEADER_LINES = 18


def parse_byte_line(line: str) -> bytes | None:
    m = BYTE_LINE_RE.search(line)
    if not m:
        return None
    parts = [p.strip() for p in m.group(1).split(',')]
    try:
        return bytes(int(p, 16) & 0xFF for p in parts)
    except ValueError:
        return None


def bytes_from_s(path: Path) -> bytes:
    """Extract raw bytes from a .s file's .byte directives."""
    lines = path.read_text().splitlines()
    result = bytearray()
    for line in lines:
        chunk = parse_byte_line(line)
        if chunk is not None:
            result.extend(chunk)
    return bytes(result)


def format_bytes(data: bytes) -> str:
    """Format raw bytes as .byte directives (16 per line)."""
    lines = []
    for i in range(0, len(data), 16):
        chunk = data[i:i+16]
        parts = ', '.join(f'0x{b:02X}' for b in chunk)
        lines.append(f'    .byte {parts}')
    return '\n'.join(lines)


def va_from_path(path: str) -> int | None:
    m = VA_RE.search(path)
    return int(m.group(1), 16) if m else None


def rewrite_s_file(path: Path, truncated_bytes: bytes) -> bool:
    """Truncate a .s file to the given bytes, preserving header and updating Size."""
    content = path.read_text()
    lines = content.splitlines()

    # Find header and label
    header_end = 0
    label = path.stem
    for i, l in enumerate(lines):
        if l.strip().startswith(f'{label}:'):
            header_end = i
            break
    
    if header_end == 0:
        header_end = HEADER_LINES  # fallback
    
    header = lines[:header_end]
    # Update Size comment
    new_header = []
    for l in header:
        if l.strip().startswith('* Size (bytes):'):
            new_header.append(f' * Size (bytes):    {len(truncated_bytes)}')
        else:
            new_header.append(l)

    body = format_bytes(truncated_bytes)
    new_content = '\n'.join(new_header) + '\n\n.section .text\n.global ' + \
        label + '\n.type   ' + label + ', %function\n\n' + \
        label + ':\n' + body + '\n'

    if new_content != content:
        path.write_text(new_content)
        return True
    return False


def main():
    parser = argparse.ArgumentParser(description='Resolve overlapping function stubs')
    parser.add_argument('--dry-run', action='store_true', help='Show without modifying')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    args = parser.parse_args()

    if not FUNCTIONS_JSON.exists():
        print(f"[ERROR] {FUNCTIONS_JSON} not found")
        return 1

    fun_sizes: dict[str, int] = json.loads(FUNCTIONS_JSON.read_text())

    # Build sorted VA -> (path, size) map, excluding asm/data/
    entries: list[tuple[int, str, int]] = []
    for path, size in fun_sizes.items():
        if path.startswith('asm/data/'):
            continue
        va = va_from_path(path)
        if va is not None:
            entries.append((va, path, size))

    entries.sort(key=lambda x: x[0])

    # Walk: track the entry that set cur_end
    cur_end = BASE_ADDR
    # Stores: (va, path, size_at_time_of_placement)
    cur_anchor: tuple[int, str, int] | None = None
    truncations: list[tuple[str, int, int, int]] = []

    for va, path, size in entries:
        if va < cur_end:
            # Overlap: truncate the entry that set cur_end
            if cur_anchor is not None:
                pva, ppath, psize = cur_anchor
                trunc_size = va - pva
                if trunc_size < psize:
                    if trunc_size >= 4:  # minimum useful function size
                        truncations.append((ppath, psize, trunc_size, pva))
                        if args.verbose:
                            print(f"  TRUNC {Path(ppath).name}: {psize} -> {trunc_size} ({Path(path).name} at 0x{va:08X})")
                    # This child becomes the new anchor
                    cur_anchor = (va, path, size)
                    cur_end = va + size
                else:
                    if args.verbose:
                        print(f"  SKIP  {Path(ppath).name}: trunc_size={trunc_size} >= cur_size={psize}")
            continue

        # No overlap
        cur_anchor = (va, path, size)
        cur_end = va + size

    if not truncations:
        print("[OK] No overlaps to resolve")
        return 0

    print(f"[INFO] {len(truncations)} overlaps to resolve")
    if args.verbose:
        print()

    if args.dry_run:
        for path, old, new, va in truncations:
            print(f"  WOULD TRUNC {path}: {old} -> {new} bytes")
        print(f"\n[DRY-RUN] No files modified")
        return 0

    # Apply truncations
    modified_count = 0
    for path, old_size, new_size, va in truncations:
        s_file = ROOT / path
        if not s_file.exists():
            print(f"  [WARN] {s_file} not found, skipping")
            continue

        actual_bytes = bytes_from_s(s_file)
        if len(actual_bytes) < new_size:
            print(f"  [WARN] {path}: .s has {len(actual_bytes)} bytes, "
                  f"less than target {new_size}. Skipping.")
            continue

        truncated = actual_bytes[:new_size]
        if rewrite_s_file(s_file, truncated):
            fun_sizes[path] = new_size
            modified_count += 1
            if args.verbose:
                print(f"  OK  {path}: {old_size} -> {new_size} bytes")
        else:
            print(f"  [WARN] {path}: content unchanged (unexpected)")

    # Save updated functions.json
    FUNCTIONS_JSON.write_text(json.dumps(dict(sorted(fun_sizes.items())), indent=2))

    print(f"\n[RESULT] {modified_count} .s files truncated, functions.json updated")
    print(f"         Then run: python tools/generate_linker_script.py")
    print(f"         Then run: make -j$(nproc) && make check")
    return 0


if __name__ == '__main__':
    exit(main())
