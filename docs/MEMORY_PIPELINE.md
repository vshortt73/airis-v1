# Memory Generation Pipeline

**Last Updated:** 2026-01-29

How conversations become long-term memories. Two independent paths exist: the nightly automated pipeline and real-time tool-based short-term facts.

---

## Pipeline Overview

```
                    NIGHTLY PIPELINE (3:00 AM cron)
                    ════════════════════════════════

chat_history (DB)
    │
    ▼
┌────────────────────────────────────────────────────────┐
│ 1. TOPIC SEGMENTATION       topic_segmentation.py      │
│    LLM detects topic boundaries in each session        │
│    Assigns topic_id + conv_title to chat_history rows  │
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────┐
│ 2. MEMORY EVALUATION        memory_evaluator.py        │
│    Per topic: psychological scoring + LLM worthiness   │
│    Decision: WORTHY or NOT_WORTHY                      │
└──────────────────────────┬─────────────────────────────┘
                           │ (worthy topics only)
                           ▼
┌────────────────────────────────────────────────────────┐
│ 3. SUMMARY GENERATION       memory_creation.py         │
│    LLM generates 6 structured summaries (JSON mode)    │
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────┐
│ 4. EMBEDDING GENERATION     core/embeddings.py         │
│    6 embeddings (768-dim) via all-mpnet-base-v2        │
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────┐
│ 5. DATABASE INSERT          episodic_memories table    │
│    Mark chat_history as memory_processed_at = NOW()    │
└────────────────────────────────────────────────────────┘


                    REAL-TIME PATH (tool call)
                    ═════════════════════════

Iris calls memory(action="insert", fact="...")
    │
    ▼
┌────────────────────────────────────────────────────────┐
│ INSERT INTO short_term_facts                           │
│ (immediate, no evaluation or embedding)                │
└────────────────────────────────────────────────────────┘


                    RETRIEVAL (every turn)
                    ══════════════════════

build_system_message()
    ├── get_memories()          → episodic_memories (long-term)
    ├── get_short_term_facts()  → short_term_facts (real-time)
    └── FastReactiveMemory      → embedding-based context match
```

---

## Nightly Pipeline Detail

### Orchestration

| What | Where |
|------|-------|
| Cron trigger | `0 3 * * *` runs `scripts/nightly_memory_creation.sh` |
| Pre-flight | DB password, venv, sudo, lock file checks |
| Ollama startup | Ensure llama.cpp running on port 11434 |
| System messages | Inserts start/completion messages into chat_history |
| Log cleanup | Deletes logs older than 30 days |

### Stage 1: Topic Segmentation

`backend/memory/new/topic_segmentation.py`

```
Unsessioned messages from chat_history
    │
    ▼
detect_boundaries_with_llm()          :71
    Chunk 40 messages at a time
    LLM identifies topic change points
    │
    ▼
refine_boundaries_with_context()      :206
    Verify each boundary (4 msgs before/after)
    LLM confirms: "Is this a real topic change?"
    │
    ▼
validate_topic_coherence()            :331
    Flag tiny groups (<2 msgs) and huge groups (>30 msgs)
    │
    ▼
assign_topic_ids()                    :729
generate_topic_titles()               :379
    LLM creates human-readable title per topic
    │
    ▼
update_topic_ids_and_titles()         :824
    UPDATE chat_history SET topic_id, conv_title
```

### Stage 2: Memory Evaluation

`backend/memory/new/memory_evaluator.py`

For each (session_id, topic_id) pair:

```
score_topic()                         psychological_scoring_transformers.py
    Transformer models calculate:
    ├── arousal      (0-1, emotional intensity)
    ├── valence      (-1 to +1, positive/negative)
    ├── novelty      (0-1, uniqueness)
    ├── coherence    (0-1, semantic flow)
    ├── cohesion     (0-1, narrative connectedness)
    ├── recurrence   (0-1, similarity to existing memories)
    └── embedding    (768-dim vector)
        │
        ▼
evaluate_memory_worthiness()          :68
    LLM judges: WORTHY or NOT_WORTHY
    Returns: category, voice, emotion, confidence, reasoning
    Temperature: 0.2 (analytical)
    Transcript truncated to 3000 chars (first 15 + last 15 pairs)
```

**Categories:** Practical, Personal, Technical, Creative, Relational, Learning, Other
**Voices:** neutral, practical, emotional, technical, creative
**Emotions:** joy, sadness, fear, anger, surprise, love, curiosity, frustration, satisfaction, excitement, neutral

### Stage 3: Summary Generation

`backend/memory/new/memory_creation.py:generate_summaries():80`

LLM generates 6 structured fields in JSON mode:

| Field | Content |
|-------|---------|
| `summary_context` | 3-4 sentences of situational context |
| `summary_event` | 3-4 sentences of what happened |
| `summary_significance` | 3-4 sentences of why it matters |
| `summary_tone` | 1-2 sentences of emotional tone |
| `takeaway` | 3-4 sentences of key insight |
| `key_details` | 3-4 sentences of specific memorable details |

