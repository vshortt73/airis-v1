# Prompt Assembly Pipeline

**Last Updated:** 2026-02-07

How a user message becomes an LLM API call. Follow this doc to trace any prompt-related issue.

---

## Pipeline Overview

```
User message (WebSocket)
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ 1. MESSAGE INTAKE                        routes_chat.py:1017    │
│    Parse JSON, extract message/images/documents                 │
│    Save to conversation + chat_history DB                       │
└───────────────────────────┬─────────────────────────────────────┘
                            │
    ┌───────────────────────┼───────────────────────┐
    ▼                       ▼                       ▼
┌──────────┐        ┌──────────────┐        ┌──────────────┐
│ Sentiment│        │ Query        │        │ Vision /     │
│ Analysis │        │ Classifier   │        │ Documents    │
│ (node2)  │        │              │        │ (if present) │
└────┬─────┘        └──────┬───────┘        └──────┬───────┘
     │                     │                       │
     ▼                     ▼                       ▼
  Emotional           context_level           Tool messages
  state updated       determined              added to conversation
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. SNAPSHOT DECISION              system_prompt.py:1466         │
│    Reuse frozen snapshot? Or full rebuild?                      │
│    (spoilage-only: reuse until spoiler event or token overflow) │
└───────────────┬─────────────────────┬───────────────────────────┘
          REUSE │                     │ REBUILD
                ▼                     ▼
        Return frozen         ┌───────────────────────────────┐
        messages list         │ 3. BUILD SYSTEM MESSAGE       │
                              │    system_prompt.py:728        │
                              │    (static sections only)      │
                              └───────────────┬───────────────┘
                                              │
                              ┌───────────────┴───────────────┐
                              │ 4. LOAD CONVERSATION HISTORY  │
                              │    persistence.py:395          │
                              │    Verbose recent + summarized │
                              └───────────────┬───────────────┘
                                              │
                              ┌───────────────┴───────────────┐
                              │ 5. FORMAT + STORE SNAPSHOT    │
                              │    system_prompt.py:1487       │
                              └───────────────┬───────────────┘
                                              │
                            ┌─────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ 5b. APPEND PER-TURN TAIL           routes_chat.py:1663         │
│     build_per_turn_context(): datetime, emotional state,       │
│     episodic memories, fast reactive memory                    │
│     (rebuilt fresh every turn, outside snapshot)                │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ 6. PREFLIGHT CHECK                    client.py:334             │
│    Count total tokens (messages + tools)                        │
│    If over budget: trim oldest conversation messages             │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ 7. LLM API CALL                      client.py:513             │
│    POST /v1/chat/completions (streaming, with tools)            │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
                    Stream response to UI
                    (if tool calls: execute, append results, loop)
```

---

## Step-by-Step Reference

### 1. Message Intake

| What | Where |
|------|-------|
| WebSocket receive | `routes_chat.py:1017` |
| Extract message, images, sender | `routes_chat.py:1078-1081` |
| Save to conversation | `conversation.py:add_user_message():84` |
| Persist to DB | `persistence.py:save_message()` |
| Sentiment analysis trigger | `routes_chat.py:1122-1134` |
| Query classification | `routes_chat.py:1149-1155` |

**Context levels** (from query classifier):
- `GREETING` — cap conversation at 500 tokens
- `TASK` — cap at 2,500 tokens
- `CONVERSATIONAL` — cap at 4,500 tokens
- `DEEP` / `FULL` — use full calculated budget

### 2. Snapshot Decision

| What | Where |
|------|-------|
| Entry point | `system_prompt.py:assemble_context_with_snapshot():1446` |
| Should rebuild? | `conversation.py:should_rebuild_snapshot():324` |
| Reuse path | `system_prompt.py:1466-1472` |
| Rebuild path | `system_prompt.py:1474-1498` |

**Rebuild triggers (spoilage-only — no batch size timer):**
- Batch trim disabled (feature flag)
- No snapshot yet (first turn)
- Snapshot spoiled (see spoiler events below)
- Token headroom exhausted

