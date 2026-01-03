#!/usr/bin/env python3
"""
Backfill embeddings for chat_history messages that are missing them
Processes messages in batches for efficiency
"""
import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, PROJECT_ROOT)

import psycopg2
from app import config
from core.embeddings import generate_embeddings_batch
from typing import List, Tuple

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

def get_messages_without_embeddings(conn, limit: int = 100) -> List[Tuple[int, str]]:
    """
    Get messages that don't have embeddings

    Returns:
        List of (id, message) tuples
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, message
        FROM chat_history
        WHERE emb_message IS NULL
          AND message IS NOT NULL
          AND message != ''
        ORDER BY id ASC
        LIMIT %s
    """, (limit,))

    results = cursor.fetchall()
    cursor.close()
    return results

def update_embeddings(conn, updates: List[Tuple[int, List[float]]]) -> int:
    """
    Update chat_history with embeddings

    Args:
        updates: List of (id, embedding) tuples

    Returns:
        Number of rows updated
    """
    cursor = conn.cursor()
    updated_count = 0

    for msg_id, embedding in updates:
        if embedding is None:
            continue

        try:
            cursor.execute("""
                UPDATE chat_history
                SET emb_message = %s
                WHERE id = %s
            """, (embedding, msg_id))
            updated_count += cursor.rowcount
        except Exception as e:
            print(f"[backfill] ✗ Error updating message {msg_id}: {e}")
            continue

    conn.commit()
    cursor.close()
    return updated_count

def backfill_embeddings(batch_size: int = 100, max_messages: int = None):
    """
    Backfill embeddings for all messages that don't have them

    Args:
        batch_size: Number of messages to process at once
        max_messages: Maximum number of messages to process (None = all)
    """
    print("=" * 70)
    print("EMBEDDING BACKFILL SCRIPT")
    print("=" * 70)

    conn = get_db_connection()

    # Get total count
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*)
        FROM chat_history
        WHERE emb_message IS NULL
          AND message IS NOT NULL
          AND message != ''
    """)
    total_missing = cursor.fetchone()[0]
    cursor.close()

    print(f"\nTotal messages without embeddings: {total_missing}")

    if total_missing == 0:
        print("✓ All messages already have embeddings!")
        conn.close()
        return

    if max_messages:
        total_to_process = min(total_missing, max_messages)
        print(f"Processing: {total_to_process} messages (limited by max_messages)")
    else:
        total_to_process = total_missing
        print(f"Processing: ALL {total_to_process} messages")

    print(f"Batch size: {batch_size}")
    print()

    processed = 0
    total_updated = 0

    while processed < total_to_process:
        # Get next batch
        messages = get_messages_without_embeddings(conn, batch_size)

        if not messages:
            break

        # Extract IDs and texts
        msg_ids = [m[0] for m in messages]
        msg_texts = [m[1] for m in messages]

        print(f"[Batch {processed // batch_size + 1}] Processing messages {msg_ids[0]} to {msg_ids[-1]}...")

        # Generate embeddings for batch
        try:
            embeddings = generate_embeddings_batch(msg_texts)
            print(f"  ✓ Generated {len(embeddings)} embeddings")
        except Exception as e:
            print(f"  ✗ Error generating embeddings: {e}")
            continue

        # Update database
        updates = list(zip(msg_ids, embeddings))
        updated = update_embeddings(conn, updates)
        total_updated += updated
        processed += len(messages)

        print(f"  ✓ Updated {updated}/{len(messages)} messages")
        print(f"  Progress: {processed}/{total_to_process} ({100 * processed / total_to_process:.1f}%)")
        print()

        if max_messages and processed >= max_messages:
            break

    conn.close()

    print("=" * 70)
    print(f"BACKFILL COMPLETE")
    print(f"  Total processed: {processed}")
    print(f"  Total updated: {total_updated}")
    print(f"  Remaining: {total_missing - processed}")
    print("=" * 70)

def main():
    import argparse

    parser = argparse.ArgumentParser(description='Backfill embeddings for chat_history')
    parser.add_argument('--batch-size', type=int, default=100,
                        help='Number of messages to process at once (default: 100)')
    parser.add_argument('--max-messages', type=int, default=None,
                        help='Maximum number of messages to process (default: all)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be done without actually updating')

    args = parser.parse_args()

    if args.dry_run:
        print("\n*** DRY RUN MODE - No changes will be made ***\n")
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*)
            FROM chat_history
            WHERE emb_message IS NULL
              AND message IS NOT NULL
              AND message != ''
        """)
        count = cursor.fetchone()[0]
        cursor.close()
        conn.close()
        print(f"Would process {count} messages without embeddings")
        return

    try:
        backfill_embeddings(
            batch_size=args.batch_size,
            max_messages=args.max_messages
        )
    except KeyboardInterrupt:
        print("\n\n⚠ Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
