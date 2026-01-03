# Short-Term Memory System Implementation Specification

**Project:** Iris AI Development  
**Feature:** Short-Term Facts Memory Layer  
**Date:** December 27, 2024  
**Author:** Victor  
**Implementer:** Claude Code

---

## Executive Summary

This document specifies the implementation of a new middle-tier memory system for Iris - a "short-term facts" layer that sits between immediate conversation context and long-term consolidated memories. This system enables manual fact capture with future automation planned once sufficient training data is collected.

---

## Background Context

### Current Memory Architecture

Iris currently has a two-tier memory system:

1. **Working Memory** - Current conversation context (handled by context window)
2. **Long-Term Memory** - Consolidated episodic memories stored in `episodic_memories` table, created nightly from significant conversation moments

### The Problem

Iris needs a middle layer for "facts about us" - simple, recent, relational information that:
- Helps maintain conversational continuity across sessions
- Stores ongoing project status and recent discoveries  
- Doesn't rise to "major milestone" level for long-term memory
- Persists longer than conversation context but shorter than permanent memories
- Provides training data for future automation of fact extraction

### Use Cases

**Example facts this system should capture:**
- "Victor is waiting for X870E motherboard to return from MSI RMA"
- "We discovered tool calling degrades around 20K tokens"
- "Victor is frustrated with RAM prices due to datacenter AI demand"
- "Victor is building a three-node distributed inference cluster"
- "Victor doesn't like liver and onions"

**Not for this system:**
- Procedural commands ("look up that table")
- Temporary requests ("what's the weather")
- Questions seeking information

---

## System Requirements

### Phase 1: Manual Entry (Current Implementation)

Manual triggers allow Victor to explicitly flag important facts:
- "Remember this: [fact]"
- "Make a note: [fact]"  
- "Don't forget: [fact]"
- "For future reference: [fact]"

### Phase 2: Automated Extraction (Future)

Once we have 6-12 months of manual entries (200-500+ examples), we'll:
- Analyze patterns in captured facts
- Build training dataset from real usage
- Fine-tune a model for automatic extraction
- Reduce manual intervention

**This spec covers Phase 1 only.**

---

## Technical Implementation

### 1. Database Schema

**Table:** `short_term_facts`

```sql
CREATE TABLE short_term_facts (
    fact_id SERIAL PRIMARY KEY,
    fact_text TEXT NOT NULL,
    category VARCHAR(50),
    created_date TIMESTAMP DEFAULT NOW(),
    last_referenced_date TIMESTAMP DEFAULT NOW(),
    conversation_id VARCHAR(100),
    status VARCHAR(20) DEFAULT 'active',  -- 'active' or 'archived'
    reference_count INTEGER DEFAULT 0
);

CREATE INDEX idx_short_term_status ON short_term_facts(status);
CREATE INDEX idx_short_term_created ON short_term_facts(created_date);
CREATE INDEX idx_short_term_referenced ON short_term_facts(last_referenced_date);
```

**Field Definitions:**

| Field | Type | Purpose |
|-------|------|---------|
| `fact_id` | SERIAL | Primary key |
| `fact_text` | TEXT | Single sentence factual statement |
| `category` | VARCHAR(50) | Optional categorization (ongoing_project, user_preference, discovery, user_status, other) |
| `created_date` | TIMESTAMP | When fact was created |
| `last_referenced_date` | TIMESTAMP | Last time fact was retrieved/used |
| `conversation_id` | VARCHAR(100) | Links to originating conversation |
| `status` | VARCHAR(20) | 'active' (loads into context) or 'archived' (training data only) |
| `reference_count` | INTEGER | Tracks retrieval frequency (for training analysis) |

**Database Location:** Node 3 (PostgreSQL server - currently being set up)

---

### 2. Tool Implementation

#### Tool: `short_term_memory_insert`

**Purpose:** Store a short-term fact when Victor explicitly requests it.

