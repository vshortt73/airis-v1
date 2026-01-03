"""
Test script for fact reference tracking via response markers
Verifies parsing, database updates, and system prompt formatting
"""

import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)

from core.system_prompt import parse_fact_references, update_fact_references, get_short_term_facts
import psycopg2
from app import config

def get_db_connection():
    """Create database connection"""
    password = os.environ.get('IRIS_DB_PASSWORD') or getattr(config, 'DB_PASSWORD', None)

    conn_params = {
        'host': config.DB_HOST,
        'port': config.DB_PORT,
        'database': config.DB_NAME,
        'user': config.DB_USER
    }

    if password:
        conn_params['password'] = password

    return psycopg2.connect(**conn_params)


def test_parse_fact_references():
    """Test parsing fact references from response text"""
    print("\n[test_fact_reference_tracking] Testing parse_fact_references()...")

    test_cases = [
        {
            "response": "Hi Victor! I see you're working on the memory system. [FACTS_USED: 7, 10]",
            "expected_ids": [7, 10],
            "expected_cleaned": "Hi Victor! I see you're working on the memory system."
        },
        {
            "response": "That's great! [FACTS_USED: 7]",
            "expected_ids": [7],
            "expected_cleaned": "That's great!"
        },
        {
            "response": "No facts used here.",
            "expected_ids": [],
            "expected_cleaned": "No facts used here."
        },
        {
            "response": "Multiple facts: [FACTS_USED: 7, 8, 9, 10, 11]",
            "expected_ids": [7, 8, 9, 10, 11],
            "expected_cleaned": "Multiple facts:"
        }
    ]

    passed = 0
    for i, test in enumerate(test_cases, 1):
        cleaned, ids = parse_fact_references(test["response"])

        if ids == test["expected_ids"] and cleaned == test["expected_cleaned"]:
            print(f"  ✓ Test case {i} passed: {ids}")
            passed += 1
        else:
            print(f"  ✗ Test case {i} failed:")
            print(f"    Expected IDs: {test['expected_ids']}, Got: {ids}")
            print(f"    Expected cleaned: '{test['expected_cleaned']}'")
            print(f"    Got cleaned: '{cleaned}'")

    if passed == len(test_cases):
        print(f"[test_fact_reference_tracking] ✓ All {passed}/{len(test_cases)} parsing tests passed")
        return True
    else:
        print(f"[test_fact_reference_tracking] ✗ Only {passed}/{len(test_cases)} parsing tests passed")
        return False


def test_update_fact_references():
    """Test database update functionality"""
    print("\n[test_fact_reference_tracking] Testing update_fact_references()...")

    conn = get_db_connection()
    cursor = conn.cursor()

    # Get current reference counts for existing facts
    cursor.execute("SELECT fact_id, reference_count FROM short_term_facts WHERE status = 'active' ORDER BY fact_id LIMIT 2")
    facts = cursor.fetchall()

    if not facts:
        print("[test_fact_reference_tracking] ✗ No active facts found in database!")
        cursor.close()
        conn.close()
        return False

    fact_id_1, initial_count_1 = facts[0]
    fact_id_2, initial_count_2 = facts[1] if len(facts) > 1 else (facts[0][0], facts[0][1])

    print(f"[test_fact_reference_tracking] Testing with fact IDs: {fact_id_1}, {fact_id_2}")
    print(f"[test_fact_reference_tracking] Initial counts: {initial_count_1}, {initial_count_2}")

    cursor.close()
    conn.close()

    # Update references
    update_fact_references([fact_id_1, fact_id_2])

    # Check new counts
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT reference_count FROM short_term_facts WHERE fact_id = %s", (fact_id_1,))
    new_count_1 = cursor.fetchone()[0]

    cursor.execute("SELECT reference_count FROM short_term_facts WHERE fact_id = %s", (fact_id_2,))
    new_count_2 = cursor.fetchone()[0]

    cursor.close()
    conn.close()

    print(f"[test_fact_reference_tracking] New counts: {new_count_1}, {new_count_2}")

    if new_count_1 == initial_count_1 + 1 and new_count_2 == initial_count_2 + 1:
        print("[test_fact_reference_tracking] ✓ Reference counts updated correctly")
        return True
    else:
        print("[test_fact_reference_tracking] ✗ Reference counts not updated correctly!")
        return False


