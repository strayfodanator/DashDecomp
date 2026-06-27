#!/usr/bin/env bash
# DashDecomp — Ghidra Headless Symbol Extraction Pipeline
#
# This script automates the full BSim/symbol extraction flow:
#   1. Import and analyze the DLP code.bin (which has C++ RTTI strings)
#   2. Export all found symbols + strings to CSV/TXT
#   3. Run tools/import_symbols.py to rename our sub_XXXXXXXX.s stubs
#      to their real names using the extracted data
#
# Prerequisites:
#   - ghidra-analyzeHeadless must be installed (/usr/bin/ghidra-analyzeHeadless)
#   - build/dlp_exefs/code.bin must exist (run tools/extract.py first)
#   - Java 17+ for Ghidra
#
# Usage:
#   chmod +x tools/ghidra_extract_symbols.sh
#   ./tools/ghidra_extract_symbols.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$SCRIPT_DIR/.."

DLP_BIN="$ROOT/build/dlp_exefs/code.bin"
RETAIL_BIN="$ROOT/build/code.dec.bin"
GHIDRA_PROJECT="$ROOT/build/ghidra_project"
SCRIPT_PATH="$ROOT/tools/ghidra"

if [[ ! -f "$DLP_BIN" ]]; then
    echo "[ERR] DLP binary not found: $DLP_BIN"
    echo "      Run: python tools/extract.py"
    exit 1
fi

if [[ ! -f "$RETAIL_BIN" ]]; then
    echo "[ERR] Retail binary not found: $RETAIL_BIN"
    echo "      Run: python tools/extract.py"
    exit 1
fi

mkdir -p "$GHIDRA_PROJECT"

echo ""
echo "══════════════════════════════════════════════════════"
echo " DashDecomp — Ghidra Symbol Extraction"
echo "══════════════════════════════════════════════════════"
echo ""

# ── Step 1: Import and analyze DLP binary ─────────────────────────────────────
echo "[1/3] Importing DLP binary into Ghidra..."
echo "      Binary: $DLP_BIN"
echo "      This will take ~5-15 minutes for full auto-analysis..."
echo ""

ghidra-analyzeHeadless \
    "$GHIDRA_PROJECT" "MK7_DLP" \
    -import "$DLP_BIN" \
    -processor "ARM:LE:32:v8" \
    -cspec "default" \
    -loader BinaryLoader \
    -loader-baseAddr 0x00100000 \
    -overwrite \
    -postScript ExtractSymbols.java \
    -scriptPath "$SCRIPT_PATH" \
    -scriptlog "$ROOT/build/ghidra_dlp.log" \
    -log "$ROOT/build/ghidra_import.log" \
    2>&1 | tee "$ROOT/build/ghidra_stdout.log"

echo ""
echo "[2/3] Checking output files..."
ls -lh "$ROOT/build/dlp_symbols.csv" "$ROOT/build/dlp_strings.txt" 2>/dev/null || {
    echo "[WARN] Symbol files not found in build/. Checking inside project dir..."
    find "$GHIDRA_PROJECT" -name "dlp_symbols.csv" -o -name "dlp_strings.txt" 2>/dev/null | head -5
}

# ── Step 2: Import symbols into our stub system ────────────────────────────────
echo ""
echo "[3/3] Importing symbols into DashDecomp stub map..."
source "$ROOT/.venv/bin/activate" 2>/dev/null || true

if [[ -f "$ROOT/build/dlp_symbols.csv" ]]; then
    python "$ROOT/tools/import_symbols.py" \
        --symbols "$ROOT/build/dlp_symbols.csv" \
        --strings "$ROOT/build/dlp_strings.txt" \
        --retail "$RETAIL_BIN" \
        --dlp "$DLP_BIN"
else
    echo "[WARN] dlp_symbols.csv not found. Run the Ghidra step first."
fi

echo ""
echo "══════════════════════════════════════════════════════"
echo " Done! Check build/dlp_symbols.csv for extracted names"
echo "══════════════════════════════════════════════════════"
