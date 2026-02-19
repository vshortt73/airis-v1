"""
Backfill turn_metrics from chat_history.

Populates partial turn_metrics rows from historical assistant messages:
  - response_embedding (generated fresh via all-mpnet-base-v2)
  - response_tokens (tiktoken count)
  - session_id, timestamp
  - tool_calls_count, tools_used (parsed from chat_history.tool_calls JSON)

Fields that CANNOT be backfilled (ephemeral data, never persisted):
  - Memory retrieval provenance (live_memories truncated each turn)
  - Emotional state before/after (only current state stored)
  - KV cache metrics (logged to console only)
  - Memory influence scores (need retrieval context at time of response)

Usage:
    python backend/observability/backfill_turn_metrics.py [--batch-size 100] [--dry-run]

Estimated time: ~12 minutes for 14K messages (50ms per embedding).
Idempotent: skips timestamps that already have a turn_metrics row.
"""

import os
import sys
import json
import time
import argparse

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ["HF_HUB_OFFLINE"] = "1"

import psycopg2
import psycopg2.extras

DB_CFG = {
    'dbname': os.environ.get('AIRIS_DB_NAME', 'airisdb'),
    'user': os.environ.get('AIRIS_DB_USER', 'airisuser'),
    'password': os.environ.get('AIRIS_DB_PASSWORD', ''),
    'host': 'localhost',
    'port': 5432,
}


def get_conn():
    return psycopg2.connect(**DB_CFG)


def backfill(batch_size: int = 100, dry_run: bool = False):
    from core.embeddings import generate_embedding
    from core.token_counter import TokenCounter

    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Find assistant messages not yet in turn_metrics.
    # Match on timestamp to avoid duplicates.
    cur.execute("""
        SELECT ch.id, ch.session_id, ch.c_timestamp, ch.message, ch.tool_calls
        FROM chat_history ch
        LEFT JOIN turn_metrics tm ON tm.timestamp = ch.c_timestamp
                                  AND tm.session_id = ch.session_id
        WHERE ch.role = 'assistant'
          AND ch.message IS NOT NULL
          AND LENGTH(ch.message) > 20
          AND tm.id IS NULL
        ORDER BY ch.c_timestamp ASC
    """)

    rows = cur.fetchall()
    total = len(rows)
    print(f"[backfill] {total} assistant messages to backfill")

    if dry_run:
        print(f"[backfill] Dry run — not writing anything")
        cur.close()
        conn.close()
        return

    # Process in batches
    inserted = 0
    errors = 0
    t0 = time.time()

    insert_cur = conn.cursor()

    for i, row in enumerate(rows):
        try:
            message = row["message"]
            session_id = row["session_id"]
            timestamp = row["c_timestamp"]

            # Embed response (truncate to 2000 chars for consistency with live capture)
            emb = generate_embedding(message[:2000])
            emb_str = None
            if emb:
                emb_str = "[" + ",".join(str(float(v)) for v in emb) + "]"

            # Count tokens
            response_tokens = TokenCounter.count_tokens(message)

            # Parse tool_calls
            tool_calls_count = 0
            tools_used = None
            if row.get("tool_calls"):
                tc = row["tool_calls"]
                if isinstance(tc, str):
                    try:
                        tc = json.loads(tc)
                    except json.JSONDecodeError:
                        tc = []
                if isinstance(tc, list):
                    tool_calls_count = len(tc)
                    tool_names = list({
                        t.get("function", {}).get("name", "unknown")
                        for t in tc if isinstance(t, dict)
                    })
                    tools_used = tool_names if tool_names else None

            insert_cur.execute("""
                INSERT INTO turn_metrics (
                    session_id, timestamp,
                    response_embedding, response_tokens,
                    tool_calls_count, tools_used
                ) VALUES (
                    %s, %s,
                    %s::vector, %s,
                    %s, %s
                )
            """, (
                session_id, timestamp,
                emb_str, response_tokens,
                tool_calls_count, tools_used,
            ))

            inserted += 1

            # Commit in batches
            if inserted % batch_size == 0:
                conn.commit()
                elapsed = time.time() - t0
                rate = inserted / elapsed if elapsed > 0 else 0
                eta = (total - inserted) / rate if rate > 0 else 0
                print(f"[backfill] {inserted}/{total} ({inserted*100//total}%) — "
                      f"{rate:.1f} rows/s, ETA {eta:.0f}s")

        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f"[backfill] Error on row {i} (chat_history.id={row['id']}): {e}")
            elif errors == 6:
                print(f"[backfill] Suppressing further error messages...")

    # Final commit
    conn.commit()
    insert_cur.close()
    cur.close()
    conn.close()

    elapsed = time.time() - t0
    print(f"\n[backfill] Complete: {inserted} inserted, {errors} errors, {elapsed:.1f}s")
    print(f"[backfill] Rate: {inserted/elapsed:.1f} rows/s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill turn_metrics from chat_history")
    parser.add_argument("--batch-size", type=int, default=100, help="Commit every N rows")
    parser.add_argument("--dry-run", action="store_true", help="Count rows only, don't write")
    args = parser.parse_args()
    backfill(batch_size=args.batch_size, dry_run=args.dry_run)
