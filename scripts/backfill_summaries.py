#!/usr/bin/env python3
"""
Backfill Summaries Script

Generates summaries for existing messages in chat_history that don't have them.
Uses the Mistral 7B model on node2 for fast summary generation.

Usage:
    # Backfill all messages needing summaries
    python scripts/backfill_summaries.py

    # Backfill with custom batch size
    python scripts/backfill_summaries.py --batch-size 50

    # Dry run (show what would be processed)
    python scripts/backfill_summaries.py --dry-run

    # Process specific number of messages
    python scripts/backfill_summaries.py --limit 100
"""

import os
import sys
import asyncio
import argparse
from datetime import datetime

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)

from database.persistence import (
    get_db_connection,
    get_current_chat_table,
    get_messages_needing_summaries,
    save_summary
)
from core.summary_generator import SummaryGenerator
from app import config


async def backfill_summaries(
    batch_size: int = 20,
    limit: int = None,
    dry_run: bool = False
):
    """
    Backfill summaries for existing messages.

    Args:
        batch_size: Number of messages to process in parallel
        limit: Maximum total messages to process (None = all)
        dry_run: If True, just show what would be processed
    """
    print("=" * 60)
    print("SUMMARY BACKFILL")
    print("=" * 60)
    print(f"Batch size: {batch_size}")
    print(f"Limit: {limit or 'unlimited'}")
    print(f"Dry run: {dry_run}")
    print()

    # Get messages needing summaries
    fetch_limit = limit or 10000
    messages = get_messages_needing_summaries(fetch_limit)

    if not messages:
        print("No messages need summaries!")
        return

    print(f"Found {len(messages)} messages needing summaries")

    if limit:
        messages = messages[:limit]
        print(f"Processing {len(messages)} messages (limited)")

    if dry_run:
        print("\n[DRY RUN] Would process these messages:")
        for i, msg in enumerate(messages[:20]):  # Show first 20
            content_preview = msg['content'][:80].replace('\n', ' ')
            print(f"  {i+1}. ID {msg['id']} ({msg['role']}): {content_preview}...")
        if len(messages) > 20:
            print(f"  ... and {len(messages) - 20} more")
        return

    # Initialize summary generator
    generator = SummaryGenerator()

    # Process in batches
    total_processed = 0
    total_success = 0
    total_failed = 0
    start_time = datetime.now()

    try:
        for i in range(0, len(messages), batch_size):
            batch = messages[i:i + batch_size]
            batch_num = (i // batch_size) + 1
            total_batches = (len(messages) + batch_size - 1) // batch_size

            print(f"\n--- Batch {batch_num}/{total_batches} ({len(batch)} messages) ---")

            # Generate summaries for batch
            results = await generator.generate_summaries_batch(batch)

            # Save successful summaries
            for msg_id, summary in results.items():
                if save_summary(msg_id, summary):
                    total_success += 1
                else:
                    total_failed += 1

            total_processed += len(batch)
            failed_in_batch = len(batch) - len(results)
            total_failed += failed_in_batch

            # Progress
            elapsed = (datetime.now() - start_time).total_seconds()
            rate = total_processed / elapsed if elapsed > 0 else 0
            print(f"Progress: {total_processed}/{len(messages)} ({total_success} success, {total_failed} failed)")
            print(f"Rate: {rate:.1f} messages/sec")

            # Small delay between batches to avoid overwhelming the server
            if i + batch_size < len(messages):
                await asyncio.sleep(0.5)

    finally:
        await generator.close()

    # Summary
    elapsed = (datetime.now() - start_time).total_seconds()
    print()
    print("=" * 60)
    print("BACKFILL COMPLETE")
    print("=" * 60)
    print(f"Total processed: {total_processed}")
    print(f"Successful: {total_success}")
    print(f"Failed: {total_failed}")
    print(f"Time: {elapsed:.1f} seconds")
    print(f"Rate: {total_processed / elapsed:.1f} messages/sec")


def count_messages_needing_summaries():
    """Count how many messages need summaries"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        chat_table = get_current_chat_table()
        min_length = getattr(config, 'SUMMARY_MIN_LENGTH', 50)

        cursor.execute(f"""
            SELECT
                COUNT(*) FILTER (WHERE summary IS NULL AND LENGTH(message) >= %s) as needs_summary,
                COUNT(*) FILTER (WHERE summary IS NOT NULL) as has_summary,
                COUNT(*) as total
            FROM {chat_table}
            WHERE role IN ('user', 'assistant')
        """, (min_length,))

        row = cursor.fetchone()
        cursor.close()
        conn.close()

        return {
            'needs_summary': row[0],
            'has_summary': row[1],
            'total': row[2]
        }

    except Exception as e:
        print(f"Error counting messages: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(description="Backfill summaries for chat messages")
    parser.add_argument('--batch-size', type=int, default=20,
                        help='Messages to process in parallel (default: 20)')
    parser.add_argument('--limit', type=int, default=None,
                        help='Maximum messages to process (default: all)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be processed without doing it')
    parser.add_argument('--count', action='store_true',
                        help='Just count messages needing summaries')

    args = parser.parse_args()

    if args.count:
        counts = count_messages_needing_summaries()
        if counts:
            print(f"Messages needing summaries: {counts['needs_summary']}")
            print(f"Messages with summaries: {counts['has_summary']}")
            print(f"Total eligible messages: {counts['total']}")
        return

    asyncio.run(backfill_summaries(
        batch_size=args.batch_size,
        limit=args.limit,
        dry_run=args.dry_run
    ))


if __name__ == "__main__":
    main()
