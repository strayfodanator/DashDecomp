## Description

<!-- Briefly describe what this PR decompiles or fixes -->

## Function(s)

<!-- List each function this PR addresses -->
- `Module::Class::functionName`

## Status

<!-- Check all that apply -->
- [ ] 🟢 **MATCHING** — Compiles byte-for-byte identically to the original
- [ ] 🟡 **NONMATCHING** — C++ written, but output not fully matching yet (WIP)
- [ ] 🔴 **NODECOMPILED** — Adding new asm stub for a previously undiscovered function

## Verification

<!-- How did you verify the match? -->
- [ ] Ran `make check` locally — **PASS** ✅
- [ ] Checked with `python tools/asm-differ/diff.py -u3 FunctionName`
- [ ] Tested on decomp.me (link to scratch: )

## Notes

<!-- Any tricky parts, weird compiler behavior, or context for reviewers -->
