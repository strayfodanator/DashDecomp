#!/usr/bin/env bash
# DashDecomp — Setup Script for Arch Linux (and other Linux/macOS)
# Installs all required dependencies for building and contributing.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$ROOT/.venv"

# ── Colors ───────────────────────────────────────────────────────────────────
RED='\033[31m'; GREEN='\033[32m'; YELLOW='\033[33m'; BLUE='\033[34m'
BOLD='\033[1m'; RESET='\033[0m'

info()  { echo -e "${BLUE}[INFO]${RESET}  $*"; }
ok()    { echo -e "${GREEN}[ OK ]${RESET}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
error() { echo -e "${RED}[ERR ]${RESET}  $*"; exit 1; }

echo -e "\n${BOLD}$(printf '─%.0s' {1..60})"
echo -e "  DashDecomp — Setup Script"
echo -e "$(printf '─%.0s' {1..60})${RESET}\n"

# ── Detect OS ────────────────────────────────────────────────────────────────
if [[ -f /etc/arch-release ]]; then
    OS="arch"
elif [[ "$OSTYPE" == "darwin"* ]]; then
    OS="macos"
else
    OS="linux"
fi

info "Detected OS: $OS"

# ── Install system packages ───────────────────────────────────────────────────
if [[ "$OS" == "arch" ]]; then
    info "Installing system packages via pacman..."
    sudo pacman -S --needed --noconfirm \
        base-devel git python python-pip cmake ninja \
        arm-none-eabi-gcc arm-none-eabi-binutils arm-none-eabi-newlib

    # ctrtool and 3dstool — build from AUR or download prebuilts
    if ! command -v ctrtool &>/dev/null; then
        info "Installing ctrtool from AUR..."
        if command -v yay &>/dev/null; then
            yay -S --noconfirm ctrtool-git 3dstool || warn "AUR install failed — trying binary install..."
        elif command -v paru &>/dev/null; then
            paru -S --noconfirm ctrtool-git 3dstool || warn "AUR install failed — trying binary install..."
        else
            warn "No AUR helper found. Installing ctrtool from source..."
            _build_ctrtool
        fi
    fi

elif [[ "$OS" == "macos" ]]; then
    if ! command -v brew &>/dev/null; then
        error "Homebrew not found. Install it from https://brew.sh first."
    fi
    info "Installing packages via Homebrew..."
    brew install git python cmake ninja arm-none-eabi-gcc

else
    info "Installing packages via apt (Debian/Ubuntu assumed)..."
    sudo apt-get update -qq
    sudo apt-get install -y --no-install-recommends \
        build-essential git python3 python3-pip cmake ninja-build \
        gcc-arm-none-eabi binutils-arm-none-eabi
fi

# ── Build ctrtool from source if not installed ────────────────────────────────
_build_ctrtool() {
    info "Building ctrtool from source..."
    TMPDIR=$(mktemp -d)
    git clone --depth=1 https://github.com/3DSGuy/Project_CTR.git "$TMPDIR/ctrtool"
    pushd "$TMPDIR/ctrtool/ctrtool" > /dev/null
        make -j"$(nproc)"
        sudo install -m755 ctrtool /usr/local/bin/ctrtool
    popd > /dev/null
    rm -rf "$TMPDIR"
    ok "ctrtool installed"

    info "Building 3dstool from source..."
    TMPDIR=$(mktemp -d)
    git clone --depth=1 https://github.com/dnasdw/3dstool.git "$TMPDIR/3dstool"
    pushd "$TMPDIR/3dstool" > /dev/null
        cmake -B build -DCMAKE_BUILD_TYPE=Release
        cmake --build build -j"$(nproc)"
        sudo install -m755 build/3dstool /usr/local/bin/3dstool
    popd > /dev/null
    rm -rf "$TMPDIR"
    ok "3dstool installed"
}

if ! command -v ctrtool &>/dev/null; then
    _build_ctrtool
fi

# ── Python virtual environment ────────────────────────────────────────────────
info "Creating Python virtual environment at .venv/ ..."
python3 -m venv "$VENV"
source "$VENV/bin/activate"

info "Installing Python dependencies..."
pip install --quiet --upgrade pip
pip install --quiet -r "$ROOT/requirements.txt"

ok "Python venv ready. Activate with: source .venv/bin/activate"

# ── Git submodules ────────────────────────────────────────────────────────────
if [[ -f "$ROOT/.gitmodules" ]]; then
    info "Initializing git submodules..."
    git -C "$ROOT" submodule update --init --recursive
    ok "Submodules initialized"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo -e "\n${BOLD}${GREEN}✅ Setup complete!${RESET}"
echo -e "\nNext steps:"
echo -e "  1. ${BOLD}source .venv/bin/activate${RESET}   (activate the Python environment)"
echo -e "  2. Place your ROM dump in ${BOLD}baserom/game.3ds${RESET}"
echo -e "  3. ${BOLD}make extract${RESET}                 (extract and disassemble the code)"
echo -e "  4. ${BOLD}make${RESET}                         (build the project)"
echo -e "  5. ${BOLD}make check${RESET}                   (verify matching)\n"
