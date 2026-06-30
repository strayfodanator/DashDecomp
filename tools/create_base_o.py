#!/usr/bin/env python3
"""
create_base_o.py — DashDecomp
Create base ELF .o files from the original code.dec.bin,
mirroring the directory structure under asm/ so that paths
match what objdiff expects.

Usage:
    python tools/create_base_o.py
"""

import re
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASM_DIR = ROOT / "asm"
BASE_DIR = ROOT / "build" / "base"
ORIG_CODE = ROOT / "build" / "code.dec.bin"
BASE_ADDR = 0x00100000

# ── ELF constants ──────────────────────────────────────────────────────────────
ET_REL = 1
EM_ARM = 40
EV_CURRENT = 1

SHT_PROGBITS = 1
SHT_SYMTAB = 2
SHT_STRTAB = 3

SHF_ALLOC = 2
SHF_EXECINSTR = 4
SHF_STRINGS = 32

STB_GLOBAL = 1
STT_FUNC = 2
STT_OBJECT = 1
STV_DEFAULT = 0

# ── ELF object builder ─────────────────────────────────────────────────────────

def make_elf32_o(data: bytes, symbol: str, is_func: bool = True) -> bytes:
    """
    Create a minimal ELF32 relocatable object (.o) with:
      - .text section containing `data`
      - a global symbol pointing to .text start
      - .symtab, .strtab, .shstrtab
    """
    shnum = 5
    shstrndx = 4

    # Align .text to 4 bytes
    text_align = 4
    text_padding = (text_align - len(data) % text_align) % text_align
    text_data = data + b'\xff' * text_padding  # padding with 0xff (unused)
    text_size = len(text_data)

    # Section name string table
    shstr_data = b'\x00' + b'.text\x00' + b'.symtab\x00' + b'.strtab\x00' + b'.shstrtab\x00'

    # Symbol name string table (leading null, then symbol name)
    sym_name = symbol.encode('utf-8') + b'\x00'
    strtab_data = b'\x00' + sym_name

    # Symbol table: NULL entry + function/data entry
    sym_info = (STB_GLOBAL << 4) | (STT_FUNC if is_func else STT_OBJECT)
    null_entry = b'\x00' * 16
    sym_entry = struct.pack('<IIIBBH',
        1,              # st_name (offset 1 in .strtab, skip leading null)
        0,              # st_value (offset within section)
        0,              # st_size (0 to match assembler without .size)
        sym_info,
        STV_DEFAULT,
        1,              # st_shndx (.text section index)
    )
    symtab_data = null_entry + sym_entry

    # ── Layout ───────────────────────────────────────────────────────────────────
    eh_size = 52
    sh_size = 40
    sh_offset = eh_size
    data_offset = (sh_offset + shnum * sh_size + 3) & ~3  # align to 4

    text_offset = data_offset
    symtab_offset = text_offset + text_size
    strtab_offset = symtab_offset + len(symtab_data)
    shstrtab_offset = strtab_offset + len(strtab_data)

    total_size = shstrtab_offset + len(shstr_data)
    total_size = (total_size + 3) & ~3

    # ── ELF header ───────────────────────────────────────────────────────────────
    e_ident_payload = struct.pack('<BBBBBBBBBBBB',
        1, 1, EV_CURRENT, 0, 0,
        0, 0, 0, 0, 0, 0, 0,
    )
    ehdr = struct.pack('<4s12sHHI4I6H',
        b'\x7fELF', e_ident_payload,
        ET_REL,
        EM_ARM,
        EV_CURRENT,
        0,              # e_entry
        0,              # e_phoff
        sh_offset,
        0,              # e_flags
        eh_size,        # e_ehsize
        0,              # e_phentsize
        0,              # e_phnum
        sh_size,        # e_shentsize
        shnum,
        shstrndx,
    )

    # ── Section headers ──────────────────────────────────────────────────────────
    def sh(name_off, stype, flags, offset, size, link=0, info=0, align=1, es=0):
        return struct.pack('<IIIIIIIIII',
            name_off, stype, flags, 0, offset, size, link, info, align, es,
        )

    sh_null    = b'\x00' * sh_size
    sh_text    = sh(1,  SHT_PROGBITS, SHF_ALLOC | SHF_EXECINSTR, text_offset,    text_size,     align=text_align)
    sh_symtab  = sh(8,  SHT_SYMTAB,   0,                          symtab_offset,  len(symtab_data), link=3, info=1, align=4, es=16)
    sh_strtab  = sh(16, SHT_STRTAB,   0,                          strtab_offset,  len(strtab_data))
    sh_shstrtab= sh(24, SHT_STRTAB,   SHF_STRINGS,                shstrtab_offset, len(shstr_data))

    shdrs = sh_null + sh_text + sh_symtab + sh_strtab + sh_shstrtab

    # ── Data ─────────────────────────────────────────────────────────────────────
    data_block = text_data + symtab_data + strtab_data + shstr_data
    data_block += b'\x00' * ((4 - len(data_block) % 4) % 4)

    result = ehdr + shdrs + data_block
    # Pad total to alignment
    if len(result) < total_size:
        result += b'\x00' * (total_size - len(result))
    return result