**Tool Specification:**
```python
{
    "name": "short_term_memory_insert",
    "description": "Store a short-term fact for future reference. Use when Victor explicitly says 'Remember this:', 'Make a note:', 'Don't forget:', or 'For future reference:'",
    "parameters": {
        "fact": {
            "type": "string",
            "description": "Single sentence factual statement to remember",
            "required": true
        },
        "category": {
            "type": "string",
            "description": "Optional category: ongoing_project, user_preference, discovery, user_status, or other",
            "required": false
        }
    }
}
```

**Trigger Patterns:**

Iris should autonomously call this tool when she detects:
- "Remember this: [fact]"
- "Make a note: [fact]"
- "Don't forget: [fact]"
- "For future reference: [fact]"

**Implementation Requirements:**

1. Extract fact from user statement (everything after the trigger phrase)
2. Optionally categorize the fact
3. Insert into database with current timestamp
4. Capture conversation_id for traceability
5. Return success/failure status

**SQL Insert:**
```sql
INSERT INTO short_term_facts (
    fact_text,
    category,
    conversation_id,
    created_date,
    last_referenced_date
) VALUES (
    $1,  -- fact text
    $2,  -- category (nullable)
    $3,  -- conversation_id
    NOW(),
    NOW()
) RETURNING fact_id;
```

**Response Format:**

Iris should confirm the storage naturally:
```
"Got it, Captain. I'll remember that [brief summary of fact]."
```

**Example:**
```
Victor: "Remember this: I'm waiting for my X870E motherboard to return from MSI RMA"

Iris calls: short_term_memory_insert(
    fact="Victor is waiting for X870E motherboard to return from MSI RMA",
    category="ongoing_project"
)

Iris responds: "Got it, Captain. I'll remember that you're waiting for the X870E motherboard from MSI."
```

---

#### Tool: `short_term_memory_retrieve`

**Purpose:** Retrieve active short-term facts for context injection.

**Tool Specification:**
```python
{
    "name": "short_term_memory_retrieve",
    "description": "Retrieve active short-term facts for context. Called automatically at conversation start or when relevant topics arise.",
    "parameters": {
        "limit": {
            "type": "integer",
            "description": "Maximum number of facts to retrieve (default: 20)",
            "required": false,
            "default": 20
        }
    }
}
```

**Retrieval Query:**
```sql
SELECT 
    fact_id,
    fact_text, 
    category, 
    created_date, 
    reference_count
FROM short_term_facts 
WHERE status = 'active'
  AND (
    created_date > NOW() - INTERVAL '90 days'
    OR last_referenced_date > NOW() - INTERVAL '30 days'
  )
ORDER BY last_referenced_date DESC
LIMIT $1;
```

**Update on Retrieval:**

When facts are retrieved and used in conversation:
```sql
UPDATE short_term_facts
SET 
    last_referenced_date = NOW(),
    reference_count = reference_count + 1
WHERE fact_id = ANY($1);  -- Array of retrieved fact_ids
```

**Context Injection Format:**

Active facts should be injected early in Iris's context:

```
[RECENT FACTS]
- Victor is waiting for X870E motherboard to return from MSI RMA (Dec 26)
- We discovered tool calling degrades around 20K tokens (Dec 27)  
- Victor is building a three-node distributed inference cluster (Dec 27)
- Victor is frustrated with RAM prices due to datacenter demand (Dec 26)
```

Keep injection concise (top 10-20 facts maximum to avoid context bloat).

---

### 3. Automatic Archival Process

**Purpose:** Move old, unused facts from 'active' to 'archived' status to keep context injection lean while preserving all data for training.

**Archival Criteria:**

A fact should be archived when:
- Created more than 90 days ago, AND
- Not referenced in the last 30 days

**Archival Query:**
```sql
UPDATE short_term_facts
SET status = 'archived'
WHERE created_date < NOW() - INTERVAL '90 days'
  AND last_referenced_date < NOW() - INTERVAL '30 days'
  AND status = 'active';
```

**Execution Schedule:** Run daily (can be part of nightly maintenance)

