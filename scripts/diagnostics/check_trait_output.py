#!/usr/bin/env python3
"""Check what get_trait_list returns"""
import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, PROJECT_ROOT)

from database.character_traits import get_trait_list

traits = get_trait_list()
print("=== TRAIT OUTPUT ===")
print(f"Type: {type(traits)}")
print(f"Length: {len(traits) if traits else 0} chars")
print("\nFirst 500 chars:")
print(traits[:500] if traits else "None")
print("\n...")
print("\nLast 200 chars:")
print(traits[-200:] if traits else "None")
