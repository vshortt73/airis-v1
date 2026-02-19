"""
Test script for short-term facts database schema
Verifies table creation and basic operations
"""

import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)

import psycopg2
from app import config

def get_db_connection():
    """Create database connection"""
    password = os.environ.get('AIRIS_DB_PASSWORD') or getattr(config, 'DB_PASSWORD', None)

    conn_params = {
        'host': config.DB_HOST,
        'port': config.DB_PORT,
        'database': config.DB_NAME,
        'user': config.DB_USER
    }

    if password:
        conn_params['password'] = password

    return psycopg2.connect(**conn_params)

def create_table():
    """Create the short_term_facts table"""
    print("[test_short_term_facts_schema] Creating short_term_facts table...")

    conn = get_db_connection()
    cursor = conn.cursor()

    # Read and execute SQL file
    sql_file = os.path.join(PROJECT_ROOT, 'database', 'sql', 'create_short_term_facts.sql')
    with open(sql_file, 'r') as f:
        sql = f.read()

    cursor.execute(sql)
    conn.commit()

    print("[test_short_term_facts_schema] ✓ Table created successfully")

    cursor.close()
    conn.close()

def verify_schema():
    """Verify table schema matches specification"""
    print("\n[test_short_term_facts_schema] Verifying table schema...")

    conn = get_db_connection()
    cursor = conn.cursor()

    # Check table exists
    cursor.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables
            WHERE table_name = 'short_term_facts'
        );
    """)

    exists = cursor.fetchone()[0]
    if not exists:
        print("[test_short_term_facts_schema] ✗ Table does not exist!")
        return False

    print("[test_short_term_facts_schema] ✓ Table exists")

    # Check columns
    cursor.execute("""
        SELECT column_name, data_type, column_default
        FROM information_schema.columns
        WHERE table_name = 'short_term_facts'
        ORDER BY ordinal_position;
    """)

    columns = cursor.fetchall()
    print(f"\n[test_short_term_facts_schema] Table columns:")
    for col_name, data_type, default in columns:
        print(f"  - {col_name}: {data_type} (default: {default})")

    # Check indexes
    cursor.execute("""
        SELECT indexname, indexdef
        FROM pg_indexes
        WHERE tablename = 'short_term_facts'
        ORDER BY indexname;
    """)

    indexes = cursor.fetchall()
    print(f"\n[test_short_term_facts_schema] Table indexes:")
    for idx_name, idx_def in indexes:
        print(f"  - {idx_name}")

    cursor.close()
    conn.close()

    return True

def test_insert():
    """Test inserting a fact"""
    print("\n[test_short_term_facts_schema] Testing insert operation...")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO short_term_facts (
            fact_text,
            category,
            conversation_id
        ) VALUES (
            %s, %s, %s
        ) RETURNING fact_id, created_date, status, reference_count;
    """, (
        "Test fact: Victor is testing the short-term memory system",
        "discovery",
        "test_session_123"
    ))

    result = cursor.fetchone()
    fact_id, created_date, status, ref_count = result

    print(f"[test_short_term_facts_schema] ✓ Inserted fact with ID: {fact_id}")
    print(f"  - Created: {created_date}")
    print(f"  - Status: {status}")
    print(f"  - Reference count: {ref_count}")

    conn.commit()
    cursor.close()
    conn.close()

    return fact_id

def test_retrieve(fact_id):
    """Test retrieving facts"""
    print("\n[test_short_term_facts_schema] Testing retrieve operation...")

    conn = get_db_connection()
    cursor = conn.cursor()

    # Retrieve active facts (like the system will do)
    cursor.execute("""
        SELECT
            fact_id,
            fact_text,
            category,
            created_date,
            reference_count
        FROM short_term_facts
        WHERE status = 'active'
          AND (
            created_date > NOW() - INTERVAL '90 days'
            OR last_referenced_date > NOW() - INTERVAL '30 days'
          )
        ORDER BY last_referenced_date DESC
        LIMIT 20;
    """)

    facts = cursor.fetchall()
    print(f"[test_short_term_facts_schema] ✓ Retrieved {len(facts)} active fact(s):")
    for fact in facts:
        fid, text, cat, created, refs = fact
        print(f"  - [{fid}] {text[:60]}... (category: {cat}, refs: {refs})")

    # Update reference tracking for the fact we just retrieved
    cursor.execute("""
        UPDATE short_term_facts
        SET
            last_referenced_date = NOW(),
            reference_count = reference_count + 1
        WHERE fact_id = %s
        RETURNING reference_count;
    """, (fact_id,))

    new_ref_count = cursor.fetchone()[0]
    print(f"\n[test_short_term_facts_schema] ✓ Updated reference count to: {new_ref_count}")

    conn.commit()
    cursor.close()
    conn.close()

def test_archival():
    """Test archival query (simulation)"""
    print("\n[test_short_term_facts_schema] Testing archival query (dry run)...")

    conn = get_db_connection()
    cursor = conn.cursor()

    # Show what WOULD be archived (but don't actually archive yet)
    cursor.execute("""
        SELECT
            fact_id,
            fact_text,
            created_date,
            last_referenced_date,
            reference_count
        FROM short_term_facts
        WHERE created_date < NOW() - INTERVAL '90 days'
          AND last_referenced_date < NOW() - INTERVAL '30 days'
          AND status = 'active';
    """)

    would_archive = cursor.fetchall()
    print(f"[test_short_term_facts_schema] Would archive {len(would_archive)} fact(s) based on criteria")

    cursor.close()
    conn.close()

def cleanup_test_data():
    """Clean up test data"""
    print("\n[test_short_term_facts_schema] Cleaning up test data...")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM short_term_facts WHERE conversation_id = 'test_session_123'")
    deleted = cursor.rowcount

    print(f"[test_short_term_facts_schema] ✓ Deleted {deleted} test fact(s)")

    conn.commit()
    cursor.close()
    conn.close()

def main():
    """Run all tests"""
    print("=" * 60)
    print("SHORT-TERM FACTS DATABASE SCHEMA TEST")
    print("=" * 60)

    try:
        # 1. Create table
        create_table()

        # 2. Verify schema
        if not verify_schema():
            print("\n✗ Schema verification failed!")
            return

        # 3. Test insert
        fact_id = test_insert()

        # 4. Test retrieve
        test_retrieve(fact_id)

        # 5. Test archival query
        test_archival()

        # 6. Cleanup
        cleanup_test_data()

        print("\n" + "=" * 60)
        print("✓ ALL TESTS PASSED")
        print("=" * 60)

    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