# ── VA extraction ──────────────────────────────────────────────────────────────

VA_RE = re.compile(r'(?:^|_)([0-9a-fA-F]{8})\.s$')

def va_from_stem(stem: str) -> int | None:
    m = VA_RE.search(stem)
    if m:
        return int(m.group(1), 16)
    return None


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    if not ORIG_CODE.exists():
        print(f"[ERROR] {ORIG_CODE} not found.")
        return
    with open(ORIG_CODE, 'rb') as f:
        code = f.read()

    asm_files = sorted(ASM_DIR.rglob('*.s'))

    # Load functions.json for size hints (but also read .s files for VA)
    import json
    fjson_path = ASM_DIR / 'functions.json'
    fun_sizes: dict[str, int] = {}
    if fjson_path.exists():
        with open(fjson_path) as f:
            fun_sizes = json.load(f)

    print(f"[INFO] Processing {len(asm_files)} assembly stubs...")
    created = 0
    errors = 0

    for s_path in asm_files:
        rel = s_path.relative_to(ASM_DIR)
        stem = s_path.stem

        va = va_from_stem(stem)
        if va is None:
            # fallback: look up in functions.json by relative path
            key = f"asm/{rel}"
            size = fun_sizes.get(key, 0)
            if size == 0:
                print(f"[WARN] Cannot determine VA for {rel}")
                errors += 1
                continue
            # Try to find size from functions.json
            va = int(stem.split('_')[-1], 16) if '_' in stem else 0
            if va == 0:
                errors += 1
                continue

        offset = va - BASE_ADDR
        key = f"asm/{rel}"
        expected_size = fun_sizes.get(key, 0)

        # Read bytes from original binary
        if expected_size == 0:
            # Guess from file size? Just try to read what's available
            print(f"[WARN] No size info for {rel}, skipping")
            errors += 1
            continue

        if offset < 0 or offset + expected_size > len(code):
            print(f"[WARN] {rel}: out of range (VA=0x{va:08X}, size={expected_size})")
            errors += 1
            continue

        bytes_data = code[offset:offset + expected_size]

        # Determine symbol name from stem
        sym = stem

        # Create output directory
        out_path = BASE_DIR / rel.parent / f"{stem}.o"
        out_path.parent.mkdir(parents=True, exist_ok=True)

        elf_data = make_elf32_o(bytes_data, sym, is_func=True)
        with open(out_path, 'wb') as f:
            f.write(elf_data)

        created += 1
        if created % 2000 == 0:
            print(f"  ... {created}/{len(asm_files)}")

    print(f"\n[RESULT] Created: {created}, Errors: {errors}, Total stubs: {len(asm_files)}")


if __name__ == '__main__':
    main()
