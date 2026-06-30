#!/usr/bin/env python3
"""
generate_linker_script.py — DashDecomp

1. Scans asm/ for function stubs, builds VA → target .o mapping
2. Finds data gaps in the original binary not covered by stubs
3. Creates ELF .o files + .s stubs for data regions
4. Generates config/mk7.ld with exact-per-VA placement

Usage:
    python tools/generate_linker_script.py
"""

import json, re, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASM_DIR = ROOT / "asm"
BUILD_DIR = ROOT / "build"
BASE_DIR = BUILD_DIR / "base"
CONFIG_DIR = ROOT / "config"
ORIG_CODE = BUILD_DIR / "code.dec.bin"
LINKER_SCRIPT = CONFIG_DIR / "mk7.ld"

BASE_ADDR = 0x00100000
BINARY_SIZE = 5619712
BINARY_END = BASE_ADDR + BINARY_SIZE

VA_RE = re.compile(r'_([0-9a-fA-F]{8})(?:\.[^.]*)?$')


def va_from_stem(stem: str) -> int | None:
    m = VA_RE.search(stem)
    return int(m.group(1), 16) if m else None


def make_elf_o(data: bytes, sym: str, section: str) -> bytes:
    """Create minimal ELF32 .o with named section ('.text' or '.rodata')."""
    shnum, shstrndx = 5, 4
    pad = (4 - len(data) % 4) % 4
    tdata = data + b'\x00' * pad
    tsz = len(tdata)
    is_code = section == '.text'
    flags = 6 if is_code else 2
    stt = 2 if is_code else 1

    sec_enc = section.encode() + b'\x00'
    shstr = b'\x00' + sec_enc + b'.symtab\x00.strtab\x00.shstrtab\x00'

    strtab = b'\x00' + sym.encode() + b'\x00'
    sym_entry = struct.pack('<IIIBBH', 1, 0, 0, (1 << 4) | stt, 0, 1)
    symtab = b'\x00' * 16 + sym_entry

    eh_sz, sh_sz = 52, 40
    sh_off = eh_sz
    d_off = (sh_off + shnum * sh_sz + 3) & ~3

    to = d_off
    so = to + tsz
    stro = so + len(symtab)
    shstro = stro + len(strtab)
    total = max((shstro + len(shstr) + 3) & ~3, 1)

    eid = struct.pack('<BBBBBBBBBBBB', 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    ehdr = struct.pack('<4s12sHHI4I6H',
        b'\x7fELF', eid, 1, 40, 1, 0, 0, sh_off, 0, eh_sz, 0, 0, sh_sz, shnum, shstrndx)

    def mk_sh(no, ty, fl, off, sz, lk=0, inf=0, al=1, es=0):
        return struct.pack('<IIIIIIIIII', no, ty, fl, 0, off, sz, lk, inf, al, es)

    sn = 1  # offset of section name in shstr
    shdrs = (b'\x00' * sh_sz +
             mk_sh(sn, 1, flags, to, tsz, al=4) +
             mk_sh(sn + len(sec_enc), 2, 0, so, len(symtab), lk=3, inf=1, al=4, es=16) +
             mk_sh(sn + len(sec_enc) + 8, 3, 0, stro, len(strtab)) +
             mk_sh(sn + len(sec_enc) + 16, 3, 32, shstro, len(shstr)))

    blk = tdata + symtab + strtab + shstr
    blk += b'\x00' * ((4 - len(blk) % 4) % 4)
    r = ehdr + shdrs + blk
    return r + b'\x00' * max(0, total - len(r))


def main():
    if not ORIG_CODE.exists():
        print(f"[ERROR] {ORIG_CODE} not found"); sys.exit(1)
    code = ORIG_CODE.read_bytes()

    # ── Load function sizes ─────────────────────────────────────────────────
    fjson = ASM_DIR / "functions.json"
    fun_sizes: dict[str, int] = json.loads(fjson.read_text()) if fjson.exists() else {}
    va_sizes: dict[int, int] = {}
    for path, size in fun_sizes.items():
        va = va_from_stem(path)
        if va is not None:
            va_sizes[va] = size

    def stub_size(va: int) -> int:
        return va_sizes.get(va, 0)

    # ── Scan function stubs (asm) ──────────────────────────────────────────
    print("[INFO] Scanning asm/ for function stubs...")
    stubs: dict[int, Path] = {}  # va → build/...o path
    for sfile in sorted(ASM_DIR.rglob("*.s")):
        if sfile.parent.name == "data" and sfile.stem.startswith("DAT_"):
            continue  # skip auto-generated data stubs
        va = va_from_stem(sfile.stem)
        if va is None:
            continue
        stubs[va] = BUILD_DIR / "asm" / sfile.relative_to(ASM_DIR).with_suffix('.o')

    print(f"       {len(stubs)} asm stubs with VA")

    # ── C++ source overrides ───────────────────────────────────────────────
    SRC_DIR = ROOT / "src"
    print(f"[INFO] Scanning {SRC_DIR} for C++ replacements...")
    src_overrides = 0
    for cppfile in sorted(SRC_DIR.rglob("*.cpp")):
        va = va_from_stem(cppfile.stem)
        if va is None:
            continue
        src_o = BUILD_DIR / "src" / cppfile.relative_to(SRC_DIR).with_suffix('.o')
        if va in stubs:
            print(f"       Override: asm -> src for VA 0x{va:08X} ({cppfile.stem})")
        else:
            print(f"       Add: src for VA 0x{va:08X} ({cppfile.stem})")
        stubs[va] = src_o
        src_overrides += 1

    print(f"       {src_overrides} C++ overrides")
    print(f"       {len(stubs)} total stubs with VA")

    # ── Build non-overlapping function list ─────────────────────────────────
    print("[INFO] Filtering to non-overlapping functions...")

    sorted_all = sorted(stubs)
    non_overlap: list[int] = []
    cur_end = BASE_ADDR
    for va in sorted_all:
        if va >= cur_end:
            non_overlap.append(va)
            sz = stub_size(va)
            cur_end = va + sz

    # ── Find data gaps ──────────────────────────────────────────────────────
    print("[INFO] Finding data gaps...")
    gaps: list[tuple[int, int]] = []
    cur_end = BASE_ADDR
    for va in non_overlap:
        if va > cur_end:
            gaps.append((cur_end, va - cur_end))
        sz = stub_size(va)
        cur_end = max(cur_end, va + sz)
    if cur_end < BINARY_END:
        gaps.append((cur_end, BINARY_END - cur_end))

    total_gap = sum(sz for _, sz in gaps)
    total_fun = sum(stub_size(va) for va in non_overlap)
    print(f"       {len(non_overlap)} non-overlapping functions")
    print(f"       {len(gaps)} gaps, {total_gap:,} bytes")
    print(f"       Coverage: {total_fun + total_gap:,} / {BINARY_SIZE:,}")

    # ── Create data region objects ──────────────────────────────────────────
    print("[INFO] Creating data region .o files...")
    asm_data = ASM_DIR / "data"
    base_data = BASE_DIR / "data"
    asm_data.mkdir(parents=True, exist_ok=True)
    base_data.mkdir(parents=True, exist_ok=True)

    data_map: dict[int, str] = {}  # va → label
    for va, sz in gaps:
        if sz < 4:
            continue
        off = va - BASE_ADDR
        raw = code[off:off + sz]
        label = f"DAT_{va:08X}"
        data_map[va] = label

        base_data.joinpath(f"{label}.o").write_bytes(make_elf_o(raw, label, '.text'))
        hex_bytes = ', '.join(f'0x{b:02X}' for b in raw)
        asm_data.joinpath(f"{label}.s").write_text(
            f'.section .text\n.global {label}\n{label}:\n    .byte {hex_bytes}\n')

    print(f"       {len(data_map)} data objects")

    # ── Generate linker script ──────────────────────────────────────────────
    print(f"[INFO] Generating {LINKER_SCRIPT}...")
    lines = [
        'OUTPUT_FORMAT("elf32-littlearm")',
        'OUTPUT_ARCH(arm)',
        '',
        'SECTIONS',
        '{',
        '    .text 0x00100000 :',
        '    {',
    ]

    # Build combined sorted list: (va, type, path)
    regions = []
    for va in non_overlap:
        regions.append((va, "FUNC", stubs[va]))
    for va, label in data_map.items():
        regions.append((va, "DATA", BUILD_DIR / "asm" / "data" / f"{label}.o"))
    regions.sort(key=lambda r: r[0])

    for va, rtype, path in regions:
        lines.append(f'        KEEP({path}(.text))')

    lines.append('')
    lines.append('    }')
    lines.append('')
    lines.append('    /DISCARD/ : { *(*) }')
    lines.append('}')

    LINKER_SCRIPT.write_text('\n'.join(lines))
    print(f"       -> {LINKER_SCRIPT} ({len(lines)} lines)")

    print()
    print(f"[RESULT] Non-overlap functions: {len(non_overlap)}, Data: {len(data_map)}")
    print(f"         Fun bytes: {total_fun:,}, Gap bytes: {total_gap:,}")
    total = total_fun + total_gap
    print(f"         Total:     {total:,} / {BINARY_SIZE:,}")
    if total == BINARY_SIZE:
        print("         STATUS: FULL COVERAGE")
    else:
        print(f"         MISSING:  {BINARY_SIZE - total:,} bytes ({100*total/BINARY_SIZE:.1f}%)")


if __name__ == '__main__':
    main()
