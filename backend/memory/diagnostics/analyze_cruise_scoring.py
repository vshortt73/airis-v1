#!/usr/bin/env python3
"""
Analyze why cruise memories aren't scoring higher

This script will:
1. Get the current conversation summaries
2. Calculate similarity scores for ALL cruise memories
3. Compare to what's actually being retrieved
4. Identify why they're being filtered out
"""

import sys
sys.path.insert(0, '/iris-v3/backend/memory')

import psycopg2
from psycopg2.extras import DictCursor
from sentence_transformers import SentenceTransformer
import numpy as np
import httpx
import json

DB_CFG = dict(dbname="irisdb", user="irisuser", password="yourpassword", host="localhost", port=5432)

def get_current_summaries():
    """Get summaries from current conversation using Ollama"""

    # Get conversation
    conn = psycopg2.connect(**DB_CFG)
    cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("""
        SELECT role, message FROM (
            SELECT id, role, message
            FROM chat_history
            ORDER BY c_timestamp DESC
            LIMIT 10
        ) sub
        ORDER BY id ASC
    """)
    rows = cur.fetchall()
    conversation = "\n".join([f"{row['role'].upper()}: {row['message']}" for row in rows])
    cur.close()
    conn.close()

    # Generate summaries with Ollama
    prompt = f"""Analyze this conversation between a user and an AI assistant named Iris.

Extract ABSTRACT, CONCEPTUAL summaries (not literal quotes).

CONVERSATION:
{conversation}

Provide these fields (write in third-person, be conceptual):

Context: What is the general topic/domain being discussed?
Event: What is happening conceptually?
Significance: Why does this conversation matter?
Takeaway: What's the key insight?
Tone: Emotional tone in one word

Return as JSON with fields: Context, Event, Significance, Takeaway, Tone"""

    response = httpx.post(
        "http://localhost:11434/api/generate",
        json={
            "model": "qwen3:32b",
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.1, "num_ctx": 8192}
        },
        timeout=60.0
    )

    result = response.json()
    summaries = json.loads(result["response"])

    print("CURRENT CONVERSATION SUMMARIES:")
    print("=" * 70)
    for field, value in summaries.items():
        print(f"{field}: {value}")
    print()

    return summaries

