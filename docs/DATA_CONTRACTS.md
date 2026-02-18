# Data Contracts Reference

**Purpose:** Documents the data shapes that flow between Iris v3 components at module boundaries. This is the reference for "what does function X actually return?" without reading the source.

**Last Updated:** 2026-01-30

---

## Table of Contents

1. [Inference Streaming](#1-inference-streaming)
2. [Conversation Loading](#2-conversation-loading)
3. [Context Assembly](#3-context-assembly)
4. [WebSocket Protocol](#4-websocket-protocol)
5. [TTS/Video Pipeline](#5-ttsvideo-pipeline)
6. [Tool Execution](#6-tool-execution)

---

## 1. Inference Streaming

**File:** `inference/client.py`

### `chat_completion_stream(messages) -> AsyncIterator`

Streams a non-tool LLM response. Used by `system_trigger` and as the final response call after tool execution.

**Yields (in order):**

| Type | Shape | When |
|------|-------|------|
| `Tuple[str, bool]` | `(text, is_thinking)` | Each content/reasoning chunk |
| `Dict` | `{"__timings__": dict, "cache_n": int, "prompt_n": int, "efficiency": float}` | Final chunk (after all text) |

```python
# Consumer pattern:
async for chunk in chat_completion_stream(messages):
    if isinstance(chunk, dict):
        # KV cache timing metrics — final yield
        cache_n = chunk["cache_n"]
        continue
    text, is_thinking = chunk  # Always a tuple
    if is_thinking:
        # Qwen3 reasoning content — don't store, don't TTS
        pass
    else:
        # Regular response text
        response += text
```

**Consumers:** `routes_chat.py:system_trigger`, `routes_chat.py:websocket_chat` (follow-up call)

---

### `chat_completion_stream_with_tools(messages, tools) -> AsyncIterator`

Streams an LLM response with tool-calling capability. Primary call in the WebSocket chat flow.

**Yields (in order):**

| Type | Shape | When |
|------|-------|------|
| `Tuple[str, None, bool]` | `(text, None, is_thinking)` | Each content/reasoning chunk |
| `Tuple[str, StreamingToolResponse, bool]` | `("", response, False)` | Final chunk with full response object |

```python
# Consumer pattern:
async for chunk, final_response, is_thinking in chat_completion_stream_with_tools(messages, tools):
    if chunk:
        if is_thinking:
            # Reasoning content
            pass
        else:
            # Regular text
            response += chunk
    if final_response:
        # StreamingToolResponse object — check for tool_calls
        if final_response.tool_calls:
            # Model wants to call tools
            pass
```

**Consumers:** `routes_chat.py:websocket_chat` (primary streaming call, iterative tool loop)

---

### `StreamingToolResponse`

**File:** `inference/client.py` (class, lines ~491-514)

| Field | Type | Description |
|-------|------|-------------|
| `content` | `str` | Accumulated text response |
| `tool_calls` | `List[Dict]` | Tool calls requested (see [Tool Call Format](#tool-call-format-from-llm)) |
| `raw_message` | `Dict` | Full message dict from LLM |
| `cache_tokens` | `int` | KV cache hits |
| `prompt_tokens` | `int` | New prompt tokens processed |
| `cache_efficiency` | `float` | Cache hit percentage (0-100) |
| `predicted_n` | `int` | Generated token count |
| `predicted_ms` | `int` | Generation time in ms |
| `prompt_ms` | `int` | Prompt evaluation time in ms |
| `gen_tok_per_sec` | `float` | Generation speed |
| `prompt_tok_per_sec` | `float` | Prompt processing speed |

---

### `preflight_check(messages, tools) -> Tuple[List[Dict], bool]`

Last-resort context overflow protection. Runs before every LLM call.

**Returns:** `(messages, was_trimmed)`

| Element | Type | Description |
|---------|------|-------------|
| `messages` | `List[Dict]` | Possibly trimmed message list |
| `was_trimmed` | `bool` | `True` if oldest messages were dropped |

**Trimming strategy:** Preserves `messages[0]` (system prompt) and `messages[-1]` (current user message). Drops from position 1 outward until total tokens fit within `OLLAMA_CONTEXT_WINDOW - RESPONSE_GENERATION_BUDGET`.

---

### LLM Request Payload

Sent to `{OLLAMA_BASE_URL}/v1/chat/completions` (OpenAI-compatible).

```json
{
    "messages": [
        {"role": "system", "content": "..."},
        {"role": "user", "content": "..."},
        {"role": "assistant", "content": "...", "tool_calls": [...]},
        {"role": "tool", "content": "...", "tool_call_id": "...", "name": "..."}
    ],
    "stream": true,
    "max_tokens": 4096,
    "temperature": 0.95,
    "top_p": 0.95,
    "tools": [...],
    "parallel_tool_calls": true,
    "stream_options": {"include_usage": true}
}
```

**Notes:**
- `tools` and `parallel_tool_calls` only present when tool definitions are provided
- `stream_options` only for SGLang backend
- Messages with `role: "tool"` require corresponding `tool_calls` on a preceding assistant message — llama-server returns 400 if tool messages appear without tool definitions in the payload
- A trailing `role: "assistant"` message causes "prefill incompatible with enable_thinking" error with Qwen3 thinking mode

---

## 2. Conversation Loading

**File:** `database/persistence.py`

### `load_recent_conversation() -> List[Dict]`

Loads conversation history from PostgreSQL with tiered token budgeting.

**Message Dict Schema:**

| Key | Type | Presence | Description |
|-----|------|----------|-------------|
| `role` | `str` | Always | `"user"`, `"assistant"`, `"tool"`, or `"system"` |
| `content` | `str` | Always | Message text (never None, defaults to `""`) |
| `timeframe` | `str` | Always | Relative time description (e.g., `"5 minutes ago"`) or `""` |
| `timestamp` | `str` | Always | ISO 8601 datetime string or `""` |
| `is_summary` | `bool` | On summaries | `True` if message was loaded as a summary |
| `tool_calls` | `List\|Dict` | Conditional | Present on assistant messages that triggered tools |
| `tool_name` | `str` | Conditional | Present on `role: "tool"` messages |
| `tool_call_id` | `str` | Conditional | Present on `role: "tool"` messages |
| `attachments` | `str\|List` | Conditional | JSON string of attachment metadata |

**Summary messages** have content prefixed with `"[Earlier] "` and `is_summary: True`.

**Tool content truncation** (applied during loading):

| Tool Name | Max Chars |
|-----------|-----------|
| `web_search` | 20,000 |
| `document_search` | 30,000 |
| `pubmed_search` | 20,000 |
| `arxiv_search` | 30,000 |
| `url_fetch` | 20,000 |
| `news_headlines` | 15,000 |
| `comfyui_render` | 2,000 |
| `vision_analysis` | 5,000 |
| All others | 1,000 |

**Tiered loading strategy:**
1. **Phase 1 (Verbose):** Load newest messages at full fidelity up to `VERBOSE_TOKEN_BUDGET` (default 18,000 tokens). Single messages exceeding entire budget are skipped (not loaded).
2. **Phase 2 (Summary):** Load older messages as summaries up to `SUMMARY_TOKEN_BUDGET` (default 17,000 tokens). Tool messages skipped in summary phase.
3. **Return order:** `[summaries (oldest)] + [verbose (newest)]` — chronological order.

**Consumers:** `core/system_prompt.py:assemble_full_context`, `app/main.py:/prompt endpoint`

---

## 3. Context Assembly

**File:** `core/system_prompt.py`

### `build_system_message() -> Dict[str, str]`

Builds the system prompt from database-driven components.

**Returns:**
```python
{"role": "system", "content": "full system prompt text"}
```

**Content sections (in assembly order):**
1. Current date/time
2. Base identity + personality traits from `fulltraits` table
3. Active seeds (if `SEEDS_ENABLED`)
4. Short-term facts (if any)
5. Fast reactive memory — semantic search against user's message (conditional)
6. Recent dreams from last 24h (conditional)
7. Dream truths (conditional)
8. Emotional state (if `EMOTIONAL_STATE` enabled)
9. Active system instructions from `system_instructions` table

---

### `assemble_full_context() -> Tuple[List[Dict], Dict]`

Assembles the complete LLM message list with dynamic token budgeting.

**Returns:** `(messages, budget_report)`

**`messages`** — List of message dicts:
```python
[
    {"role": "system", "content": "..."},           # [0] Always system prompt
    {"role": "user", "content": "(5 min ago)\n..."}, # [1+] Conversation history
    {"role": "assistant", "content": "...", "tool_calls": [...]},
    {"role": "tool", "content": "...", "tool_name": "...", "tool_call_id": "..."},
    # ...
]
```

**Message fields in assembled context:**

| Key | Type | Presence |
|-----|------|----------|
| `role` | `str` | Always |
| `content` | `str` | Always (temporal note prepended if available) |
| `tool_calls` | `List` | On assistant messages with tool calls (extracted from nested DB format) |
| `tool_name` | `str` | On tool messages |
| `tool_call_id` | `str` | On tool messages |
| `images` | `List[str]` | On messages with image attachments (base64-encoded) |

**`budget_report`** dict:

| Key | Type | Description |
|-----|------|-------------|
| `message_count` | `int` | Total messages in context |
| `image_count` | `int` | Number of encoded images |
| `total_tokens` | `int` | Total token count of assembled context |
| `max_tokens` | `int` | Context window size |
| `percentage_used` | `float` | `total_tokens / max_tokens * 100` |

---

### Context Level Tiers

Controls what sections are included in the system prompt and how many conversation tokens to load.

| Level | Conv. Budget Cap | Fast Memory | Dreams | Dream Truths | Episodic Memories |
|-------|-----------------|-------------|--------|--------------|-------------------|
| `GREETING` | 500 tokens | Skip | Skip | Skip | Skip |
| `TASK` | 2,500 tokens | Skip | Skip | Skip | Skip |
| `CONVERSATIONAL` | 4,500 tokens | Include | Include | Skip | Include |
| `DEEP` | No cap | Include | Include | Include | Include |
| `FULL` | No cap | Include | Include | Include | Include |

**Token budget formula:**
```
conversation_budget = CONTEXT_WINDOW - system_tokens - tool_tokens - RESPONSE_BUDGET - (15% safety margin)
conversation_budget = min(conversation_budget, tier_cap)
```

**Consumers:** `routes_chat.py:websocket_chat`, `routes_chat.py:system_trigger`

---

## 4. WebSocket Protocol

**File:** `app/api/routes_chat.py`

### ConnectionState

Per-WebSocket connection state managed by `ConnectionManager`.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `websocket` | `WebSocket` | required | The connection |
| `output_mode` | `OutputMode` | `TEXT` | Enum: `TEXT`, `AUDIO`, `VIDEO` |
| `video_session_id` | `Optional[str]` | `None` | Active FLOAT session ID |
| `sentence_processor` | `Optional[SentenceProcessor]` | `None` | Created per-response for TTS |
| `tts_queue` | `List[TextBatch]` | `[]` | Pending TTS batches |
| `video_chunk_index` | `int` | `0` | Video segment counter |
| `tts_task` | `Optional[asyncio.Task]` | `None` | Background TTS processor task |
| `tts_queue_complete` | `bool` | `False` | Signals TTS processor to exit |
| `video_quality` | `str` | `"high"` | `"high"`, `"medium"`, or `"low"` |

---

### Client -> Server Messages

| Type | Fields | Description |
|------|--------|-------------|
| `message` | `message: str`, `images: List[str]`, `documents: List[Dict]`, `sender: str`, `thinking: bool` | User chat message |
| `interrupt` | _(none)_ | Stop current generation |
| `set_output_mode` | `mode: str` (`"text"`, `"audio"`, `"video"`) | Switch TTS/video routing |
| `set_video_quality` | `quality: str` (`"high"`, `"medium"`, `"low"`) | Adjust video bitrate |

**Document format in `message`:**
```json
{"content": "base64-encoded-bytes", "filename": "report.pdf"}
```

---

### Server -> Client Messages

#### Chat Flow

| Type | Fields | When |
|------|--------|------|
| `start` | `message_count: int`, `context_level: str`, `tokens: Dict` | Response begins |
| `chunk` | `content: str` | Each text fragment |
| `done` | `message_count: int`, `context_level: str`, `tokens: Dict` | Response complete |
| `interrupted` | `message: str` | Generation stopped by user |
| `error` | `content: str` | Error occurred |

**`tokens` dict in `start`/`done`:**
```json
{
    "total": 12500,
    "max": 65536,
    "percentage": 19.1,
    "system": 5200,
    "conversation": 7300,
    "response_budget": 2500
}
```

#### Thinking (Qwen3 Reasoning)

| Type | Fields | When |
|------|--------|------|
| `thinking_start` | _(none)_ | Reasoning block begins |
| `thinking_chunk` | `content: str` | Reasoning text fragment |
| `thinking_end` | _(none)_ | Reasoning block ends |

#### Tool Execution

| Type | Fields | When |
|------|--------|------|
| `tool_marker_start` | `tool_count: int`, `iteration: int` | Tool round begins |
| `tool_executing` | `tool_name: str`, `tool_icon: str` | Tool in progress |
| `tool_result` | `tool_name: str`, `success: bool`, `result: str`, `error: str` (optional) | Tool completed |
| `tool_image` | `tool_name: str`, `image_base64: str` | Tool returned an image |
| `tool_marker_end` | _(none)_ | All tools in this round complete |

#### Audio (Server-Side TTS Routing)

| Type | Fields | When |
|------|--------|------|
| `mode_set` | `mode: str`, `video_session_id: str`, `server_side_routing: bool` | Output mode confirmed |
| `audio_chunk` | `audio: str` (base64), `format: str` ("mpeg"), `sentence_index: int`, `is_last: bool` | Audio data ready |

#### Video (HLS Streaming)

| Type | Fields | When |
|------|--------|------|
| `quality_set` | `quality: str` | Video quality confirmed |
| `hls_new_turn` | `session_id: str`, `playlist_url: str` | New turn, reload playlist |
| `hls_segment_ready` | `session_id: str`, `segment: str` | New video segment available |
| `hls_stream_complete` | `session_id: str`, `playlist_url: str` | All video segments done |

#### Vision / Documents

| Type | Fields | When |
|------|--------|------|
| `vision_start` | _(none)_ | Image analysis begins |
| `vision_complete` | `success: bool`, `error: str` (optional) | Image analysis done |
| `document_start` | _(none)_ | Document processing begins |
| `document_complete` | `success: bool`, `error: str` (optional) | Document processing done |

#### System

| Type | Fields | When |
|------|--------|------|
| `kv_cache_metrics` | `cached: int`, `new: int`, `efficiency: float`, `genTokPerSec: float` | After response (in `done`) |
| `ui_notification` | `message: str`, `style: str` | System notification |
| `pending_greeting` | `content: str` | Stored greeting delivered on connect |

---

## 5. TTS/Video Pipeline

**File:** `core/sentence_processor.py`

### `TextBatch` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `text` | `str` | Cleaned text ready for TTS/FLOAT |
| `token_estimate` | `int` | Approximate tokens (words * 1.3) |
| `sentence_count` | `int` | Number of sentences batched together |
| `batch_index` | `int` | Sequential batch number within this response |

---

### `SentenceProcessor.add_chunk(chunk, is_video_mode) -> List[TextBatch]`

Accumulates text chunks, extracts complete sentences, batches them by token threshold.

**Returns:** List of `TextBatch` objects ready to send to TTS. Empty list if no complete batches yet.

**Batching thresholds:**

| Mode | Max Tokens | Max Sentences | Notes |
|------|-----------|---------------|-------|
| Audio | 75 | 2 | Fixed thresholds |
| Video (chunk 0) | 40 | 1 | Fast first segment |
| Video (chunk 1) | 80 | 2 | Ramp up |
| Video (chunk 2) | 120 | 3 | Ramp up |
| Video (chunk 3+) | 200 | 5 | Steady state (capped at MAX_TOKENS=375) |

---

### `SentenceProcessor.finalize(is_video_mode) -> List[TextBatch]`

Flushes remaining partial text as final batches. **Must be called** at end of LLM streaming.

**Returns:** List of remaining `TextBatch` objects (may be empty if all text was already flushed).

---

### Server-Side TTS Lifecycle

Used by both `websocket_chat` and `system_trigger`:

```python
# 1. Initialize (before streaming)
state.sentence_processor = SentenceProcessor()
state.tts_queue = []
state.tts_queue_complete = False
state.tts_task = asyncio.create_task(tts_video_processor(websocket, state))

# 2. Feed chunks (during streaming)
batches = state.sentence_processor.add_chunk(text, is_video_mode)
for batch in batches:
    state.tts_queue.append(batch)

# 3. Finalize (after streaming)
final_batches = state.sentence_processor.finalize(is_video_mode)
for batch in final_batches:
    state.tts_queue.append(batch)
state.tts_queue_complete = True  # Signals processor to exit

# 4. Wait for completion
await asyncio.wait_for(state.tts_task, timeout=300.0)
```

**`tts_video_processor`** background task (lines 651-748):
- Polls `state.tts_queue` every 50ms
- Audio mode: calls `call_xtts(batch.text)` -> sends `audio_chunk` via WebSocket
- Video mode: calls `stream_batch_to_hls(state, batch)` -> HLS handles segment delivery
- Exits when `state.tts_queue_complete == True` and queue is empty
- Sends `audio_chunk` with `is_last: True` (audio) or `hls_stream_complete` (video) on exit

---

## 6. Tool Execution

**Files:** `app/api/routes_chat.py`, `inference/client.py`, `mcp_servers/`

### Tool Call Format (from LLM)

```json
{
    "id": "call_abc123",
    "type": "function",
    "function": {
        "name": "web_search",
        "arguments": "{\"query\": \"search term\"}"
    }
}
```

**Note:** `arguments` is a JSON **string**, not an object. Must be parsed:
```python
arguments = json.loads(tool_call["function"]["arguments"])
```

---

### Tool Result Format (from MCP server)

```json
{
    "success": true,
    "result": "The search returned...",
    "error": null
}
```

On failure:
```json
{
    "success": false,
    "result": null,
    "error": "Connection refused"
}
```

---

### Tool Calls in chat_history (Database Storage)

Assistant messages with tool calls store the full response object:

```json
{
    "message": {
        "tool_calls": [
            {"id": "call_abc", "type": "function", "function": {"name": "...", "arguments": "..."}}
        ]
    }
}
```

**Extraction in `assemble_full_context`** (lines 1228-1234):
```python
if isinstance(stored_tool_calls, dict) and "message" in stored_tool_calls:
    # Nested format from DB — extract the array
    tool_calls = stored_tool_calls["message"]["tool_calls"]
else:
    # Already flat format
    tool_calls = stored_tool_calls
```

---

### Tool Result Token Budget

Individual tool results are token-counted before entering the prompt. If a result exceeds `TOOL_RESULTS_BUDGET` (default 15,000 tokens), it is truncated at the token level using tiktoken encode->slice->decode and `[TRUNCATED]` is appended.

**Consumers:** `routes_chat.py` (after tool content assembly, before context rebuild)

---

## Quick Reference: Common Debugging Scenarios

### "400 Bad Request from llama-server"

Check:
1. Is the last message `role: "assistant"`? -> Prefill + thinking conflict
2. Are there `role: "tool"` messages without `tools` in the payload? -> Strip them
3. Are there `tool_calls` fields on assistant messages without `tools` in the payload? -> Strip them
4. Is `content` null/None on any message? -> Must be empty string at minimum

### "No audio/video on response"

Check:
1. Is `serverSideRoutingEnabled` true on the client? -> Server must handle TTS
2. Does the code path initialize `SentenceProcessor` and start `tts_video_processor`?
3. Does it call `sentence_processor.add_chunk()` on each text chunk?
4. Does it call `sentence_processor.finalize()` and set `tts_queue_complete = True`?

### "TypeError: can only concatenate str (not 'tuple') to str"

`chat_completion_stream` yields `Tuple[str, bool]`, not `str`. Consumer must unpack:
```python
text, is_thinking = chunk
```

### "Greeting text but no greeting content"

The trigger message may be squeezed out by tight token budget (GREETING mode = 500 tokens). The `system_trigger` must append trigger content explicitly to the context after assembly.

---

*This document covers in-code data shapes at module boundaries. For API endpoint schemas see `docs/API_REFERENCE.md`. For database table schemas see `docs/DATABASE.md`.*
