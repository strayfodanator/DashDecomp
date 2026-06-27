#!/usr/bin/env python3
"""Generate objdiff.json from functions.json, organizing by Units."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FUNCTIONS_JSON = ROOT / "asm" / "functions.json"
OBJDIFF_JSON = ROOT / "objdiff.json"

with open(FUNCTIONS_JSON) as f:
    functions = json.load(f)

units = []
for asm_path, size in functions.items():
    # asm_path: "asm/Unit/Subdir.../Function.s"
    rel = asm_path.removeprefix("asm/")
    stem = rel.removesuffix(".s")
    obj_path = stem + ".o"
    units.append({
        "name": stem,
        "target_path": obj_path,
        "base_path": obj_path,
    })

config = {
    "$schema": "https://raw.githubusercontent.com/encounter/objdiff/main/config.schema.json",
    "min_version": "2.0.0",
    "custom_make": "make",
    "target_dir": "build/asm",
    "base_dir": "build/src",
    "build_target": False,
    "build_base": False,
    "watch_patterns": [
        "src/**/*.cpp",
        "src/**/*.c",
        "include/**/*.h",
        "asm/**/*.s",
    ],
    "units": units,
}

with open(OBJDIFF_JSON, "w") as f:
    json.dump(config, f, indent=2)

print(f"Generated {OBJDIFF_JSON} with {len(units)} units")
