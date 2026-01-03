#!/usr/bin/env python3
"""
Fix Session IDs Script

Recreates session_id values in chat_history based on conversation gaps.
Messages within 20 minutes of each other belong to the same session.

Usage:
    python fix_session_ids.py --dry-run            # Preview changes
    python fix_session_ids.py --commit             # Apply changes
    python fix_session_ids.py --gap 30 --commit    # Use 30-minute gap
"""

import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
sys.path.insert(0, PROJECT_ROOT)

import argparse
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor
import uuid

try:
    from app import config
except ImportError:
    print("Error: Could not import config. Make sure you're running from the project root.")
    sys.exit(1)

def get_db_connection():
    """Get database connection"""
    password = os.environ.get('IRIS_DB_PASSWORD') or getattr(config, 'IRIS_DB_PASSWORD', None)

    conn_params = {
        'host': config.DB_HOST,
        'port': config.DB_PORT,
        'database': config.DB_NAME,
        'user': config.DB_USER
    }

    if password:
        conn_params['password'] = password

    return psycopg2.connect(**conn_params)

def load_all_messages(conn):
    """Load all messages from chat_history ordered by timestamp"""
    print("\n[Loading] Fetching all messages from chat_history...")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT id, c_timestamp, session_id, role, message
            FROM chat_history
            ORDER BY c_timestamp ASC
        """)

        messages = cur.fetchall()
        print(f"[Loading] ✓ Loaded {len(messages)} messages")
        return messages

def analyze_current_sessions(messages):
    """Analyze current session distribution"""
    session_counts = {}

    for msg in messages:
        session_id = msg['session_id']
        if session_id not in session_counts:
            session_counts[session_id] = 0
        session_counts[session_id] += 1

    # Count sessions by size
    size_distribution = {}
    for count in session_counts.values():
        if count not in size_distribution:
            size_distribution[count] = 0
        size_distribution[count] += 1

    print("\n[Current State] Session distribution:")
    print(f"  Total sessions: {len(session_counts)}")
    print(f"  Total messages: {len(messages)}")

    # Show distribution
    for size in sorted(size_distribution.keys())[:10]:  # Show first 10 sizes
        count = size_distribution[size]
        print(f"    Sessions with {size} message(s): {count}")

    if len(size_distribution) > 10:
        print(f"    ... and {len(size_distribution) - 10} more size categories")

    return session_counts

def create_new_sessions(messages, gap_minutes=20):
    """
    Create new session groupings based on time gaps

    Args:
        messages: List of all messages ordered by timestamp
        gap_minutes: Gap in minutes to trigger new session

    Returns:
        Dict mapping message id to new session_id
    """
    print(f"\n[Regrouping] Creating new sessions with {gap_minutes}-minute gap threshold...")

    if not messages:
        return {}

    new_assignments = {}
    current_session_id = str(uuid.uuid4())
    previous_timestamp = None
    session_count = 0
    message_count = 0

    session_messages = []  # Track messages per session

    for msg in messages:
        msg_timestamp = msg['c_timestamp']

        # First message or gap exceeded
        if previous_timestamp is None:
            # First message ever
            current_session_id = str(uuid.uuid4())
            session_count = 1
            message_count = 1
            session_messages = [msg_timestamp]
        else:
            # Calculate gap
            gap = msg_timestamp - previous_timestamp
            gap_minutes_actual = gap.total_seconds() / 60

            if gap_minutes_actual >= gap_minutes:
                # Start new session
                print(f"  [Session {session_count}] {message_count} messages (gap: {gap_minutes_actual:.1f} min)")
                current_session_id = str(uuid.uuid4())
                session_count += 1
                message_count = 1
                session_messages = [msg_timestamp]
            else:
                # Continue current session
                message_count += 1
                session_messages.append(msg_timestamp)

        new_assignments[msg['id']] = current_session_id
        previous_timestamp = msg_timestamp

    # Print last session
    print(f"  [Session {session_count}] {message_count} messages")

    print(f"\n[Regrouping] ✓ Created {session_count} sessions from {len(messages)} messages")

    return new_assignments

def analyze_new_sessions(new_assignments):
    """Analyze new session distribution"""
    session_counts = {}

    for session_id in new_assignments.values():
        if session_id not in session_counts:
            session_counts[session_id] = 0
        session_counts[session_id] += 1

    # Count sessions by size
    size_distribution = {}
    for count in session_counts.values():
        if count not in size_distribution:
            size_distribution[count] = 0
        size_distribution[count] += 1

    print("\n[New State] Session distribution:")
    print(f"  Total sessions: {len(session_counts)}")
    print(f"  Total messages: {len(new_assignments)}")

    # Show distribution
    for size in sorted(size_distribution.keys())[:10]:  # Show first 10 sizes
        count = size_distribution[size]
        print(f"    Sessions with {size} message(s): {count}")

    if len(size_distribution) > 10:
        print(f"    ... and {len(size_distribution) - 10} more size categories")

    return session_counts

def apply_new_sessions(conn, new_assignments, dry_run=True):
    """
    Apply new session IDs to database

    Args:
        conn: Database connection
        new_assignments: Dict mapping message id to new session_id
        dry_run: If True, don't actually commit changes
    """
    if dry_run:
        print("\n[Dry Run] Would update session_id for all messages")
        print("[Dry Run] Use --commit to apply changes")
        return

    print("\n[Updating] Applying new session IDs to database...")

    with conn.cursor() as cur:
        # Update each message
        update_count = 0
        for msg_id, new_session_id in new_assignments.items():
            cur.execute("""
                UPDATE chat_history
                SET session_id = %s
                WHERE id = %s
            """, (new_session_id, msg_id))
            update_count += 1

            if update_count % 100 == 0:
                print(f"  Updated {update_count}/{len(new_assignments)} messages...")

        conn.commit()
        print(f"[Updating] ✓ Updated {update_count} messages with new session IDs")

def main():
    parser = argparse.ArgumentParser(
        description='Fix session IDs in chat_history based on conversation gaps'
    )
    parser.add_argument(
        '--gap',
        type=int,
        default=20,
        help='Gap in minutes to trigger new session (default: 20)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without applying them (default)'
    )
    parser.add_argument(
        '--commit',
        action='store_true',
        help='Actually apply the changes to the database'
    )

    args = parser.parse_args()

    # Default to dry-run unless --commit is specified
    dry_run = not args.commit

    print("=" * 60)
    print("SESSION ID FIX SCRIPT")
    print("=" * 60)
    print(f"Gap threshold: {args.gap} minutes")
    print(f"Mode: {'DRY RUN (no changes)' if dry_run else 'COMMIT (will modify database)'}")
    print("=" * 60)

    # Connect to database
    conn = get_db_connection()

    try:
        # Load all messages
        messages = load_all_messages(conn)

        if not messages:
            print("[Error] No messages found in chat_history")
            return

        # Analyze current state
        analyze_current_sessions(messages)

        # Create new session groupings
        new_assignments = create_new_sessions(messages, gap_minutes=args.gap)

        # Analyze new state
        analyze_new_sessions(new_assignments)

        # Apply changes
        apply_new_sessions(conn, new_assignments, dry_run=dry_run)

        if dry_run:
            print("\n" + "=" * 60)
            print("DRY RUN COMPLETE - No changes made")
            print("Run with --commit to apply these changes")
            print("=" * 60)
        else:
            print("\n" + "=" * 60)
            print("✓ SESSION IDs UPDATED SUCCESSFULLY")
            print("=" * 60)

    finally:
        conn.close()

if __name__ == "__main__":
    main()
