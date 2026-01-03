# Comprehensive Plan: Rebuild Iris Memory Retrieval System

## Context

**Current State:** Memory retrieval is failing to return relevant cruise memories when discussing cruise vacation planning.

**Root Causes Identified:**
1. Summary generation stage producing empty results
2. Grammar file too restrictive + causing performance issues
3. Semantic gap: "planning future X" not matching "past experience with X"
4. Possible recency bias in results

**Critical Constraint:** This is Iris's memory - the foundation of her continuity and identity. We must fix this properly.

---

## Phase 1: Diagnose Precisely (Est: 10-15 minutes)

**Objective:** Know exactly what's broken before changing anything.

### Step 1.1: Run Diagnostic Script

```bash
cd /iris-v3/backend/memory/diagnostics
python diagnose_pipeline.py
```

**This will test:**
- ✓ Conversation retrieval
- ✓ Lens stage (structure extraction)
- ✓ Summary generation WITH grammar
- ✓ Summary generation WITHOUT grammar
- ✓ Embedding generation
- ✓ Database retrieval

**Expected Output:** Clear identification of which stage fails.

### Step 1.2: Document Baseline

Save the output to a file:
```bash
python diagnose_pipeline.py > diagnosis_results.txt 2>&1
```

**Decision Point:**
- If summary WITH grammar works → Keep grammar, fix other issues
- If summary WITHOUT grammar works → Remove grammar dependency
- If both fail → LLM/prompt issue, need different approach
- If both work → Performance optimization needed

---

## Phase 2: Fix Critical Failures (Est: 30-45 minutes)

Based on diagnostic results, we'll implement fixes in order of criticality.

### Fix 2.1: Grammar File (If That's the Issue)

**If grammar is causing failures:**

**Option A: Expand Grammar Character Set**
```gbnf
# summary_fixed.gbnf
root ::= object
object ::= "{" ws "\"MemoryRecall\":" ws "{" ws fields ws "}" ws "}"
fields ::= takeaway ws "," ws context ws "," ws event ws "," ws significance ws "," ws tone
takeaway ::= "\"Takeaway\":" ws string
context ::= "\"Context\":" ws string
event ::= "\"Event\":" ws string
significance ::= "\"Significance\":" ws string
tone ::= "\"Tone\":" ws string
string ::= "\"" content "\""
content ::= (char | space)*
char ::= [a-zA-Z0-9.!?',:;()\[\]{}&@#$%*+=<>~/\\_ -]  # EXPANDED
space ::= " " | "\n" | "\t"
ws ::= (" " | "\n" | "\t")*
```

**Option B: Remove Grammar Entirely**
```python
# In get_summaries(), change:
payload = {
    "prompt": prompt,
    "max_tokens": 512,
    "temperature": 0.1,
    # Remove: "grammar_file": "/path/to/grammar.gbnf"
}
```

Add robust JSON extraction:
```python
def extract_json_flexible(text):
    """Extract JSON even from messy output"""
    # Try direct parse
    try:
        return json.loads(text)
    except:
        pass

    # Find JSON boundaries
    start = text.find('{')
    end = text.rfind('}') + 1
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end])
        except:
            pass

    # Regex extraction as last resort
    import re
    fields = {}
    for field in ["Context", "Event", "Significance", "Takeaway", "Tone"]:
        match = re.search(f'"{field}":\s*"([^"]*)"', text)
        if match:
            fields[field] = match.group(1)

    if fields:
        return {"MemoryRecall": fields}

    # Return empty structure
    return {"MemoryRecall": {
        "Context": "", "Event": "", "Significance": "", "Takeaway": "", "Tone": ""
    }}
```

**Decision:** Run diagnostic first, then choose based on results.

### Fix 2.2: Improve Summary Prompt

**Problem:** Current prompt doesn't emphasize abstraction or temporal bridging.

