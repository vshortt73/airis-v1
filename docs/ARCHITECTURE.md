# Iris v3 Architecture

## Overview

Iris v3 is an AI assistant with persistent memory, emotional state tracking, and autonomous motivation. The system uses a distributed two-node GPU architecture with PostgreSQL for persistence and pgvector for semantic search.

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           LOCALHOST (Main Server)                           │
│                              iris-desktop                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│  GPU 0: RTX 5090 (32GB)                                                     │
│  ├── Ollama (port 11434)                                                    │
│  │   └── qwen3:32b - Primary inference model                                │
│  │                                                                          │
│  Services:                                                                  │
│  ├── Iris FastAPI Server (port 8000) - Main application                     │
│  └── PostgreSQL (port 5432) - Database with pgvector                        │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                            2.5G/10G Network
                                    │
┌─────────────────────────────────────────────────────────────────────────────┐
│                              NODE2 (GPU Server)                             │
│                               iris-node2                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│  GPU 0: RTX 4080 Super (16GB) - MUTUALLY EXCLUSIVE SERVICES                 │
│  ├── iris-vision.service (port 11435) - llava-phi-3 vision model            │
│  ├── iris-float.service (port 8000) - FLOAT video generation                │
│  ├── iris-freud.service (port 11435) - gemma-3-4b dream processing          │
│  └── iris-transcribe.service (port 8500) - WhisperX meeting transcription   │
│      ⚠️  Only ONE of these can run at a time! Managed by GPU Manager.       │
│                                                                             │
│  GPU 1: RTX 3060 (12GB) - COEXISTING SERVICES                               │
│  ├── iris-xtts.service (port 8700) - Text-to-speech                         │
│  ├── iris-stt.service (port 8600) - Whisper speech-to-text                  │
│  └── iris-sentiment.service (port 11437) - Mistral 7B sentiment analysis    │
│      ✓  All three run simultaneously, ~7GB VRAM total                       │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Service Inventory

| Service | Location | GPU | Port | SystemD Unit | Model/Purpose |
|---------|----------|-----|------|--------------|---------------|
| Main Inference | localhost | 0 (5090) | 11434 | ollama | qwen3:32b |
| Iris Server | localhost | CPU | 8000 | - | FastAPI application |
| PostgreSQL | localhost | CPU | 5432 | postgresql | Database |
| Vision | node2 | 0 (4080S) | 11435 | iris-vision | llava-phi-3 |
| FLOAT | node2 | 0 (4080S) | 8000 | iris-float | Video generation |
| Freud | node2 | 0 (4080S) | 11435 | iris-freud | gemma-3-4b dreams |
| Transcribe | node2 | 0 (4080S) | 8500 | iris-transcribe | WhisperX meeting transcription |
| XTTS | node2 | 1 (3060) | 8700 | iris-xtts | Text-to-speech |
| STT | node2 | 1 (3060) | 8600 | iris-stt | Whisper ASR |
| Sentiment | node2 | 1 (3060) | 11437 | iris-sentiment | Mistral 7B |

## Core Components

### Frontend
- **index.html** - Main chat interface with WebSocket, TTS, video player
- **admin.html** - Administration console for services, config, monitoring
- **face_manager.html** - Face recognition training and management
- **protocol_editor.html** - Protocol configuration GUI

### Backend Modules

