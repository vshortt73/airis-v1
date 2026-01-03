#!/usr/bin/env python3
"""
Apply memory_processed_at column migration to chat_history table

This script adds the memory_processed_at column to track which topics
have been evaluated for memory creation, preventing re-processing.
"""

import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, PROJECT_ROOT)

import psycopg2
from app import config

def get_db_connection():
    """Get database connection with password from environment"""
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

def apply_migration():
    """Apply the migration"""
    print("="*60)
    print("APPLYING MEMORY PROCESSING MIGRATION")
    print("="*60)

    # Read SQL file
    sql_file = os.path.join(os.path.dirname(__file__), 'add_memory_processed_column.sql')

    if not os.path.exists(sql_file):
        print(f"✗ SQL file not found: {sql_file}")
        return False

    with open(sql_file, 'r') as f:
        sql = f.read()

    # Apply migration
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            print("\n[1/3] Adding memory_processed_at column...")
            cur.execute(sql)
            conn.commit()
            print("✓ Column added successfully")

            # Check if column exists
            print("\n[2/3] Verifying column...")
            cur.execute("""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_name = 'chat_history'
                AND column_name = 'memory_processed_at'
            """)
            result = cur.fetchone()
            if result:
                print(f"✓ Column verified: {result[0]} ({result[1]}, nullable={result[2]})")
            else:
                print("✗ Column not found after migration!")
                return False

            # Check how many topics exist
            print("\n[3/3] Checking topic counts...")
            cur.execute("""
                SELECT
                    COUNT(DISTINCT topic_id) FILTER (WHERE topic_id IS NOT NULL AND topic_id != 0) as total_topics,
                    COUNT(DISTINCT topic_id) FILTER (WHERE memory_processed_at IS NULL AND topic_id IS NOT NULL AND topic_id != 0) as unprocessed_topics,
                    COUNT(DISTINCT topic_id) FILTER (WHERE memory_processed_at IS NOT NULL) as processed_topics
                FROM chat_history
            """)
            counts = cur.fetchone()
            print(f"  Total topics: {counts[0]}")
            print(f"  Unprocessed topics: {counts[1]}")
            print(f"  Already processed: {counts[2]}")

            print("\n" + "="*60)
            print("✓ MIGRATION COMPLETE")
            print("="*60)
            print("\nNext steps:")
            print("1. Run memory_creation.py to process unprocessed topics")
            print("2. Topics deemed 'not worthy' will now be marked as processed")
            print("3. Future runs will skip already-processed topics")
            return True

    except Exception as e:
        print(f"\n✗ Error applying migration: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        conn.close()

if __name__ == "__main__":
    success = apply_migration()
    sys.exit(0 if success else 1)
