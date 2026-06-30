# DashDecomp — Agent Context

## Goal
Decompile Mario Kart 7 (3DS, v1.0 USA) from binary → matching C++.  
Target: `arm-none-eabi-g++ -march=armv6k -mfloat-abi=hard -mfpu=vfpv2 -mthumb-interwork -O2 -fno-rtti -fno-exceptions -fshort-wchar -std=c++11`

## Build
- `make -j$(nproc)` → `build/dashdecomp.elf` → `build/dashdecomp.bin`
- `make check` — compares `build/dashdecomp.bin` vs `build/code.dec.bin` (must be byte-identical)

## Project State (current)

| Metric | Value |
|---|---|
| Total stubs in `asm/` (excl. `asm/data/`) | 15.109 |
| MATCHING C++ | 1.569 |
| Non-overlap linker entries | 15.109 |
| Data stubs (`asm/data/DAT_*`) | ~10.144 (auto-generated, not in report) |
| Functions in decomp.dev report | 13.264 (after filtering ~1.846 data pseudo-functions) |
| Bad boundaries (< 1%) | 0 (all aligned) |
| `make check` | **PASS** |
| `.text` matched bytes | **29.696 / 3.657.812 (0,81%)** |

## Linking Model (IMPORTANT — removed `. = VA;` lines)
- Linker script has **no** `. = address;` lines
- `.text 0x100000 : { KEEP(a.o(.text)) KEEP(b.o(.text)) ... }`
- Linker concatenates .o `.text` sections sequentially in VA order
- Each .o file's `.text` section contains the exact binary bytes for its span
- `asm/data/DAT_*` stubs fill gaps between function .o files → 100% coverage
- **Never add `. = VA;` back** — it causes linker padding bugs

## Overlap Resolution (DONE)
- `tools/resolve_overlaps.py` truncated 392 parent .s files to end before first child
- `functions.json` updated with new sizes
- All 637 overlaps → 0 remaining
- After truncation, regenerate: `python tools/generate_linker_script.py && make -j$(nproc) && make check`

## Data Pseudo-Functions
~1.846 entries in `functions.json` are data (jump tables, constant pools, vtables) mislabeled as functions. Detected by: last 4 bytes look like addresses/data (high nibble pattern, 0x75F1B26B etc.). They are excluded from the decomp.dev report, never decompiled.

## Known Issues
1. **~1.846 data pseudo-functions** — in report, inflate function count (jump tables, constant pools, vtables mislabeled as functions). Detected by: last 4 bytes look like addresses/data. Should be excluded from decomp.dev report, never decompiled.
2. **0 bad boundaries** — all 15.109 stubs have correct instruction-aligned boundaries (verified).

## Useful Commands
- `python tools/resolve_overlaps.py` — truncate overlapping stubs
- `python tools/generate_linker_script.py` — regenerate linker script + data stubs
- `python tools/generate_report.py` — generate decomp.dev report
- `python tools/validate_returns.py` — find stubs without valid return
- `make check` — verify binary match

## Files
- `config/mk7.ld` — linker script (25k+ KEEP entries, no `. = VA;`)
- `asm/functions.json` — VA → size map for all stubs
- `build/retail_hashes.csv` — Ghidra function list (address, size, name)
- `build/report.json` — decomp.dev compatible progress report
