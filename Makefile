# DashDecomp — Makefile
# Mario Kart 7 (3DS, v1.0) Decompilation Project

GAME_NAME   := dashdecomp
VERSION     := USA_V10

ARCH        := -march=armv6k -mtune=mpcore -mfloat-abi=hard -mfpu=vfpv2 -mthumb-interwork
ASARCH      := -march=armv6k -mfloat-abi=hard -mfpu=vfpv2 -mthumb-interwork

CXX         := arm-none-eabi-g++
AS          := arm-none-eabi-as
LD          := arm-none-eabi-ld
OBJCOPY     := arm-none-eabi-objcopy

CXXFLAGS    := $(ARCH) -O2 -fno-rtti -fno-exceptions -fshort-wchar -std=c++11 \
               -DVERSION=$(VERSION) -Iinclude

ASFLAGS     := $(ASARCH)
LDFLAGS     := -T config/mk7.ld --no-undefined

ROOT        := $(shell pwd)
SRC_DIR     := $(ROOT)/src
ASM_DIR     := $(ROOT)/asm
INCLUDE_DIR := $(ROOT)/include
BUILD_DIR   := $(ROOT)/build
TOOLS_DIR   := $(ROOT)/tools
CONFIG_DIR  := $(ROOT)/config
BASEROM_DIR := $(ROOT)/baserom

ORIG_CODE   := $(BUILD_DIR)/code.dec.bin
OUT_ELF     := $(BUILD_DIR)/$(GAME_NAME).elf
OUT_CODE    := $(BUILD_DIR)/$(GAME_NAME).bin

SRC_FILES   := $(shell find $(SRC_DIR) -name '*.cpp' 2>/dev/null)
ASM_FILES   := $(shell find $(ASM_DIR) -name '*.s'   2>/dev/null)

OBJ_FILES   := $(patsubst $(SRC_DIR)/%.cpp, $(BUILD_DIR)/src/%.o, $(SRC_FILES)) \
               $(patsubst $(ASM_DIR)/%.s,   $(BUILD_DIR)/asm/%.o, $(ASM_FILES))

.PHONY: all extract check progress clean help linkerscript base

all: $(OUT_CODE)

extract:
	@echo "  Extracting code.bin from baserom/ ..."
	@source .venv/bin/activate && python $(TOOLS_DIR)/extract.py
	@echo "  Done."

# Regenerate linker script and data stubs from the original binary
linkerscript: $(ORIG_CODE)
	@echo "  Generating linker script + data stubs..."
	@python $(TOOLS_DIR)/generate_linker_script.py

base: $(ORIG_CODE)
	@echo "  Creating base .o files..."
	@python $(TOOLS_DIR)/create_base_o.py

# Build: all .o files must exist, but linker script handles placement
# The linker script references .o files explicitly, so we need them built.
# We just ensure all .o files are present before linking.
$(OUT_ELF): $(OBJ_FILES) $(CONFIG_DIR)/mk7.ld
	@echo "  LD   $@"
	@$(LD) $(LDFLAGS) -o $@ -Map=$(BUILD_DIR)/$(GAME_NAME).map

$(OUT_CODE): $(OUT_ELF)
	@echo "  OBJCOPY $@"
	@$(OBJCOPY) -O binary $< $@

$(BUILD_DIR)/src/%.o: $(SRC_DIR)/%.cpp
	@mkdir -p $(@D)
	@echo "  CXX  $<"
	@$(CXX) $(CXXFLAGS) -c -o $@ $<

$(BUILD_DIR)/asm/%.o: $(ASM_DIR)/%.s
	@mkdir -p $(@D)
	@echo "  AS   $<"
	@$(AS) $(ASFLAGS) -o $@ $<

check: $(OUT_CODE)
	@echo ""
	@echo "  Verifying matching ..."
	@if [ ! -f "$(ORIG_CODE)" ]; then \
		echo "  ERROR: $(ORIG_CODE) not found. Run 'make extract' first."; \
		exit 1; \
	fi
	@if cmp -s $(OUT_CODE) $(ORIG_CODE); then \
		echo "  PASS — Build output matches original code.bin byte-for-byte!"; \
	else \
		echo "  FAIL — Build output does NOT match original code.bin."; \
		stat --printf="  Original: %s bytes\n  Build:    " $(ORIG_CODE); \
		stat --printf="%s bytes\n" $(OUT_CODE); \
		exit 1; \
	fi

progress:
	@source .venv/bin/activate && python $(TOOLS_DIR)/check_matching.py

clean:
	@echo "  Cleaning build artifacts..."
	@rm -rf $(BUILD_DIR)/src $(BUILD_DIR)/asm $(OUT_ELF) $(OUT_CODE) \
	       $(BUILD_DIR)/$(GAME_NAME).map $(BUILD_DIR)/base $(BUILD_DIR)/objfiles.rsp
	@echo "  Done."

help:
	@echo "  DashDecomp — Mario Kart 7 Decompilation"
	@echo ""
	@echo "  Targets:"
	@echo "    make              Build the project"
	@echo "    make extract      Extract code.bin from baserom/"
	@echo "    make linkerscript  Regenerate linker script + data stubs"
	@echo "    make base         Regenerate base .o files (for objdiff)"
	@echo "    make check        Verify byte-perfect matching"
	@echo "    make progress     Show matching progress report"
	@echo "    make clean        Remove build artifacts"
