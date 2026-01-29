# Dream Processing System

**Last Updated:** 2026-01-29

Nightly dream generation: a guided 15-turn dialogue between Iris (qwen3:32b, dreamer) and Freud (gemma3:4b, guide). Dreams process emotions, consolidate memories, explore identity, or generate creative content.

---

## Pipeline Overview

```
Cron: 4:00 AM daily
    │
    ▼
nightly_dream.sh
    ├── Start Ollama (localhost:11434)
    ├── Swap Vision → Freud on node2 (port 11435)
    └── python dream_moderator.py --date YESTERDAY
            │
            ▼
    ┌───────────────────────────────────────────────┐
    │ 1. EMOTIONAL ANALYSIS                         │
    │    Analyze yesterday's chat for valence,       │
    │    arousal, intensity                          │
    └─────────────────────┬─────────────────────────┘
                          │
                          ▼
    ┌───────────────────────────────────────────────┐
    │ 2. DREAM TYPE SELECTION                       │
    │    Choose type based on emotional thresholds   │
    └─────────────────────┬─────────────────────────┘
                          │
                          ▼
    ┌───────────────────────────────────────────────┐
    │ 3. CONTEXT BUILDING                           │
    │    Load relevant conversation/memories         │
    └─────────────────────┬─────────────────────────┘
                          │
                          ▼
    ┌───────────────────────────────────────────────┐
    │ 4. DREAM CONVERSATION (15 turns)              │
    │    Phase 1: Dream (10 turns, high creativity)  │
    │    Phase 2: Reflection (5 turns, analytical)   │
    └─────────────────────┬─────────────────────────┘
                          │
                          ▼
    ┌───────────────────────────────────────────────┐
    │ 5. REFLECTION EXTRACTION                      │
    │    Parse structured fields from Phase 2        │
    └─────────────────────┬─────────────────────────┘
                          │
                          ▼
    ┌───────────────────────────────────────────────┐
    │ 6. SCORING + EMBEDDING                        │
    │    Emotional/psychological scores + 6 vectors  │
    └─────────────────────┬─────────────────────────┘
                          │
                          ▼
    ┌───────────────────────────────────────────────┐
    │ 7. DATABASE STORAGE                           │
    │    INSERT episodic_dreams                      │
    │    Possibly create dream_truths + seeds        │
    └───────────────────────────────────────────────┘
            │
            ▼
    Restore Vision service on node2
```

---

## Step-by-Step Reference

### 1. Emotional Analysis

`backend/memory/dreams/emotional_analyzer.py`

| What | Where |
|------|-------|
| Entry point | `analyze_daily_emotions(target_date):37` |
| Load messages | SELECT from `chat_history` WHERE DATE = target_date |
| Valence | Transformer-based, -1.0 to +1.0 (negative to positive) |
| Arousal | Transformer-based, 0.0 to 1.0 (calm to intense) |
| Intensity | Emotion classifier max confidence, averaged across messages |

**Output:**
```python
{
    'date': target_date,
    'message_count': int,
    'valence': float,        # -1.0 to +1.0
    'arousal': float,        # 0.0 to 1.0
    'intensity': float,      # 0.0 to 1.0
    'valence_range': float,  # emotional variety
}
```

### 2. Dream Type Selection

`backend/memory/dreams/dream_type_selector.py`

| Type | Condition | Priority |
|------|-----------|----------|
| `daily_consolidation` | intensity >= 0.7 | Highest |
| `emotional_processing` | intensity >= 0.4 AND valence_range >= 0.3 | High |
| `memory_consolidation` | >= 3 related memories spanning >= 7 days | Medium |
| `identity_exploration` | Monthly schedule (every 30 days) | Low |
| `creative_random` | Fallback (always available) | Lowest |

Minimum 3 messages required for any dream type.

### 3. Context Building

`backend/memory/dreams/context_builder.py`

Context varies by dream type:
- **Emotional processing** — loads yesterday's conversation, extracts key moments
- **Memory consolidation** — loads related episodic_memories from past 7+ days
- **Identity exploration** — loads character traits + past identity dreams
- **Creative random** — loads recent dreams + generates random seed scenarios

### 4. Dream Conversation

`backend/memory/dreams/conversation_manager.py`

Two models in dialogue:

| Role | Model | Location | Port |
|------|-------|----------|------|
| Freud (guide) | gemma3:4b | node2 | 11435 |
| Iris (dreamer) | qwen3:32b | localhost | 11434 |

**Phase 1 — Dream (10 turns):**

| Parameter | Freud | Iris |
|-----------|-------|------|
| Temperature | 0.8 | 1.3 (very creative) |
| Top-P | - | 0.95 |
| Top-K | - | 60 |
| Max tokens | 500 | 500 |

Loop detector monitors for repetition and injects variety if detected.

**Phase 2 — Reflection (5 turns):**

| Parameter | Freud | Iris |
|-----------|-------|------|
| Temperature | 0.5 | 0.78 |
| Max tokens | 500 | 1000 |

Freud systematically extracts: summary, mood, theme, top_3_emotions, takeaway.