def analyze_cruise_memories(summaries):
    """Analyze similarity scores for all cruise memories"""

    # Load embedding model
    model = SentenceTransformer("/models/llm_models/huggingface/models/all-mpnet-base-v2/", local_files_only=True)

    # Generate embeddings from current summaries
    curr_embeddings = model.encode([
        summaries["Context"],
        summaries["Event"],
        summaries["Significance"],
        summaries["Takeaway"]
    ])

    # Get all cruise memories
    conn = psycopg2.connect(**DB_CFG)
    cur = conn.cursor(cursor_factory=DictCursor)

    cur.execute("""
        SELECT id, category, age_days,
               summary_context, summary_event, summary_significance, takeaway,
               emb_summary_context, emb_summary_event, emb_summary_significance, emb_takeaway,
               valence, arousal, emotion_label, recurrence, novelty, cohesion
        FROM episodic_memories_with_age
        WHERE (summary_event ILIKE '%cruise%' OR summary_context ILIKE '%cruise%'
               OR summary_event ILIKE '%ship%' OR summary_context ILIKE '%ship%')
          AND summary_context IS NOT NULL AND summary_context <> ''
        ORDER BY age_days ASC
    """)

    cruise_memories = cur.fetchall()
    cur.close()
    conn.close()

    print(f"\nFOUND {len(cruise_memories)} CRUISE MEMORIES")
    print("=" * 70)

    # Calculate scores for each
    results = []
    for mem in cruise_memories:
        # Convert embeddings from database (they're numpy arrays already)
        mem_ctx = np.array(mem['emb_summary_context'])
        mem_evt = np.array(mem['emb_summary_event'])
        mem_sig = np.array(mem['emb_summary_significance'])
        mem_take = np.array(mem['emb_takeaway'])

        # Calculate similarities
        ctx_sim = np.dot(curr_embeddings[0], mem_ctx) / (
            np.linalg.norm(curr_embeddings[0]) * np.linalg.norm(mem_ctx)
        )
        evt_sim = np.dot(curr_embeddings[1], mem_evt) / (
            np.linalg.norm(curr_embeddings[1]) * np.linalg.norm(mem_evt)
        )
        sig_sim = np.dot(curr_embeddings[2], mem_sig) / (
            np.linalg.norm(curr_embeddings[2]) * np.linalg.norm(mem_sig)
        )
        take_sim = np.dot(curr_embeddings[3], mem_take) / (
            np.linalg.norm(curr_embeddings[3]) * np.linalg.norm(mem_take)
        )

        # Weighted similarity (like the system does)
        weighted_sim = 0.25 * ctx_sim + 0.25 * evt_sim + 0.25 * sig_sim + 0.25 * take_sim

        # Calculate reranking factors
        emo_weight = abs(mem['valence'] or 0.0) * (mem['arousal'] or 0.0)
        recurrence = mem['recurrence'] or 0.0
        novelty = mem['novelty'] or 0.0
        cohesion = mem['cohesion'] or 0.0

        # Age decay (30 day half-life)
        import math
        decay = math.exp(-math.log(2) * (mem['age_days'] / 30))

        # Final score (simplified - without context/facet matching)
        final_score = (
            weighted_sim * 0.45 +
            emo_weight * 0.10 +
            recurrence * 0.10 +
            cohesion * 0.05 +
            novelty * 0.05
            # Missing: context_boost (0.15) and facet_boost (0.10)
        ) * decay

        results.append({
            'id': mem['id'],
            'age_days': mem['age_days'],
            'category': mem['category'],
            'weighted_sim': weighted_sim,
            'final_score': final_score,
            'decay': decay,
            'ctx_sim': ctx_sim,
            'evt_sim': evt_sim,
            'sig_sim': sig_sim,
            'take_sim': take_sim,
            'event': mem['summary_event'][:100]
        })

    # Sort by final score
    results.sort(key=lambda x: x['final_score'], reverse=True)

    print("\nCRUISE MEMORIES RANKED BY SCORE:")
    print("=" * 70)
    print(f"{'Rank':<5} {'ID':<7} {'Score':<7} {'Sim':<7} {'Age':<6} {'Decay':<6} Event")
    print("-" * 70)

    for i, r in enumerate(results, 1):
        print(f"{i:<5} {r['id']:<7} {r['final_score']:.3f}   {r['weighted_sim']:.3f}   {r['age_days']:.1f}d  {r['decay']:.3f}  {r['event'][:50]}")

    # Show detailed breakdown for top 5
    print(f"\n\nDETAILED BREAKDOWN - TOP 5 CRUISE MEMORIES:")
    print("=" * 70)

    for i, r in enumerate(results[:5], 1):
        print(f"\n{i}. Memory ID {r['id']} | Age: {r['age_days']:.1f} days | Category: {r['category']}")
        print(f"   Final Score: {r['final_score']:.4f}")
        print(f"   Weighted Similarity: {r['weighted_sim']:.4f}")
        print(f"   Breakdown: ctx={r['ctx_sim']:.3f} evt={r['evt_sim']:.3f} sig={r['sig_sim']:.3f} take={r['take_sim']:.3f}")
        print(f"   Age Decay: {r['decay']:.3f} (reduces all scores by this factor)")
        print(f"   Event: {r['event']}")

    # Compare to threshold
    threshold = 0.20
    passing = [r for r in results if r['weighted_sim'] >= threshold]

    print(f"\n\nTHRESHOLD ANALYSIS:")
    print("=" * 70)
    print(f"Similarity threshold: {threshold}")
    print(f"Cruise memories passing threshold: {len(passing)}/{len(results)}")

    if len(passing) < len(results):
        failing = [r for r in results if r['weighted_sim'] < threshold]
        print(f"\nFailing memories (sim < {threshold}):")
        for r in failing[:5]:
            print(f"  ID {r['id']}: {r['weighted_sim']:.3f} - {r['event'][:60]}")

    # Check what non-cruise memories scored
    print(f"\n\nCOMPARING TO NON-CRUISE MEMORIES:")
    print("=" * 70)

    conn = psycopg2.connect(**DB_CFG)
    cur = conn.cursor(cursor_factory=DictCursor)

    cur.execute("""
        SELECT id, category, age_days, summary_event,
               (
                   0.25 * (1 - (emb_summary_context <=> %s::vector)) +
                   0.25 * (1 - (emb_summary_event <=> %s::vector)) +
                   0.25 * (1 - (emb_summary_significance <=> %s::vector)) +
                   0.25 * (1 - (emb_takeaway <=> %s::vector))
               ) AS sim_score
        FROM episodic_memories_with_age
        WHERE summary_context IS NOT NULL AND summary_context <> ''
        ORDER BY sim_score DESC
        LIMIT 10
    """, (curr_embeddings[0].tolist(), curr_embeddings[1].tolist(),
          curr_embeddings[2].tolist(), curr_embeddings[3].tolist()))

    top_overall = cur.fetchall()
    cur.close()
    conn.close()

    print("Top 10 memories overall (by similarity):")
    for i, mem in enumerate(top_overall, 1):
        is_cruise = 'cruise' in mem['summary_event'].lower() or 'ship' in mem['summary_event'].lower()
        marker = "🚢 CRUISE" if is_cruise else ""
        print(f"{i}. ID {mem['id']} | Score: {mem['sim_score']:.3f} | Age: {mem['age_days']:.1f}d {marker}")
        print(f"   {mem['summary_event'][:80]}")

    # Summary
    cruise_in_top10 = sum(1 for mem in top_overall if 'cruise' in mem['summary_event'].lower() or 'ship' in mem['summary_event'].lower())

    print(f"\n\nSUMMARY:")
    print("=" * 70)
    print(f"✓ Cruise memories in database: {len(cruise_memories)}")
    print(f"✓ Cruise memories passing threshold: {len(passing)}")
    print(f"✓ Cruise memories in actual top 10: {cruise_in_top10}")
    print()

    if cruise_in_top10 < 5:
        print("❌ PROBLEM: Not enough cruise memories in top 10!")
        print()
        print("Likely causes:")
        print("1. Recency bias - cruise memories are older, so age decay reduces their scores")
        print("2. Generic summaries - 'vacation planning' matches many things, not just cruises")
        print("3. Missing keyword boost - no bonus for matching 'cruise' keyword explicitly")
        print()
        print("Recommended fixes:")
        print("1. Reduce age decay (increase HALF_LIFE_DAYS from 30 to 90)")
        print("2. Add keyword matching bonus for memories containing 'cruise', 'ship', etc.")
        print("3. Improve summary to be more specific: 'cruise vacation planning' not just 'vacation planning'")

if __name__ == "__main__":
    print("ANALYZING CRUISE MEMORY RETRIEVAL")
    print("=" * 70)
    print()

    summaries = get_current_summaries()
    analyze_cruise_memories(summaries)
