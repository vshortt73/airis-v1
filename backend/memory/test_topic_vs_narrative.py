"""
Quick test: Compare topic embedding vs narrative embeddings
against actual cruise memories in the database

This proves topic embeddings work before we modify the database schema
"""

import os
os.environ["HF_HUB_OFFLINE"] = "1"

import psycopg2
import numpy as np
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("/models/llm_models/huggingface/models/all-mpnet-base-v2/", local_files_only=True)

def cosine_similarity(vec1, vec2):
    v1 = np.array(vec1, dtype=np.float32)
    v2 = np.array(vec2, dtype=np.float32)
    return np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2))

def parse_pgvector(vec_str):
    if isinstance(vec_str, str):
        clean = vec_str.strip('[]')
        return [float(x.strip()) for x in clean.split(',')]
    return list(vec_str)

# Current conversation
topic_label = "cruise vacation planning"
narrative_context = "Planning a June cruise vacation with Iris, including social interaction and vision system exploration."

print("=" * 80)
print("TOPIC vs NARRATIVE: Which finds cruise memories better?")
print("=" * 80)

# Embed both
topic_emb = model.encode(topic_label)
narrative_emb = model.encode(narrative_context)

print(f"\nQuery Topic: '{topic_label}'")
print(f"Query Narrative: '{narrative_context[:60]}...'")

# Get 10 random cruise memories
conn = psycopg2.connect(dbname=os.environ.get('AIRIS_DB_NAME', 'airisdb'), user=os.environ.get('AIRIS_DB_USER', 'airisuser'), password=os.environ.get('AIRIS_DB_PASSWORD', ''), host="localhost", port=5432)
cur = conn.cursor()

cur.execute("""
    SELECT id, LEFT(summary_context, 80), emb_summary_context
    FROM episodic_memories
    WHERE summary_context ILIKE '%cruise%'
    ORDER BY RANDOM()
    LIMIT 10
""")

memories = cur.fetchall()

print(f"\n{'='*80}")
print(f"Testing against {len(memories)} random cruise memories:")
print(f"{'='*80}\n")

topic_scores = []
narrative_scores = []

for mem_id, mem_context, mem_emb in memories:
    mem_vec = parse_pgvector(mem_emb)

    topic_sim = cosine_similarity(topic_emb, mem_vec)
    narrative_sim = cosine_similarity(narrative_emb, mem_vec)

    topic_scores.append(topic_sim)
    narrative_scores.append(narrative_sim)

    print(f"Memory {mem_id}: {mem_context}")
    print(f"  Topic sim:     {topic_sim:.4f}")
    print(f"  Narrative sim: {narrative_sim:.4f}")
    print(f"  Improvement:   {topic_sim - narrative_sim:+.4f}")
    print()

avg_topic = np.mean(topic_scores)
avg_narrative = np.mean(narrative_scores)

print(f"{'='*80}")
print(f"RESULTS:")
print(f"{'='*80}")
print(f"Average Topic Similarity:     {avg_topic:.4f}")
print(f"Average Narrative Similarity: {avg_narrative:.4f}")
print(f"Average Improvement:          {avg_topic - avg_narrative:+.4f} ({((avg_topic/avg_narrative - 1) * 100):+.1f}%)")

if avg_topic > avg_narrative * 1.5:
    print(f"\n✅ TOPIC EMBEDDINGS ARE SIGNIFICANTLY BETTER!")
    print(f"   Ready to implement in production")
elif avg_topic > avg_narrative:
    print(f"\n✅ TOPIC EMBEDDINGS ARE BETTER")
    print(f"   Proceed with implementation")
else:
    print(f"\n❌ TOPIC EMBEDDINGS DON'T HELP")
    print(f"   Need different approach")

print(f"\n{'='*80}")

cur.close()
conn.close()