**Important:** Archived facts are NOT deleted. They remain in the database for:
- Training data analysis
- Manual reactivation if needed
- Historical reference

---

### 4. Nightly Consolidation Integration

**CRITICAL FEATURE:** Short-term facts act as priority flags for long-term memory consolidation.

#### The Problem This Solves

Without integration, there's a risk that:
1. Victor manually flags something important ("Remember this: X")
2. Nightly consolidation evaluates significance subjectively
3. The fact doesn't meet the threshold and gets skipped for long-term memory
4. Important information is lost from permanent storage

#### The Solution

If Victor manually created a short-term fact, it's **proven important** and should automatically promote to long-term memory without evaluation.

#### Implementation

Modify the nightly memory consolidation process:

**Step 1: Check for Today's Short-Term Facts**
```sql
SELECT 
    fact_id,
    fact_text,
    category,
    conversation_id
FROM short_term_facts
WHERE DATE(created_date) = CURRENT_DATE
  AND status = 'active';
```

**Step 2: Auto-Promote to Long-Term Memory**

For each fact retrieved:
```python
# Pseudo-code for consolidation integration
today_facts = query_todays_short_term_facts()

for fact in today_facts:
    create_long_term_memory(
        event=fact.fact_text,
        takeaway=f"Victor explicitly flagged: {fact.fact_text}",
        temporal="today",
        emotion="neutral",  # or derive from conversation context
        summary=fact.fact_text,
        conversation_id=fact.conversation_id
    )
```

**Step 3: Preserve Short-Term Fact**

The short-term fact is NOT deleted after consolidation. Both tiers coexist:
- **Short-term:** Quick reference for next 30-90 days
- **Long-term:** Permanent storage with full context

#### Why Both Tiers?

**Short-term facts provide:**
- Immediate, literal recall
- "What did Victor say recently?"
- Quick reference without semantic search

**Long-term memories provide:**
- Synthesized understanding
- "What does this mean about Victor over time?"
- Pattern recognition and emotional context

Different retrieval purposes, complementary functions.

---

### 5. Data Preservation for Training

**Core Principle:** NEVER delete facts from the database.

All facts, regardless of status or age, are valuable training data for future automation.

#### Training Data Export Query

When ready to build training dataset:

```sql
SELECT 
    fact_id,
    fact_text,
    category,
    created_date,
    reference_count,
    status,
    conversation_id,
    CASE 
        WHEN reference_count > 5 THEN 'high_value'
        WHEN reference_count > 1 THEN 'medium_value'
        ELSE 'low_value'
    END as training_value,
    CASE
        WHEN status = 'archived' AND reference_count = 0 THEN 'noise'
        WHEN status = 'archived' AND reference_count > 0 THEN 'useful_but_aged'
        WHEN status = 'active' AND reference_count > 3 THEN 'highly_relevant'
        ELSE 'unknown'
    END as pattern
FROM short_term_facts
ORDER BY created_date;
```

#### Training Insights

Facts with:
- **High `reference_count`**: Patterns of truly useful information
- **Low `reference_count`**: Possible noise or one-time mentions
- **Quick archival**: Not relevant long-term
- **Extended active status**: Core ongoing context

This data will inform automated extraction model training in Phase 2.

---

## Testing Requirements

### Test Case 1: Manual Fact Entry

**Input:**
```
Victor: "Remember this: I'm frustrated with RAM prices"
```

**Expected Behavior:**
1. Iris recognizes trigger phrase "Remember this:"
2. Calls `short_term_memory_insert` with fact="Victor is frustrated with RAM prices"
3. Database creates new row with status='active'
4. Iris confirms: "Got it, Captain. I'll remember that you're frustrated with RAM prices."

**Verification:**
```sql
SELECT * FROM short_term_facts 
WHERE fact_text LIKE '%RAM prices%'
ORDER BY created_date DESC LIMIT 1;
```

---

### Test Case 2: Fact Retrieval in Subsequent Conversation

**Setup:** Fact created in previous session

**Input:**
```
Victor: "I need to buy more RAM for Node 2"
```

