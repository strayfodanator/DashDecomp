# DashDecomp — Makefile
# Mario Kart 7 (3DS, v1.0) Decompilation Project
#
# Targets:
#   make extract   — Extract and disassemble code.bin from baserom/
#   make           — Build the project (compile src/ + link asm/)
#   make check     — Verify the build matches the original code.bin (byte-for-byte)
#   make progress  — Print matching progress report
#   make clean     — Remove build artifacts

# ── Configuration ─────────────────────────────────────────────────────────────
GAME_NAME   := dashdecomp
VERSION     := USA_V10

# Target architecture: ARM11 (Cortex-A9), as used in the Nintendo 3DS CTR CPU
ARCH        := -march=armv6k -mtune=mpcore -mfloat-abi=hard -mfpu=vfpv2 -mthumb-interwork

# Compiler — arm-none-eabi-g++ from devkitARM / system ARM toolchain
CXX         := arm-none-eabi-g++
AS          := arm-none-eabi-as
LD          := arm-none-eabi-ld
OBJCOPY     := arm-none-eabi-objcopy

# Compiler flags (matching Nintendo's original build flags as closely as possible)
# NOTE: These flags will be refined as we identify the exact Nintendo SDK compiler settings
CXXFLAGS    := $(ARCH) \
               -O2 \
               -fno-rtti \
               -fno-exceptions \
               -fshort-wchar \
               -std=c++11 \
               -DVERSION=$(VERSION) \
               -Iinclude

ASFLAGS     := $(ARCH)
LDFLAGS     := -T config/mk7.ld --no-undefined

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT        := $(shell pwd)
SRC_DIR     := $(ROOT)/src
ASM_DIR     := $(ROOT)/asm
INCLUDE_DIR := $(ROOT)/include
BUILD_DIR   := $(ROOT)/build
TOOLS_DIR   := $(ROOT)/tools
CONFIG_DIR  := $(ROOT)/config
BASEROM_DIR := $(ROOT)/baserom

# Original code.bin (extracted from ROM, never committed)
ORIG_CODE   := $(BUILD_DIR)/code.dec.bin
OUT_CODE    := $(BUILD_DIR)/$(GAME_NAME).bin

# ── Source Files ───────────────────────────────────────────────────────────────
SRC_FILES   := $(shell find $(SRC_DIR) -name '*.cpp' 2>/dev/null)
ASM_FILES   := $(shell find $(ASM_DIR) -name '*.s'   2>/dev/null)

OBJ_FILES   := $(patsubst $(SRC_DIR)/%.cpp, $(BUILD_DIR)/src/%.o, $(SRC_FILES)) \
               $(patsubst $(ASM_DIR)/%.s,   $(BUILD_DIR)/asm/%.o, $(ASM_FILES))

# ── Default Target ─────────────────────────────────────────────────────────────
.PHONY: all extract check progress clean help

all: $(OUT_CODE)

# ── Extract: pull code.bin from the ROM ───────────────────────────────────────
extract:
	@echo ""
	@echo "  ⟳  Extracting code.bin from baserom/ ..."
	@echo ""
	@source .venv/bin/activate && python $(TOOLS_DIR)/extract.py
	@echo ""
	@echo "  ✅ Extraction done. Run 'make' to build."
	@echo ""

# ── Build: compile src/ + assemble asm/ ───────────────────────────────────────
$(OUT_CODE): $(OBJ_FILES) $(CONFIG_DIR)/mk7.ld
	@echo "  LD   $@"
	@$(LD) $(LDFLAGS) -o $@ $(OBJ_FILES) -Map=$(BUILD_DIR)/$(GAME_NAME).map

$(BUILD_DIR)/src/%.o: $(SRC_DIR)/%.cpp
	@mkdir -p $(@D)
	@echo "  CXX  $<"
	@$(CXX) $(CXXFLAGS) -c -o $@ $<

$(BUILD_DIR)/asm/%.o: $(ASM_DIR)/%.s
	@mkdir -p $(@D)
	@echo "  AS   $<"
	@$(AS) $(ASFLAGS) -o $@ $<

# ── Check: verify byte-perfect matching ───────────────────────────────────────
check: $(OUT_CODE)
	@echo ""
	@echo "  ⟳  Verifying matching ..."
	@echo ""
	@if [ ! -f "$(ORIG_CODE)" ]; then \
		echo "  ❌ ERROR: $(ORIG_CODE) not found. Run 'make extract' first."; \
		exit 1; \
	fi
	@if cmp -s $(OUT_CODE) $(ORIG_CODE); then \
		echo "  ✅ PASS — Build output matches original code.bin byte-for-byte!"; \
	else \
		echo "  ❌ FAIL — Build output does NOT match original code.bin."; \
		echo ""; \
		echo "     Use asm-differ to find the mismatch:"; \
		echo "     source .venv/bin/activate"; \
		echo "     python tools/asm-differ/diff.py -u3 <FunctionName>"; \
		exit 1; \
	fi
	@echo ""

# ── Progress: matching report ─────────────────────────────────────────────────
progress:
	@source .venv/bin/activate && python $(TOOLS_DIR)/check_matching.py

# ── Clean ─────────────────────────────────────────────────────────────────────
clean:
	@echo "  Cleaning build artifacts..."
	@rm -rf $(BUILD_DIR)/src $(BUILD_DIR)/asm $(OUT_CODE) $(BUILD_DIR)/$(GAME_NAME).map
	@echo "  Done."

# ── Help ──────────────────────────────────────────────────────────────────────
help:
	@echo ""
	@echo "  DashDecomp — Mario Kart 7 Decompilation"
	@echo ""
	@echo "  Targets:"
	@echo "    make extract   Extract code.bin from baserom/"
	@echo "    make           Build the project"
	@echo "    make check     Verify byte-perfect matching"
	@echo "    make progress  Show matching progress report"
	@echo "    make clean     Remove build artifacts"
	@echo ""
