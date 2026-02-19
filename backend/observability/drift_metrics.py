"""
Longitudinal Drift Metrics — Nightly batch computation.

Reads turn_metrics from the last 7 days and computes drift metrics that
track how the system's behavior changes over time. Results are stored
in the drift_metrics table.

Metrics computed:
  1. response_centroid       — average response embedding for the window
  2. emotional_baseline      — mean emotional state across turns
  3. memory_influence_depth  — avg max_memory_influence per turn
  4. unexplained_ratio_trend — avg unexplained_ratio per turn
  5. retrieval_diversity     — unique memory IDs surfaced / total memories
  6. vocabulary_entropy      — token frequency distribution entropy
  7. initiative_frequency    — turns where response diverges from user topic
  8. centroid_drift_velocity — cosine distance from previous centroid

Usage:
    python backend/observability/drift_metrics.py [--window-days 7]
"""

import os
import sys
import math
import json
import argparse
from datetime import datetime, timedelta
from collections import Counter

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import psycopg2
import psycopg2.extras
import numpy as np

DB_CFG = {
    'dbname': os.environ.get('AIRIS_DB_NAME', 'airisdb'),
    'user': os.environ.get('AIRIS_DB_USER', 'airisuser'),
    'password': os.environ.get('AIRIS_DB_PASSWORD', ''),
    'host': 'localhost',
    'port': 5432,
}


def get_conn():
    return psycopg2.connect(**DB_CFG)


def save_drift(conn, window_start, window_end, metric_name, metric_value=None,
               metric_vector=None, metric_json=None, sample_count=None):
    """Insert one drift_metrics row."""
    vec_str = None
    if metric_vector is not None:
        vec_str = "[" + ",".join(str(float(v)) for v in metric_vector) + "]"

    cur = conn.cursor()
    cur.execute("""
        INSERT INTO drift_metrics
            (window_start, window_end, metric_name, metric_value,
             metric_vector, metric_json, sample_count)
        VALUES (%s, %s, %s, %s, %s::vector, %s, %s)
    """, (
        window_start, window_end, metric_name, metric_value,
        vec_str,
        json.dumps(metric_json) if metric_json else None,
        sample_count,
    ))
    conn.commit()


