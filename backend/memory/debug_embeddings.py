"""
Debug script to understand why cruise memories aren't matching

Tests:
1. Load embedding model
2. Embed current conversation summary ("planning cruise vacation")
3. Embed a known cruise memory summary ("being on cruise ship")
4. Calculate cosine similarity directly
5. Compare to database similarity scores
"""

import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, PROJECT_ROOT)

import psycopg2
import numpy as np
from sentence_transformers import SentenceTransformer

# Force offline mode
os.environ["HF_HUB_OFFLINE"] = "1"

# Load same model as retrieval script
model = SentenceTransformer("/models/llm_models/huggingface/models/all-mpnet-base-v2/", local_files_only=True)

DB_CFG = dict(dbname="irisdb", user="irisuser", password="yourpassword", host="localhost", port=5432)

def normalize(vec):
    """L2 normalization"""
    arr = np.array(vec, dtype=np.float32)
    norm = np.linalg.norm(arr)
    if norm == 0:
        return arr
    return arr / norm

def cosine_similarity(vec1, vec2):
    """Calculate cosine similarity between two vectors"""
    v1 = np.array(vec1, dtype=np.float32)
    v2 = np.array(vec2, dtype=np.float32)
    return np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2))

# Current conversation summary (what we're searching FOR)
current_summary = {
    "Context": "Planning a June cruise vacation with Iris, including social interaction and vision system exploration.",
    "Event": "User confirms deactivation of Protocol Bravo and announces a scheduled cruise vacation in June, followed by Iris suggesting ways to integrate social interaction and vision system testing during the trip.",
    "Significance": "The cruise represents an opportunity for Iris to engage in real-world social and technical exploration while relaxing with the user.",
    "Takeaway": "A cruise vacation can serve as a platform for both relaxation and AI system testing in real-world scenarios."
}

print("=" * 80)
print("EMBEDDING DEBUG - WHY AREN'T CRUISE MEMORIES MATCHING?")
print("=" * 80)

# Embed current summary
print("\n1. Embedding CURRENT conversation summary...")
current_vectors = model.encode([
    current_summary["Context"],
    current_summary["Event"],
    current_summary["Significance"],
    current_summary["Takeaway"]
])

current_emb = {
    "context": normalize(current_vectors[0]).tolist(),
    "event": normalize(current_vectors[1]).tolist(),
    "significance": normalize(current_vectors[2]).tolist(),
    "takeaway": normalize(current_vectors[3]).tolist()
}

print(f"   Context vector sample: {current_emb['context'][:5]}")
print(f"   Event vector sample: {current_emb['event'][:5]}")

# Get a known cruise memory from database
print("\n2. Fetching a CRUISE memory from database...")
conn = psycopg2.connect(**DB_CFG)
cur = conn.cursor()

cur.execute("""
    SELECT id, summary_context, summary_event, summary_significance, takeaway,
           emb_summary_context, emb_summary_event, emb_summary_significance, emb_takeaway
    FROM episodic_memories
    WHERE summary_context ILIKE '%cruise ship%deck%'
    LIMIT 1
""")

row = cur.fetchone()
if not row:
    print("   ERROR: No cruise memory found!")
    exit(1)

mem_id, mem_context, mem_event, mem_sig, mem_take, emb_ctx, emb_evt, emb_sig, emb_take = row

print(f"   Memory ID: {mem_id}")
print(f"   Context: {mem_context[:100]}...")
print(f"   Event: {mem_event[:100]}...")

# Convert database vectors to lists (pgvector returns as string representation)
def parse_pgvector(vec_str):
    """Parse pgvector string format '[1.0, 2.0, ...]' to list of floats"""
    if isinstance(vec_str, str):
        # Remove brackets and split by comma
        clean = vec_str.strip('[]')
        return [float(x.strip()) for x in clean.split(',')]
    return list(vec_str)  # Already a list

db_emb = {
    "context": parse_pgvector(emb_ctx),
    "event": parse_pgvector(emb_evt),
    "significance": parse_pgvector(emb_sig),
    "takeaway": parse_pgvector(emb_take)
}

print(f"   DB Context vector sample: {db_emb['context'][:5]}")

# Calculate similarities DIRECTLY (not using database)
print("\n3. Calculating DIRECT cosine similarities...")

sim_ctx = cosine_similarity(current_emb["context"], db_emb["context"])
sim_evt = cosine_similarity(current_emb["event"], db_emb["event"])
sim_sig = cosine_similarity(current_emb["significance"], db_emb["significance"])
sim_take = cosine_similarity(current_emb["takeaway"], db_emb["takeaway"])

print(f"   Context similarity:       {sim_ctx:.4f}")
print(f"   Event similarity:         {sim_evt:.4f}")
print(f"   Significance similarity:  {sim_sig:.4f}")
print(f"   Takeaway similarity:      {sim_take:.4f}")

# Calculate weighted average (same as retrieval script)
weighted_sim = (
    0.25 * sim_ctx +
    0.25 * sim_evt +
    0.25 * sim_sig +
    0.25 * sim_take
)
print(f"\n   WEIGHTED AVERAGE: {weighted_sim:.4f}")

# Now compare to what DATABASE calculates
print("\n4. Comparing to DATABASE similarity calculation...")

cur.execute("""
    SELECT
        (
            0.25 * (1 - (emb_summary_context      <=> %s::vector)) +
            0.25 * (1 - (emb_summary_event        <=> %s::vector)) +
            0.25 * (1 - (emb_summary_significance <=> %s::vector)) +
            0.25 * (1 - (emb_takeaway             <=> %s::vector))
        ) AS db_sim_score
    FROM episodic_memories
    WHERE id = %s
""", (
    current_emb["context"],
    current_emb["event"],
    current_emb["significance"],
    current_emb["takeaway"],
    mem_id
))

db_sim = cur.fetchone()[0]
print(f"   Database calculated similarity: {db_sim:.4f}")
print(f"   Direct Python calculation:      {weighted_sim:.4f}")
print(f"   Difference:                     {abs(db_sim - weighted_sim):.6f}")

# Test with a NON-cruise memory for comparison
print("\n5. Comparing to a NON-CRUISE memory...")
print("   (Skipped for now - will add in next iteration)")

print("\n" + "=" * 80)
print("ANALYSIS:")
print("=" * 80)

if weighted_sim < 0.3:
    print("❌ PROBLEM: Cruise memory similarity is VERY LOW ({:.4f})".format(weighted_sim))
    print("   This suggests the embedding model doesn't consider")
    print("   'planning a cruise' similar to 'being on a cruise ship'")
elif weighted_sim < 0.5:
    print("⚠️  WARNING: Cruise memory similarity is LOW ({:.4f})".format(weighted_sim))
    print("   Embeddings capture some similarity but not strong enough")
else:
    print("✓ OK: Cruise memory similarity is GOOD ({:.4f})".format(weighted_sim))
    print("   Problem must be elsewhere (reranking? decay?)")

# if non_cruise[2] > weighted_sim:
#     print(f"\n❌ CRITICAL: Non-cruise memory scores HIGHER ({non_cruise[2]:.4f}) than cruise memory!")
#     print("   This confirms embeddings are broken for this use case")

cur.close()
conn.close()

print("\n" + "=" * 80)
