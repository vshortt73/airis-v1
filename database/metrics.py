"""
Observability Metrics Database Helpers

Persists per-turn metrics and queries both turn_metrics and drift_metrics
for the observability dashboard. Fire-and-forget on writes to avoid
impacting the chat flow.
"""

import os
import json
import psycopg2
import psycopg2.extras
from datetime import datetime, timedelta
from typing import Optional
from app import config


def _get_connection():
    password = os.environ.get('AIRIS_DB_PASSWORD') or getattr(config, 'DB_PASSWORD', None)
    conn_params = {
        'host': config.DB_HOST,
        'port': config.DB_PORT,
        'database': config.DB_NAME,
        'user': config.DB_USER,
    }
    if password:
        conn_params['password'] = password
    return psycopg2.connect(**conn_params)


def save_turn_metrics(metrics: dict) -> Optional[int]:
    """
    Insert one row into turn_metrics. Fire-and-forget — prints errors
    but never raises.

    Returns the row ID on success, None on failure.
    """
    try:
        conn = _get_connection()
        cur = conn.cursor()

        # Convert embedding list to pgvector string if present
        response_emb = metrics.get("response_embedding")
        emb_str = None
        if response_emb and isinstance(response_emb, (list, tuple)):
            emb_str = "[" + ",".join(str(float(v)) for v in response_emb) + "]"

        cur.execute("""
            INSERT INTO turn_metrics (
                session_id, timestamp,
                memories_in_context, memory_ids, memory_tiers, memory_scores,
                avg_topic_similarity, avg_emotional_congruence, avg_recency,
                response_embedding, memory_influence_scores,
                max_memory_influence, unexplained_ratio,
                emotional_state_before, emotional_state_after,
                emotional_delta, dominant_emotion,
                kv_cache_tokens, kv_prompt_tokens, kv_cache_efficiency,
                gen_tokens_per_sec, response_tokens, response_time_ms,
                total_context_tokens, system_prompt_tokens, conversation_tokens,
                tool_calls_count, tools_used, tool_iterations
            ) VALUES (
                %s, NOW(),
                %s, %s, %s, %s,
                %s, %s, %s,
                %s::vector, %s,
                %s, %s,
                %s, %s,
                %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s
            ) RETURNING id
        """, (
            metrics.get("session_id"),
            # Memory retrieval
            metrics.get("memories_in_context"),
            metrics.get("memory_ids"),
            metrics.get("memory_tiers"),
            metrics.get("memory_scores"),
            metrics.get("avg_topic_similarity"),
            metrics.get("avg_emotional_congruence"),
            metrics.get("avg_recency"),
            # Memory influence
            emb_str,
            metrics.get("memory_influence_scores"),
            metrics.get("max_memory_influence"),
            metrics.get("unexplained_ratio"),
            # Emotional
            json.dumps(metrics["emotional_state_before"]) if metrics.get("emotional_state_before") else None,
            json.dumps(metrics["emotional_state_after"]) if metrics.get("emotional_state_after") else None,
            metrics.get("emotional_delta"),
            metrics.get("dominant_emotion"),
            # LLM perf
            metrics.get("kv_cache_tokens"),
            metrics.get("kv_prompt_tokens"),
            metrics.get("kv_cache_efficiency"),
            metrics.get("gen_tokens_per_sec"),
            metrics.get("response_tokens"),
            metrics.get("response_time_ms"),
            # Context
            metrics.get("total_context_tokens"),
            metrics.get("system_prompt_tokens"),
            metrics.get("conversation_tokens"),
            # Tools
            metrics.get("tool_calls_count", 0),
            metrics.get("tools_used"),
            metrics.get("tool_iterations", 0),
        ))

        row_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        print(f"[metrics] ✓ Saved turn metrics (id={row_id})")
        return row_id

    except Exception as e:
        print(f"[metrics] ✗ Failed to save turn metrics: {e}")
        return None


