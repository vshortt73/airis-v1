#!/usr/bin/env python3
"""Check which instructions are loaded"""
import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, PROJECT_ROOT)

from core.system_prompt import get_system_prompt, get_active_protocol

protocol = get_active_protocol()
print(f"Active protocol: {protocol['protocol_name']}")
print(f"Rules include: {protocol['rules_include']}")
print(f"Rules exclude: {protocol['rules_exclude']}")

print("\n=== SYSTEM INSTRUCTIONS ===")
prompt = get_system_prompt(protocol)
sections = prompt.split('\n\n')

for i, section in enumerate(sections):
    print(f"\n--- Section {i+1} ({len(section)} chars) ---")
    # Show first 200 chars
    preview = section[:200].replace('\n', ' ')
    print(preview)
    if len(section) > 200:
        print("...")

    # Check for trait-related keywords
    if 'trait' in section.lower():
        print("  [Contains 'trait']")

print(f"\n=== TOTAL: {len(sections)} sections ===")

# Check if the trait trigger text exists
trigger_text = "trait settings control the way in which you respond"
if trigger_text in prompt:
    print(f"✓ Trait trigger text found: '{trigger_text}'")
else:
    print(f"✗ Trait trigger text NOT found: '{trigger_text}'")
    # Try to find similar text
    if 'trait' in prompt.lower():
        import re
        matches = re.findall(r'[^.]*trait[^.]*', prompt.lower())
        print(f"\nFound {len(matches)} lines with 'trait':")
        for match in matches[:5]:
            print(f"  - {match.strip()}")