Transcript truncated to 4000 chars. Category-specific hints guide detail extraction.

### Stage 4: Embedding Generation

`core/embeddings.py:generate_embedding():87`

| Embedding | Source Text |
|-----------|-------------|
| `emb_minilm` | From psychological scoring (full transcript) |
| `emb_summary_context` | summary_context field |
| `emb_summary_event` | summary_event field |
| `emb_summary_significance` | summary_significance field |
| `emb_takeaway` | takeaway field |
| `emb_key_details` | key_details field |

Model: `all-mpnet-base-v2` (sentence-transformers), 768 dimensions, CUDA with CPU fallback.

### Stage 5: Database Insert

`backend/memory/new/memory_creation.py:create_memory_from_topic():401`

INSERT into `episodic_memories` with all fields + RETURNING id.
Then: UPDATE `chat_history` SET `memory_processed_at = NOW()` to prevent reprocessing.

---

## Real-Time Tool Path

`mcp_servers/memory/memory_server.py`

| Action | Function | What It Does |
|--------|----------|-------------|
| `insert` | `_handle_insert():36` | INSERT into `short_term_facts` (fact_text, category) |
| `retrieve` | `_handle_retrieve():69` | SELECT active facts (created <90d OR referenced <30d) |
| `archive` | `_handle_archive():125` | SET status='archived' for old unreferenced facts |

Short-term facts have no evaluation, no embeddings, no summarization. They are immediate storage for user preferences, names, and settings.

---

## Memory Retrieval (Into System Prompt)

### Episodic Memories (Long-Term)

| What | Where |
|------|-------|
| Loader | `database/memory_loader.py:get_memories():34` |
| Source | `live_memories` view joined with `episodic_memories_with_age` |
| Context level | Skipped for GREETING/TASK, included CONV+ |
| Limit | CONVERSATIONAL: 4, DEEP/FULL: 10 |
| Format | XML with memory ID, timestamp, voice, category, all summaries |

### Short-Term Facts

| What | Where |
|------|-------|
| Loader | `core/system_prompt.py:get_short_term_facts():539` |
| Source | `short_term_facts` table |
| Filter | Active, created <90d OR referenced <30d |
| Limit | 15 facts |
| Format | Numbered list with fact ID |

### Fast Reactive Memory

| What | Where |
|------|-------|
| Loader | `database/fast_reactive_memory.py:FastReactiveMemory.get_context()` |
| Source | `episodic_memories` with embedding similarity |
| Trigger | Current user message embedded and compared |
| Context level | CONVERSATIONAL, DEEP, FULL only |
| Cache | Per-turn (same message = cached result) |

---

## Database Schema

### episodic_memories

| Column | Type | Source |
|--------|------|--------|
| id | serial | Auto |
| session_id | uuid | From chat session |
| segment_id | integer | First message ID in topic |
| topic_id | integer | From topic segmentation |
| event_time | timestamp | First message timestamp |
| transcript | text | Full conversation text |
| summary_context | text | LLM summary |
| summary_event | text | LLM summary |
| summary_significance | text | LLM summary |
| summary_tone | text | LLM summary |
| takeaway | text | LLM summary |
| key_details | text | LLM summary |
| emotion_label | text | Primary emotion |
| emotion_top3 | jsonb | Top 3 with scores |
| valence, arousal, recurrence, novelty, cohesion | float | Psychological scoring |
| voice, category | text | LLM evaluation |
| emb_minilm through emb_key_details | float[768] | Sentence transformers |
| immutable | boolean | Whether memory can be edited |
| memory_processed_at | timestamp | Prevents reprocessing |

### short_term_facts

| Column | Type | Purpose |
|--------|------|---------|
| fact_id | serial | Auto |
| fact_text | text | The fact content |
| category | text | Optional category |
| status | text | 'active' or 'archived' |
| created_date | timestamp | When created |
| last_referenced_date | timestamp | Last access |
| reference_count | integer | Access count |

---

## Key Files

| File | Role |
|------|------|
| `scripts/nightly_memory_creation.sh` | Cron orchestrator |
| `backend/memory/new/topic_segmentation.py` | Topic boundary detection |
| `backend/memory/new/memory_evaluator.py` | Worthiness evaluation |
| `backend/memory/new/memory_creation.py` | Summary generation + DB insert |
| `backend/memory/new/psychological_scoring_transformers.py` | Transformer-based scoring |
| `core/embeddings.py` | Embedding generation (all-mpnet-base-v2) |
| `mcp_servers/memory/memory_server.py` | Real-time memory tool |
| `database/memory_loader.py` | Episodic memory retrieval |
| `database/fast_reactive_memory.py` | Embedding-based context matching |
| `scripts/README_NIGHTLY_MEMORY.md` | Additional nightly pipeline docs |
