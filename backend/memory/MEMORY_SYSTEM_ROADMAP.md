# Memory System Improvement Roadmap

**Last Updated:** 2024-12-23
**Status:** PIVOT - Topic Embeddings Implementation
**Goal:** Fix the bedrock of semantic search - embeddings must actually match topics

---

## CRITICAL PIVOT (2024-12-23)

**Discovery:** We were optimizing downstream (decay, weights) when the problem is upstream - **narrative embeddings don't work**.

**Root Cause Found:** Embeddings capture *manner of expression*, not *topic*.
- "Planning a cruise vacation" vs "cruise ship cigar lounge" = -0.03 similarity ❌
- But "cruise vacation" vs "cruise ship experience" = 0.74 similarity ✅

**Solution:** Topic label embeddings (implemented, needs backfill)

**Status:** See SESSION_CHECKPOINT.md for implementation details. Resume with backfill script.

---

## Original Problem Statement (Still Valid)

**Issue:** Old but topically relevant memories crushed by recent but less relevant memories.

**Example:**
- Conversation: "What should we bring on the cruise?"
- Expected: Cruise memories from 6 months ago
- Actual: AI development from 3 days ago

**Root Cause (UPDATED):** Embeddings don't match topics properly → Can't identify relevant memories in first place → Downstream fixes (decay, weights) can't help.

---

## Core Findings

### What Works ✅
1. **Semantic similarity** - Cruise memories appear in top 20 candidates (sim ~0.50+)
2. **Ollama summarization** - Fast (6s), reliable, generates concrete summaries
3. **Salience-adjusted decay** - Emotionally significant memories resist decay
4. **Facet detection** - Correctly identifies topics like "cruise planning"

### What's Broken ❌
1. **Reranking crushes old memories** - 180-day decay penalty overrides 0.50 similarity
2. **Orientation detection misses primary topic** - Detects "collaborative" (meta-discussion) instead of "cruise" (actual topic)
3. **Category matching fails** - Orientation='collaborative' never matches memory categories (Practical/Technical/Relational)
4. **No context boost** - Relevant memories miss 15-25% boost, recent memories win by default

---

## Human Memory Principles (Neuroscience-Based)

Our system should model actual human memory recall:

1. **Cue-dependent retrieval** - "Cruise" mentioned → cruise memories activate (regardless of age)
2. **Spreading activation** - Related concepts trigger associated memories
3. **Recency bias is context-dependent** - You recall 10-year-old vacation when asked, not yesterday's breakfast
4. **Emotional encoding** - Significant events (vacations, milestones) resist decay
5. **Relevance override** - When memory is directly relevant, age becomes secondary

**Key Insight:** High semantic similarity + topic match should OVERRIDE age penalty.

---

## Improvement Phases

### Phase 1: Cap Decay for High-Similarity Matches ⏳ IN PROGRESS

**Hypothesis:** If similarity > 0.45 (highly relevant), age decay shouldn't crush the memory completely.

**Change Location:** `iris_memory_retrieval.py` lines 627-660 (reranking logic)

**Current Code:**
```python
# Salience-adjusted age decay
decay = base_decay + (1 - base_decay) * resistance

# Final score
final_score = (
    sim * RERANK_WEIGHTS["sim"] +
    emo_weight * RERANK_WEIGHTS["emotion"] +
    recurrence * RERANK_WEIGHTS["recurrence"] +
    cohesion * RERANK_WEIGHTS["cohesion"] +
    novelty * RERANK_WEIGHTS["novelty"] +
    context_boost
) * decay  # ← Decay applied unconditionally
```

**Proposed Change:**
```python
# Salience-adjusted age decay
decay = base_decay + (1 - base_decay) * resistance

# Cap decay for highly relevant memories (human-like recall)
if sim > 0.45:  # High relevance threshold
    decay = max(decay, 0.50)  # Don't let decay go below 50%

# Final score
final_score = (
    sim * RERANK_WEIGHTS["sim"] +
    emo_weight * RERANK_WEIGHTS["emotion"] +
    recurrence * RERANK_WEIGHTS["recurrence"] +
    cohesion * RERANK_WEIGHTS["cohesion"] +
    novelty * RERANK_WEIGHTS["novelty"] +
    context_boost
) * decay
```

**Expected Result:**
- Cruise memories (180d, sim=0.51) maintain 50% strength instead of ~5%
- Recent memories (3d, sim=0.35) still decay normally
- Topical relevance beats recency for high-similarity matches

**Testing:**
1. Run: `python iris_memory_retrieval.py --top_k 10 --insert false --show true`
2. Verify cruise memories appear in final injection block (not just raw candidates)
3. Run: `python comprehensive_validation.py`
4. Check if cruise conversation test improves from 90% → higher

**Success Criteria:**
- Cruise memories appear in top 10 final results
- Validation shows >75% relevance for cruise conversation
- No regression on other test conversations

