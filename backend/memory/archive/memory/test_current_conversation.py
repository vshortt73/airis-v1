"""
Test memory retrieval on current conversation
Simplified version that bypasses lens/emotion stages
"""

import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, PROJECT_ROOT)

import psycopg2
from psycopg2.extras import DictCursor
from sentence_transformers import SentenceTransformer
import numpy as np
from Colors import Colors

DB_CFG = dict(dbname="irisdb", user="irisuser", password="yourpassword", host="localhost", port=5432)

# Load embedding model
model = SentenceTransformer("/models/llm_models/huggingface/models/all-mpnet-base-v2/", local_files_only=True)

def get_recent_conversation(limit=20):
    """Get recent conversation from chat_history"""
    conn = psycopg2.connect(**DB_CFG)
    cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("""
        SELECT role, message FROM (
            SELECT id, role, message
            FROM chat_history
            ORDER BY c_timestamp DESC
            LIMIT %s
        ) sub
        ORDER BY id ASC
    """, (limit,))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    conversation = ""
    for role, message in rows:
        conversation += f"{role.upper()}: {message}\n"

    return conversation

def calculate_similarity(emb1, emb2):
    """Calculate cosine similarity"""
    emb1_arr = np.array(emb1)
    emb2_arr = np.array(emb2)

    dot_product = np.dot(emb1_arr, emb2_arr)
    norm1 = np.linalg.norm(emb1_arr)
    norm2 = np.linalg.norm(emb2_arr)

    if norm1 == 0 or norm2 == 0:
        return 0.0

    return float(dot_product / (norm1 * norm2))

def retrieve_memories(conversation, top_k=10):
    """Retrieve memories for conversation"""

    print(f"\n{Colors.BRIGHT_CYAN}{'='*70}")
    print("TESTING MEMORY RETRIEVAL ON CURRENT CONVERSATION")
    print(f"{'='*70}{Colors.RESET}\n")

    print(f"{Colors.BRIGHT_YELLOW}Recent Conversation (last 20 messages):{Colors.RESET}")
    print(f"{conversation[:500]}...")
    print()

    # Generate embedding from conversation
    print(f"{Colors.BRIGHT_GREEN}Generating embeddings from conversation...{Colors.RESET}")
    query_embedding = model.encode(conversation).tolist()

    # Query database for memories
    print(f"{Colors.BRIGHT_GREEN}Querying episodic memories...{Colors.RESET}")
    conn = psycopg2.connect(**DB_CFG)
    cur = conn.cursor(cursor_factory=DictCursor)

    cur.execute("""
        SELECT
            id,
            transcript,
            takeaway,
            summary_context,
            summary_event,
            summary_significance,
            category,
            emotion_label,
            valence,
            arousal,
            recurrence,
            novelty,
            cohesion,
            age_days,
            (1 - (emb_summary_context <=> %s::vector))::float AS sim_ctx,
            (1 - (emb_summary_event <=> %s::vector))::float AS sim_evt,
            (1 - (emb_summary_significance <=> %s::vector))::float AS sim_sig,
            (1 - (emb_takeaway <=> %s::vector))::float AS sim_take
        FROM episodic_memories_with_age
        WHERE summary_context IS NOT NULL AND summary_context <> ''
          AND summary_event IS NOT NULL AND summary_event <> ''
          AND summary_significance IS NOT NULL AND summary_significance <> ''
          AND takeaway IS NOT NULL AND takeaway <> ''
        ORDER BY (
            0.25 * (1 - (emb_summary_context <=> %s::vector)) +
            0.25 * (1 - (emb_summary_event <=> %s::vector)) +
            0.25 * (1 - (emb_summary_significance <=> %s::vector)) +
            0.25 * (1 - (emb_takeaway <=> %s::vector))
        ) DESC
        LIMIT %s
    """, (
        query_embedding, query_embedding, query_embedding, query_embedding,
        query_embedding, query_embedding, query_embedding, query_embedding,
        top_k * 2  # Get extra for display
    ))

    memories = cur.fetchall()
    cur.close()
    conn.close()

    # Display results
    print(f"\n{Colors.BRIGHT_MAGENTA}{'='*70}")
    print(f"TOP {top_k} RETRIEVED MEMORIES")
    print(f"{'='*70}{Colors.RESET}\n")

    for i, mem in enumerate(memories[:top_k], 1):
        # Calculate weighted similarity (new weights)
        weighted_sim = (
            0.25 * float(mem['sim_ctx']) +
            0.25 * float(mem['sim_evt']) +
            0.25 * float(mem['sim_sig']) +
            0.25 * float(mem['sim_take'])
        )

        print(f"{Colors.WHITE}{i}. Memory ID: {mem['id']}{Colors.RESET}")
        print(f"   Category: {mem['category']} | Emotion: {mem['emotion_label']}")
        print(f"   Age: {mem['age_days']:.1f} days")
        print(f"   {Colors.BRIGHT_GREEN}Overall Similarity: {weighted_sim:.3f}{Colors.RESET}")
        print(f"   Breakdown: ctx={mem['sim_ctx']:.3f} evt={mem['sim_evt']:.3f} "
              f"sig={mem['sim_sig']:.3f} take={mem['sim_take']:.3f}")
        print(f"\n   {Colors.BRIGHT_CYAN}Context:{Colors.RESET} {mem['summary_context']}")
        print(f"   {Colors.BRIGHT_CYAN}Event:{Colors.RESET} {mem['summary_event']}")
        print(f"   {Colors.BRIGHT_CYAN}Significance:{Colors.RESET} {mem['summary_significance']}")
        print(f"   {Colors.BRIGHT_YELLOW}Takeaway:{Colors.RESET} {mem['takeaway']}")

        # Emotional metrics
        emo_intensity = abs(mem['valence'] or 0.0) * (mem['arousal'] or 0.0)
        print(f"   Emotional Intensity: {emo_intensity:.3f} "
              f"(valence={mem['valence']:.2f}, arousal={mem['arousal']:.2f})")
        print(f"   Psychological: recurrence={mem['recurrence']:.2f} "
              f"novelty={mem['novelty']:.2f} cohesion={mem['cohesion']:.2f}")
        print()
        print("-" * 70)
        print()

    # Summary statistics
    print(f"\n{Colors.BRIGHT_CYAN}{'='*70}")
    print("RETRIEVAL STATISTICS")
    print(f"{'='*70}{Colors.RESET}\n")

    if memories:
        similarities = [
            0.25 * float(m['sim_ctx']) +
            0.25 * float(m['sim_evt']) +
            0.25 * float(m['sim_sig']) +
            0.25 * float(m['sim_take'])
            for m in memories[:top_k]
        ]

        print(f"Top match similarity: {similarities[0]:.3f}")
        print(f"Average similarity (top {top_k}): {np.mean(similarities):.3f}")
        print(f"Similarity range: {min(similarities):.3f} - {max(similarities):.3f}")

        categories = [m['category'] for m in memories[:top_k]]
        print(f"\nCategories retrieved: {', '.join(set(categories))}")

        avg_age = np.mean([m['age_days'] for m in memories[:top_k]])
        print(f"Average memory age: {avg_age:.1f} days")

if __name__ == "__main__":
    conversation = get_recent_conversation(limit=10)
    retrieve_memories(conversation, top_k=10)
