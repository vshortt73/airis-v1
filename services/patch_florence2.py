#!/usr/bin/env python3
"""
Patch Florence2 modeling file to fix past_key_values compatibility issue.

Run this on node2 after the model has been loaded once (to cache the files):
    python patch_florence2.py

This patches the prepare_inputs_for_generation method to handle past_key_values=None.
"""

import os
import re
from pathlib import Path

# Find the cached Florence2 modeling file
CACHE_PATHS = [
    Path.home() / ".cache/huggingface/modules/transformers_modules/florence2/modeling_florence2.py",
    Path("/models/vision/florence2/modeling_florence2.py"),
]

def find_model_file():
    for path in CACHE_PATHS:
        if path.exists():
            return path
    # Also check for any florence2 folder in the HF cache
    hf_cache = Path.home() / ".cache/huggingface/modules/transformers_modules"
    if hf_cache.exists():
        for folder in hf_cache.iterdir():
            if "florence" in folder.name.lower():
                model_file = folder / "modeling_florence2.py"
                if model_file.exists():
                    return model_file
    return None

def patch_file(filepath: Path):
    print(f"Patching: {filepath}")

    with open(filepath, 'r') as f:
        content = f.read()

    # Check if already patched
    if "# PATCHED: Handle past_key_values=None" in content:
        print("File already patched!")
        return True

    # Find and patch the prepare_inputs_for_generation method
    # Original problematic code:
    #     past_length = past_key_values[0][0].shape[2]
    #
    # We need to add a check for None

    old_code = "past_length = past_key_values[0][0].shape[2]"
    new_code = """# PATCHED: Handle past_key_values=None
        if past_key_values is None:
            past_length = 0
        else:
            past_length = past_key_values[0][0].shape[2]"""

    if old_code not in content:
        print("Could not find the code to patch. The file might have a different version.")
        print("Looking for alternative patterns...")

        # Try alternative pattern with different indentation
        patterns = [
            r"(\s+)past_length = past_key_values\[0\]\[0\]\.shape\[2\]",
        ]

        for pattern in patterns:
            match = re.search(pattern, content)
            if match:
                indent = match.group(1)
                old = match.group(0)
                new = f"""{indent}# PATCHED: Handle past_key_values=None
{indent}if past_key_values is None:
{indent}    past_length = 0
{indent}else:
{indent}    past_length = past_key_values[0][0].shape[2]"""
                content = content.replace(old, new)
                print(f"Found and patched with pattern: {pattern}")
                break
        else:
            print("ERROR: Could not find any matching pattern to patch")
            return False
    else:
        content = content.replace(old_code, new_code)

    # Backup original
    backup_path = filepath.with_suffix('.py.bak')
    if not backup_path.exists():
        with open(backup_path, 'w') as f:
            with open(filepath, 'r') as orig:
                f.write(orig.read())
        print(f"Backup saved to: {backup_path}")

    # Write patched file
    with open(filepath, 'w') as f:
        f.write(content)

    print("Patch applied successfully!")
    return True

def main():
    print("=" * 60)
    print("Florence2 Model Patcher")
    print("=" * 60)

    model_file = find_model_file()

    if model_file is None:
        print("ERROR: Could not find Florence2 modeling file.")
        print("Make sure you've loaded the model at least once to cache it.")
        print(f"Searched paths: {CACHE_PATHS}")
        return 1

    print(f"Found model file: {model_file}")

    if patch_file(model_file):
        print("\nPatch complete! Restart the Florence2 server.")
        return 0
    else:
        return 1

if __name__ == "__main__":
    exit(main())