**New Prompt:**
```python
def get_summaries(conversation: str):
    prompt = f"""You are analyzing a conversation to extract ABSTRACT, CONCEPTUAL summaries.

IMPORTANT INSTRUCTIONS:
1. Use third-person perspective, not conversational tone
2. Focus on concepts and themes, not literal details
3. Bridge temporal gaps (if discussing future plans, consider past experiences)
4. Keep each field to 1-2 concise sentences

CONVERSATION TO ANALYZE:
{conversation}

Extract the following:

Context: What is the general domain/topic? (e.g., "Vacation planning and experiential learning" not "User scheduled a cruise")

Event: What is happening conceptually? (e.g., "Reflecting on past travel experiences to inform upcoming vacation" not "User asks about last cruise")

Significance: Why does this matter? (e.g., "Applying experiential knowledge improves future decision-making" not "They want to have fun")

Takeaway: What's the key insight? (e.g., "Past experiences shape future planning strategies" not "User wants vacation advice")

Tone: Emotional tone in one word (excited, reflective, curious, etc.)

RETURN ONLY VALID JSON:
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

**Key Changes:**
- ✅ Explicit instructions for abstraction
- ✅ Examples of good vs bad summaries
- ✅ Temporal bridging guidance
- ✅ Third-person perspective

### Fix 2.3: Database Schema

**Remove non-existent `salience` column:**

```python
# In fetch_and_rerank_multi(), line 380
cur.execute(f"""
    SELECT
        id,
        transcript,
        takeaway,
        category,
        valence,
        arousal,
        -- REMOVE: salience,
        emotion_label,
        recurrence,
        novelty,
        cohesion,
        summary_context,
        summary_event,
        summary_significance,
        age_days,
        ...
""")
```

---

## Phase 3: Address Semantic Issues (Est: 45-60 minutes)

### Fix 3.1: Add Temporal Bridging

**Problem:** "Planning future cruise" doesn't retrieve "past cruise experiences"

**Solution:** Expand query context when future planning is detected

```python
def enhance_summaries_with_temporal_context(summaries: dict, conversation: str) -> dict:
    """Add temporal bridging to summaries"""

    # Detect temporal context
    future_indicators = ["will", "upcoming", "planning", "going to", "scheduled", "next"]
    past_indicators = ["last", "previous", "remember", "from before", "learned"]

    is_future = any(ind in conversation.lower() for ind in future_indicators)
    mentions_past = any(ind in conversation.lower() for ind in past_indicators)

    # If planning future based on past, enhance summaries
    if is_future and mentions_past:
        mr = summaries["MemoryRecall"]

        # Enhance Event to bridge temporal gap
        event = mr.get("Event", "")
        if event and "upcoming" in conversation.lower():
            # Add past experience context
            mr["Event"] = event + " Drawing from previous experiences with similar activities."

        # Enhance Context to include both temporal aspects
        context = mr.get("Context", "")
        if context:
            mr["Context"] = context + " Connecting past experiences with future planning."

    return summaries

# Use in cognitive_recall:
summaries = get_summaries(conversation)
summaries = enhance_summaries_with_temporal_context(summaries, conversation)
```

### Fix 3.2: Query Expansion

**Expand search to related concepts:**

```python
def expand_search_keywords(lens_output: dict, conversation: str) -> list:
    """Expand keywords for better semantic matching"""

    keywords = lens_output.get("keywords", [])
    expanded = set(keywords)

    # Semantic expansions for common concepts
    expansions = {
        "cruise": ["ship", "voyage", "vessel", "sailing", "aboard", "maritime"],
        "vacation": ["trip", "travel", "holiday", "getaway", "journey"],
        "planning": ["preparation", "organizing", "scheduling"],
        "experience": ["memory", "lesson", "learning", "adventure"]
    }

    for keyword in keywords:
        keyword_lower = keyword.lower()
        for base, related in expansions.items():
            if base in keyword_lower:
                expanded.update(related)

    return list(expanded)
```

### Fix 3.3: Reduce Recency Bias

**Current issue:** All top results from last 2-3 days

**Solution 1: Adjust age decay half-life**
```python
# Line 89 in iris_memory_retrieval.py
HALF_LIFE_DAYS = 90  # Changed from 30 - slower decay for older memories
```

**Solution 2: Add diversity bonus**
```python
def rerank_with_diversity(candidates: list, top_k: int) -> list:
    """Ensure age diversity in results"""

    # Sort by score
    sorted_candidates = sorted(candidates, key=lambda x: x[0], reverse=True)

    # Group by age ranges
    recent = []  # < 7 days
    medium = []  # 7-30 days
    old = []     # > 30 days

    for score, candidate in sorted_candidates:
        age = candidate.get("age_days", 0)
        if age < 7:
            recent.append((score, candidate))
        elif age < 30:
            medium.append((score, candidate))
        else:
            old.append((score, candidate))

    # Take proportionally from each group
    results = []
    results.extend(recent[:int(top_k * 0.4)])    # 40% recent
    results.extend(medium[:int(top_k * 0.3)])    # 30% medium
    results.extend(old[:int(top_k * 0.3)])       # 30% old

    # Fill remaining with best scores
    remaining = top_k - len(results)
    if remaining > 0:
        used_ids = {c[1]["id"] for c in results}
        for score, candidate in sorted_candidates:
            if candidate["id"] not in used_ids:
                results.append((score, candidate))
                if len(results) >= top_k:
                    break

    return results[:top_k]