def compute_all(window_days: int = 7, explicit_start=None, explicit_end=None):
    """Compute all drift metrics for a window.

    If explicit_start/explicit_end are given, use those.
    Otherwise, compute the most recent window ending now.
    """
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    if explicit_start and explicit_end:
        window_start = explicit_start
        window_end = explicit_end
    else:
        window_end = datetime.now()
        window_start = window_end - timedelta(days=window_days)

    print(f"[drift] Window: {window_start.isoformat()} → {window_end.isoformat()}")

    # ── Fetch turn_metrics for this window ──
    cur.execute("""
        SELECT id, timestamp, memories_in_context, memory_ids,
               max_memory_influence, unexplained_ratio,
               emotional_state_after, emotional_delta,
               response_embedding::text as response_embedding_text
        FROM turn_metrics
        WHERE timestamp >= %s AND timestamp <= %s
        ORDER BY timestamp ASC
    """, (window_start, window_end))
    turns = cur.fetchall()
    sample_count = len(turns)
    print(f"[drift] {sample_count} turns in window")

    if sample_count == 0:
        print("[drift] No turns — skipping all metrics")
        cur.close()
        conn.close()
        return

    # ── 1. Response Centroid ──
    embeddings = []
    for t in turns:
        emb_text = t.get("response_embedding_text")
        if emb_text:
            try:
                vals = [float(x) for x in emb_text.strip("[]").split(",")]
                if len(vals) == 768:
                    embeddings.append(np.array(vals, dtype=np.float32))
            except Exception:
                pass

    centroid = None
    if embeddings:
        centroid = np.mean(embeddings, axis=0)
        norm = np.linalg.norm(centroid)
        if norm > 0:
            centroid = centroid / norm
        save_drift(conn, window_start, window_end, "response_centroid",
                   metric_vector=centroid.tolist(), sample_count=len(embeddings))
        print(f"[drift] response_centroid: computed from {len(embeddings)} embeddings")

    # ── 2. Emotional Baseline ──
    emo_accum = Counter()
    emo_count = 0
    for t in turns:
        state = t.get("emotional_state_after")
        if state and isinstance(state, dict):
            for k, v in state.items():
                emo_accum[k] += float(v)
            emo_count += 1

    if emo_count:
        baseline = {k: round(v / emo_count, 4) for k, v in emo_accum.items()}
        save_drift(conn, window_start, window_end, "emotional_baseline",
                   metric_json=baseline, sample_count=emo_count)
        print(f"[drift] emotional_baseline: {emo_count} turns")

    # ── 3. Memory Influence Depth ──
    influence_vals = [float(t["max_memory_influence"]) for t in turns if t.get("max_memory_influence") is not None]
    if influence_vals:
        avg_influence = sum(influence_vals) / len(influence_vals)
        save_drift(conn, window_start, window_end, "memory_influence_depth",
                   metric_value=round(avg_influence, 4), sample_count=len(influence_vals))
        print(f"[drift] memory_influence_depth: {avg_influence:.4f} ({len(influence_vals)} turns)")

    # ── 4. Unexplained Ratio Trend ──
    unexplained_vals = [float(t["unexplained_ratio"]) for t in turns if t.get("unexplained_ratio") is not None]
    if unexplained_vals:
        avg_unexplained = sum(unexplained_vals) / len(unexplained_vals)
        save_drift(conn, window_start, window_end, "unexplained_ratio_trend",
                   metric_value=round(avg_unexplained, 4), sample_count=len(unexplained_vals))
        print(f"[drift] unexplained_ratio_trend: {avg_unexplained:.4f} ({len(unexplained_vals)} turns)")

    # ── 5. Retrieval Diversity ──
    all_memory_ids = set()
    for t in turns:
        if t.get("memory_ids"):
            for mid in t["memory_ids"]:
                all_memory_ids.add(mid)

    if all_memory_ids:
        # Total episodic memories in DB
        cur.execute("SELECT COUNT(*) FROM episodic_memories")
        total_memories = cur.fetchone()["count"]
        diversity = len(all_memory_ids) / max(total_memories, 1)
        save_drift(conn, window_start, window_end, "retrieval_diversity",
                   metric_value=round(diversity, 4), sample_count=sample_count)
        print(f"[drift] retrieval_diversity: {len(all_memory_ids)}/{total_memories} = {diversity:.4f}")

    # ── 6. Vocabulary Entropy ──
    # Compute from assistant responses in chat_history for this window
    cur.execute("""
        SELECT message FROM chat_history
        WHERE role = 'assistant' AND c_timestamp >= %s AND c_timestamp <= %s
          AND message IS NOT NULL AND message != ''
    """, (window_start, window_end))
    all_text = " ".join(row["message"] for row in cur.fetchall())

    if all_text:
        words = all_text.lower().split()
        if len(words) > 50:  # need enough tokens for meaningful entropy
            freq = Counter(words)
            total = sum(freq.values())
            entropy = -sum((c / total) * math.log2(c / total) for c in freq.values() if c > 0)
            save_drift(conn, window_start, window_end, "vocabulary_entropy",
                       metric_value=round(entropy, 4), sample_count=len(words))
            print(f"[drift] vocabulary_entropy: {entropy:.4f} ({len(words)} words)")

    # ── 7. Initiative Frequency ──
    # Count turns where response cosine sim to user message < 0.5
    # We approximate by checking turns where unexplained_ratio > 0.5
    initiative_turns = sum(1 for t in turns if (t.get("unexplained_ratio") or 0) > 0.5)
    if sample_count > 0:
        initiative_freq = initiative_turns / sample_count
        save_drift(conn, window_start, window_end, "initiative_frequency",
                   metric_value=round(initiative_freq, 4), sample_count=sample_count)
        print(f"[drift] initiative_frequency: {initiative_freq:.4f} ({initiative_turns}/{sample_count})")

    # ── 8. Centroid Drift Velocity ──
    if centroid is not None:
        # Fetch previous window's centroid (by window_end, not computed_at)
        cur.execute("""
            SELECT metric_vector::text as vec_text FROM drift_metrics
            WHERE metric_name = 'response_centroid'
              AND window_end <= %s
            ORDER BY window_end DESC LIMIT 1
        """, (window_start,))
        prev_row = cur.fetchone()

        if prev_row and prev_row["vec_text"]:
            try:
                prev_vals = [float(x) for x in prev_row["vec_text"].strip("[]").split(",")]
                prev_centroid = np.array(prev_vals, dtype=np.float32)
                prev_norm = np.linalg.norm(prev_centroid)
                if prev_norm > 0:
                    prev_centroid = prev_centroid / prev_norm
                # Cosine distance = 1 - cosine_similarity
                cos_sim = float(np.dot(centroid, prev_centroid))
                drift_velocity = 1.0 - cos_sim
                save_drift(conn, window_start, window_end, "centroid_drift_velocity",
                           metric_value=round(drift_velocity, 6), sample_count=sample_count)
                print(f"[drift] centroid_drift_velocity: {drift_velocity:.6f}")
            except Exception as e:
                print(f"[drift] centroid_drift_velocity failed: {e}")
        else:
            print("[drift] centroid_drift_velocity: no previous centroid, skipping")

    cur.close()
    conn.close()
    print(f"[drift] All metrics computed successfully")


def backfill(window_days: int = 7):
    """Compute drift metrics for all historical windows.

    Slides a window from the earliest turn_metrics data to now,
    stepping by window_days each iteration.
    """
    conn = get_conn()
    cur = conn.cursor()

    # Find earliest turn_metrics entry
    cur.execute("SELECT MIN(timestamp) FROM turn_metrics WHERE response_embedding IS NOT NULL")
    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row or not row[0]:
        print("[backfill] No turn_metrics data found")
        return

    earliest = row[0]
    # Align to start of day, preserving timezone
    window_start = earliest.replace(hour=0, minute=0, second=0, microsecond=0)
    now = datetime.now(tz=window_start.tzinfo)

    window_count = 0
    while window_start + timedelta(days=window_days) <= now:
        window_end = window_start + timedelta(days=window_days)
        print(f"\n{'='*50}")
        print(f"[backfill] Window {window_count + 1}: {window_start.date()} → {window_end.date()}")
        compute_all(window_days=window_days,
                     explicit_start=window_start, explicit_end=window_end)
        window_start = window_end
        window_count += 1

    print(f"\n[backfill] Completed {window_count} windows")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compute longitudinal drift metrics")
    parser.add_argument("--window-days", type=int, default=7, help="Window size in days")
    parser.add_argument("--backfill", action="store_true", help="Backfill all historical windows")
    args = parser.parse_args()

    if args.backfill:
        backfill(window_days=args.window_days)
    else:
        compute_all(window_days=args.window_days)
