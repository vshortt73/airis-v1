#!/usr/bin/env python3
"""
Test Memory Retrieval from Specific Session

Modified version of iris_memory_retrieval.py that:
- Takes a session_id as parameter
- Loads that session's conversation
- Runs the full retrieval pipeline
- Returns results without modifying database

Usage:
  python test_retrieval_from_session.py <session_id>
"""

import sys
sys.path.insert(0, '/iris-v3/backend/memory')

import psycopg2
from psycopg2.extras import DictCursor
from sentence_transformers import SentenceTransformer
import json

# Import the actual retrieval functions
from iris_memory_retrieval import (
    run_lens_stage,
    run_emotion_stage,
    get_summaries,
    fetch_and_rerank_multi,
    DB_CFG
)

def load_session_conversation(session_id):
    """Load conversation messages from a specific session"""
    conn = psycopg2.connect(**DB_CFG)
    cur = conn.cursor(cursor_factory=DictCursor)

    cur.execute("""
        SELECT role, message
        FROM chat_history
        WHERE session_id = %s
        ORDER BY c_timestamp ASC
    """, (session_id,))

    messages = cur.fetchall()
    cur.close()
    conn.close()

    if not messages:
        raise ValueError(f"No messages found for session {session_id}")

    # Format as conversation text
    convo = "\n".join([f"{m['role'].upper()}: {m['message']}" for m in messages])
    return convo, len(messages)

def run_retrieval_for_session(session_id):
    """Run full retrieval pipeline for a specific session"""

    print(f"Loading session {session_id}...")
    convo, msg_count = load_session_conversation(session_id)
    print(f"Loaded {msg_count} messages\n")

    # Stage 1: Summaries (MUST BE FIRST - changed pipeline order!)
    print("Running summary generation...")
    summaries = get_summaries(convo)
    mr = summaries.get('MemoryRecall', {})
    print(f"  Topic: {mr.get('TopicLabel', '')}")
    print(f"  Context: {mr.get('Context', '')[:100]}...")
    print(f"  Event: {mr.get('Event', '')[:100]}...")
    print()

    # Stage 2: Lens (NOW extracts from summary, not raw convo)
    print("Running lens extraction from summary...")
    lens = run_lens_stage(summaries)
    print(f"  Keywords: {lens.get('keywords', [])[:5]}")
    print(f"  Facets: {lens.get('facets', [])}")
    print()

    # Stage 3: Emotion
    print("Running emotion scoring...")
    emo_results, valence, arousal, top_emotion, json_results = run_emotion_stage(convo)
    print(f"  Valence: {valence:.3f}, Arousal: {arousal:.3f}, Emotion: {top_emotion}")
    print()

    # Stage 4: Generate embeddings (INCLUDING TOPIC!)
    print("Generating embeddings...")
    embedder = SentenceTransformer(
        "/models/llm_models/huggingface/models/all-mpnet-base-v2/",
        local_files_only=True
    )

    # Encode all fields including topic label
    vectors = embedder.encode([
        mr.get("TopicLabel", ""),
        mr.get("Context", ""),
        mr.get("Event", ""),
        mr.get("Significance", ""),
        mr.get("Takeaway", "")
    ])

    embeddings = {
        "topic": vectors[0].tolist(),
        "context": vectors[1].tolist(),
        "event": vectors[2].tolist(),
        "significance": vectors[3].tolist(),
        "takeaway": vectors[4].tolist()
    }
    print(f"  ✓ Embeddings generated (including topic: '{mr.get('TopicLabel', '')}')")
    print()

    # Stage 5: Fetch and rerank
    print("Fetching and reranking memories...")
    candidates = fetch_and_rerank_multi(
        embeddings=embeddings,
        conn_params=DB_CFG,
        emb_context=embeddings["context"],
        emb_event=embeddings["event"],
        emb_significance=embeddings["significance"],
        emb_takeaway=embeddings["takeaway"],
        orientation=lens.get("orientation"),
        facets=lens.get("facets", []),
        current_valence=valence,
        current_arousal=arousal,
        top_emotion=top_emotion,
        limit=10
    )

    # Parse output (fetch_and_rerank_multi prints to stdout)
    print()
    print("="*80)
    print("RETRIEVAL RESULTS")
    print("="*80)

    # Return results
    return {
        'session_id': session_id,
        'message_count': msg_count,
        'lens': lens,
        'emotion': {'valence': valence, 'arousal': arousal, 'label': top_emotion},
        'summaries': mr,
        'top_10_count': 10  # fetch_and_rerank_multi returns top 10
    }

def main():
    if len(sys.argv) < 2:
        print("Usage: python test_retrieval_from_session.py <session_id>")
        sys.exit(1)

    session_id = sys.argv[1]

    print("="*80)
    print("TEST MEMORY RETRIEVAL FROM SESSION")
    print("="*80)
    print()

    try:
        result = run_retrieval_for_session(session_id)

        print()
        print("✓ Retrieval complete")
        print(f"  Session: {result['session_id']}")
        print(f"  Messages: {result['message_count']}")
        print(f"  Summaries generated: {len(result['summaries'])} fields")

    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
