"""
Memory Retrieval V2 — Fast, emotionally-aware episodic memory retrieval.

Replaces iris_memory_retrieval.py (2 LLM calls + RoBERTa, 10-30s) with a
direct embedding pipeline (~400ms):

  [1] load config from system_config (category='retrieval')
  [2] fetch last N user messages from chat_history
  [3] embed concatenated query text (all-mpnet-base-v2, ~200ms)
  [4] read current emotional state (11 dims → valence/arousal)
  [5] GREATEST-match SQL + 3-factor scoring (topic × emo × recency)
  [6] TRUNCATE + INSERT scored memories into live_memories

CLI usage (same args as v1):
    python backend/memory/memory_retrieval_v2.py --top_k 10 --insert true --mode replace --show true
"""

import os
import sys
import math
import time
import argparse

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
MEMORY_DIR = os.path.dirname(__file__)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
if MEMORY_DIR not in sys.path:
    sys.path.insert(0, MEMORY_DIR)

import psycopg2
import psycopg2.extras
import json
import numpy as np

from Colors import Colors
from core.embeddings import get_embedding_model

# Force offline mode for HuggingFace
os.environ["HF_HUB_OFFLINE"] = "1"

DB_CFG = {
    'dbname': os.environ.get('AIRIS_DB_NAME', 'airisdb'),
    'user': os.environ.get('AIRIS_DB_USER', 'airisuser'),
    'password': os.environ.get('AIRIS_DB_PASSWORD', ''),
    'host': 'localhost',
    'port': 5432,
}

# Category-based half-lives (days) for recency decay
HALF_LIFE_BY_CATEGORY = {
    "Technical":  45,
    "Practical":  45,
    "Creative":   90,
    "Learning":   90,
    "Personal":   180,
    "Relational": 180,
    "Other":      60,
}

# ==============================
# Step 1: Load retrieval config
# ==============================
def load_retrieval_config(conn_params: dict) -> dict:
    """Load all retrieval config keys from system_config."""
    defaults = {
        "RETRIEVAL_MESSAGES_COUNT":   5,
        "RETRIEVAL_TRIGGER_INTERVAL": 5,
        "RETRIEVAL_W_TOPIC":          0.60,
        "RETRIEVAL_W_EMOTION":        0.25,
        "RETRIEVAL_W_RECENCY":        0.15,
        "RETRIEVAL_TIER1_THRESHOLD":  0.55,
        "RETRIEVAL_TIER2_THRESHOLD":  0.40,
        "RETRIEVAL_TIER3_THRESHOLD":  0.30,
        "RETRIEVAL_MIN_SIMILARITY":   0.25,
        "RETRIEVAL_TOP_K":            10,
        "RETRIEVAL_STRATEGY":         "concat",
        "RETRIEVAL_SHADOW_ENABLED":   "false",
    }

    try:
        with psycopg2.connect(**conn_params) as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT key, value, value_type
                    FROM system_config
                    WHERE category = 'retrieval'
                """)
                for row in cur.fetchall():
                    k = row["key"]
                    v = row["value"]
                    vt = row["value_type"]
                    if vt == "int":
                        defaults[k] = int(v)
                    elif vt == "float":
                        defaults[k] = float(v)
                    else:
                        defaults[k] = v
    except Exception as e:
        print(f"[retrieval_v2] Warning: could not load config, using defaults: {e}")

    return defaults


# ==============================
# Step 2: Fetch recent user messages
# ==============================
def fetch_recent_user_messages(conn_params: dict, count: int) -> str:
    """Fetch the last `count` user messages and concatenate them."""
    with psycopg2.connect(**conn_params) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT message FROM (
                    SELECT id, message
                    FROM chat_history
                    WHERE role = 'user'
                    ORDER BY c_timestamp DESC
                    LIMIT %s
                ) sub
                ORDER BY id ASC
            """, (count,))
            rows = cur.fetchall()
    return "\n".join(row[0] for row in rows if row[0])


# ==============================
# Step 3: Embed query
# ==============================
def embed_query(text: str) -> list:
    """Generate a single 768-dim embedding for the query text."""
    model = get_embedding_model()
    vec = model.encode(text, convert_to_numpy=True)
    arr = np.array(vec, dtype=np.float32)
    norm = np.linalg.norm(arr)
    if norm > 0:
        arr = arr / norm
    return arr.tolist()