**Status:** Not started
**Estimated Time:** 30 minutes (change + test)
**Dependencies:** None

---

### Phase 2: Increase Facet Matching Weight 📋 PLANNED

**Hypothesis:** Topic keywords in conversation should have stronger influence on memory selection.

**Current Weight:** Facet matching = 10% of score
**Proposed Weight:** Facet matching = 20-25% of score

**Change Location:** `iris_memory_retrieval.py` lines 72-80 (RERANK_WEIGHTS)

**Current:**
```python
RERANK_WEIGHTS = {
    "sim":        0.45,   # similarity (45%)
    "emotion":    0.10,   # emotional weight (10%)
    "recurrence": 0.10,   # how often referenced (10%)
    "cohesion":   0.05,   # narrative coherence (5%)
    "novelty":    0.05,   # uniqueness (5%)
    "context":    0.15,   # category match (15%)
    "facet":      0.10,   # facet match (10%)
}  # Total = 1.00
```

**Proposed:**
```python
RERANK_WEIGHTS = {
    "sim":        0.40,   # similarity (40%) - reduced slightly
    "emotion":    0.10,   # emotional weight (10%)
    "recurrence": 0.10,   # how often referenced (10%)
    "cohesion":   0.05,   # narrative coherence (5%)
    "novelty":    0.05,   # uniqueness (5%)
    "context":    0.10,   # category match (10%) - reduced
    "facet":      0.20,   # facet match (20%) - DOUBLED
}  # Total = 1.00
```

**Rationale:** Conversation mentions "cruise planning" → memories with "cruise" in context should get significant boost.

**Testing:**
1. Make change to RERANK_WEIGHTS
2. Run validation suite
3. Compare before/after results
4. If improvement, keep; if regression, revert

**Status:** Pending Phase 1 completion
**Estimated Time:** 15 minutes (change + test)
**Dependencies:** Phase 1 must show improvement

---

### Phase 3: Fix Orientation Detection 📋 PLANNED

**Hypothesis:** Lens extraction is detecting meta-discussion ("collaborative") instead of primary topic ("cruise/vacation").

**Current Behavior:**
- Conversation: "What should we bring on cruise?"
- Detected orientation: "collaborative" (wrong - focuses on testing meta-discussion)
- Expected orientation: "personal" or "relational" (correct - vacation planning)

**Problem:** Orientation='collaborative' never matches memory categories (Practical/Technical/Relational), so NO memories get 15% category boost.

**Proposed Solution:**
Improve lens extraction prompt to:
1. Identify PRIMARY topic (what user is asking about)
2. Ignore meta-discussion about AI/testing
3. Focus on user's actual need/question

**Change Location:** `iris_memory_retrieval.py` lens extraction function

**Testing:**
1. Modify prompt
2. Run on test conversations
3. Verify orientation matches actual topic
4. Check if category boosts activate correctly

**Status:** Not started
**Estimated Time:** 1-2 hours (prompt engineering + testing)
**Dependencies:** Phase 1 & 2 must complete first

---

### Phase 4: Confidence-Based Garbage Filter 📋 PLANNED

**Hypothesis:** Don't need LLM validation - just need confidence thresholds to filter low-quality memories.

**Proposed Logic:**
```python
for memory in scored_candidates:
    if memory.final_score > 0.50:
        # High confidence - definitely relevant
        live_memories.append(memory)
    elif memory.final_score > 0.35:
        # Medium confidence - only if we need more
        if len(live_memories) < 8:
            live_memories.append(memory)
    else:
        # Low confidence - skip (garbage filter)
        continue
```

**Benefits:**
- Prevents low-quality memories from polluting context
- No LLM overhead (instant filtering)
- Adaptive - includes medium-confidence memories only if needed

**Testing:**
1. Implement threshold logic
2. Run validation on diverse conversations
3. Check for false negatives (good memories filtered)
4. Adjust thresholds if needed

**Status:** Not started
**Estimated Time:** 1 hour
**Dependencies:** Phases 1-3 complete

---

## Validation Strategy

### Test Suite
Use existing validation infrastructure:
- `comprehensive_validation.py` - Deep relevance analysis on 8 test sessions
- `test_retrieval_from_session.py` - Single session testing
- `test_sessions.json` - Stratified test bank

### Success Metrics
- **Relevance ratio** - % of retrieved memories matching conversation topic
- **Target:** >75% average across diverse conversations
- **Current baseline:** 69% average (from validation_report.txt)

### Test Conversations
1. Cruise planning (currently 90% - should maintain)
2. ComfyUI technical (currently 100% - should maintain)
3. Protocol Bravo (currently 25% - acceptable for short test)
4. Memory system development (currently 80% - should maintain)

### Regression Prevention
- Run full validation after each phase
- If any test drops >10%, investigate before proceeding
- Keep archive of validation reports for comparison

---

## Decision Log