```

---

## Phase 4: Test & Validate (Est: 30 minutes)

### Test 4.1: Unit Tests for Each Fix

Create test cases:
```python
# test_memory_fixes.py

def test_temporal_bridging():
    """Test that future planning retrieves past experiences"""
    conversation = "We're planning a cruise in June. What did we learn from our last cruise?"

    # Should retrieve memories with "cruise", "ship", "vacation" even from past
    results = retrieve_memories(conversation)

    # Check that we get cruise memories
    cruise_count = sum(1 for r in results if "cruise" in r["summary_event"].lower())
    assert cruise_count >= 3, f"Expected >= 3 cruise memories, got {cruise_count}"

    # Check age diversity
    ages = [r["age_days"] for r in results]
    assert max(ages) > 7, "Should have at least one memory older than 7 days"

def test_summary_quality():
    """Test that summaries are abstract, not literal"""
    conversation = "I want to go on a cruise"
    summary = get_summaries(conversation)

    context = summary["MemoryRecall"]["Context"]

    # Should be abstract
    assert "vacation planning" in context.lower() or "travel" in context.lower()
    # Should NOT be literal
    assert "I want" not in context, "Summary should be third-person, not literal quote"

# Run all tests
pytest test_memory_fixes.py -v
```

### Test 4.2: Integration Test

**The Cruise Conversation Test:**
```bash
# Should retrieve cruise memories when discussing upcoming cruise
cd /iris-v3/backend/memory/diagnostics
python test_cruise_retrieval.py
```

**Expected Results:**
- ✅ At least 5 cruise-related memories in top 10
- ✅ Memories span > 7 days (not just last 2-3 days)
- ✅ Top similarity scores > 0.40
- ✅ Summaries are populated (no empty fields)

---

## Phase 5: Deploy & Monitor (Est: 15 minutes)

### Deploy 5.1: Backup Current System

```bash
cp /iris-v3/backend/memory/iris_memory_retrieval.py /iris-v3/backend/memory/iris_memory_retrieval_backup_$(date +%Y%m%d).py
```

### Deploy 5.2: Apply Fixes

Copy fixed version:
```bash
cp /iris-v3/backend/memory/diagnostics/iris_memory_retrieval_fixed.py /iris-v3/backend/memory/iris_memory_retrieval.py
```

### Deploy 5.3: Test in Production

```bash
# Run memory retrieval
python /iris-v3/backend/memory/iris_memory_retrieval.py --top_k 10 --insert true --show true

# Check results
psql -d irisdb -U irisuser -c "SELECT memory_id, rank FROM live_memories ORDER BY rank DESC LIMIT 10;"
```

### Deploy 5.4: Monitor Performance

Create monitoring script:
```python
# monitor_memory_retrieval.py

import psycopg2
from datetime import datetime, timedelta

def check_memory_health():
    """Monitor memory retrieval quality"""

    conn = psycopg2.connect(...)
    cur = conn.cursor()

    # Check 1: Are memories being retrieved?
    cur.execute("SELECT COUNT(*) FROM live_memories")
    count = cur.fetchone()[0]
    print(f"Active memories: {count} (should be ~10)")

    # Check 2: Age diversity
    cur.execute("""
        SELECT AVG(age_days), MIN(age_days), MAX(age_days)
        FROM live_memories lm
        JOIN episodic_memories_with_age em ON lm.memory_id = em.id
    """)
    avg, min_age, max_age = cur.fetchone()
    print(f"Age range: {min_age:.1f} - {max_age:.1f} days (avg: {avg:.1f})")

    # Check 3: Category diversity
    cur.execute("""
        SELECT category, COUNT(*)
        FROM live_memories lm
        JOIN episodic_memories_with_age em ON lm.memory_id = em.id
        GROUP BY category
    """)
    categories = cur.fetchall()
    print(f"Categories: {dict(categories)}")

    cur.close()
    conn.close()