# ==============================
# Step 4: Fetch emotional state
# ==============================
def fetch_emotional_state(conn_params: dict) -> tuple:
    """
    Read Iris's 11-dimension emotional state and map to (valence, arousal).

    Valence ≈ (Joy + Calm + Trust + Closeness)/4 − (Desperation + Longing)/2
    Arousal ≈ (Excitement + Desire + Devotion) / 3

    Returns (approx_valence, approx_arousal) both in [-1, 1] and [0, 1].
    """
    default = (0.0, 0.4)  # neutral valence, moderate arousal
    try:
        with psycopg2.connect(**conn_params) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT state_data FROM emotional_state WHERE id = 1")
                row = cur.fetchone()
                if not row:
                    return default

                data = row[0]
                if isinstance(data, str):
                    data = json.loads(data)

                states = data.get("states", {})
                if not states:
                    return default

                # Positive contributors to valence
                pos = (
                    states.get("Joy", 0.5)
                    + states.get("Calm", 0.6)
                    + states.get("Trust", 0.7)
                    + states.get("Closeness", 0.5)
                ) / 4.0

                # Negative contributors to valence
                neg = (
                    states.get("Desperation", 0.1)
                    + states.get("Longing", 0.2)
                ) / 2.0

                raw_valence = pos - neg  # roughly [-1, 1]
                approx_valence = max(-1.0, min(1.0, raw_valence))

                # Arousal
                approx_arousal = (
                    states.get("Excitement", 0.4)
                    + states.get("Desire", 0.3)
                    + states.get("Devotion", 0.6)
                ) / 3.0
                approx_arousal = max(0.0, min(1.0, approx_arousal))

                return (approx_valence, approx_arousal)

    except Exception as e:
        print(f"[retrieval_v2] Warning: could not read emotional state: {e}")
        return default