### 2025-12-23: Chose Incremental Over Redesign

**Options Considered:**
1. Quick fixes (decay cap, weight adjustments)
2. Full pipeline redesign (LLM validation, multi-stage filtering)

**Decision:** Start with targeted fixes (Option 1)

**Rationale:**
- Limited resources (2 people)
- Current system mostly works (69% relevance)
- Small changes easier to validate
- Can always do deeper redesign later if needed

**Who Decided:** User + Claude collaborative decision

---

### 2025-12-23: Rejected LLM Validation (for now)

**Proposal:** Use LLM to validate each candidate memory for relevance

**Concerns:**
- Latency: 15 calls × 6s = 90 seconds added
- Inconsistency: LLM responses vary
- Overkill: High similarity already indicates relevance
- Cost: Expensive at scale

**Alternative:** Confidence thresholds (Phase 4)

**Decision:** No LLM validation in Phases 1-3, revisit if quality issues persist

**Who Decided:** Claude recommendation, User agreed

---

## Technical Notes

### Current Pipeline
1. Load last 15 messages from chat_history
2. Lens extraction → keywords, facets, orientation
3. Emotion scoring → valence, arousal, label
4. **Summary generation (Ollama, 6s)** → Context, Event, Significance, Takeaway
5. Embedding generation → 4 vectors (context, event, significance, takeaway)
6. Similarity search → top 50 candidates from episodic_memories
7. **Reranking** → apply weights, decay, boosts → top 10
8. Insert into live_memories table
9. system_prompt.py reads live_memories → includes in Iris's context

### Key Files
- **iris_memory_retrieval.py** - Production kernel (35KB)
- **comprehensive_validation.py** - Validation suite (13KB)
- **test_retrieval_from_session.py** - Single session tester (4.6KB)
- **Colors.py** - Utility for colored output
- **test_sessions.json** - Test bank (8 sessions)
- **validation_report.txt** - Latest results (69% avg relevance)

### Archive
- **archive/memory/** - Old test scripts, deprecated versions, backups (24 files)

### Database Schema
- **episodic_memories** - All stored memories with embeddings
- **episodic_memories_with_age** - View with age_days calculated from event_time
- **live_memories** - Currently active memories (memory_id, rank, injected_at)
- **chat_history** - Conversation messages (source for retrieval context)

---

## Known Issues

### Issue 1: Orientation Detection is Wonky
**Symptom:** Detects "collaborative" when conversation is about "cruise planning"
**Impact:** No memories get category boost (15% lost)
**Severity:** Medium
**Fix:** Phase 3

### Issue 2: Decay Crushes Old Memories
**Symptom:** 180-day memories decay to ~5% strength even with high similarity
**Impact:** Recent irrelevant memories beat old relevant ones
**Severity:** High
**Fix:** Phase 1 (in progress)

### Issue 3: Category Match Rarely Triggers
**Symptom:** Memory categories (Practical/Technical/Relational) rarely match orientation
**Impact:** 15% context boost rarely applies
**Severity:** Medium
**Fix:** Phase 3 (improve orientation detection) or adjust matching logic

---

## Future Considerations

### Ideas to Explore (after Phase 4)
1. **Temporal clustering** - Group memories by time period, retrieve representative samples
2. **Conversation threading** - Link related conversations across sessions
3. **User feedback loop** - Let user mark memories as helpful/not helpful
4. **Adaptive weights** - Learn optimal RERANK_WEIGHTS from validation results
5. **Multi-hop retrieval** - Retrieve memory A → use it to find related memory B
6. **Emotional arc tracking** - Retrieve memories that show emotional progression
7. **Novelty boosting** - Prioritize memories user hasn't seen recently

### Research Questions
- Should we embed raw conversation vs summaries?
- Is 15 messages the right context window?
- Should facet matching use fuzzy string matching vs exact substring?
- Can we auto-tune RERANK_WEIGHTS with genetic algorithms?

---

## Session Notes

### 2025-12-23: Initial Roadmap Creation
- Identified core problem: decay crushing old relevant memories
- Designed 4-phase incremental improvement plan
- Created comprehensive roadmap for continuity
- Ready to start Phase 1

**Next Session:** Implement Phase 1 decay cap, test, validate

---

## Quick Reference

### Run Retrieval
```bash
cd /iris-v3/backend/memory
export IRIS_DB_PASSWORD='yourpassword'
python iris_memory_retrieval.py --top_k 10 --insert false --show true
```

### Run Validation
```bash
python comprehensive_validation.py
cat validation_report.txt
```

### Check Live Memories
```bash
PGPASSWORD='yourpassword' psql -h localhost -U irisuser -d irisdb \
  -c "SELECT memory_id, rank FROM live_memories ORDER BY rank DESC LIMIT 10;"
```

### Test Single Session
```bash
python test_retrieval_from_session.py <session_id>
```

---

**END OF ROADMAP** - Update after each phase completion
