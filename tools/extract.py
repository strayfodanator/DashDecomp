#!/usr/bin/env python3
"""
DashDecomp - Mario Kart 7 Decompilation Project
extract.py: Extracts and decompresses code.bin from baserom/game.3ds

Usage:
    python tools/extract.py

Requires:
    - baserom/game.3ds (or baserom/game.cia)
    - ctrtool and 3dstool in PATH (installed by setup.sh)
"""

import os
import sys
import shutil
import subprocess
import hashlib
import struct
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────
ROOT        = Path(__file__).resolve().parent.parent
BASEROM_DIR = ROOT / "baserom"
BUILD_DIR   = ROOT / "build"
TOOLS_DIR   = ROOT / "tools"

BASEROM_3DS = BASEROM_DIR / "game.3ds"
BASEROM_CIA = BASEROM_DIR / "game.cia"

# Output paths
EXEFS_DIR   = BUILD_DIR / "exefs"
CODE_BIN    = BUILD_DIR / "code.bin"          # Compressed (raw from ExeFS)
CODE_DEC    = BUILD_DIR / "code.dec.bin"      # Decompressed (used for disassembly)

# ── Known MD5 hashes for code.bin (decompressed) ─────────────────────────────
KNOWN_HASHES = {
    # v1.0 USA — MD5 confirmed from community dump
    "usa_v10": {
        "title_id": "0004000000030800",
        "md5_compressed":   None,
        "md5_decompressed": "4b8320677e3311b14a75d2abb97772e8",
    },
    # v1.0 EUR
    "eur_v10": {
        "title_id": "0004000000030700",
        "md5_compressed":   None,
        "md5_decompressed": None,
    },
}

# ── Colors ───────────────────────────────────────────────────────────────────
RED    = "\033[31m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
BLUE   = "\033[34m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def info(msg):  print(f"{BLUE}[INFO]{RESET}  {msg}")
def ok(msg):    print(f"{GREEN}[ OK ]{RESET}  {msg}")
def warn(msg):  print(f"{YELLOW}[WARN]{RESET}  {msg}")
def error(msg): print(f"{RED}[ERR ]{RESET}  {msg}"); sys.exit(1)

def check_tool(name):
    if shutil.which(name) is None:
        error(f"'{name}' not found in PATH. Run ./setup.sh first.")