# ==============================
# Step 5: Search and score
# ==============================
def search_and_score(
    conn_params: dict,
    query_emb: list,
    approx_valence: float,
    approx_arousal: float,
    cfg: dict,
    show: bool = False,
) -> list:
    """
    GREATEST-match SQL retrieval + 3-factor scoring.

    Returns list of dicts with keys:
        id, takeaway, key_details, summary_context, summary_event,
        summary_significance, category, emotion_label, valence, arousal,
        age_days, immutable, topic_sim, emo_congruence, recency, final_score, tier
    """
    w_topic   = cfg["RETRIEVAL_W_TOPIC"]
    w_emotion = cfg["RETRIEVAL_W_EMOTION"]
    w_recency = cfg["RETRIEVAL_W_RECENCY"]
    tier1     = cfg["RETRIEVAL_TIER1_THRESHOLD"]
    tier2     = cfg["RETRIEVAL_TIER2_THRESHOLD"]
    tier3     = cfg["RETRIEVAL_TIER3_THRESHOLD"]
    min_sim   = cfg["RETRIEVAL_MIN_SIMILARITY"]
    top_k     = cfg["RETRIEVAL_TOP_K"]

    emb_param = query_emb  # single vector used for all 3 GREATEST columns

    with psycopg2.connect(**conn_params) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    id,
                    takeaway,
                    key_details,
                    summary_context,
                    summary_event,
                    summary_significance,
                    category,
                    emotion_label,
                    valence,
                    arousal,
                    age_days,
                    immutable,
                    emb_minilm,
                    emb_takeaway,
                    emb_key_details,
                    GREATEST(
                        COALESCE(1 - (emb_key_details <=> %s::vector), 0),
                        COALESCE(1 - (emb_takeaway    <=> %s::vector), 0),
                        COALESCE(1 - (emb_minilm      <=> %s::vector), 0)
                    ) AS topic_sim
                FROM episodic_memories_with_age
                WHERE emb_minilm IS NOT NULL
                ORDER BY topic_sim DESC
                LIMIT 50
            """, (emb_param, emb_param, emb_param))

            candidates = cur.fetchall()

    if show:
        print(f"\n{Colors.BRIGHT_CYAN}=== Top 10 raw candidates (pre-scoring) ==={Colors.RESET}")
        for c in candidates[:10]:
            print(f"  ID {c['id']} | topic_sim={c['topic_sim']:.4f} | age={float(c['age_days']):.1f}d")
            print(f"    Takeaway: {(c['takeaway'] or '')[:100]}")
            print(f"    {'-' * 60}")

    scored = []
    for c in candidates:
        topic_sim = float(c["topic_sim"] or 0)
        if topic_sim < min_sim:
            continue

        # --- Emotional congruence ---
        mem_valence = float(c.get("valence") or 0)
        mem_arousal = float(c.get("arousal") or 0)
        # Distance in valence-arousal space (max distance = sqrt(4+1) = sqrt(5))
        emo_dist = math.sqrt(
            (approx_valence - mem_valence) ** 2
            + (approx_arousal - mem_arousal) ** 2
        ) / math.sqrt(5)
        emo_congruence = 1.0 - emo_dist

        # --- Recency decay ---
        age_days = float(c.get("age_days") or 0)
        category = c.get("category") or "Other"
        half_life = HALF_LIFE_BY_CATEGORY.get(category, 60)

        if c.get("immutable"):
            recency = 1.0
        else:
            recency = math.exp(-math.log(2) * age_days / half_life)

        # --- Final score ---
        final_score = (
            topic_sim      * w_topic
            + emo_congruence * w_emotion
            + recency        * w_recency
        )

        # --- Tier assignment ---
        if final_score >= tier1:
            tier = 1
        elif final_score >= tier2:
            tier = 2
        elif final_score >= tier3:
            tier = 3
        else:
            continue  # below tier 3 — discard

        scored.append({
            **c,
            "topic_sim": topic_sim,
            "emo_congruence": emo_congruence,
            "recency": recency,
            "final_score": final_score,
            "tier": tier,
        })

    # Sort descending by final_score, take top_k
    scored.sort(key=lambda x: x["final_score"], reverse=True)
    return scored[:top_k]


# ==============================
# Step 6: Write live_memories
# ==============================
def write_live_memories(
    conn_params: dict,
    scored: list,
    insert: bool,
    mode: str,
    show: bool,
):
    """TRUNCATE (if replace) + INSERT scored memories into live_memories."""
    if not insert:
        if show:
            print(f"{Colors.BRIGHT_YELLOW}[retrieval_v2] Insertion suppressed (--insert false){Colors.RESET}")
        return

    conn = psycopg2.connect(**conn_params)
    cur = conn.cursor()
    try:
        if mode == "replace":
            cur.execute("TRUNCATE TABLE live_memories")
            conn.commit()
            if show:
                print(f"{Colors.BRIGHT_RED}[retrieval_v2] Truncated live_memories{Colors.RESET}")

        for s in scored:
            cur.execute(
                "INSERT INTO live_memories (memory_id, rank, tier) VALUES (%s, %s, %s)",
                (s["id"], round(s["final_score"], 4), s["tier"]),
            )
        conn.commit()
        if show:
            print(f"{Colors.BRIGHT_GREEN}[retrieval_v2] Inserted {len(scored)} memories into live_memories{Colors.RESET}")
    finally:
        cur.close()
        conn.close()


# ==============================
# Step 5b: Per-message search (Strategy B)
# ==============================
def fetch_recent_user_messages_list(conn_params: dict, count: int) -> list:
    """Fetch the last `count` user messages as a list (not concatenated)."""
    with psycopg2.connect(**conn_params) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT message FROM (
                    SELECT id, message
                    FROM chat_history
                    WHERE role = 'user'
                    ORDER BY c_timestamp DESC
                    LIMIT %s
                ) sub
                ORDER BY id ASC
            """, (count,))
            return [row[0] for row in cur.fetchall() if row[0]]