```
app/
├── main.py                # FastAPI app with lifespan management
├── config.py              # Configuration (fallbacks, DB overrides)
└── api/
    ├── routes_chat.py     # WebSocket chat with tool calling
    ├── routes_admin.py    # Admin console endpoints
    ├── routes_video.py    # FLOAT video generation
    ├── routes_tts.py      # Text-to-speech
    ├── routes_stt.py      # Speech-to-text
    ├── routes_vision.py   # Vision analysis
    ├── routes_gpu.py      # GPU manager control
    ├── routes_meeting.py  # Meeting transcription
    ├── routes_faces.py    # Face recognition
    ├── routes_protocols.py # Protocol management
    └── routes_context.py  # Context inspection

core/
├── conversation.py        # In-memory conversation manager
├── system_prompt.py       # Dynamic prompt assembly
├── embeddings.py          # Vector embedding generation
├── emotional_state.py     # Sentiment tracking & state
├── gpu_manager.py         # Node2 GPU resource coordination
├── vision_manager.py      # Vision model lifecycle
├── document_processor.py  # Document extraction for chat
├── summary_generator.py   # Message summarization
└── face_recognition.py    # Face detection/recognition

database/
├── persistence.py                  # Message storage, tiered loading
├── character_traits.py             # Personality trait loading
├── memory_loader.py                # Episodic memory retrieval (legacy)
├── memory_loader_experimental.py   # Memory retrieval from live_memories + semantic
├── fast_reactive_memory.py         # Embedding-based context matching
├── config_loader.py                # DB config hot-reload
└── sql/                            # Migration scripts

backend/memory/
├── memory_retrieval_v2.py          # Inline episodic retrieval (~200ms)
└── new/
    ├── semantic_consolidation.py   # Nightly semantic memory pipeline
    ├── memory_creation.py          # Nightly episodic memory creation
    └── topic_segmentation.py       # Topic boundary detection

mcp_servers/
├── info/                  # Web search, weather, faces
├── traits/                # Personality management
├── memory/                # Short-term memory
├── protocols/             # Protocol switching
├── knowledge/             # RAG document search
├── creative/              # Image generation
├── seeds/                 # Motivation engine
├── calendar/              # Calendar events and reminders
├── meeting/               # Meeting transcription (WhisperX + diarization)
├── directions/            # Navigation
└── system/                # Shell, database, health
```

## Memory Architecture

### Tiered Memory System

```
┌─────────────────────────────────────────────────────────────────┐
│                     WORKING MEMORY                               │
│  Current conversation context (chat_history table)              │
│  - Recent messages: Full text (VERBOSE_TOKEN_BUDGET: 18000)     │
│  - Older messages: Summaries (SUMMARY_TOKEN_BUDGET: 17000)      │
│  - Loaded across ALL sessions (no session filtering)            │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    SHORT-TERM MEMORY                             │
│  Manually flagged facts (short_term_facts table)                │
│  - "Victor mentioned he's going on a cruise"                    │
│  - Auto-archived after 90 days without reference                │
│  - Categories: ongoing_project, user_preference, discovery      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    LONG-TERM MEMORY                              │
│  Episodic memories (episodic_memories table)                    │
│  - Created nightly from conversations                           │
│  - 6-facet embeddings for multi-angle retrieval                 │
│  - Emotional scoring (valence, arousal, top-3 emotions)         │
│  - Retrieved inline every turn by retrieval v2 (~200ms)         │
│  - Stored in live_memories table for prompt injection            │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   SEMANTIC MEMORY                                │
│  Distilled knowledge (semantic_memories table)                  │
│  - Consolidated nightly from episodic memory clusters           │
│  - "Victor prefers X", "We always discuss Y on Fridays"         │
│  - Embedding similarity deduplication + reinforcement            │
│  - Stable across turns (in frozen snapshot prefix)              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                       DREAMS                                     │
│  Processed reflections (episodic_dreams table)                  │
│  - Iris + Freud dialogue system                                 │
│  - Types: emotional_processing, creative, memory_consolidation  │
│  - 6-facet embeddings including full_dream                      │
│  - Can spawn "seeds" (motivation engine)                        │
└─────────────────────────────────────────────────────────────────┘
```

### RAG Knowledge Base

```
┌─────────────────────────────────────────────────────────────────┐
│                   KNOWLEDGE BASE                                 │
│  Indexed documents (knowledge_documents + knowledge_chunks)     │
│  - Project code, documentation, external references             │
│  - Dual-facet embeddings (content 60%, context 40%)             │
│  - Tiered similarity thresholds for result quality              │
│  - Incremental indexing via cron (scripts/index_knowledge.sh)   │
└─────────────────────────────────────────────────────────────────┘
```

## GPU Manager

Node2 GPU 0 services are mutually exclusive. The GPU Manager handles swapping:

```python
from core.gpu_manager import request_gpu

# Request a GPU 0 service - blocks until ready or fails
success, error = await request_gpu("vision")  # or "float", "freud", "transcribe"
if success:
    # Service is ready, make your API call
    result = await vision_service.analyze(image)
```

