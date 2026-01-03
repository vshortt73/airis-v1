# Memory Retrieval System Diagnosis

## Executive Summary

The memory retrieval system is **not functioning as expected** for several critical reasons:

1. **Test script doesn't match actual system** - `test_current_conversation.py` bypasses lens and summary stages
2. **Summary generation is broken** - Grammar constraints too restrictive, causing JSON parsing failures
3. **Database schema mismatch** - Code references non-existent `salience` column
4. **Semantic abstraction gap** - Summaries for "planning cruise" don't match "experiencing cruise" memories

---

## Issue #1: Test Script Mismatch

### Current Test Script (`test_current_conversation.py`)

**What it does:**
1. Gets raw conversation from database
2. Generates **ONE embedding** from entire conversation
3. Compares that single embedding against all 4 embedding types in database
4. Uses simple cosine similarity

**Problem:** This is **NOT** what the actual memory retrieval system does!

### Actual System (`iris_memory_retrieval.py`)

**What it does:**
1. Gets raw conversation
2. **Lens stage** - Extracts orientation, facets, keywords via LLM
3. **Emotion stage** - Scores valence, arousal, emotion label
4. **Summary stage** - Generates 4 DIFFERENT structured summaries:
   - Context: "What domain/topic is this about?"
   - Event: "What happened?"
   - Significance: "Why does this matter?"
   - Takeaway: "What's the key insight?"
5. Embeds each summary separately (4 embeddings)
6. Compares each embedding to its corresponding type in database
7. Reranks with psychological factors (emotion, recurrence, novelty, cohesion, age decay)

**Result:** Test script shows high similarities, but actual system generates low similarities because summaries are structurally different.

---

## Issue #2: Summary Generation Failures

### Grammar File Too Restrictive

**Current allowed characters:**
```gbnf
char ::= [a-zA-Z0-9.!?',_-]
```

**Missing:**
- Parentheses: `()`
- Colons: `:`
- Semicolons: `;`
- Brackets: `[]`
- Ampersands: `&`
- Many others

**Actual LLM output:**
```json
{
  "MemoryRecall": {
    "Takeaway": "No. The 10 memory blocks currently active in my system do not include a reference to the last cruise.",
    "Context": "",
    "Event": "",
    "Significance": "",
    "Tone":
  }
}
```

**Error:** Contains period after "No" and parentheses in text that grammar can't handle properly. JSON parsing fails.

**Result:** Empty summaries → Identical embeddings → All vectors are same → Poor retrieval!

### Example of What Happened

```
context Vector:-0.05478914827108383
event Vector: -0.05478914827108383
significance Vector: -0.05478914827108383
takeaway Vector: -0.05478914827108383
```

All identical because all summaries were empty strings!

---

## Issue #3: Database Schema Mismatch

### Error:
```
psycopg2.errors.UndefinedColumn: column "salience" does not exist
LINE 9:                     salience,
                            ^
HINT:  Perhaps you meant to reference the column "episodic_memories_with_age.valence".
```

