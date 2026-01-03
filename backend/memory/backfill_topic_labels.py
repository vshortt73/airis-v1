"""
Backfill Topic Labels for Existing Memories

Generates topic labels from existing summary fields and embeds them.

Usage:
    # Test on cruise memories only (~2 minutes)
    python backfill_topic_labels.py --cruise-only

    # Full backfill (~10 hours)
    python backfill_topic_labels.py --full

    # Resume from specific ID
    python backfill_topic_labels.py --full --start-id 12345

    # Custom batch size
    python backfill_topic_labels.py --full --batch-size 500
"""

import os
os.environ["HF_HUB_OFFLINE"] = "1"

import sys
import argparse
import httpx
import psycopg2
import time
import json
from datetime import datetime
from sentence_transformers import SentenceTransformer
import numpy as np

# Load embedding model
print("Loading embedding model...")
model = SentenceTransformer("/models/llm_models/huggingface/models/all-mpnet-base-v2/", local_files_only=True)

DB_CFG = dict(dbname="irisdb", user="irisuser", password="yourpassword", host="localhost", port=5432)

def normalize(vec):
    """L2 normalization"""
    arr = np.array(vec, dtype=np.float32)
    norm = np.linalg.norm(arr)
    if norm == 0:
        return arr
    return arr / norm

def generate_topic_label(context, event, significance, takeaway, model_name="qwen2.5:14b"):
    """
    Generate topic label from existing summary fields

    Returns: (topic_label, elapsed_time) or (None, elapsed_time) on failure
    """
    # Handle empty fields
    if not context or not event or not takeaway:
        return None, 0.0

    prompt = f"""Given this memory summary, extract a 2-5 word topic label describing what this is FUNDAMENTALLY about.

Context: {context}
Event: {event}
Significance: {significance}
Takeaway: {takeaway}

Examples of good topic labels:
- "cruise vacation planning"
- "software debugging"
- "cooking recipe development"
- "AI system development"
- "image generation workflow"

Return ONLY the topic label (2-5 words), nothing else. Be specific and concrete."""

    start = time.time()
    try:
        response = httpx.post(
            "http://localhost:11434/api/generate",
            json={
                "model": model_name,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.1,
                    "num_ctx": 2048
                }
            },
            timeout=30.0
        )
        elapsed = time.time() - start

        if response.status_code == 200:
            result = response.json()
            label = result["response"].strip().strip('"').strip()

            # Validate label (not too long, not instructions)
            if len(label) > 100 or "I'm" in label or "please" in label.lower():
                print(f"    ⚠️  Invalid label generated: {label[:50]}")
                return None, elapsed

            return label, elapsed
        else:
            print(f"    ❌ Ollama error: {response.status_code}")
            return None, elapsed

    except Exception as e:
        elapsed = time.time() - start
        print(f"    ❌ Error generating topic: {str(e)[:100]}")
        return None, elapsed

def embed_topic_label(label):
    """Embed topic label and return normalized vector"""
    try:
        vec = model.encode(label)
        normalized = normalize(vec)
        return normalized.tolist()
    except Exception as e:
        print(f"    ❌ Error embedding: {str(e)[:100]}")
        return None