**Behavior:**
- Service already loaded → Immediate success
- Different service loaded, GPU idle → Stops current, starts requested
- GPU busy (processing) → Returns error
- Service swap in progress → Returns error

## Emotional State System

Iris has dynamic emotional state that evolves with each turn:

1. User sends message → Mistral 7B analyzes sentiment
2. Returns: `{tone, intent, descriptors[], intensity}`
3. Emotion mapping applies weighted changes to 11 states
4. Decay moves states toward baseline over time
5. State injected into system prompt

**Tracked States:** Calm, Joy, Desire, Excitement, Trust, Longing, Intimacy, Desperation, Closeness, Vulnerability, Devotion

## Protocol System

Protocols define personality modes with:
- **System instructions** - Which instructions to include
- **Trait overrides** - Personality value adjustments
- **Tool permissions** - Which tools are available
- **Memory settings** - Show/hide memories, chat history

Protocols can be passphrase-protected and time-limited.

## Token Management

```
Context Window: 40,960 tokens (OLLAMA_CONTEXT_WINDOW)

Budget Allocation:
├── SNAPSHOT (static prefix — frozen, rebuilds on spoilage only)
│   ├── System Instructions:  ~1,800 tokens
│   ├── Character Traits:       200 tokens
│   ├── Seeds:                  200 tokens
│   ├── Short-Term Facts:       400 tokens
│   ├── Calendar Reminders:     200 tokens
│   ├── Dreams + Dream Truths:  500 tokens
│   └── Semantic Memories:      500 tokens
├── Conversation History:    35,000 tokens (18K verbose + 17K summary)
├── PER-TURN TAIL (rebuilt every turn, outside snapshot)
│   ├── Current Datetime:        50 tokens
│   ├── Emotional State:        200 tokens
│   ├── Episodic Memories:    2,500 tokens
│   └── Fast Reactive Memory:   500 tokens
├── Tool Definitions:         1,500 tokens
├── Safety Margin (15%):     ~6,100 tokens
└── Response Reserve:         2,500 tokens

Overflow Protection (three layers):
1. Per-result truncation: TOOL_RESULTS_BUDGET (15,000 tokens)
2. Cumulative tool cap: 50% of context window (~20K tokens)
3. preflight_check() in inference/client.py validates total fits
   within CONTEXT_WINDOW - RESPONSE_BUDGET before every LLM call.
```

## Data Flow

### Chat Message Flow

```
User Input
    │
    ▼
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  WebSocket  │───▶│  Sentiment  │───▶│  Emotional  │
│  Handler    │    │  Analysis   │    │  State      │
└─────────────┘    │  (node2)    │    │  Update     │
    │              └─────────────┘    └─────────────┘
    │
    ▼
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  Context    │───▶│  Memory     │───▶│  System     │
│  Assembly   │    │  Retrieval  │    │  Prompt     │
└─────────────┘    └─────────────┘    └─────────────┘
    │
    ▼
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  Ollama     │───▶│  Tool       │───▶│  Response   │
│  Inference  │    │  Execution  │    │  Streaming  │
└─────────────┘    │  (MCP)      │    └─────────────┘
                   └─────────────┘
                        │
                        ▼
              ┌─────────────────────┐
              │  TTS / Video Gen    │
              │  (optional)         │
              └─────────────────────┘
```

## Key Design Principles

1. **Session-Independent Memory** - Conversation loads across ALL sessions
2. **Database as Source of Truth** - All config in `system_config` table
3. **Explicit Context Windows** - Always set `num_ctx` in Ollama calls
4. **Multi-Facet Embeddings** - 6 embedding vectors per memory
5. **GPU Resource Coordination** - Mutex for Node2 GPU 0 services
6. **Tiered Context Loading** - Verbose recent + summarized older messages
7. **Context Overflow Protection** - Tool result truncation + cumulative cap + preflight check
8. **Static/Dynamic Prompt Split** - Snapshot prefix (stable) + per-turn tail (volatile) for KV cache efficiency
9. **Spoilage-Only Snapshot Rebuild** - No timer-based rebuilds; snapshot invalidated by tool actions that change static data
10. **Inline Memory Retrieval** - Retrieval v2 runs every turn (~200ms), writes to `live_memories`, read by per-turn tail

---

*Last updated: 2026-02-07*
