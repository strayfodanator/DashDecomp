# Contributing to DashDecomp

Thank you for your interest in contributing! Every function you decompile brings Mario Kart 7 one step closer to a native PC port.

---

## Understanding Function States

Every function in this project has one of three states:

| State | Symbol | Description |
|-------|--------|-------------|
| `nodecompiled` | 🔴 | Function only exists as raw `.s` assembly in `asm/`. No C++ has been written yet. |
| `nonmatching` | 🟡 | C++ source exists in `src/` but does NOT compile to byte-identical output. Work in progress. |
| `matching` | 🟢 | C++ source compiles **byte-for-byte identical** to the original binary. Done! |

The goal is to move every function from 🔴 → 🟡 → 🟢.

---

## How to Contribute

### Option A: Use decomp.me (Easiest — No Setup Required)

1. Go to [decomp.me/projects/dashdecomp](https://decomp.me/projects/dashdecomp)
2. Pick any function from the list
3. Paste the assembly from `asm/` into a new "scratch"
4. Write C++ in the editor until the diff turns fully green (100% match)
5. Copy your C++ and open a PR against this repo

### Option B: Contribute Locally (Full Setup)

1. **Fork & clone the repo:**
   ```bash
   git clone --recursive https://github.com/YOUR_ORG/dashdecomp.git
   cd dashdecomp
   ```

2. **Install dependencies and extract the ROM:**
   ```bash
   ./setup.sh
   cp /path/to/MarioKart7.3ds baserom/game.3ds
   make extract
   ```

3. **Pick a function to decompile:**
   Browse `asm/` for a function that looks approachable. Functions are organized by module (`Kart/`, `Race/`, `Item/`, etc.).

4. **Write C++ for the function:**
   - Create the corresponding file in `src/` (e.g., `src/Kart/KartMove.cpp`)
   - Add the header declaration in `include/` (e.g., `include/Kart/KartMove.h`)
   - Mark it as `NONMATCHING` in the source (see below)

5. **Compare your output with asm-differ:**
   ```bash
   # Activate the venv first
   source .venv/bin/activate
   
   # Compare your function
   python tools/asm-differ/diff.py -u3 FunctionName
   ```

6. **Once it matches, update the state to MATCHING:**
   ```bash
   make check  # Should print PASS ✅
   ```

7. **Open a Pull Request** with a clear title like `[matching] Kart::KartMove::calcPhysics`

---

## Function Status Annotations

In `src/` files, annotate your functions clearly:

```cpp
// MATCHING — compiles byte-for-byte identically
void Kart::KartMove::calcSpeed() {
    // ...
}

// NONMATCHING — written but output doesn't match yet
// See: asm/Kart/KartMove/calcCollision.s
#pragma NONMATCHING
void Kart::KartMove::calcCollision() {
    // ...
}
#pragma MATCHING
```

---

## PR Guidelines

- **One function per PR** is preferred, but related small functions can be grouped
- PR title format: `[matching] Module::Class::functionName`
- Include a brief note if you had to do anything tricky to get the match
- Make sure `make check` passes before opening the PR — the CI will verify this automatically

---

## Questions?

- Open a GitHub Issue
- Join the discussion on our Discord (link TBD)
- Create a scratch on [decomp.me](https://decomp.me/projects/dashdecomp) and share the link in the issue
