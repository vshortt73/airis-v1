#!/usr/bin/env python3
"""Test inline citation parsing"""
import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)

from core.system_prompt import parse_fact_references

# Test cases for inline citations
test_cases = [
    {
        "name": "Single inline citation",
        "response": "The vision system runs on GPU 1 [9] with llava.",
        "expected_ids": [9],
        "expected_cleaned": "The vision system runs on GPU 1 with llava."
    },
    {
        "name": "Multiple inline citations",
        "response": "You're implementing the memory system [7] and testing context injection [10].",
        "expected_ids": [7, 10],
        "expected_cleaned": "You're implementing the memory system and testing context injection ."
    },
    {
        "name": "Duplicate citations",
        "response": "The GPU 1 [9] system uses llava [9] for vision.",
        "expected_ids": [9],
        "expected_cleaned": "The GPU 1 system uses llava for vision."
    },
    {
        "name": "Mixed with text in brackets",
        "response": "The vision system [9] runs on GPU 1 [not a citation].",
        "expected_ids": [9],
        "expected_cleaned": "The vision system runs on GPU 1 [not a citation]."
    },
    {
        "name": "Legacy format",
        "response": "Here's my response. [FACTS_USED: 7, 9, 10]",
        "expected_ids": [7, 9, 10],
        "expected_cleaned": "Here's my response."
    },
    {
        "name": "No citations",
        "response": "This is a response without any citations.",
        "expected_ids": [],
        "expected_cleaned": "This is a response without any citations."
    }
]

print("=" * 70)
print("INLINE CITATION PARSING TESTS")
print("=" * 70)

passed = 0
for test in test_cases:
    cleaned, ids = parse_fact_references(test["response"])

    ids_match = ids == test["expected_ids"]
    # For cleaned text, just check that citations were removed (whitespace differences ok)
    cleaned_normalized = ' '.join(cleaned.split())
    expected_normalized = ' '.join(test["expected_cleaned"].split())
    cleaned_match = cleaned_normalized == expected_normalized

    if ids_match and cleaned_match:
        print(f"✓ {test['name']}")
        print(f"  IDs: {ids}")
        passed += 1
    else:
        print(f"✗ {test['name']}")
        if not ids_match:
            print(f"  Expected IDs: {test['expected_ids']}, Got: {ids}")
        if not cleaned_match:
            print(f"  Expected: '{expected_normalized}'")
            print(f"  Got: '{cleaned_normalized}'")

print("\n" + "=" * 70)
if passed == len(test_cases):
    print(f"✓ ALL {passed}/{len(test_cases)} TESTS PASSED")
else:
    print(f"✗ {passed}/{len(test_cases)} TESTS PASSED")
print("=" * 70)
