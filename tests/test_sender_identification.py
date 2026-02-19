#!/usr/bin/env python3
"""
Test script to verify sender identification in chat_history
"""
import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
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

def test_sender_identification():
    """Query recent messages and show sender information"""
    print("=== Testing Sender Identification ===\n")

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Check if sender column exists
        cursor.execute("""
            SELECT column_name, data_type, column_default
            FROM information_schema.columns
            WHERE table_name = 'chat_history'
            AND column_name = 'sender'
        """)

        result = cursor.fetchone()
        if result:
            print(f"✓ Sender column exists: {result[0]} ({result[1]}) DEFAULT {result[2]}\n")
        else:
            print("✗ Sender column NOT found in chat_history table!\n")
            return

        # Get recent messages with sender info
        cursor.execute("""
            SELECT
                id,
                role,
                sender,
                LEFT(message, 50) as preview,
                c_timestamp
            FROM chat_history
            ORDER BY c_timestamp DESC
            LIMIT 20
        """)

        messages = cursor.fetchall()

        if not messages:
            print("No messages found in chat_history\n")
            return

        print(f"Recent messages (last 20):\n")
        print(f"{'ID':<8} {'Role':<10} {'Sender':<15} {'Preview':<50} {'Timestamp'}")
        print("=" * 120)

        for msg in messages:
            msg_id, role, sender, preview, timestamp = msg
            sender_display = sender or "NULL"
            preview_display = (preview or "")[:47] + "..." if preview and len(preview) > 50 else (preview or "")
            print(f"{msg_id:<8} {role:<10} {sender_display:<15} {preview_display:<50} {timestamp}")

        # Count by sender
        cursor.execute("""
            SELECT sender, COUNT(*) as count
            FROM chat_history
            GROUP BY sender
            ORDER BY count DESC
        """)

        sender_counts = cursor.fetchall()

        print(f"\nMessage counts by sender:")
        print("=" * 40)
        for sender, count in sender_counts:
            sender_display = sender or "NULL"
            print(f"{sender_display:<20} {count:>5} messages")

        cursor.close()
        conn.close()

        print("\n✓ Sender identification test complete!")

    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_sender_identification()