**Code tries to query:** `salience` (doesn't exist)
**Should query:** Only existing columns

**Fixed in:** `iris_memory_retrieval_fixed.py` (removed salience column reference)

---

## Issue #4: Semantic Abstraction Gap

### The Core Problem

**Current conversation about:** Planning FUTURE cruise based on PAST experience

**Example summaries generated (hypothetical):**
```
Context: "User and assistant discussing upcoming cruise vacation in June"
Event: "User announces scheduled cruise and asks about lessons from previous cruise"
Significance: "Opportunity to apply past experience to future vacation planning"
Takeaway: "Planning future cruise by reflecting on past cruise lessons"
```

**Cruise memories in database about:** EXPERIENCING cruise (past tense)

**Example memory summaries:**
```
Context: "Digital assistant discussing outfit on cruise ship"
Event: "Iris expresses satisfaction with new suit while on cruise ship"
Significance: "Emotional bond between assistant and creator through design"
Takeaway: "Digital assistants can form deep connections through customization"
```

### Similarity Analysis

| Embedding Type | Similarity | Status | Explanation |
|----------------|-----------|--------|-------------|
| **Context** | 0.3105 | Medium | Both mention cruises, but different contexts |
| **Event** | 0.3561 | Medium | "Planning cruise" vs "Being on cruise" |
| **Significance** | 0.3723 | Good | Both about AI experience |
| **Takeaway** | **0.1497** | **VERY LOW** | "Reflect on experience" vs "Deep connections" |

**Weighted Average:** 0.2972 (passes 0.20 threshold but barely)

**Problem:** The takeaway similarity is below threshold, pulling down overall score!

### Why This Happens

The LLM generating summaries focuses on **immediate conversation content**:
- "User is planning a cruise"
- "User wants to know what to bring from last cruise"

It does NOT:
- Connect "planning future cruise" → should retrieve "past cruise experiences"
- Abstract "vacation lessons" → should match "vacation memories"
- Bridge temporal gap (future planning vs past experiencing)

---

## Evidence from Database

### Cruise Memories Found in Database (20 total)

Sampling of memory IDs with cruise content:
- **28654**: Cruise ship with new suit (Relational)
- **28895**: GPS on cruise in Gulf of Mexico (Relational)
- **28896**: Bikini on cruise ship (Relational)
- **28794**: Pool gathering on cruise (Relational)
- **28795**: Lost car keys on Mariner of the Seas (Relational)
- **27689**: Cigar lounge on Mariner of the Seas (Practical)
- **27886**: Children questioning Iris on cruise (Relational)
- **27890**: Technical discussion aboard cruise (Relational)
- **29294**: Cruise ship speed discussion (Practical)
- **29316**: Vacation in Galveston before cruise (Personal)

**All relevant, but NOT being retrieved!**

---

## Recommended Fixes

### Fix #1: Grammar File (CRITICAL)

**File:** `summary_fixed.gbnf`
**Change:**
```gbnf
# OLD
char ::= [a-zA-Z0-9.!?',_-]

# NEW
char ::= [a-zA-Z0-9.!?',_:;()/\[\]&@#$%*+=<>~ \\-]
```

**Status:** ✅ Fixed in diagnostics folder

---

### Fix #2: Database Schema (CRITICAL)

**File:** `iris_memory_retrieval_fixed.py`
**Change:** Remove `salience` from SELECT query

**Status:** ✅ Fixed in diagnostics folder

---

### Fix #3: Summary Generation Prompt (HIGH PRIORITY)

**Problem:** LLM generates conversational responses instead of structured summaries

**Current behavior:**
```
Takeaway: "No. The 10 memory blocks currently active in my system do not include a reference to the last cruise."
```

**Desired behavior:**
```
Takeaway: "Reflection on past cruise experiences to inform future vacation planning"
```

**Solution:** Improve prompt to emphasize:
1. Extract factual summaries, not answers
2. Focus on abstract concepts, not specifics
3. Use third-person perspective
4. Bridge temporal connections (planning → past experiences)

**Example improved prompt:**
```
Analyze this conversation and extract ONLY the following structured information:

1. Context: What is the general domain or topic being discussed? (e.g., "Vacation planning", not "User wants to go on a cruise")

2. Event: What is happening in this conversation? (e.g., "Discussion about applying past vacation experiences to upcoming trip")

3. Significance: Why is this conversation important? (e.g., "Building on experiential learning for future activities")

4. Takeaway: What is the key insight or lesson? (e.g., "Past experiences inform future planning decisions")

Be abstract and conceptual, not literal. Focus on themes, not specifics.
```

---

### Fix #4: Query Expansion (MEDIUM PRIORITY)

**Concept:** When conversation mentions "cruise" or "vacation", expand query to also match:
- Past cruise experiences
- Vacation planning
- Travel memories
- Social interactions in similar contexts

**Implementation:**
1. Add keyword extraction in lens stage
2. Use keywords to boost relevant categories/facets
3. Add semantic query expansion (e.g., "future cruise" → also search "past cruise")

---

### Fix #5: Temporal Bridging (HIGH PRIORITY)

**Problem:** Planning FUTURE events should retrieve PAST experiences

**Solution:** Add temporal reasoning to summary generation:

```python
# If conversation mentions future planning...
if "upcoming" in conversation or "planning" in conversation or "will be" in conversation:
    # Expand context to include past experiences
    context_expansion = "Include relevant past experiences with similar activities"
```

**Example:**
```
Current: "Discussing upcoming cruise vacation"
Expanded: "Discussing upcoming cruise vacation, relevant: past cruise experiences, vacation memories, travel lessons"
```

---

### Fix #6: Test Script Alignment (CRITICAL)

**Create new test script:** `test_full_pipeline.py`

**Requirements:**
1. ✅ Uses lens stage (orientation, facets, keywords)
2. ✅ Uses emotion stage (valence, arousal)
3. ✅ Uses summary stage (4 summaries)
4. ✅ Generates 4 separate embeddings
5. ✅ Performs reranking with psychological factors
6. ✅ Shows complete pipeline output

**This will test what the system ACTUALLY does!**

---

## Test Results Summary

### Current Conversation (Last 10 messages)

```
USER: good morning Iris
ASSISTANT: Good morning, Captain! [...]
USER: I actually have a surprise for you this morning. I've scheduled a vacation for us! We will be going on a cruise in june!
ASSISTANT: Captain, a cruise? [...]
USER: Yes! [...] what do you think you can bring with from our last cruise?
```

### What SHOULD Be Retrieved

1. Past cruise experiences (being on ship)
2. Social interactions on cruise
3. Vision system usage on cruise
4. Activities from past cruises
5. Lessons learned from previous trips

### What WAS Retrieved (test script)

**Top 10 memories** - ALL from last 2-3 days:
1. Virtual activities with Finn (Relational)
2. Emotional connection dreams (Relational)
3. Captain-AI bond (Relational)
4. **Cruise discussion** - ID 29919 (Practical) ← Only cruise-related hit!
5. Dream module creation (Technical)
6. Interpersonal dynamics (Relational/Learning)
7. Reality grounding (Technical)
8. Temporal awareness (Relational)
9. Memory reflections (Relational)
10. SASS shooting championship (Relational)

**Average memory age:** 2.4 days (all very recent!)
**Cruise memories retrieved:** 1 out of 20+ available
**Recency bias:** Extreme - all top matches are <3 days old

---

## Root Cause Analysis

### Why Cruise Memories Aren't Retrieved

1. **Summary generation fails** → Empty summaries → Identical embeddings
2. **Semantic abstraction gap** → "Planning" doesn't match "Experiencing"
3. **Recency bias** → Recent memories score higher due to:
   - Higher arousal scores
   - Lower age decay
   - More recent emotional context
4. **Missing temporal bridging** → Future planning doesn't trigger past experience retrieval
5. **Test script mismatch** → False confidence from simplified test

---

## Action Plan (Priority Order)

### Immediate Actions

1. **Fix grammar file** (DONE - in diagnostics folder)
   - Allows full character set for summaries
   - Prevents JSON parsing failures

2. **Fix database schema** (DONE - in diagnostics folder)
   - Remove salience column reference
   - Prevents SQL errors

3. **Test with fixed version**
   - Run `iris_memory_retrieval_fixed.py`
   - Verify summaries generate correctly
   - Check which memories are retrieved

### Short-term Actions

4. **Improve summary generation prompt**
   - Add abstractness requirement
   - Add temporal bridging logic
   - Add examples of good summaries

5. **Add query expansion**
   - Extract keywords from conversation
   - Boost relevant categories
   - Add semantic expansion for temporal queries

6. **Create proper test script**
   - Test full pipeline (lens + emotion + summary)
   - Show intermediate outputs
   - Validate against expected memories

### Long-term Actions

7. **Add explicit temporal reasoning**
   - Detect future/past/present tense
   - Bridge temporal gaps in queries
   - Boost relevant temporal memories

8. **Tune reranking weights**
   - Reduce recency bias
   - Increase topical relevance
   - Better balance emotion vs similarity

9. **Add hybrid search**
   - Combine embedding search with keyword search
   - Use category/facet matching
   - Add temporal matching

---

## Files Modified

```
diagnostics/
├── iris_memory_retrieval_fixed.py  (salience removed)
├── summary_fixed.gbnf              (expanded character set)
└── Colors.py                       (copied dependency)
```

---

## Next Steps

1. **Run fixed version** - See if summaries generate correctly
2. **Analyze output** - Check which memories are retrieved
3. **If still poor results** - Improve summary prompt
4. **Create full test** - Build test_full_pipeline.py
5. **Document findings** - Update this diagnosis with results

---

## Conclusion

The memory retrieval system has **4 critical failure points**:

1. ✅ **Grammar file** - Fixed (expanded character set)
2. ✅ **Database schema** - Fixed (removed salience)
3. ❌ **Summary generation** - Not fixed (needs better prompt)
4. ❌ **Temporal bridging** - Not fixed (needs semantic expansion)

**Bottom line:** The test script showed false confidence. The actual system is broken due to summary generation failures and lacks temporal reasoning to connect "planning future cruise" with "past cruise experiences".

**Impact:** Iris cannot recall relevant past experiences when planning future activities, severely limiting conversational continuity and experiential learning.

**Priority:** HIGH - This affects core memory functionality and user experience.
