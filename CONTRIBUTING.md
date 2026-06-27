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

## Branch & PR Guidelines

To keep the git history clean and make reviews efficient, we follow a strict **class-scoped** workflow:

1. **One Class per Branch/PR:** 
   - Every Pull Request and branch must focus on **only one class** (e.g., branch `class/KartMove` for working on `KartMove`).
   - Do **NOT** mix modifications to different classes in a single PR.
   
2. **Partial Decompilation is Welcome:**
   - You do **not** need to decompile 100% of a class to submit a PR.
   - Contributions of any size (even just 5% or 10% of a class, or a single function) are welcome, as long as they are contained within that class's branch.

3. **Branch Naming Convention:**
   - Use the prefix `class/` followed by the class name.
     - Example: `class/KartMove`
     - Example: `class/RaceDirector`

4. **Pull Request Title Format:**
   - Use the format: `[matching] Module::Class (Progress Update)`
     - Example: `[matching] Kart::KartMove (added 3 functions)`
     - Example: `[matching] Race::RaceDirector (100% matched)`

---

## How to Contribute (Local Workflow)

1. **Fork & clone the repo:**
   ```bash
   git clone --recursive https://github.com/strayfodanator/dashdecomp.git
   cd dashdecomp
   ```

2. **Create your class-specific branch:**
   ```bash
   git checkout -b class/KartMove
   ```

3. **Install dependencies and extract the ROM:**
   ```bash
   ./setup.sh
   cp /path/to/MarioKart7.3ds baserom/game.3ds
   make extract
   ```

4. **Pick a function to decompile:**
   Browse `asm/` for a function belonging to your target class.

5. **Write C++ for the function:**
   - Create/edit the corresponding file in `src/` (e.g., `src/Kart/KartMove.cpp`)
   - Add/edit the header declaration in `include/` (e.g., `include/Kart/KartMove.h`)
   - Mark it as `NONMATCHING` in the source if it is work-in-progress, or let it match.

6. **Compare your output with asm-differ:**
   ```bash
   # Activate the venv first
   source .venv/bin/activate
   
   # Compare your function
   python tools/asm-differ/diff.py -u3 FunctionName
   ```

7. **Verify & Check:**
   ```bash
   make check  # Should print PASS ✅ if all matched functions are byte-identical
   ```

8. **Commit & Push:**
   Keep all commits in this branch restricted to this class, then open your PR.

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
