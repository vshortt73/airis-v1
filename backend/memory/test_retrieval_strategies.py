"""
Retrieval Strategy A/B/C Test Harness

Compares three memory retrieval strategies using the same scoring pipeline:
  A: Current — concatenate N user messages, embed as one, search
  B: Per-message — embed each message separately, search each, merge/dedup by best score
  C: LLM-distilled — send N messages to Mistral 7B for topic distillation, embed result, search

Usage:
    python backend/memory/test_retrieval_strategies.py
    python backend/memory/test_retrieval_strategies.py --msg_count 5 --top_k 10
"""

import os
import sys
import time
import json
import argparse
import requests

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
MEMORY_DIR = os.path.dirname(__file__)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
if MEMORY_DIR not in sys.path:
    sys.path.insert(0, MEMORY_DIR)

from Colors import Colors
from memory_retrieval_v2 import (
    load_retrieval_config,
    fetch_recent_user_messages,
    embed_query,
    fetch_emotional_state,
    search_and_score,
    DB_CFG,
    TIER_LABELS,
)
import psycopg2

# ==============================
# Helpers
# ==============================

def fetch_recent_user_messages_list(conn_params: dict, count: int, offset: int = 0) -> list:
    """Fetch `count` user messages as a list, with optional offset from most recent."""
    with psycopg2.connect(**conn_params) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT message FROM (
                    SELECT id, message
                    FROM chat_history
                    WHERE role = 'user'
                    ORDER BY c_timestamp DESC
                    LIMIT %s OFFSET %s
                ) sub
                ORDER BY id ASC
            """, (count, offset))
            return [row[0] for row in cur.fetchall() if row[0]]


def fetch_user_messages_concat(conn_params: dict, count: int, offset: int = 0) -> str:
    """Fetch `count` user messages concatenated, with optional offset."""
    msgs = fetch_recent_user_messages_list(conn_params, count, offset)
    return "\n".join(msgs)


def get_mistral_url(conn_params: dict) -> str:
    """Read MISTRAL_URL from system_config."""
    try:
        with psycopg2.connect(**conn_params) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT value FROM system_config WHERE key = 'MISTRAL_URL'")
                row = cur.fetchone()
                if row:
                    return row[0]
    except Exception:
        pass
    return "http://node2:11437/v1/chat/completions"


def distill_with_llm(messages: list, mistral_url: str) -> str:
    """Send messages to Mistral 7B for topic/concept distillation."""
    conversation_block = "\n".join(f"- {m}" for m in messages)

    payload = {
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a conversation analyst. Given recent user messages, "
                    "distill the key topics, concepts, emotions, and intent into a "
                    "single focused paragraph. This will be used to search a memory "
                    "database, so emphasize specific subjects, names, technical terms, "
                    "and emotional themes. Be concise — 2-4 sentences max."
                ),
            },
            {
                "role": "user",
                "content": f"Recent user messages:\n{conversation_block}\n\nDistill the key topics and themes.",
            },
        ],
        "stream": False,
        "max_tokens": 200,
        "temperature": 0.2,
    }

    response = requests.post(mistral_url, json=payload, timeout=30)
    response.raise_for_status()
    data = response.json()
    choices = data.get("choices", [])
    if choices:
        return choices[0].get("message", {}).get("content", "")
    return ""


def display_strategy_results(name: str, scored: list, color: str, elapsed: float):
    """Display results for one strategy."""
    print(f"\n{color}{'=' * 80}")
    print(f"  STRATEGY {name}  ({elapsed:.3f}s)")
    print(f"{'=' * 80}{Colors.RESET}\n")

    if not scored:
        print(f"  {Colors.BRIGHT_YELLOW}No memories above threshold.{Colors.RESET}\n")
        return

    for i, s in enumerate(scored):
        tier = s["tier"]
        label = TIER_LABELS.get(tier, "?")
        print(
            f"  {Colors.BOLD}#{i+1} [Tier {tier} {label}]{Colors.RESET}  "
            f"score={s['final_score']:.4f}  "
            f"topic={s['topic_sim']:.4f}  "
            f"emo={s['emo_congruence']:.4f}  "
            f"recency={s['recency']:.4f}  "
            f"age={float(s['age_days']):.0f}d  "
            f"cat={s.get('category', '?')}"
        )
        takeaway = (s.get("takeaway") or "")[:140]
        print(f"    {takeaway}")
        print()


def display_comparison(results_a: list, results_b: list, results_c: list):
    """Show which memories are unique to each strategy."""
    ids_a = {s["id"] for s in results_a}
    ids_b = {s["id"] for s in results_b}
    ids_c = {s["id"] for s in results_c}

    all_ids = ids_a | ids_b | ids_c

    print(f"\n{Colors.BRIGHT_CYAN}{'=' * 80}")
    print(f"  COMPARISON MATRIX")
    print(f"{'=' * 80}{Colors.RESET}\n")

    print(f"  {'Memory ID':<12} {'A (concat)':<12} {'B (per-msg)':<12} {'C (LLM)':<12} {'Unique to'}")
    print(f"  {'-' * 60}")

    # Build lookup for scores
    score_a = {s["id"]: s["final_score"] for s in results_a}
    score_b = {s["id"]: s["final_score"] for s in results_b}
    score_c = {s["id"]: s["final_score"] for s in results_c}
    takeaways = {}
    for s in results_a + results_b + results_c:
        takeaways[s["id"]] = (s.get("takeaway") or "")[:80]

    for mid in sorted(all_ids):
        in_a = f"{score_a[mid]:.4f}" if mid in ids_a else "  —"
        in_b = f"{score_b[mid]:.4f}" if mid in ids_b else "  —"
        in_c = f"{score_c[mid]:.4f}" if mid in ids_c else "  —"

        unique = []
        if mid in ids_a and mid not in ids_b and mid not in ids_c:
            unique.append("A only")
        if mid in ids_b and mid not in ids_a and mid not in ids_c:
            unique.append("B only")
        if mid in ids_c and mid not in ids_a and mid not in ids_b:
            unique.append("C only")
        if mid in ids_a and mid in ids_b and mid in ids_c:
            unique.append("all")

        unique_str = ", ".join(unique) if unique else ""
        print(f"  {mid:<12} {in_a:<12} {in_b:<12} {in_c:<12} {unique_str}")
        print(f"    {Colors.DIM}{takeaways.get(mid, '')}{Colors.RESET}")

    overlap_ab = ids_a & ids_b
    overlap_ac = ids_a & ids_c
    overlap_bc = ids_b & ids_c
    overlap_all = ids_a & ids_b & ids_c

    print(f"\n  Totals: A={len(ids_a)}, B={len(ids_b)}, C={len(ids_c)}")
    print(f"  Overlap: A∩B={len(overlap_ab)}, A∩C={len(overlap_ac)}, B∩C={len(overlap_bc)}, A∩B∩C={len(overlap_all)}")
    print(f"  Unique:  A-only={len(ids_a - ids_b - ids_c)}, B-only={len(ids_b - ids_a - ids_c)}, C-only={len(ids_c - ids_a - ids_b)}")
    print()


# ==============================
# Strategy runners
# ==============================

def run_strategy_a(conn_params: dict, cfg: dict, approx_valence: float, approx_arousal: float, msg_count: int, offset: int = 0) -> tuple:
    """Strategy A: Current — concatenate all messages, one embedding."""
    t0 = time.time()
    query_text = fetch_user_messages_concat(conn_params, msg_count, offset)
    query_emb = embed_query(query_text)
    scored = search_and_score(conn_params, query_emb, approx_valence, approx_arousal, cfg)
    elapsed = time.time() - t0
    return scored, elapsed, query_text


def run_strategy_b(conn_params: dict, cfg: dict, approx_valence: float, approx_arousal: float, msg_count: int, offset: int = 0) -> tuple:
    """Strategy B: Per-message — embed each, search each, merge by best score."""
    t0 = time.time()
    messages = fetch_recent_user_messages_list(conn_params, msg_count, offset)

    all_candidates = {}  # memory_id → best scored dict

    for msg in messages:
        if not msg.strip():
            continue
        query_emb = embed_query(msg)
        scored = search_and_score(conn_params, query_emb, approx_valence, approx_arousal, cfg)
        for s in scored:
            mid = s["id"]
            if mid not in all_candidates or s["final_score"] > all_candidates[mid]["final_score"]:
                all_candidates[mid] = s

    # Sort by final_score, take top_k
    top_k = cfg["RETRIEVAL_TOP_K"]
    merged = sorted(all_candidates.values(), key=lambda x: x["final_score"], reverse=True)[:top_k]
    elapsed = time.time() - t0
    return merged, elapsed, messages


def run_strategy_c(conn_params: dict, cfg: dict, approx_valence: float, approx_arousal: float, msg_count: int, mistral_url: str, offset: int = 0) -> tuple:
    """Strategy C: LLM-distilled — Mistral extracts topics, embed that, search."""
    t0 = time.time()
    messages = fetch_recent_user_messages_list(conn_params, msg_count, offset)

    t_llm = time.time()
    distilled = distill_with_llm(messages, mistral_url)
    llm_time = time.time() - t_llm

    query_emb = embed_query(distilled)
    scored = search_and_score(conn_params, query_emb, approx_valence, approx_arousal, cfg)
    elapsed = time.time() - t0
    return scored, elapsed, distilled, llm_time


# ==============================
# Main
# ==============================

def main():
    parser = argparse.ArgumentParser(description="A/B/C test for memory retrieval strategies")
    parser.add_argument("--msg_count", type=int, default=5, help="Number of recent user messages")
    parser.add_argument("--top_k", type=int, default=10, help="Max memories per strategy")
    parser.add_argument("--offset", type=int, default=0, help="Skip N most recent messages (slide the window)")
    parser.add_argument("--no-c", action="store_true", help="Skip Strategy C (LLM) to save time")
    args = parser.parse_args()

    print(f"\n{Colors.BRIGHT_CYAN}{'=' * 80}")
    print(f"  MEMORY RETRIEVAL STRATEGY TEST HARNESS")
    print(f"{'=' * 80}{Colors.RESET}\n")

    # Shared setup
    cfg = load_retrieval_config(DB_CFG)
    cfg["RETRIEVAL_TOP_K"] = args.top_k
    approx_valence, approx_arousal = fetch_emotional_state(DB_CFG)
    mistral_url = get_mistral_url(DB_CFG)

    print(f"  Config: top_k={args.top_k}, msg_count={args.msg_count}, offset={args.offset}")
    print(f"  Weights: topic={cfg['RETRIEVAL_W_TOPIC']}, emotion={cfg['RETRIEVAL_W_EMOTION']}, recency={cfg['RETRIEVAL_W_RECENCY']}")
    print(f"  Emotional state: valence={approx_valence:.3f}, arousal={approx_arousal:.3f}")

    # Fetch messages for display
    messages = fetch_recent_user_messages_list(DB_CFG, args.msg_count, args.offset)
    print(f"\n  {Colors.BRIGHT_YELLOW}Query messages ({len(messages)}, offset={args.offset}):{Colors.RESET}")
    for i, m in enumerate(messages):
        preview = m[:120].replace("\n", " ")
        print(f"    [{i+1}] {preview}")

    # Run strategies
    print(f"\n{Colors.DIM}Running Strategy A (concatenated)...{Colors.RESET}")
    results_a, time_a, query_a = run_strategy_a(DB_CFG, cfg, approx_valence, approx_arousal, args.msg_count, args.offset)

    print(f"{Colors.DIM}Running Strategy B (per-message)...{Colors.RESET}")
    results_b, time_b, msgs_b = run_strategy_b(DB_CFG, cfg, approx_valence, approx_arousal, args.msg_count, args.offset)

    if args.no_c:
        results_c, time_c, distilled_c, llm_time_c = [], 0, "SKIPPED", 0
    else:
        print(f"{Colors.DIM}Running Strategy C (LLM-distilled)...{Colors.RESET}")
        try:
            results_c, time_c, distilled_c, llm_time_c = run_strategy_c(DB_CFG, cfg, approx_valence, approx_arousal, args.msg_count, mistral_url, args.offset)
        except Exception as e:
            print(f"  {Colors.BRIGHT_RED}Strategy C failed: {e}{Colors.RESET}")
            results_c, time_c, distilled_c, llm_time_c = [], 0, f"FAILED: {e}", 0

    # Display results
    display_strategy_results("A — Concatenated Embedding", results_a, Colors.BRIGHT_GREEN, time_a)
    display_strategy_results("B — Per-Message Embeddings", results_b, Colors.BRIGHT_YELLOW, time_b)

    if distilled_c and distilled_c not in ("SKIPPED", ) and not distilled_c.startswith("FAILED"):
        print(f"\n  {Colors.BRIGHT_MAGENTA}LLM Distillation ({llm_time_c:.3f}s):{Colors.RESET}")
        print(f"    {distilled_c}")
    display_strategy_results("C — LLM-Distilled Embedding", results_c, Colors.BRIGHT_MAGENTA, time_c)

    # Comparison
    display_comparison(results_a, results_b, results_c)


if __name__ == "__main__":
    main()