def get_turn_metrics(
    session_id: str = None,
    start: datetime = None,
    end: datetime = None,
    limit: int = 500,
) -> list[dict]:
    """Query turn_metrics for dashboard display."""
    conn = _get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    conditions = []
    params = []

    if session_id:
        conditions.append("session_id = %s")
        params.append(session_id)
    if start:
        conditions.append("timestamp >= %s")
        params.append(start)
    if end:
        conditions.append("timestamp <= %s")
        params.append(end)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    cur.execute(f"""
        SELECT id, session_id, timestamp,
               memories_in_context, memory_ids, memory_tiers, memory_scores,
               avg_topic_similarity, avg_emotional_congruence, avg_recency,
               memory_influence_scores, max_memory_influence, unexplained_ratio,
               emotional_state_before, emotional_state_after,
               emotional_delta, dominant_emotion,
               kv_cache_tokens, kv_prompt_tokens, kv_cache_efficiency,
               gen_tokens_per_sec, response_tokens, response_time_ms,
               total_context_tokens, system_prompt_tokens, conversation_tokens,
               tool_calls_count, tools_used, tool_iterations
        FROM turn_metrics
        {where}
        ORDER BY timestamp DESC
        LIMIT %s
    """, params + [limit])

    rows = cur.fetchall()
    cur.close()
    conn.close()

    # Convert to serializable dicts
    result = []
    for row in rows:
        d = dict(row)
        if d.get("timestamp"):
            d["timestamp"] = d["timestamp"].isoformat()
        if d.get("session_id"):
            d["session_id"] = str(d["session_id"])
        result.append(d)

    return result


def get_drift_metrics(
    metric_name: str = None,
    start: datetime = None,
    end: datetime = None,
) -> list[dict]:
    """Query drift_metrics for dashboard display."""
    conn = _get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    conditions = []
    params = []

    if metric_name:
        conditions.append("metric_name = %s")
        params.append(metric_name)
    if start:
        conditions.append("window_end >= %s")
        params.append(start)
    if end:
        conditions.append("window_end <= %s")
        params.append(end)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    cur.execute(f"""
        SELECT id, computed_at, window_start, window_end,
               metric_name, metric_value, metric_json, sample_count
        FROM drift_metrics
        {where}
        ORDER BY window_end ASC
    """, params)

    rows = cur.fetchall()
    cur.close()
    conn.close()

    result = []
    for row in rows:
        d = dict(row)
        for ts_field in ("computed_at", "window_start", "window_end"):
            if d.get(ts_field):
                d[ts_field] = d[ts_field].isoformat()
        result.append(d)

    return result


def get_observability_summary() -> dict:
    """
    Latest drift values for overview cards + recent turn stats.
    """
    conn = _get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Latest value for each drift metric
    cur.execute("""
        SELECT DISTINCT ON (metric_name)
            metric_name, metric_value, metric_json, computed_at, sample_count
        FROM drift_metrics
        ORDER BY metric_name, computed_at DESC
    """)
    drift_latest = {row["metric_name"]: dict(row) for row in cur.fetchall()}

    # Recent turn stats (last 24h)
    cur.execute("""
        SELECT COUNT(*) as turn_count,
               AVG(max_memory_influence) as avg_memory_influence,
               AVG(unexplained_ratio) as avg_unexplained,
               AVG(emotional_delta) as avg_emotional_delta,
               AVG(kv_cache_efficiency) as avg_cache_efficiency,
               AVG(response_time_ms) as avg_response_ms
        FROM turn_metrics
        WHERE timestamp >= NOW() - INTERVAL '24 hours'
    """)
    recent = dict(cur.fetchone())

    cur.close()
    conn.close()

    # Serialize timestamps in drift_latest
    for k, v in drift_latest.items():
        if v.get("computed_at"):
            v["computed_at"] = v["computed_at"].isoformat()

    return {
        "drift_latest": drift_latest,
        "recent_24h": recent,
    }
