# DashDecomp

> A matching decompilation of **Mario Kart 7** for Nintendo 3DS (v1.0, USA)

[![Build Status](https://github.com/strayfodanator/dashdecomp/actions/workflows/build.yml/badge.svg)](https://github.com/strayfodanator/dashdecomp/actions)
[![Progress](https://decomp.dev/strayfodanator/dashdecomp.svg)](https://decomp.dev/strayfodanator/dashdecomp)
[![decomp.me](https://img.shields.io/badge/decomp.me-scratches-blue)](https://decomp.me/projects/dashdecomp)

**DashDecomp** is the first public decompilation project for *Mario Kart 7* (internally referred to as "Dash" by Nintendo during development). The goal is to produce a 100% byte-matching C++ source code reconstruction of the game's executable (`code.bin`, v1.0 USA), eventually enabling a native PC port.

> **"Dash"** is the internal codename Nintendo used for Mario Kart 7 during development, found in string references inside the game's binary.

---

## ⚠️ Important Notice

This project does **not** include any copyrighted Nintendo material (ROMs, assets, or executables). You must provide your own legally dumped copy of the game.

This project is for **research, preservation, and educational purposes only.**

---

## Project Status

| Module       | Status    | Functions          | Bytes                  | Progress |
|--------------|-----------|--------------------|------------------------|----------|
| System       | 🟢 partial | 404 / 3,233       | 8,872 / 674,228       | 1.3%    |
| Sead         | 🟢 partial | 285 / 2,576       | 5,392 / 539,576       | 1.0%    |
| Race         | 🟢 partial | 187 / 2,888       | 4,296 / 805,000       | 0.5%    |
| Kart         | 🟢 partial | 133 / 2,415       | 2,404 / 735,196       | 0.3%    |
| Item         | 🟢 partial | 188 / 1,741       | 3,624 / 427,388       | 0.8%    |
| UI           | 🟢 partial | 306 / 1,003       | 3,928 / 111,040       | 3.5%    |
| Sound        | 🟢 partial | 19 / 434          | 324 / 224,820         | 0.1%    |
| Net          | 🟢 partial | 11 / 366          | 172 / 68,328          | 0.3%    |

### Sub-units

| Sub-unit              | Status | Functions     | Bytes             | Progress |
|-----------------------|--------|---------------|-------------------|----------|
| `Sead/nn`             | 🟢     | 13 / 13       | 2,284 / 2,284     | 100.0%   |
| `UI/nw`               | 🟡     | 1 / 3         | 12 / 124          | 9.7%     |
| `Kart/Menu3D`         | 🟡     | 1 / 5         | 16 / 280          | 5.7%     |
| `System/nn`           | 🟡     | 22 / 100      | 496 / 15,920      | 3.1%     |
| `Item/Field`          | 🟡     | 1 / 2         | 16 / 716          | 2.2%     |
| `System/UI`           | 🟡     | 3 / 18        | 56 / 3,132        | 1.8%     |
| `System/sead`         | 🟡     | 1 / 6         | 16 / 896          | 1.8%     |
| `Sead/nw`             | 🟡     | 1 / 14        | 8 / 2,528         | 0.3%     |
| `Item/nw`             | 🟡     | 1 / 5         | 4 / 7,200         | 0.1%     |
| `Race/Field`          | 🟡     | 1 / 34        | 8 / 9,508         | 0.1%     |

**Function States:**
- 🔴 `nodecompiled` — Function exists only as raw assembly in `asm/`
- 🟡 `nonmatching` — C++ written but doesn't compile to identical bytes yet
- 🟢 `matching` — C++ compiles byte-for-byte identically to the original

**Overall: 1,579 / 14,966 functions matched (10.6%) — 31,944 / 3,657,812 bytes (0.87%)**

---

## Repository Structure

```
dashdecomp/
├── asm/            # Raw assembly stubs (nodecompiled/nonmatching functions)
│   ├── Race/
│   ├── Kart/
│   ├── Item/
│   └── ...
├── src/            # Decompiled C++ source code (matching functions)
│   ├── Race/
│   ├── Kart/
│   └── ...
├── include/        # Header files: structs, enums, typedefs
│   ├── Race/
│   └── ...
├── tools/          # Extraction and comparison scripts
├── config/         # Symbol maps and project configuration
├── baserom/        # ← Put your ROM dump here (gitignored)
└── build/          # Compiled output (gitignored)
```

---

## Getting Started

### Prerequisites

You will need a legally dumped copy of Mario Kart 7 v1.0 (USA or EUR). You can dump your own cartridge using a 3DS with [Luma3DS](https://github.com/LumaTeam/Luma3DS) CFW and [GodMode9](https://github.com/d0k3/GodMode9).

### Dependencies

**Arch Linux:**
```bash
sudo pacman -S base-devel git python cmake ninja
# Then run the setup script:
./setup.sh
```

**Other Linux / macOS:**
```bash
# Install ARM toolchain (devkitARM):
# https://devkitpro.org/wiki/Getting_Started
./setup.sh
```

### Setup

```bash
# 1. Clone the repository
git clone --recursive https://github.com/strayfodanator/dashdecomp.git
cd dashdecomp

# 2. Run setup (creates venv, installs Python tools, installs ARM toolchain)
./setup.sh

# 3. Place your ROM dump in baserom/
cp /path/to/your/MarioKart7.3ds baserom/game.3ds
# OR for CIA format:
cp /path/to/your/MarioKart7.cia baserom/game.cia

# 4. Extract the executable from the ROM
make extract

# 5. Build and check matching
make
make check
```

---

## Contributing

We welcome contributions of all sizes! Whether you decompile a single function or an entire module, every PR helps.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full guide, including:
- How to use [decomp.me](https://decomp.me/projects/dashdecomp) to write scratches online
- How to verify your function is byte-matching
- How to submit a PR

### Quick Start for Contributors

1. Browse the assembly in `asm/` to find a function you'd like to decompile
2. Create a scratch on [decomp.me](https://decomp.me/projects/dashdecomp) with that function's assembly
3. Write C++ until you get a match, then open a PR

---

## Tools Used

| Tool | Purpose |
|------|---------|
| [decomp-toolkit (dtk)](https://github.com/encounter/decomp-toolkit) | Auto-disassembly of `code.bin` into per-function `.s` files |
| [asm-differ](https://github.com/simonlindholm/asm-differ) | Side-by-side diff of compiled vs. original assembly |
| [ctrtool](https://github.com/3DSGuy/Project_CTR) | Extraction of 3DS file formats |
| [arm-none-eabi-gcc](https://devkitpro.org) | ARM cross-compiler (via devkitARM) |

---

## Related Projects & Resources

- [CTGP-7](https://github.com/PabloMK7/CTGP-7_Open_Source) — Mario Kart 7 mod with extensive reverse engineering work
- [MK7 Reverse Engineering](https://github.com/PabloMK7) — Symbol maps and struct documentation
- [3dbrew.org](https://www.3dbrew.org) — 3DS hardware documentation
- [3dsdecomp/RedPepper](https://github.com/3dsdecomp/redpepper) — Super Mario 3D Land decomp (structural reference)

---

## License

The decompiled source code in `src/` and `include/` is licensed under **MIT**.  
Assembly stubs in `asm/` are derived from the original binary and are for research purposes only.

---

*DashDecomp is not affiliated with or endorsed by Nintendo Co., Ltd.*
