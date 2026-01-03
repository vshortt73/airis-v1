"""
Test script for short-term facts context injection
Verifies facts are properly loaded and formatted in system prompt
"""

import os
import sys
import psycopg2
from datetime import datetime, timedelta

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)

from app import config
from core.system_prompt import get_short_term_facts, build_system_message

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

def insert_test_facts():
    """Insert test facts for testing context injection"""
    print("\n[test_context_injection] Inserting test facts...")

    conn = get_db_connection()
    cursor = conn.cursor()

    # Clean up any existing test facts first
    cursor.execute("DELETE FROM short_term_facts WHERE fact_text LIKE '%[TEST]%'")

    test_facts = [
        ("Victor is testing the short-term memory system [TEST]", "discovery", "test_session_1"),
        ("Victor prefers dark mode interfaces [TEST]", "user_preference", "test_session_2"),
        ("Victor is building a distributed AI cluster [TEST]", "ongoing_project", "test_session_3"),
        ("Victor is waiting for motherboard RMA [TEST]", "user_status", "test_session_4"),
        ("The vision system runs on GPU 1 [TEST]", "discovery", "test_session_5"),
    ]

    for fact_text, category, conversation_id in test_facts:
        cursor.execute("""
            INSERT INTO short_term_facts (
                fact_text,
                category,
                conversation_id,
                created_date,
                last_referenced_date,
                status
            ) VALUES (%s, %s, %s, NOW(), NOW(), 'active')
            RETURNING fact_id;
        """, (fact_text, category, conversation_id))

        fact_id = cursor.fetchone()[0]
        print(f"  ✓ Inserted fact {fact_id}: {fact_text[:50]}...")

    conn.commit()
    cursor.close()
    conn.close()

    print(f"[test_context_injection] Inserted {len(test_facts)} test facts")

def test_get_short_term_facts():
    """Test the get_short_term_facts function"""
    print("\n[test_context_injection] Testing get_short_term_facts()...")

    facts_str = get_short_term_facts(limit=10)

    if not facts_str:
        print("[test_context_injection] ✗ No facts retrieved!")
        return False

    print(f"[test_context_injection] ✓ Retrieved facts:")
    print("─" * 60)
    print(facts_str)
    print("─" * 60)

    # Verify format
    if "[RECENT FACTS]" not in facts_str:
        print("[test_context_injection] ✗ Missing [RECENT FACTS] header!")
        return False

    if "[TEST]" not in facts_str:
        print("[test_context_injection] ✗ Test facts not found in output!")
        return False

    # Count facts
    fact_lines = [line for line in facts_str.split("\n") if line.strip().startswith("-")]
    print(f"\n[test_context_injection] ✓ Found {len(fact_lines)} formatted facts")

    return True

def test_build_system_message():
    """Test that facts are included in system message"""
    print("\n[test_context_injection] Testing build_system_message()...")

    # Temporarily enable SHORT_TERM_FACTS
    original_setting = getattr(config, 'SHORT_TERM_FACTS', True)
    config.SHORT_TERM_FACTS = True

    try:
        system_msg = build_system_message()

        if not system_msg or "content" not in system_msg:
            print("[test_context_injection] ✗ Invalid system message format!")
            return False

        content = system_msg["content"]

        # Check if facts are included
        if "[RECENT FACTS]" in content:
            print("[test_context_injection] ✓ Short-term facts included in system message")

            # Check position in content
            parts = content.split("[RECENT FACTS]")
            print(f"[test_context_injection] Facts appear after {len(parts[0])} characters")

            # Verify test facts are present
            if "[TEST]" in content:
                print("[test_context_injection] ✓ Test facts found in system message")
            else:
                print("[test_context_injection] ✗ Test facts not found in system message!")
                return False

            return True
        else:
            print("[test_context_injection] ✗ Short-term facts NOT included in system message!")
            print(f"[test_context_injection] Content length: {len(content)} characters")
            print(f"[test_context_injection] Content preview: {content[:500]}...")
            return False

    finally:
        # Restore original setting
        config.SHORT_TERM_FACTS = original_setting

def test_reference_tracking():
    """Test that reference count is updated when facts are retrieved"""
    print("\n[test_context_injection] Testing reference tracking...")

    conn = get_db_connection()
    cursor = conn.cursor()

    # Get initial reference counts
    cursor.execute("""
        SELECT fact_id, reference_count
        FROM short_term_facts
        WHERE fact_text LIKE '%[TEST]%'
        ORDER BY fact_id
        LIMIT 1;
    """)

    result = cursor.fetchone()
    if not result:
        print("[test_context_injection] ✗ No test facts found!")
        cursor.close()
        conn.close()
        return False

    fact_id, initial_count = result
    print(f"[test_context_injection] Fact {fact_id} initial reference count: {initial_count}")

    cursor.close()
    conn.close()

    # Retrieve facts (this should increment reference count)
    get_short_term_facts(limit=10)

    # Check new reference count
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT reference_count
        FROM short_term_facts
        WHERE fact_id = %s;
    """, (fact_id,))

    new_count = cursor.fetchone()[0]
    print(f"[test_context_injection] Fact {fact_id} new reference count: {new_count}")

    cursor.close()
    conn.close()

    if new_count > initial_count:
        print(f"[test_context_injection] ✓ Reference count incremented ({initial_count} → {new_count})")
        return True
    else:
        print(f"[test_context_injection] ✗ Reference count not incremented!")
        return False

def cleanup_test_facts():
    """Remove test facts from database"""
    print("\n[test_context_injection] Cleaning up test facts...")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM short_term_facts WHERE fact_text LIKE '%[TEST]%'")
    deleted = cursor.rowcount

    conn.commit()
    cursor.close()
    conn.close()

    print(f"[test_context_injection] ✓ Deleted {deleted} test facts")

def main():
    """Run all context injection tests"""
    print("=" * 70)
    print("SHORT-TERM FACTS CONTEXT INJECTION TESTS")
    print("=" * 70)

    results = {}

    try:
        # 1. Insert test facts
        insert_test_facts()

        # 2. Test fact retrieval and formatting
        results['fact_retrieval'] = test_get_short_term_facts()

        # 3. Test system message integration
        results['system_message'] = test_build_system_message()

        # 4. Test reference tracking
        results['reference_tracking'] = test_reference_tracking()

        # 5. Cleanup
        cleanup_test_facts()

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
            print("\nContext injection is working correctly!")
            print("Short-term facts will now appear in Iris's system prompt.")
        else:
            print("✗ SOME TESTS FAILED")
        print("=" * 70)

        return all_passed

    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()

        # Cleanup on error
        try:
            cleanup_test_facts()
        except:
            pass

        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
