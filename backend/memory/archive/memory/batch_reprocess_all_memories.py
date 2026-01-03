"""
Batch re-process ALL memories with V3 system (improved summaries + KEY_DETAILS)

Features:
- Resume capability (tracks progress with memory_version column)
- Error handling (logs failures, continues processing)
- Progress tracking (saves after each batch)
- Detailed logging

Usage:
    python batch_reprocess_all_memories.py [--batch-size 50] [--start-from ID]
"""

import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, PROJECT_ROOT)

import asyncio
import psycopg2
from psycopg2.extras import DictCursor
from datetime import datetime
from Colors import Colors
import argparse
import time

# Import the improved memory creation functions
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'new'))
from memory_creation import generate_summaries, analyze_emotions
from core.embeddings import generate_embedding

# Import emotion scoring from retrieval system (has valence/arousal)
from memory_retrieval_v2 import score_emotion

DB_CFG = dict(
    dbname="irisdb",
    user="irisuser",
    password=os.environ.get('IRIS_DB_PASSWORD', 'yourpassword'),
    host="localhost",
    port=5432
)

# Progress tracking
PROGRESS_FILE = "/iris-v3/backend/memory/batch_progress.txt"
ERROR_LOG = "/iris-v3/backend/memory/batch_errors.log"


def log_error(memory_id: int, error: str):
    """Log errors to file"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(ERROR_LOG, 'a') as f:
        f.write(f"[{timestamp}] Memory {memory_id}: {error}\n")


def save_progress(last_processed_id: int, total_processed: int, total_failed: int):
    """Save progress to file"""
    with open(PROGRESS_FILE, 'w') as f:
        f.write(f"last_id={last_processed_id}\n")
        f.write(f"processed={total_processed}\n")
        f.write(f"failed={total_failed}\n")
        f.write(f"timestamp={datetime.now().isoformat()}\n")


def load_progress():
    """Load progress from file"""
    if not os.path.exists(PROGRESS_FILE):
        return None

    try:
        with open(PROGRESS_FILE, 'r') as f:
            data = {}
            for line in f:
                key, value = line.strip().split('=')
                data[key] = value
            return data
    except Exception as e:
        print(f"[Progress] Could not load progress: {e}")
        return None


async def reprocess_single_memory(memory_id: int, transcript: str, category: str, conn) -> bool:
    """Re-process a single memory with improved V3 system"""

    try:
        # 1. Generate improved summaries (with category-aware prompts)
        summaries = await generate_summaries(transcript, conv_title=None, category=category)

        if not summaries:
            return False

        # Handle missing key_details
        if not summaries.get('key_details'):
            summaries['key_details'] = ''

        # 2. Generate embeddings for all 5 facets
        emb_summary_context = generate_embedding(summaries['summary_context']) if summaries['summary_context'] else None
        emb_summary_event = generate_embedding(summaries['summary_event']) if summaries['summary_event'] else None
        emb_summary_significance = generate_embedding(summaries['summary_significance']) if summaries['summary_significance'] else None
        emb_takeaway = generate_embedding(summaries['takeaway']) if summaries['takeaway'] else None
        emb_key_details = generate_embedding(summaries['key_details']) if summaries['key_details'] else None

        # 3. Score emotions (using retrieval system's emotion scorer)
        emotion = score_emotion(transcript)

        # 4. Update database
        cur = conn.cursor()
        cur.execute("""
            UPDATE episodic_memories
            SET
                summary_context = %s,
                summary_event = %s,
                summary_significance = %s,
                summary_tone = %s,
                takeaway = %s,
                key_details = %s,
                emb_summary_context = %s,
                emb_summary_event = %s,
                emb_summary_significance = %s,
                emb_takeaway = %s,
                emb_key_details = %s,
                emotion_label = %s,
                valence = %s,
                arousal = %s,
                memory_version = 'V3',
                updated_at = NOW()
            WHERE id = %s
        """, (
            summaries['summary_context'],
            summaries['summary_event'],
            summaries['summary_significance'],
            summaries['summary_tone'],
            summaries['takeaway'],
            summaries['key_details'],
            emb_summary_context,
            emb_summary_event,
            emb_summary_significance,
            emb_takeaway,
            emb_key_details,
            emotion['emotion_label'],
            emotion['valence'],
            emotion['arousal'],
            memory_id
        ))
        cur.close()

        return True

    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}"
        log_error(memory_id, error_msg)
        return False


async def batch_reprocess(batch_size: int = 50, start_from_id: int = None):
    """Batch re-process all V2 memories to V3"""

    print(f"\n{Colors.BRIGHT_MAGENTA}{'='*80}")
    print("BATCH RE-PROCESSING: V2 → V3 MEMORY SYSTEM")
    print(f"{'='*80}{Colors.RESET}\n")

    # Check for previous progress
    progress = load_progress()
    if progress and not start_from_id:
        print(f"{Colors.BRIGHT_CYAN}Previous progress found:{Colors.RESET}")
        print(f"  Last processed ID: {progress['last_id']}")
        print(f"  Total processed: {progress['processed']}")
        print(f"  Total failed: {progress['failed']}")
        print(f"  Timestamp: {progress['timestamp']}")

        resume = input("\nResume from last position? (y/n): ")
        if resume.lower() == 'y':
            start_from_id = int(progress['last_id']) + 1
            print(f"{Colors.BRIGHT_GREEN}Resuming from ID {start_from_id}{Colors.RESET}\n")

    # Get memories to process
    conn = psycopg2.connect(**DB_CFG)
    cur = conn.cursor(cursor_factory=DictCursor)

    # Count total
    cur.execute("""
        SELECT COUNT(*)
        FROM episodic_memories
        WHERE memory_version != 'V3' OR memory_version IS NULL
    """)
    total_remaining = cur.fetchone()[0]

    print(f"Memories to process: {Colors.BRIGHT_YELLOW}{total_remaining}{Colors.RESET}")
    print(f"Batch size: {batch_size}")
    print(f"Estimated time: {Colors.BRIGHT_CYAN}{(total_remaining * 60) / 3600:.1f} hours{Colors.RESET}")
    print()

    # Process in batches
    success_count = 0
    fail_count = 0
    batch_num = 0
    start_time = time.time()

    while True:
        # Fetch next batch
        query = """
            SELECT id, transcript, category
            FROM episodic_memories
            WHERE (memory_version != 'V3' OR memory_version IS NULL)
        """

        if start_from_id:
            query += f" AND id >= {start_from_id}"

        query += f" ORDER BY id LIMIT {batch_size}"

        cur.execute(query)
        batch = cur.fetchall()

        if not batch:
            print(f"\n{Colors.BRIGHT_GREEN}✓ All memories processed!{Colors.RESET}")
            break

        batch_num += 1
        print(f"\n{Colors.BRIGHT_CYAN}Batch {batch_num} ({len(batch)} memories){Colors.RESET}")
        print(f"IDs: {batch[0]['id']} → {batch[-1]['id']}")

        # Process batch
        batch_success = 0
        batch_fail = 0

        for i, mem in enumerate(batch, 1):
            print(f"  [{i}/{len(batch)}] ID {mem['id']}: ", end='', flush=True)

            success = await reprocess_single_memory(
                mem['id'],
                mem['transcript'],
                mem['category'],
                conn
            )

            if success:
                print(f"{Colors.BRIGHT_GREEN}✓{Colors.RESET}")
                batch_success += 1
                success_count += 1
            else:
                print(f"{Colors.BRIGHT_RED}✗{Colors.RESET}")
                batch_fail += 1
                fail_count += 1

        # Commit batch
        conn.commit()

        # Save progress
        last_id = batch[-1]['id']
        save_progress(last_id, success_count, fail_count)

        # Stats
        elapsed = time.time() - start_time
        rate = success_count / elapsed if elapsed > 0 else 0
        remaining = total_remaining - (success_count + fail_count)
        eta_seconds = remaining / rate if rate > 0 else 0

        print(f"\n  Batch: {Colors.BRIGHT_GREEN}{batch_success} success{Colors.RESET}, ", end='')
        print(f"{Colors.BRIGHT_RED}{batch_fail} failed{Colors.RESET}")
        print(f"  Total: {success_count} processed, {fail_count} failed, {remaining} remaining")
        print(f"  Rate: {rate * 60:.1f} memories/min")
        print(f"  ETA: {eta_seconds / 3600:.1f} hours")
        print(f"  Progress saved to: {PROGRESS_FILE}")

    # Final summary
    cur.close()
    conn.close()

    total_time = time.time() - start_time

    print(f"\n{Colors.BRIGHT_MAGENTA}{'='*80}")
    print("BATCH PROCESSING COMPLETE")
    print(f"{'='*80}{Colors.RESET}\n")
    print(f"Total processed: {Colors.BRIGHT_GREEN}{success_count}{Colors.RESET}")
    print(f"Total failed: {Colors.BRIGHT_RED}{fail_count}{Colors.RESET}")
    print(f"Total time: {total_time / 3600:.2f} hours")
    print(f"Average rate: {success_count / (total_time / 60):.1f} memories/min")

    if fail_count > 0:
        print(f"\n{Colors.BRIGHT_YELLOW}Check error log: {ERROR_LOG}{Colors.RESET}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Batch re-process all memories to V3')
    parser.add_argument('--batch-size', type=int, default=50,
                       help='Number of memories to process per batch (default: 50)')
    parser.add_argument('--start-from', type=int,
                       help='Start from specific memory ID (overrides resume)')

    args = parser.parse_args()

    asyncio.run(batch_reprocess(
        batch_size=args.batch_size,
        start_from_id=args.start_from
    ))