def backfill_memories(cruise_only=False, start_id=None, batch_size=100, model_name="qwen2.5:14b"):
    """
    Backfill topic labels for memories

    Args:
        cruise_only: Only process cruise-related memories (for testing)
        start_id: Resume from this memory ID
        batch_size: Process this many before committing
        model_name: LLM to use for topic generation
    """
    conn = psycopg2.connect(**DB_CFG)
    cur = conn.cursor()

    # Build query
    where_clauses = [
        "summary_context IS NOT NULL",
        "summary_event IS NOT NULL",
        "takeaway IS NOT NULL",
        "topic_label IS NULL"  # Only process memories without topics
    ]

    if cruise_only:
        where_clauses.append("(summary_context ILIKE '%cruise%' OR summary_event ILIKE '%cruise%')")

    if start_id:
        where_clauses.append(f"id >= {start_id}")

    where_clause = " AND ".join(where_clauses)

    # Get count
    cur.execute(f"SELECT COUNT(*) FROM episodic_memories WHERE {where_clause}")
    total = cur.fetchone()[0]

    if total == 0:
        print("✅ No memories to backfill!")
        return

    print(f"\n{'='*80}")
    print(f"BACKFILL TOPIC LABELS")
    print(f"{'='*80}")
    print(f"Mode: {'CRUISE ONLY' if cruise_only else 'FULL DATABASE'}")
    print(f"Model: {model_name}")
    print(f"Total memories: {total}")
    print(f"Batch size: {batch_size}")
    if start_id:
        print(f"Starting from ID: {start_id}")
    print(f"{'='*80}\n")

    # Estimate time
    avg_time = 1.19  # qwen2.5:14b average
    estimated_hours = (total * avg_time) / 3600
    print(f"⏱️  Estimated time: {estimated_hours:.1f} hours ({int(total * avg_time / 60)} minutes)\n")

    # Get memories to process
    cur.execute(f"""
        SELECT id, summary_context, summary_event, summary_significance, takeaway
        FROM episodic_memories
        WHERE {where_clause}
        ORDER BY id ASC
    """)

    memories = cur.fetchall()

    processed = 0
    successful = 0
    failed = 0
    start_time = time.time()
    batch_start = time.time()

    for idx, (mem_id, context, event, significance, takeaway) in enumerate(memories, 1):
        # Generate topic label
        topic_label, gen_time = generate_topic_label(context, event, significance, takeaway, model_name)

        if topic_label is None:
            failed += 1
            processed += 1
            print(f"[{idx}/{total}] ID {mem_id}: ❌ FAILED")
            continue

        # Embed topic label
        topic_embedding = embed_topic_label(topic_label)

        if topic_embedding is None:
            failed += 1
            processed += 1
            print(f"[{idx}/{total}] ID {mem_id}: ❌ FAILED (embedding)")
            continue

        # Update database
        try:
            cur.execute("""
                UPDATE episodic_memories
                SET topic_label = %s, emb_topic = %s::vector
                WHERE id = %s
            """, (topic_label, topic_embedding, mem_id))

            successful += 1
            processed += 1

            # Show progress
            if idx % 10 == 0 or cruise_only:
                elapsed = time.time() - batch_start
                rate = 10 / elapsed if elapsed > 0 else 0
                remaining = total - idx
                eta_seconds = remaining / rate if rate > 0 else 0
                eta_minutes = int(eta_seconds / 60)

                print(f"[{idx}/{total}] ID {mem_id}: ✅ '{topic_label}' ({gen_time:.2f}s) | {rate:.1f}/s | ETA: {eta_minutes}m")
                batch_start = time.time()

            # Commit in batches
            if processed % batch_size == 0:
                conn.commit()
                print(f"\n✅ Batch committed ({processed}/{total})\n")

        except Exception as e:
            failed += 1
            processed += 1
            print(f"[{idx}/{total}] ID {mem_id}: ❌ DB error: {str(e)[:50]}")

    # Final commit
    conn.commit()

    # Summary
    total_time = time.time() - start_time
    print(f"\n{'='*80}")
    print(f"BACKFILL COMPLETE")
    print(f"{'='*80}")
    print(f"Total processed: {processed}")
    print(f"Successful: {successful}")
    print(f"Failed: {failed}")
    print(f"Success rate: {(successful/processed*100):.1f}%")
    print(f"Total time: {int(total_time/60)} minutes")
    print(f"Average time: {total_time/processed:.2f}s per memory")
    print(f"{'='*80}\n")

    cur.close()
    conn.close()

    return successful, failed

def check_status():
    """Check how many memories have topic labels"""
    conn = psycopg2.connect(**DB_CFG)
    cur = conn.cursor()

    cur.execute("""
        SELECT
            COUNT(*) as total,
            COUNT(topic_label) as with_labels,
            COUNT(emb_topic) as with_embeddings,
            COUNT(*) FILTER (WHERE summary_context ILIKE '%cruise%' OR summary_event ILIKE '%cruise%') as cruise_total,
            COUNT(topic_label) FILTER (WHERE summary_context ILIKE '%cruise%' OR summary_event ILIKE '%cruise%') as cruise_with_labels
        FROM episodic_memories
    """)

    total, with_labels, with_embeddings, cruise_total, cruise_with_labels = cur.fetchone()

    print(f"\n{'='*80}")
    print(f"DATABASE STATUS")
    print(f"{'='*80}")
    print(f"Total memories: {total}")
    print(f"With topic labels: {with_labels} ({with_labels/total*100:.1f}%)")
    print(f"With embeddings: {with_embeddings} ({with_embeddings/total*100:.1f}%)")
    print(f"\nCruise memories: {cruise_total}")
    print(f"Cruise with labels: {cruise_with_labels} ({cruise_with_labels/cruise_total*100:.1f}% if cruise_total else 0)")
    print(f"{'='*80}\n")

    cur.close()
    conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill topic labels for existing memories")
    parser.add_argument("--cruise-only", action="store_true", help="Only process cruise memories (for testing)")
    parser.add_argument("--full", action="store_true", help="Process all memories")
    parser.add_argument("--status", action="store_true", help="Check backfill status")
    parser.add_argument("--start-id", type=int, help="Resume from this memory ID")
    parser.add_argument("--batch-size", type=int, default=100, help="Commit every N memories")
    parser.add_argument("--model", default="qwen2.5:14b", help="Model to use for topic generation")

    args = parser.parse_args()

    if args.status:
        check_status()
    elif args.cruise_only or args.full:
        backfill_memories(
            cruise_only=args.cruise_only,
            start_id=args.start_id,
            batch_size=args.batch_size,
            model_name=args.model
        )
        # Show final status
        check_status()
    else:
        parser.print_help()
        print("\nExamples:")
        print("  python backfill_topic_labels.py --status")
        print("  python backfill_topic_labels.py --cruise-only")
        print("  python backfill_topic_labels.py --full")
        print("  python backfill_topic_labels.py --full --start-id 12345")
