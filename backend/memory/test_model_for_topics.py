"""
Compare llama3.1:8b vs qwen2.5:14b for topic label generation

Tests on 5 random memories to see which produces better labels faster
"""

import os
import httpx
import psycopg2
import json
import time

DB_CFG = dict(dbname="irisdb", user="irisuser", password=os.environ.get('IRIS_DB_PASSWORD', ''), host="localhost", port=5432)

def generate_topic_label(context, event, takeaway, model_name):
    """Generate topic label using specified model"""
    prompt = f"""Given this memory summary, extract a 2-5 word topic label describing what this is FUNDAMENTALLY about.

Context: {context}
Event: {event}
Takeaway: {takeaway}

Examples:
- If about planning a vacation → "vacation travel planning"
- If about debugging code → "software debugging"
- If about cooking recipe → "cooking recipe development"

Return ONLY the topic label (2-5 words), nothing else."""

    start = time.time()
    response = httpx.post(
        "http://localhost:11434/api/generate",
        json={
            "model": model_name,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.1, "num_ctx": 2048}
        },
        timeout=30.0
    )
    elapsed = time.time() - start

    if response.status_code == 200:
        result = response.json()
        label = result["response"].strip().strip('"').strip()
        return label, elapsed
    return None, elapsed

# Get 5 random diverse memories
conn = psycopg2.connect(**DB_CFG)
cur = conn.cursor()

cur.execute("""
    SELECT id, LEFT(summary_context, 100), LEFT(summary_event, 100), LEFT(takeaway, 100)
    FROM episodic_memories
    WHERE summary_context IS NOT NULL
      AND summary_event IS NOT NULL
      AND takeaway IS NOT NULL
    ORDER BY RANDOM()
    LIMIT 5
""")

memories = cur.fetchall()

print("=" * 80)
print("MODEL COMPARISON: llama3.1:8b vs qwen2.5:14b")
print("=" * 80)

models = ["llama3.1:8b", "qwen2.5:14b"]
results = {m: {"labels": [], "times": []} for m in models}

for idx, (mem_id, context, event, takeaway) in enumerate(memories, 1):
    print(f"\n{'='*80}")
    print(f"MEMORY {idx} (ID {mem_id})")
    print(f"{'='*80}")
    print(f"Context: {context}")
    print(f"Event:   {event}")
    print(f"Takeaway: {takeaway}")
    print()

    for model in models:
        label, elapsed = generate_topic_label(context, event, takeaway, model)
        results[model]["labels"].append(label)
        results[model]["times"].append(elapsed)
        print(f"{model:20s} | {elapsed:5.2f}s | {label}")

print(f"\n{'='*80}")
print("SUMMARY")
print(f"{'='*80}\n")

for model in models:
    avg_time = sum(results[model]["times"]) / len(results[model]["times"])
    print(f"{model}:")
    print(f"  Average time: {avg_time:.2f}s")
    print(f"  Labels generated:")
    for i, label in enumerate(results[model]["labels"], 1):
        print(f"    {i}. {label}")
    print()

print("\nRECOMMENDATION:")
llama_time = sum(results["llama3.1:8b"]["times"]) / len(results["llama3.1:8b"]["times"])
qwen_time = sum(results["qwen2.5:14b"]["times"]) / len(results["qwen2.5:14b"]["times"])

if qwen_time < llama_time * 1.5:
    print(f"✅ Use qwen2.5:14b - good quality, comparable speed")
    print(f"   Expected backfill time for 115 cruise memories: ~{int(qwen_time * 115 / 60)} minutes")
    print(f"   Expected backfill time for 30k memories: ~{int(qwen_time * 30000 / 3600)} hours")
else:
    print(f"✅ Use llama3.1:8b - significantly faster")
    print(f"   Expected backfill time for 115 cruise memories: ~{int(llama_time * 115 / 60)} minutes")
    print(f"   Expected backfill time for 30k memories: ~{int(llama_time * 30000 / 3600)} hours")

print(f"\nManually review labels above to check quality before full backfill!")

cur.close()
conn.close()
