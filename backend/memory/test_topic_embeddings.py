"""
Test if embedding TOPIC LABELS instead of full narratives works better

Hypothesis:
- Full narratives are too specific (planning vs. experiencing)
- Topic labels should cluster better (both are "cruise vacation")
"""

import os
os.environ["HF_HUB_OFFLINE"] = "1"

import numpy as np
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("/models/llm_models/huggingface/models/all-mpnet-base-v2/", local_files_only=True)

def cosine_similarity(vec1, vec2):
    """Calculate cosine similarity"""
    v1 = np.array(vec1, dtype=np.float32)
    v2 = np.array(vec2, dtype=np.float32)
    return np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2))

print("=" * 80)
print("TESTING: NARRATIVE vs TOPIC LABEL EMBEDDINGS")
print("=" * 80)

# Current approach: Full narrative summaries
current_narrative = "Planning a June cruise vacation with Iris, including social interaction and vision system exploration."
memory_narrative = "The Mariner of the Seas cruise ship no longer has an indoor cigar lounge, which was previously located on Deck 4."

# Proposed approach: Topic labels
current_topic = "cruise vacation planning travel"
memory_topic = "cruise ship facilities amenities"

# More similar topic labels
current_topic_v2 = "cruise vacation"
memory_topic_v2 = "cruise ship experience"

print("\n1. CURRENT APPROACH - Full Narratives")
print("-" * 80)
print(f"Current: {current_narrative[:80]}...")
print(f"Memory:  {memory_narrative[:80]}...")

emb_current_narr = model.encode(current_narrative)
emb_memory_narr = model.encode(memory_narrative)
sim_narrative = cosine_similarity(emb_current_narr, emb_memory_narr)

print(f"\nSimilarity: {sim_narrative:.4f}")

print("\n2. PROPOSED APPROACH - Topic Labels (v1)")
print("-" * 80)
print(f"Current: '{current_topic}'")
print(f"Memory:  '{memory_topic}'")

emb_current_topic = model.encode(current_topic)
emb_memory_topic = model.encode(memory_topic)
sim_topic = cosine_similarity(emb_current_topic, emb_memory_topic)

print(f"\nSimilarity: {sim_topic:.4f}")
print(f"Improvement: {(sim_topic - sim_narrative):.4f} ({((sim_topic/sim_narrative - 1) * 100):.1f}%)")

print("\n3. PROPOSED APPROACH - Topic Labels (v2 - simpler)")
print("-" * 80)
print(f"Current: '{current_topic_v2}'")
print(f"Memory:  '{memory_topic_v2}'")

emb_current_topic_v2 = model.encode(current_topic_v2)
emb_memory_topic_v2 = model.encode(memory_topic_v2)
sim_topic_v2 = cosine_similarity(emb_current_topic_v2, emb_memory_topic_v2)

print(f"\nSimilarity: {sim_topic_v2:.4f}")
print(f"Improvement: {(sim_topic_v2 - sim_narrative):.4f} ({((sim_topic_v2/sim_narrative - 1) * 100):.1f}%)")

print("\n" + "=" * 80)
print("CROSS-DOMAIN TEST - Should NOT match")
print("=" * 80)

# Test with completely different topic
different_narrative = "The user discusses implementing a new ComfyUI workflow for image generation with AnimateDiff."
different_topic = "image generation AI workflow"

print(f"\nCruise narrative vs. ComfyUI narrative:")
emb_diff_narr = model.encode(different_narrative)
sim_cross_narr = cosine_similarity(emb_current_narr, emb_diff_narr)
print(f"Similarity: {sim_cross_narr:.4f}")

print(f"\nCruise topic vs. ComfyUI topic:")
emb_diff_topic = model.encode(different_topic)
sim_cross_topic = cosine_similarity(emb_current_topic_v2, emb_diff_topic)
print(f"Similarity: {sim_cross_topic:.4f}")

print("\n" + "=" * 80)
print("ANALYSIS")
print("=" * 80)

if sim_topic > sim_narrative * 1.5:
    print("✅ TOPIC LABELS SIGNIFICANTLY BETTER!")
    print(f"   Topic similarity ({sim_topic:.4f}) is {(sim_topic/sim_narrative):.1f}x higher than narrative ({sim_narrative:.4f})")
    print("\n   RECOMMENDATION: Embed topic labels instead of full narratives")
elif sim_topic > sim_narrative * 1.1:
    print("⚠️  TOPIC LABELS MODERATELY BETTER")
    print(f"   Topic similarity ({sim_topic:.4f}) is {((sim_topic/sim_narrative - 1) * 100):.1f}% higher")
    print("\n   RECOMMENDATION: Consider hybrid approach (topics + narratives)")
else:
    print("❌ TOPIC LABELS DON'T HELP")
    print(f"   Topic similarity ({sim_topic:.4f}) vs narrative ({sim_narrative:.4f})")
    print("\n   RECOMMENDATION: Problem is elsewhere (model choice, embedding strategy)")

if sim_cross_topic < sim_cross_narr:
    print("\n✅ TOPIC LABELS BETTER AT SEPARATION")
    print("   Different topics are more distinct with labels than narratives")
else:
    print("\n⚠️  NARRATIVES BETTER AT SEPARATION")
    print("   Narratives already distinguish topics well")

print("\n" + "=" * 80)