def test_system_prompt_formatting():
    """Test that system prompt includes fact IDs"""
    print("\n[test_fact_reference_tracking] Testing system prompt formatting...")

    facts_str = get_short_term_facts(limit=10)

    if not facts_str:
        print("[test_fact_reference_tracking] ✗ No facts retrieved!")
        return False

    print(f"[test_fact_reference_tracking] System prompt output:")
    print("─" * 70)
    print(facts_str)
    print("─" * 70)

    # Check for required elements
    checks = {
        "Header present": "[RECENT FACTS]" in facts_str,
        "Instructions present": "FACTS_USED" in facts_str,
        "Fact IDs present": "[7]" in facts_str or "[8]" in facts_str or "[9]" in facts_str or "[10]" in facts_str or "[11]" in facts_str,
    }

    all_passed = True
    for check_name, passed in checks.items():
        status = "✓" if passed else "✗"
        print(f"  {status} {check_name}")
        if not passed:
            all_passed = False

    if all_passed:
        print("[test_fact_reference_tracking] ✓ System prompt formatting correct")
        return True
    else:
        print("[test_fact_reference_tracking] ✗ System prompt formatting issues")
        return False


def test_end_to_end():
    """Test complete flow: format → parse → update"""
    print("\n[test_fact_reference_tracking] Testing end-to-end flow...")

    # Get fact IDs from system prompt
    facts_str = get_short_term_facts(limit=5)

    # Extract a fact ID from the output
    import re
    id_match = re.search(r'\[(\d+)\]', facts_str)

    if not id_match:
        print("[test_fact_reference_tracking] ✗ No fact IDs found in system prompt!")
        return False

    test_fact_id = int(id_match.group(1))
    print(f"[test_fact_reference_tracking] Using test fact ID: {test_fact_id}")

    # Get initial reference count
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT reference_count FROM short_term_facts WHERE fact_id = %s", (test_fact_id,))
    initial_count = cursor.fetchone()[0]
    cursor.close()
    conn.close()

    print(f"[test_fact_reference_tracking] Initial reference count: {initial_count}")

    # Simulate Iris's response with fact reference
    simulated_response = f"I understand you're working on this project. [FACTS_USED: {test_fact_id}]"

    # Parse it
    cleaned, ids = parse_fact_references(simulated_response)

    print(f"[test_fact_reference_tracking] Parsed IDs: {ids}")
    print(f"[test_fact_reference_tracking] Cleaned response: '{cleaned}'")

    # Update database
    update_fact_references(ids)

    # Check new count
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT reference_count FROM short_term_facts WHERE fact_id = %s", (test_fact_id,))
    new_count = cursor.fetchone()[0]
    cursor.close()
    conn.close()

    print(f"[test_fact_reference_tracking] New reference count: {new_count}")

    if new_count == initial_count + 1 and cleaned == "I understand you're working on this project.":
        print("[test_fact_reference_tracking] ✓ End-to-end flow working correctly")
        return True
    else:
        print("[test_fact_reference_tracking] ✗ End-to-end flow failed!")
        return False


def main():
    """Run all tests"""
    print("=" * 70)
    print("FACT REFERENCE TRACKING TESTS")
    print("=" * 70)

    results = {}

    try:
        # Run tests
        results['parsing'] = test_parse_fact_references()
        results['database_update'] = test_update_fact_references()
        results['system_prompt'] = test_system_prompt_formatting()
        results['end_to_end'] = test_end_to_end()

        # Summary
        print("\n" + "=" * 70)
        print("TEST SUMMARY")
        print("=" * 70)

        for test_name, passed in results.items():
            status = "✓ PASSED" if passed else "✗ FAILED"
            print(f"{test_name.replace('_', ' ').title()}: {status}")

        all_passed = all(results.values())
        print("\n" + "=" * 70)
        if all_passed:
            print("✓ ALL TESTS PASSED")
            print("\nFact reference tracking is working correctly!")
            print("Iris will now track which facts she uses via [FACTS_USED: id1, id2] markers.")
        else:
            print("✗ SOME TESTS FAILED")
        print("=" * 70)

        return all_passed

    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