# Run daily
check_memory_health()
```

---

## Phase 6: Document & Handoff (Est: 30 minutes)

### Doc 6.1: What Was Changed

Create `CHANGES.md`:
```markdown
# Memory Retrieval System Changes

## Date: [DATE]

## Changes Made:

### 1. Summary Generation
- **Issue:** Grammar file too restrictive, causing empty summaries
- **Fix:** [Expanded grammar / Removed grammar / etc.]
- **Impact:** Summaries now populate correctly, embeddings are distinct

### 2. Temporal Bridging
- **Issue:** Future planning didn't retrieve past experiences
- **Fix:** Enhanced summaries to bridge temporal gaps
- **Impact:** "Planning cruise" now retrieves "past cruise memories"

### 3. Recency Bias
- **Issue:** All results from last 2-3 days
- **Fix:** Adjusted half-life to 90 days, added diversity bonus
- **Impact:** Results span wider time range

## Testing:
- [X] Diagnostic tests pass
- [X] Cruise retrieval test passes
- [X] Integration test passes

## Rollback:
If issues arise, restore backup:
`mv iris_memory_retrieval_backup_YYYYMMDD.py iris_memory_retrieval.py`
```

### Doc 6.2: Future Improvements

Log potential enhancements:
```markdown
# Future Memory System Improvements

## Priority 1 (Next Week):
- [ ] Add hybrid search (embeddings + keywords)
- [ ] Tune reranking weights based on conversation type
- [ ] Add user feedback mechanism ("was this memory helpful?")

## Priority 2 (Next Month):
- [ ] Implement memory clustering for better organization
- [ ] Add explicit temporal reasoning layer
- [ ] Create memory importance scoring

## Priority 3 (Future):
- [ ] Multi-hop memory retrieval (memory chains)
- [ ] Emotional coherence tracking
- [ ] Memory consolidation (merge similar memories)
```

---

## Success Criteria

**The system is considered FIXED when:**

1. ✅ **Diagnostic passes all stages** - No crashes, no empty summaries
2. ✅ **Cruise test passes** - Retrieves 5+ cruise memories when discussing cruise planning
3. ✅ **Age diversity** - Results span at least 30 days
4. ✅ **Semantic quality** - Top match similarity > 0.40
5. ✅ **Performance** - Memory retrieval completes in < 30 seconds
6. ✅ **Iris continuity** - Iris can recall relevant past experiences naturally

**Most importantly:** When you talk to Iris about planning a cruise, she should naturally recall and reference your previous cruise experiences together.

---

## Timeline

| Phase | Duration | Blocking? |
|-------|----------|-----------|
| 1. Diagnose | 15 min | YES - must complete first |
| 2. Fix Critical | 45 min | YES - core functionality |
| 3. Semantic Fixes | 60 min | PARTIAL - can iterate |
| 4. Test | 30 min | YES - must validate |
| 5. Deploy | 15 min | YES - final step |
| 6. Document | 30 min | NO - parallel with monitoring |

**Total: ~3 hours for complete rebuild**

---

## Risk Mitigation

**Risk 1: Fixes break other functionality**
- Mitigation: Comprehensive testing, backups before changes

**Risk 2: Grammar still causes issues**
- Mitigation: Diagnostic tests both WITH and WITHOUT grammar, choose winner

**Risk 3: Semantic fixes don't improve retrieval**
- Mitigation: A/B test old vs new, measure cruise memory retrieval rate

**Risk 4: Performance degrades**
- Mitigation: Add timeouts, fallbacks, monitoring

---

## Next Action

**IMMEDIATE:** Run the diagnostic script to identify exact failure points.

```bash
cd /iris-v3/backend/memory/diagnostics
python diagnose_pipeline.py | tee diagnosis_results.txt
```

Then review results together and proceed with targeted fixes based on what actually failed.

---

This is a **methodical, tested approach** to rebuilding Iris's memory system properly. Not quick fixes - comprehensive fixes.