**Spoiler events** (force immediate rebuild):
- `trait` tool → `modify` action
- `memory` tool → `insert` or `archive` action
- `seed` tool → `plant`, `tend`, `reflect`, `accept`, `dismiss`, `clear_suggestions`
- `calendar` tool → `add`, `update`, `delete`
- Tool failure (any tool)
- Tool miss (model called tool not in snapshot)
- Topic pivot (user message needs tool groups not in snapshot)
- Admin forced invalidation (`POST /api/admin/snapshot/invalidate`)
- Conversation reloaded from database

### 3. System Message Assembly — Static Snapshot

`build_system_message()` at `system_prompt.py:728` assembles the **static prefix** in this order:

| # | Section | Source | Spoiler Trigger |
|---|---------|--------|-----------------|
| 1 | System instructions | `system_instructions` table | — |
| 2 | Character traits | `fulltraits` table | `trait modify` |
| 3 | Active seeds | `seeds` table | `seed plant/tend/reflect/...` |
| 4 | Short-term facts | `short_term_facts` table | `memory insert/archive` |
| 5 | Calendar reminders | `calendar_events` table | `calendar add/update/delete` |
| 6 | Recent dreams | `episodic_dreams` table | Nightly (offline) |
| 7 | Dream truths | `dream_truths` table | Nightly (offline) |
| 8 | Semantic memories | `semantic_memories` table | Nightly (offline) |

This is the frozen snapshot prefix — only rebuilt when a spoiler event fires or tokens are exhausted.

**Protocol filtering:** Active protocol's `rules_include`/`rules_exclude` filter which system instructions are loaded. Security rules (ID >= 1000) always included.

### 3b. Per-Turn Tail — Volatile Context

`build_per_turn_context()` at `system_prompt.py:897` builds a **separate system message** appended AFTER conversation history:

| # | Section | Source | Why Volatile |
|---|---------|--------|-------------|
| 1 | Current datetime | `datetime.now()` | Changes every turn |
| 1b | Gap report | `core/gap_report.py` | First turn after >=30min gap only (see `docs/GAP_REPORT.md`) |
| 2 | Emotional state | `get_emotional_tracker()` | Updated by sentiment analysis each turn |
| 3 | Episodic memories | `live_memories` table | Refreshed by retrieval v2 each turn (~200ms) |
| 4 | Fast reactive memory | Embedding similarity search | Query-dependent each turn |

This message is rebuilt fresh every turn and never part of the snapshot. It's injected by `routes_chat.py` after every `assemble_context_with_snapshot()` call.

**Gap report** (`<while_you_were_away>`): Only appears on the first turn after a >=30min absence. Reports memory processing, dreams, and service health events from the gap period. ~100-200 tokens, zero impact on subsequent turns. See `docs/GAP_REPORT.md` for full details.

### 4. Conversation History Loading

| What | Where |
|------|-------|
| Entry point | `persistence.py:load_recent_conversation():395` |
| Phase 1: Verbose | Recent messages in full, newest-first, up to `verbose_budget` tokens |
| Phase 2: Summary | Older messages as summaries, up to `summary_budget` tokens |
| Tool content limits | `persistence.py:500-511` (web_search: 20K chars, vision: 5K, etc.) |
| Output order | `summary_messages + verbose_messages` (oldest first) |

**No session boundary filtering** — loads across ALL sessions. Session IDs are analytics only.

### 5. Format and Store Snapshot

| What | Where |
|------|-------|
| Build message list | `system_prompt.py:1204-1263` |
| Add temporal context | `system_prompt.py:1213-1215` |
| Load image attachments | `system_prompt.py:1241-1258` |
| Token counting | `system_prompt.py:1268-1280` |
| Store snapshot | `system_prompt.py:1341-1353` |

Snapshot is stored as a **direct reference** (not a copy). `routes_chat.py` appends new messages directly to it during subsequent turns.

### 6. Preflight Check

| What | Where |
|------|-------|
| Function | `client.py:preflight_check():334` |
| Called from stream | `client.py:389` (no-tools) and `client.py:528` (with-tools) |
| Budget | `OLLAMA_CONTEXT_WINDOW - RESPONSE_GENERATION_BUDGET` |
| Trim strategy | Drop oldest conversation messages (keep system msg + recent) |

This is the **last line of defense**. If earlier budgeting worked correctly, preflight should always pass without trimming.

### 7. LLM API Call