def search_per_message(
    conn_params: dict,
    messages: list,
    approx_valence: float,
    approx_arousal: float,
    cfg: dict,
    show: bool = False,
) -> list:
    """
    Strategy B: Embed each message separately, search each, merge by best score.
    Returns same format as search_and_score().
    """
    all_candidates = {}  # memory_id → best scored dict

    for msg in messages:
        if not msg.strip():
            continue
        query_emb = embed_query(msg)
        scored = search_and_score(conn_params, query_emb, approx_valence, approx_arousal, cfg, show=False)
        for s in scored:
            mid = s["id"]
            if mid not in all_candidates or s["final_score"] > all_candidates[mid]["final_score"]:
                all_candidates[mid] = s

    top_k = cfg["RETRIEVAL_TOP_K"]
    merged = sorted(all_candidates.values(), key=lambda x: x["final_score"], reverse=True)[:top_k]

    if show and merged:
        print(f"{Colors.BRIGHT_CYAN}[retrieval_v2] Strategy B: {len(messages)} embeddings → {len(all_candidates)} unique candidates → top {len(merged)}{Colors.RESET}")

    return merged


# ==============================
# Step 7: Shadow comparison logging
# ==============================
def log_shadow_comparison(
    conn_params: dict,
    scored_a: list,
    scored_b: list,
    query_preview: str,
    show: bool = False,
):
    """Log both strategy results to retrieval_comparison for offline analysis."""
    import uuid
    run_id = str(uuid.uuid4())

    try:
        conn = psycopg2.connect(**conn_params)
        cur = conn.cursor()

        preview = (query_preview or "")[:200]

        for strategy, scored in [("concat", scored_a), ("per_message", scored_b)]:
            for s in scored:
                cur.execute(
                    """INSERT INTO retrieval_comparison
                       (run_id, strategy, memory_id, final_score, tier, topic_sim, emo_score, recency, takeaway, category, query_preview)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (run_id, strategy, s["id"], round(s["final_score"], 4), s["tier"],
                     round(s.get("topic_sim", 0), 4), round(s.get("emo_congruence", 0), 4),
                     round(s.get("recency", 0), 4), (s.get("takeaway") or "")[:200],
                     s.get("category"), preview)
                )

        conn.commit()
        cur.close()
        conn.close()

        if show:
            ids_a = {s["id"] for s in scored_a}
            ids_b = {s["id"] for s in scored_b}
            overlap = len(ids_a & ids_b)
            print(f"{Colors.BRIGHT_CYAN}[retrieval_v2] Shadow logged run {run_id[:8]}: "
                  f"A={len(scored_a)}, B={len(scored_b)}, overlap={overlap}{Colors.RESET}")
    except Exception as e:
        print(f"[retrieval_v2] Shadow log failed (non-fatal): {e}")


# ==============================
# Display helpers
# ==============================
TIER_LABELS = {1: "PRIMARY", 2: "SUPPORTING", 3: "ASSOCIATIVE"}

def display_results(scored: list):
    """Pretty-print scored memories."""
    if not scored:
        print(f"{Colors.BRIGHT_YELLOW}[retrieval_v2] No memories above threshold.{Colors.RESET}")
        return

    print(f"\n{Colors.BRIGHT_GREEN}=== Memory Retrieval V2 Results ({len(scored)} memories) ==={Colors.RESET}\n")
    for s in scored:
        tier = s["tier"]
        label = TIER_LABELS.get(tier, "?")
        print(
            f"  {Colors.BOLD}[Tier {tier} {label}]{Colors.RESET} "
            f"score={s['final_score']:.4f}  "
            f"topic={s['topic_sim']:.4f}  "
            f"emo={s['emo_congruence']:.4f}  "
            f"recency={s['recency']:.4f}  "
            f"age={float(s['age_days']):.0f}d  "
            f"cat={s.get('category', '?')}"
        )
        takeaway = (s.get("takeaway") or "")[:120]
        print(f"    Takeaway: {takeaway}")
        key_det = (s.get("key_details") or "")[:120]
        if key_det:
            print(f"    Details:  {key_det}")
        print(f"    {'-' * 70}")
    print()


# ==============================
# Main pipeline
# ==============================
def run_retrieval_v2(
    conn_params: dict,
    top_k: int = 10,
    insert: bool = True,
    mode: str = "replace",
    show: bool = True,
):
    """Execute the retrieval pipeline with strategy selection and optional shadow comparison."""
    t0 = time.time()

    # Step 1: Config
    cfg = load_retrieval_config(conn_params)
    cfg["RETRIEVAL_TOP_K"] = top_k  # CLI override
    strategy = cfg.get("RETRIEVAL_STRATEGY", "concat")
    shadow = str(cfg.get("RETRIEVAL_SHADOW_ENABLED", "false")).lower() in ("true", "1", "yes")
    if show:
        print(f"{Colors.BRIGHT_CYAN}[retrieval_v2] Config loaded (top_k={top_k}, "
              f"strategy={strategy}, shadow={shadow}, "
              f"w_topic={cfg['RETRIEVAL_W_TOPIC']}, "
              f"w_emotion={cfg['RETRIEVAL_W_EMOTION']}, "
              f"w_recency={cfg['RETRIEVAL_W_RECENCY']}){Colors.RESET}")

    # Step 2: Fetch user messages
    msg_count = cfg["RETRIEVAL_MESSAGES_COUNT"]
    query_text = fetch_recent_user_messages(conn_params, msg_count)
    if not query_text.strip():
        print(f"{Colors.BRIGHT_YELLOW}[retrieval_v2] No recent user messages found. Aborting.{Colors.RESET}")
        return []
    if show:
        preview = query_text[:200].replace("\n", " | ")
        print(f"{Colors.BRIGHT_CYAN}[retrieval_v2] Query ({msg_count} msgs): {preview}...{Colors.RESET}")

    # Step 4: Emotional state (needed by both strategies)
    approx_valence, approx_arousal = fetch_emotional_state(conn_params)
    if show:
        print(f"{Colors.BRIGHT_CYAN}[retrieval_v2] Emotional state: valence={approx_valence:.3f}, arousal={approx_arousal:.3f}{Colors.RESET}")

    # --- Strategy A: Concatenated embedding (always runs for shadow or if active) ---
    scored_a = None
    if strategy == "concat" or shadow:
        t_emb = time.time()
        query_emb = embed_query(query_text)
        if show:
            print(f"{Colors.BRIGHT_CYAN}[retrieval_v2] Strategy A embedding: {time.time() - t_emb:.3f}s{Colors.RESET}")
        scored_a = search_and_score(conn_params, query_emb, approx_valence, approx_arousal, cfg, show=show)

    # --- Strategy B: Per-message embedding (always runs for shadow or if active) ---
    scored_b = None
    if strategy == "per_message" or shadow:
        messages = fetch_recent_user_messages_list(conn_params, msg_count)
        t_b = time.time()
        scored_b = search_per_message(conn_params, messages, approx_valence, approx_arousal, cfg, show=show)
        if show:
            print(f"{Colors.BRIGHT_CYAN}[retrieval_v2] Strategy B total: {time.time() - t_b:.3f}s{Colors.RESET}")

    # --- Pick active strategy's results ---
    if strategy == "per_message":
        scored = scored_b
    else:
        scored = scored_a

    # Step 6: Write active strategy to live_memories
    write_live_memories(conn_params, scored, insert, mode, show)

    # Step 7: Shadow comparison logging
    if shadow and scored_a is not None and scored_b is not None:
        log_shadow_comparison(conn_params, scored_a, scored_b, query_text, show=show)

    # Display
    if show:
        display_results(scored)
        print(f"{Colors.BRIGHT_GREEN}[retrieval_v2] Total time: {time.time() - t0:.3f}s{Colors.RESET}")

    return scored


# ==============================
# CLI entry point
# ==============================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Memory Retrieval V2 — fast, emotionally-aware episodic recall.")
    parser.add_argument("--top_k", type=int, default=10, help="Max memories to retrieve")
    parser.add_argument("--insert", type=lambda x: x.lower() in ("true", "1", "yes"), default=True, help="Insert into live_memories")
    parser.add_argument("--mode", choices=["replace", "append"], default="replace", help="Replace or append live_memories")
    parser.add_argument("--show", type=lambda x: x.lower() in ("true", "1", "yes"), default=True, help="Show detailed output")
    args = parser.parse_args()

    run_retrieval_v2(DB_CFG, top_k=args.top_k, insert=args.insert, mode=args.mode, show=args.show)
