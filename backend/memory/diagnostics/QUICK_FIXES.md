# Quick Fixes for Memory Retrieval

## TL;DR - The Problems

1. **Grammar file is too slow and too restrictive** - Causes CPU to peg at 100%
2. **Summary generation breaks** - Returns empty summaries → all embeddings identical
3. **No temporal bridging** - "Planning future cruise" doesn't retrieve "past cruise experiences"
4. **Test script is misleading** - Doesn't test what the real system does

---

## Immediate Fix: Bypass Grammar for Now

The grammar file is killing performance. Here's a faster approach:

### Option A: Remove Grammar Constraint (Fast)

**Edit:** `iris_memory_retrieval.py` line 251

```python
# BEFORE
payload = {
    "prompt": prompt,
    "max_tokens": 512,
    "temperature": 0.1,
    "grammar_file": "/iris-v3/backend/memory/summary.gbnf"  # Remove this!
}

# AFTER
payload = {
    "prompt": prompt,
    "max_tokens": 512,
    "temperature": 0.1
    # No grammar - let LLM generate freely, parse with fallback
}
```

**Trade-off:** Less structured output, but **much faster** and won't peg CPU

---

### Option B: Use Simpler Grammar (Medium)

Create `summary_simple.gbnf`:

```gbnf
root ::= object
object ::= "{" ws "\"MemoryRecall\":" ws "{" ws fields ws "}" ws "}"
fields ::= field (ws "," ws field)*
field ::= "\"" [A-Z][a-z]+ "\"" ws ":" ws string
string ::= "\"" [^"]* "\""
ws ::= [ \n\t]*
```

Much simpler, much faster!

---

### Option C: Switch to Ollama for Summaries (Recommended)

Instead of llama.cpp on port 9600, use Ollama (already running on 11434):

```python
def get_summaries_ollama(conversation: str):
    """Use Ollama instead of llama.cpp for faster, more reliable summaries"""
    import httpx

    prompt = f"""Extract structured information from this conversation:

{conversation}

Return ONLY valid JSON in this exact format:
{{
  "MemoryRecall": {{
    "Context": "brief domain/topic description",
    "Event": "what happened",
    "Significance": "why it matters",
    "Takeaway": "key insight",
    "Tone": "emotional tone"
  }}
}}"""

    response = httpx.post(
        "http://localhost:11434/api/generate",
        json={
            "model": "qwen3:32b",
            "prompt": prompt,
            "stream": False,
            "format": "json",  # Ollama's JSON mode - much faster!
            "options": {
                "temperature": 0.1,
                "num_ctx": 4096
            }
        },
        timeout=30.0
    )

    result = response.json()
    return json.loads(result["response"])
```

**Benefits:**
- ✅ Much faster (no grammar constraints)
- ✅ Uses Ollama's native JSON mode
- ✅ More reliable parsing
- ✅ Doesn't peg CPU

---

## Better Summary Prompt

The current prompt doesn't guide the LLM well enough. Here's an improved version:

```python
def get_summaries_improved(conversation: str):
    """Improved prompt for better abstraction and temporal bridging"""

    prompt = f"""Analyze this conversation and extract ABSTRACT, CONCEPTUAL summaries (not literal conversation details):

CONVERSATION:
{conversation}

Extract the following in third-person perspective:

1. **Context**: What general topic/domain is discussed? Focus on abstract themes, not specifics.
   Example: "Vacation planning and experiential learning" NOT "User wants to go on a cruise"

2. **Event**: What is happening conceptually? Bridge temporal gaps.
   Example: "Applying past travel experiences to upcoming vacation planning" NOT "User announces cruise"

3. **Significance**: Why does this matter abstractly?
   Example: "Leveraging experiential knowledge for future decision-making" NOT "They want to have a good time"

4. **Takeaway**: What's the key insight or pattern?
   Example: "Past experiences inform future activity planning" NOT "User asks about lessons from last cruise"

5. **Tone**: Overall emotional tone (one word: excited, reflective, curious, etc.)

Return valid JSON:
{{
  "MemoryRecall": {{
    "Context": "...",
    "Event": "...",
    "Significance": "...",
    "Takeaway": "...",
    "Tone": "..."
  }}
}}"""

    # ... rest of implementation
```

**Key improvements:**
- ✅ Emphasizes abstraction over literals
- ✅ Provides examples of good vs bad summaries
- ✅ Encourages temporal bridging ("past experiences" → "future planning")
- ✅ Third-person perspective for consistency

---

## Fix the Test Script

Create `test_full_pipeline.py` that actually tests what the system does:

```python
"""
Test memory retrieval with FULL pipeline (lens + emotion + summary + rerank)
This matches what the actual system does, unlike test_current_conversation.py
"""

import sys
sys.path.insert(0, '/iris-v3/backend/memory')

from iris_memory_retrieval import cognitive_recall, DB_CFG
from sentence_transformers import SentenceTransformer
import psycopg2

# Get recent conversation
conn = psycopg2.connect(**DB_CFG)
cur = conn.cursor()
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
conversation = "\n".join([f"{role.upper()}: {msg}" for role, msg in rows])
cur.close()
conn.close()

# Create embedder
class Embedder:
    def __init__(self):
        self.model = SentenceTransformer("/models/llm_models/huggingface/models/all-mpnet-base-v2/", local_files_only=True)
    def embed(self, text: str):
        return self.model.encode(text, normalize_embeddings=True).tolist()

embedder = Embedder()

# Run FULL pipeline
print("Running FULL memory retrieval pipeline...\n")
print("=" * 70)
print("CONVERSATION:")
print("=" * 70)
print(conversation[:500] + "...")
print("\n" + "=" * 70)
print("RUNNING PIPELINE...")
print("=" * 70 + "\n")

injection = cognitive_recall(
    convo=conversation,
    embedder=embedder,
    conn_params=DB_CFG,
    top_k=10,
    insert=False,
    show=True,
    mode="replace",
    prompt=True
)

print("\n" + "=" * 70)
print("RESULTS:")
print("=" * 70)
print(injection)
```

---

## Reduce Recency Bias

Your current results are ALL from the last 2-3 days. This is because:

1. Recent memories have higher arousal scores
2. Age decay favors recent memories
3. Emotional context is fresher

**Fix:** Tune the age decay half-life

```python
# CURRENT (line 89)
HALF_LIFE_DAYS = 30  # Memories lose 50% strength every 30 days

# RECOMMENDED
HALF_LIFE_DAYS = 90  # Slower decay = older memories stay relevant longer
```

**Or:** Add recency penalty for very recent memories:

```python
# In reranking (around line 465)
age_days = float(c.get("age_days") or 0)

# Add recency penalty for memories < 1 day old
if age_days < 1.0:
    recency_penalty = 0.8  # 20% penalty for brand new memories
else:
    recency_penalty = 1.0

decay = math.exp(-math.log(2) * (age_days / half_life_days)) * recency_penalty
```

---

## Add Temporal Bridging

The biggest issue: "Planning future cruise" doesn't retrieve "past cruise experiences"

**Quick fix:** Add keyword expansion in lens stage

```python
def expand_temporal_keywords(keywords: list, conversation: str) -> list:
    """Expand keywords to bridge temporal gaps"""
    expanded = keywords.copy()

    # Detect future planning
    future_indicators = ["upcoming", "will be", "planning", "going to", "scheduled"]
    is_future_planning = any(indicator in conversation.lower() for indicator in future_indicators)

    if is_future_planning:
        # Expand keywords to include past experiences
        temporal_expansions = {
            "cruise": ["cruise", "ship", "voyage", "sailing", "aboard"],
            "vacation": ["vacation", "trip", "travel", "holiday", "getaway"],
            "visit": ["visit", "visited", "visiting", "location", "destination"]
        }

        for keyword in keywords:
            for base, expansions in temporal_expansions.items():
                if base in keyword.lower():
                    expanded.extend(expansions)

    return list(set(expanded))  # Remove duplicates

# Use in lens stage:
lens_output = run_lens_stage(conversation)
lens_output["keywords"] = expand_temporal_keywords(
    lens_output["keywords"],
    conversation
)
```

---

## Priority Order

1. **IMMEDIATE**: Switch to Ollama for summaries (Option C above) - Solves CPU issue
2. **HIGH**: Improve summary prompt - Better abstraction
3. **HIGH**: Add temporal bridging - Connect past/future
4. **MEDIUM**: Fix test script - Actually test the pipeline
5. **MEDIUM**: Reduce recency bias - Tune half-life or add penalty
6. **LOW**: Expand grammar if keeping llama.cpp approach

---

## Test After Fixes

After implementing fixes, test with:

```bash
# Use the cruise conversation
python test_full_pipeline.py
```

**Expected results:**
- ✅ Summaries generate successfully (no empty fields)
- ✅ At least 3-5 cruise memories in top 10
- ✅ Memories span more than just last 2-3 days
- ✅ Top similarities > 0.40 (not < 0.30)

---

## Files to Modify

```
backend/memory/
├── iris_memory_retrieval.py       (switch to Ollama, improve prompt)
├── test_full_pipeline.py          (NEW - create this)
└── diagnostics/
    ├── MEMORY_RETRIEVAL_DIAGNOSIS.md  (full analysis)
    └── QUICK_FIXES.md                 (this file)
```

---

## Questions?

**Q: Why is grammar so slow?**
A: Grammar-constrained generation forces the LLM to explore a constrained state space, requiring many more tokens to generate. It's exponentially slower than free generation.

**Q: Won't free generation produce invalid JSON?**
A: Sometimes, but Ollama's `"format": "json"` mode is very reliable and much faster. Plus you have fallback parsing already.

**Q: Why not just use keyword search?**
A: Embedding search is better for semantic similarity, but you could combine both (hybrid search) for best results.

**Q: How do I know if it's working?**
A: When you ask about future cruise, you should see memories like:
- Lost car keys on Mariner of the Seas
- Pool gathering on cruise
- Children asking questions on cruise
- Cruise ship speed discussions
- etc.

Currently you see NONE of these in top 10!
