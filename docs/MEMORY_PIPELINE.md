# Memory Generation Pipeline

**Last Updated:** 2026-02-07

How conversations become long-term memories. Three independent pipelines exist: nightly episodic memory creation, nightly semantic consolidation, and real-time tool-based short-term facts. Retrieval runs inline every turn.

---

## Pipeline Overview

```
                    NIGHTLY EPISODIC PIPELINE (3:00 AM cron)
                    ════════════════════════════════════════

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


              NIGHTLY SEMANTIC PIPELINE (3:30 AM cron)
              ════════════════════════════════════════

episodic_memories (unclustered)
    │
    ▼
┌────────────────────────────────────────────────────────┐
│ 1. CLUSTER BY SIMILARITY   semantic_consolidation.py   │
│    Cosine similarity on takeaway embeddings            │
│    Threshold: SEMANTIC_CLUSTER_THRESHOLD (0.72)        │
└──────────────────────────┬─────────────────────────────┘
                           │ (clusters ≥ min_size only)
                           ▼
┌────────────────────────────────────────────────────────┐
│ 2. LLM CONSOLIDATION                                  │
│    Distill N episodes → 1 semantic insight             │
│    "Victor prefers X when Y"                           │
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────┐
│ 3. DEDUP + STORE                                       │
│    If similar to existing (>0.85): reinforce           │
│    Else: insert new semantic_memories row              │
│    Mark source episodes as clustered = TRUE            │
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


              RETRIEVAL V2 (inline, every turn, ~200ms)
              ═════════════════════════════════════════

User message arrives
    │
    ▼
┌────────────────────────────────────────────────────────┐
│ 1. Embed last N user messages (all-mpnet-base-v2)      │
│ 2. Read current emotional state (11 dims)              │
│ 3. GREATEST-match SQL across 6 embedding facets        │
│ 4. 3-factor scoring: topic × emotion × recency         │
│ 5. TRUNCATE + INSERT into live_memories table          │
└────────────────────────────────────────────────────────┘
    │
    ▼
build_per_turn_context() reads live_memories
    → injected in per-turn tail (outside snapshot)
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

## Memory Retrieval (Into Prompt)

Retrieval is split between the static snapshot and the per-turn tail:

### Static Snapshot (stable across turns)

**Short-Term Facts:**

| What | Where |
|------|-------|
| Loader | `core/system_prompt.py:get_short_term_facts():657` |
| Source | `short_term_facts` table |
| Filter | Active, created <90d OR referenced <30d |
| Limit | 15 facts |
| Spoiler | `memory insert/archive` tool calls |

**Semantic Memories:**

| What | Where |
|------|-------|
| Loader | `database/memory_loader_experimental.py:get_semantic_memories()` |
| Source | `semantic_memories` table |
| Limit | `SEMANTIC_MEMORY_LIMIT` (default 10) |
| Spoiler | None needed (only changes nightly when Iris is idle) |

### Per-Turn Tail (rebuilt every turn)

**Episodic Memories (Retrieval V2):**

| What | Where |
|------|-------|
| Retrieval | `backend/memory/memory_retrieval_v2.py` (inline, ~200ms) |
| Loader | `database/memory_loader_experimental.py:get_memories()` |
| Source | `live_memories` table (populated by retrieval v2 each turn) |
| Scoring | 3-factor: topic similarity (0.60) × emotional resonance (0.25) × recency (0.15) |
| Limit | `RETRIEVAL_TOP_K` (default 10) |
| Format | XML with memory ID, timestamp, voice, category, all summaries |

**Fast Reactive Memory:**

| What | Where |
|------|-------|
| Loader | `database/fast_reactive_memory.py:FastReactiveMemory.get_context()` |
| Source | `episodic_memories` with embedding similarity |
| Trigger | Current user message embedded and compared |

---

## Semantic Consolidation Pipeline

`backend/memory/new/semantic_consolidation.py`

Runs nightly at 3:30 AM via `scripts/nightly_semantic_consolidation.sh`.

| Step | Function | What It Does |
|------|----------|-------------|
| Config | `get_pipeline_config()` | Read 8 config keys from `system_config` (category `semantic`) |
| Fetch | `fetch_unclustered_episodes()` | Episodes above HWM where `clustered = FALSE` |
| Cluster | Cosine similarity on `emb_takeaway` | Group by similarity ≥ `SEMANTIC_CLUSTER_THRESHOLD` (0.72) |
| Consolidate | LLM call (JSON mode) | Distill cluster → insight + category + confidence |
| Dedup | Embedding similarity check | If ≥ `SEMANTIC_DEDUP_THRESHOLD` (0.85): reinforce existing |
| Store | `insert_semantic_memory()` | New row in `semantic_memories` with 768-dim embedding |
| Mark | `mark_episodes_clustered()` | SET `clustered = TRUE` on source episodes |
| HWM | Update `SEMANTIC_HWM` | Prevent reprocessing on next run |

### semantic_memories Schema

| Column | Type | Purpose |
|--------|------|---------|
| id | serial | Auto |
| insight | text | Distilled knowledge statement |
| category | text | Creative, Relational, Technical, etc. |
| confidence | float | LLM's confidence in the insight |
| embedding | float[768] | For dedup similarity checking |
| source_episode_ids | integer[] | Which episodes contributed |
| reinforcement_count | integer | How many times reinforced |
| created_at | timestamp | First creation |
| last_reinforced_at | timestamp | Last reinforcement |

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
| **Nightly Episodic Pipeline** | |
| `scripts/nightly_memory_creation.sh` | Cron orchestrator (3:00 AM) |
| `backend/memory/new/topic_segmentation.py` | Topic boundary detection |
| `backend/memory/new/memory_evaluator.py` | Worthiness evaluation |
| `backend/memory/new/memory_creation.py` | Summary generation + DB insert |
| `backend/memory/new/psychological_scoring_transformers.py` | Transformer-based scoring |
| `core/embeddings.py` | Embedding generation (all-mpnet-base-v2) |
| **Nightly Semantic Pipeline** | |
| `scripts/nightly_semantic_consolidation.sh` | Cron orchestrator (3:30 AM) |
| `backend/memory/new/semantic_consolidation.py` | Cluster + consolidate + dedup + store |
| `database/sql/create_semantic_memories_table.sql` | Table + clustered column |
| `database/sql/add_semantic_memory_config.sql` | 8 config keys |
| **Retrieval (inline, every turn)** | |
| `backend/memory/memory_retrieval_v2.py` | Inline retrieval v2 (~200ms) |
| `database/memory_loader_experimental.py` | Read live_memories + semantic_memories |
| `database/fast_reactive_memory.py` | Embedding-based context matching |
| **Real-Time Tool** | |
| `mcp_servers/memory/memory_server.py` | Short-term facts tool (insert/retrieve/archive) |
| **Legacy** | |
| `database/memory_loader.py` | Original episodic memory retrieval (replaced by experimental) |
| `backend/memory/iris_memory_retrieval.py` | Original LLM-based retrieval (replaced by v2) |
| `scripts/README_NIGHTLY_MEMORY.md` | Additional nightly pipeline docs |