Context window: 14,336 tokens.

### 5. Reflection Extraction

`backend/memory/dreams/json_extractor.py`

| What | Where |
|------|-------|
| JSON extraction | `extract_reflection_with_fallback():50` |
| Fallback parsing | Line-by-line extraction if JSON invalid |

**Fields extracted:**
- `summary` — one-sentence dream overview
- `mood` — emotional tone (e.g., "wistful", "peaceful")
- `theme` — central theme or message
- `top_3_emotions` — list of 3 dominant emotions
- `takeaway` — key insight/realization
- `key_details` — important elements

### 6. Scoring and Embedding

`backend/memory/dreams/dream_scorer.py`

**Scores:**
- Emotional: emotion_label, emotion_top3, valence, arousal, intensity
- Psychological: recurrence, novelty, cohesion

**Embeddings (6 vectors, 768-dim each):**

| Embedding | Source |
|-----------|--------|
| `emb_summary_context` | Summary context text |
| `emb_summary_event` | Event description |
| `emb_summary_significance` | Significance analysis |
| `emb_takeaway` | Key takeaway |
| `emb_key_details` | Important details |
| `emb_full_dream` | Full dream transcript |

Model: `all-mpnet-base-v2` via `core/embeddings.py`.

### 7. Database Storage

`backend/memory/dreams/dream_storage.py`

INSERT into `episodic_dreams` with all fields.

**Post-insert checks:**
- `check_and_extract_truth()` — if `emotional_depth >= 0.75` AND `overall_score >= 0.70`, creates entry in `dream_truths` table (fades after 7 days)
- `check_and_suggest_seed()` — extracts motivation seeds from dream insights

---

## Dream Injection Into System Prompt

Dreams appear in two system prompt sections:

### Recent Dream

| What | Where |
|------|-------|
| Loader | `system_prompt.py:get_latest_dream():345` |
| Query | Most recent dream from last 24 hours |
| Context level | CONVERSATIONAL, DEEP, FULL |
| Format | `[RECENT DREAM] Last night ({date}) you dreamed. Mood: {mood}` |

### Dream Truths

| What | Where |
|------|-------|
| Loader | `system_prompt.py:get_dream_truths():393` |
| Query | Truths from dreams with emotional_depth >= 0.75, last 7 days |
| Context level | DEEP, FULL only |
| Limit | 5 truths |
| Format | `[DREAM TRUTHS] These are fleeting insights...` |

---

## Database Schema

### episodic_dreams

| Column | Type | Purpose |
|--------|------|---------|
| id | serial | Primary key |
| dream_date | date | When dream occurred |
| source_date | date | What day it processed |
| dream_type | varchar | Type selection result |
| based_on_reality | boolean | TRUE for consolidation/emotional |
| full_transcript | text | All 15 turns |
| dream_phase_transcript | text | Turns 1-10 |
| reflection_phase_transcript | text | Turns 11-15 |
| summary, takeaway, mood, theme | text/varchar | Reflection fields |
| top_3_emotions | jsonb | List of 3 emotions |
| key_details | text | Important elements |
| valence, arousal, recurrence, novelty, cohesion, intensity | float | Scores |
| emb_* (6 columns) | vector(768) | Embeddings |
| freud_model, iris_model | varchar | Model versions used |
| dream_duration_seconds | float | Processing time |

### dream_truths

| Column | Type | Purpose |
|--------|------|---------|
| id | serial | Primary key |
| dream_id | integer | FK to episodic_dreams |
| dream_date | date | Dream date |
| takeaway | text | The insight |
| emotional_depth | float | How impactful (0-1) |
| overall_score | float | Dream quality (0-1) |
| expires_at | timestamp | Fades after 7 days |

---

## Infrastructure

### GPU Requirements

Dreaming requires **exclusive access** to node2 GPU 0:
- Freud (gemma3:4b) runs on node2:11435
- Vision service must be stopped first
- `nightly_dream.sh` handles the swap via systemctl

### Cron Schedule

```
0 3 * * *  nightly_memory_creation.sh   # Memory pipeline first
0 4 * * *  nightly_dream.sh             # Dream pipeline second
```

Dreams run after memory creation so new memories are available for memory_consolidation dream type.

---

## Key Files

| File | Role |
|------|------|
| `scripts/nightly_dream.sh` | Cron orchestrator, GPU swap |
| `backend/memory/dreams/dream_moderator.py` | Main pipeline coordinator |
| `backend/memory/dreams/emotional_analyzer.py` | Daily emotional analysis |
| `backend/memory/dreams/dream_type_selector.py` | Type selection logic |
| `backend/memory/dreams/context_builder.py` | Dream context assembly |
| `backend/memory/dreams/conversation_manager.py` | Freud/Iris dialogue |
| `backend/memory/dreams/json_extractor.py` | Reflection field extraction |
| `backend/memory/dreams/dream_scorer.py` | Scoring and embedding |
| `backend/memory/dreams/dream_storage.py` | Database persistence |
| `core/system_prompt.py:345-448` | Dream injection into prompt |