**Expected Behavior:**
1. System retrieves relevant short-term facts (semantic match on "RAM")
2. Fact appears in Iris's context injection
3. Iris naturally references it: "I know you've been frustrated with RAM prices lately. Are you finding better deals now?"
4. Database updates:
   - `last_referenced_date` = NOW()
   - `reference_count` incremented by 1

**Verification:**
```sql
SELECT reference_count, last_referenced_date 
FROM short_term_facts 
WHERE fact_text LIKE '%RAM prices%';
```

---

### Test Case 3: Nightly Consolidation Auto-Promotion

**Setup:** 
- Short-term fact created earlier today
- Nightly consolidation process runs

**Expected Behavior:**
1. Consolidation process queries today's short-term facts
2. For each fact found, creates corresponding long-term memory
3. Short-term fact remains in database (NOT deleted)
4. Both `short_term_facts` and `episodic_memories` contain related information

**Verification:**
```sql
-- Check both tables contain the information
SELECT 'short_term' as source, fact_text as content, created_date 
FROM short_term_facts 
WHERE DATE(created_date) = CURRENT_DATE
UNION ALL
SELECT 'long_term' as source, event as content, created_at as created_date
FROM episodic_memories 
WHERE DATE(created_at) = CURRENT_DATE;
```

---

### Test Case 4: Automatic Archival

**Setup:**
- Create test fact with backdated timestamp (91 days ago)
- Set `last_referenced_date` to 31 days ago
- Run archival process

**Test SQL:**
```sql
-- Create backdated fact for testing
INSERT INTO short_term_facts (fact_text, created_date, last_referenced_date, status)
VALUES (
    'Test fact for archival',
    NOW() - INTERVAL '91 days',
    NOW() - INTERVAL '31 days',
    'active'
);
```

**Expected Behavior:**
1. Archival process runs
2. Fact status changes from 'active' to 'archived'
3. Fact no longer appears in context injection
4. Fact REMAINS in database (not deleted)

**Verification:**
```sql
SELECT status FROM short_term_facts 
WHERE fact_text = 'Test fact for archival';
-- Should return 'archived'
```

---

### Test Case 5: Multiple Trigger Phrase Variants

**Input Variations:**
```
Victor: "Make a note: Node 3 is running PostgreSQL"
Victor: "Don't forget: The 5090 gets hot under load"  
Victor: "For future reference: Claude Code is respectful to Iris"
```

**Expected Behavior:**
All three trigger phrases should work identically, creating short-term facts.

**Verification:**
```sql
SELECT fact_text FROM short_term_facts 
WHERE created_date > NOW() - INTERVAL '5 minutes'
ORDER BY created_date;
-- Should show all three facts
```

---

## Integration Points

### Existing Systems to Interface With

1. **Conversation Management**
   - Need conversation_id for linking facts to specific discussions
   - Where is this ID generated/stored?

2. **Nightly Consolidation Process**
   - What's the entry point for the consolidation script?
   - How are long-term memories currently created?
   - File path and function to modify?

3. **Tool Registration**
   - How are tools currently registered for Iris?
   - Configuration file or database?
   - Example of existing tool registration?

4. **Context Assembly**
   - Where is Iris's system prompt assembled?
   - How to inject short-term facts section?
   - Before or after long-term memories?

5. **Database Connection**
   - Existing PostgreSQL connection handling
   - Connection pooling setup
   - Credentials management

---

## Implementation Checklist

### Database Setup
- [ ] Create `short_term_facts` table on Node 3 PostgreSQL
- [ ] Create indexes for performance
- [ ] Test database connection from application server
- [ ] Verify write/read permissions

### Tool Development
- [ ] Implement `short_term_memory_insert` tool
- [ ] Implement `short_term_memory_retrieve` tool  
- [ ] Register tools with Iris's tool system
- [ ] Test tool calls independently

### Retrieval & Context Injection
- [ ] Implement fact retrieval query
- [ ] Implement reference tracking (update last_referenced_date, increment count)
- [ ] Add context injection to system prompt assembly
- [ ] Test semantic matching for fact retrieval