def md5_of(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def run(cmd, **kwargs):
    info(f"Running: {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(cmd, **kwargs)
    if result.returncode != 0:
        error(f"Command failed: {' '.join(str(c) for c in cmd)}")
    return result

# ── Main Extraction ───────────────────────────────────────────────────────────
def extract_from_3ds():
    """Extract ExeFS from a .3ds ROM file."""
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    EXEFS_DIR.mkdir(parents=True, exist_ok=True)

    info(f"Extracting from {BASEROM_3DS.name}...")

    # Use ctrtool v1.3.0+ to extract the ExeFS directly to a directory
    # --decompresscode handles the LZ11 decompression of the code section
    run([
        "ctrtool",
        "--exefs", str(BUILD_DIR / "exefs.bin"),
        str(BASEROM_3DS),
    ])
    ok(f"ExeFS binary dumped to {BUILD_DIR / 'exefs.bin'}")

    # Now extract and decompress the code from the ExeFS binary
    run([
        "ctrtool",
        "-t", "exefs",
        "--exefsdir", str(EXEFS_DIR),
        "--decompresscode",
        str(BUILD_DIR / "exefs.bin"),
    ])
    ok(f"ExeFS extracted (with decompressed code) to {EXEFS_DIR}/")

    ok(f"ExeFS contents extracted to {EXEFS_DIR}/")


def extract_from_cia():
    """Extract ExeFS from a .cia file."""
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    EXEFS_DIR.mkdir(parents=True, exist_ok=True)

    info(f"Extracting from {BASEROM_CIA.name}...")

    content_dir = BUILD_DIR / "cia_content"
    content_dir.mkdir(exist_ok=True)

    # Dump CIA contents (ctrtool v1.3.0+)
    run([
        "ctrtool",
        "--contents", str(content_dir),
        str(BASEROM_CIA),
    ])

    # Find the main CXI/NCCH content
    cxi_files = list(content_dir.glob("*.cxi")) + list(content_dir.glob("*.ncch")) + list(content_dir.glob("*.00000000"))
    if not cxi_files:
        error("No CXI content found in CIA. Is this a valid Mario Kart 7 CIA?")

    cxi = cxi_files[0]
    info(f"Found CXI: {cxi.name}")

    # Extract ExeFS from the CXI using ctrtool v1.3.0+
    run([
        "ctrtool",
        "--exefs", str(BUILD_DIR / "exefs.bin"),
        str(cxi),
    ])

    run([
        "ctrtool",
        "-t", "exefs",
        "--exefsdir", str(EXEFS_DIR),
        "--decompresscode",
        str(BUILD_DIR / "exefs.bin"),
    ])

    ok(f"ExeFS contents extracted to {EXEFS_DIR}/")


def find_and_copy_code():
    """Find the code section and copy it to the standard path."""
    # ctrtool names it '.code' or 'code.bin' depending on flags used
    candidates = [
        EXEFS_DIR / "code.bin",
        EXEFS_DIR / ".code",
        BUILD_DIR / "code.bin",
    ]

    found = None
    for c in candidates:
        if c.exists():
            found = c
            break

    if found is None:
        error(f"code.bin not found after extraction. Contents of {EXEFS_DIR}: "
              f"{list(EXEFS_DIR.iterdir())}")

    shutil.copy2(found, CODE_DEC)
    ok(f"code.bin copied to {CODE_DEC}")
    return CODE_DEC


def verify_hash(path: Path):
    """Check the MD5 of the extracted code against known good values."""
    digest = md5_of(path)
    size_kb = path.stat().st_size / 1024

    info(f"code.bin MD5:  {BOLD}{digest}{RESET}")
    info(f"code.bin size: {BOLD}{size_kb:.1f} KB{RESET}")

    # Check against known hashes
    for version, info_dict in KNOWN_HASHES.items():
        if digest == info_dict["md5_decompressed"]:
            ok(f"Hash matches known version: {BOLD}{version}{RESET}")
            return

    # Unknown hash — not necessarily wrong, just not verified yet
    warn("Hash not in known-good list. If this is a fresh dump, please open an")
    warn("issue on GitHub with your MD5 so we can add it to the verification table.")
    warn("The project will still proceed.")


def disassemble():
    """Explain how to disassemble code.dec.bin using Ghidra/IDA Pro."""
    CONFIG  = ROOT / "config" / "mk7.yaml"

    info("The decrypted executable is ready at build/code.dec.bin.")
    info("To begin disassembly and symbol mapping:")
    info("  1. Load 'build/code.dec.bin' into Ghidra or IDA Pro.")
    info("  2. Set Processor to ARM:v7 (or ARM:v6K), Thumb mode enabled.")
    info("  3. Set Base Address to 0x00100000.")
    info("  4. Once names are mapped, add them to 'config/mk7.yaml' to generate stubs.")



def main():
    print(f"\n{BOLD}{'─'*60}")
    print(f"  DashDecomp — Mario Kart 7 Extraction Script")
    print(f"{'─'*60}{RESET}\n")

    # Check required tools
    check_tool("ctrtool")
    check_tool("3dstool")

    # Decide input format
    if BASEROM_3DS.exists():
        extract_from_3ds()
    elif BASEROM_CIA.exists():
        extract_from_cia()
    else:
        error(
            "No ROM found! Place your dump in:\n"
            f"  {BASEROM_3DS}  (for .3ds format)\n"
            f"  {BASEROM_CIA}  (for .cia format)"
        )

    code_path = find_and_copy_code()
    verify_hash(code_path)
    disassemble()

    print(f"\n{BOLD}{GREEN}✅ Extraction complete!{RESET}")
    print(f"   code.bin → {CODE_DEC}\n")


if __name__ == "__main__":
    main()