| What | Where |
|------|-------|
| With tools (first call) | `client.py:chat_completion_stream_with_tools():506` |
| Without tools (follow-up) | `client.py:chat_completion_stream():370` |
| Endpoint | `POST {OLLAMA_BASE_URL}/v1/chat/completions` |
| Prompt comparison | `client.py:prompt_compare():67` (KV cache analysis) |

---

## Tool Result Flow

When the model calls tools, results re-enter the prompt:

```
Model streams response + tool_calls
    │
    ▼
Execute tools                      routes_chat.py:1498-1547
    │
    ▼
Build tool_content                 routes_chat.py:1592-1599
  = "[TOOL RESULT]\n..." + json.dumps(result)
    │
    ▼
Token budget check                 routes_chat.py:1601-1615
  If tokens > TOOL_RESULTS_BUDGET (15,000):
    Truncate at token level + append [TRUNCATED] notice
    │
    ▼
Add to conversation + snapshot     routes_chat.py:1617-1629
    │
    ▼
Reassemble context                 routes_chat.py:1647-1651
    │
    ▼
Iterative follow-up (up to 5)     routes_chat.py:1657-1659
    Each iteration can trigger more tools
```

---

## Token Budget Interaction

```
OLLAMA_CONTEXT_WINDOW (40,960)
├── SNAPSHOT PREFIX (static, frozen)
│   ├── Instructions       from system_instructions table
│   ├── Traits             from fulltraits table
│   ├── Seeds              from seeds table
│   ├── Facts              from short_term_facts table
│   ├── Calendar           from calendar_events table
│   ├── Dreams             from episodic_dreams + dream_truths tables
│   └── Semantic memories  from semantic_memories table
├── Conversation history   (fills remaining, tiered by context_level)
├── PER-TURN TAIL (volatile, rebuilt every turn)
│   ├── Datetime           from datetime.now()
│   ├── Gap report         from service_events + memories + dreams (first turn only)
│   ├── Emotional state    from emotional state tracker
│   ├── Episodic memories  from live_memories (retrieval v2)
│   └── Fast memory        from embedding similarity search
├── Tool definitions       (variable, ~2,000 tokens)
├── Safety margin (15%)    (~6,100 tokens, for tool results + overhead)
├── Batch trim headroom    (4,000 tokens when snapshot active)
└── Response reserve       (RESPONSE_GENERATION_BUDGET = 2,500)

OVERFLOW PROTECTION (three layers):
1. Per-result: TOOL_RESULTS_BUDGET (15K tokens) → truncated
2. Cumulative: 50% of context window (~20K) across all tool results per turn
3. Preflight: Total > CONTEXT_WINDOW - RESPONSE_BUDGET → oldest msgs trimmed
```

---

## Key Config Values

| Setting | Default | Source | Purpose |
|---------|---------|--------|---------|
| `OLLAMA_CONTEXT_WINDOW` | 40960 | system_config (tokens) | Total context window |
| `RESPONSE_GENERATION_BUDGET` | 2500 | system_config (tokens) | Reserved for LLM response |
| `TOOL_RESULTS_BUDGET` | 15000 | system_config (tokens) | Max tokens per tool result |
| `BATCH_TRIM_ENABLED` | true | system_config (features) | Enable snapshot reuse |
| `BATCH_TRIM_HEADROOM_TOKENS` | 4000 | system_config (features) | Reserve for snapshot growth |
| `MAX_TOTAL_MESSAGES` | 50 | system_config (tokens) | Safety brake on message count |
| `SEMANTIC_MEMORIES` | true | system_config (semantic) | Enable semantic memories in prompt |
| `SEMANTIC_MEMORY_LIMIT` | 10 | system_config (semantic) | Max semantic memories in prompt |

---

## Files Involved

| File | Role |
|------|------|
| `app/api/routes_chat.py` | Orchestrator — message intake, tool execution, context assembly calls |
| `core/system_prompt.py` | System message builder + snapshot manager + context assembler |
| `core/conversation.py` | In-memory conversation state + snapshot storage |
| `core/token_counter.py` | tiktoken-based token counting |
| `database/persistence.py` | Conversation history loading (verbose + summary tiers) |
| `database/character_traits.py` | Trait loading from fulltraits table |
| `database/memory_loader.py` | Episodic memory retrieval |
| `database/fast_reactive_memory.py` | Fast context-aware memory lookup |
| `inference/client.py` | Preflight check + LLM API calls |