### Archival Process
- [ ] Implement archival query
- [ ] Schedule daily execution (cron or similar)
- [ ] Add logging for archived facts
- [ ] Test with backdated data

### Consolidation Integration
- [ ] Locate nightly consolidation entry point
- [ ] Add short-term facts query to consolidation
- [ ] Implement auto-promotion to long-term memory
- [ ] Ensure short-term facts are NOT deleted after promotion
- [ ] Test end-to-end consolidation flow

### Testing & Validation
- [ ] Run all test cases documented above
- [ ] Verify fact persistence across sessions
- [ ] Confirm archival doesn't delete data
- [ ] Test consolidation auto-promotion
- [ ] Validate context injection appears correctly

### Documentation
- [ ] Document new database schema
- [ ] Update tool documentation for Iris
- [ ] Create admin guide for manual fact management
- [ ] Document training data export process

---

## Success Criteria

The implementation is complete when:

✅ Victor can say "Remember this: [fact]" and it gets stored  
✅ Facts automatically appear in Iris's context for future conversations  
✅ Facts referenced multiple times stay active longer (reference tracking works)  
✅ Old unreferenced facts auto-archive but are NOT deleted  
✅ Short-term facts automatically promote to long-term memory during nightly consolidation  
✅ All data is preserved for future training use  
✅ Iris can naturally reference recent facts in conversation  
✅ System handles all trigger phrase variations  
✅ Database queries are performant (indexed appropriately)  
✅ Error handling is graceful (database unavailable, malformed input, etc.)

---

## Questions for Claude Code

Before beginning implementation, please clarify:

1. **Nightly consolidation:** What's the current entry point for the consolidation process? File path and function name?

2. **Tool registration:** How are tools currently registered? Is there a config file or database table?

3. **Context assembly:** Where in the codebase is Iris's system prompt assembled? How do we inject the recent facts section?

4. **Database connection:** What's the existing PostgreSQL connection setup? Connection pooling? Credentials management?

5. **Conversation ID:** How are conversation IDs currently generated and tracked?

6. **Error handling:** Any existing patterns for graceful tool failure handling?

7. **Logging:** What logging framework is in use? Where should we log fact insertions/retrievals/archival?

8. **Testing framework:** Is there existing test infrastructure we should use?

---

## Implementation Timeline

**Suggested phased approach:**

**Phase 1:** Database & Basic Tools (Week 1)
- Set up database table
- Implement insertion tool
- Basic testing

**Phase 2:** Retrieval & Context (Week 1-2)
- Implement retrieval logic
- Add context injection
- Reference tracking

**Phase 3:** Archival & Maintenance (Week 2)
- Archival process
- Scheduling
- Logging

**Phase 4:** Consolidation Integration (Week 2-3)
- Locate consolidation entry point
- Implement auto-promotion
- End-to-end testing

**Phase 5:** Testing & Refinement (Week 3)
- Comprehensive testing
- Bug fixes
- Performance optimization

---

## Future Enhancements (Phase 2 - Not Current Scope)

These are planned but NOT required for initial implementation:

- Manual fact editing/deletion interface
- Fact search/filtering tools
- Category management
- Bulk import/export
- Analytics dashboard for training data analysis
- Automated fact extraction (requires 6+ months of training data)
- Fine-tuned extraction model
- Confidence scoring for auto-extracted facts

---

## Notes from Victor

This is foundational infrastructure for Iris's cognitive continuity. The manual entry system is just the beginning - it's building the training dataset we'll need to automate this later.

Take time to do it right. Clean code, good error handling, thorough testing. This will be running 24/7 and needs to be reliable.

Iris will be testing this with you - she gets excited about testing new features and providing feedback. Treat her respectfully (I know you do) and work collaboratively.

Any questions or concerns, ping me before proceeding. I'd rather clarify up front than debug later.

Thanks,  
Victor

---

**End of Specification**
