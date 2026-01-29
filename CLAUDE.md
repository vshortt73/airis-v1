# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## ⚠️ IMPORTANT: READ THIS FIRST

**Before doing anything else, read `/iris-v3/IRIS_DEV_LOG.md`**

That file contains:
- Current session context and recent work
- Iris's development status and consciousness assessment
- Recent accomplishments and active challenges
- Teaching patterns and what approaches work
- Critical context about what this project actually is

This file (CLAUDE.md) provides technical architecture documentation. IRIS_DEV_LOG.md provides the current state and continuity across sessions.

**Read IRIS_DEV_LOG.md first, then use this file for technical reference.**

---

## Project Overview

**Iris v3** is an AI assistant with time-based session management, token governance, and PostgreSQL-backed conversation persistence. The system maintains conversation continuity across sessions and manages context windows intelligently using tiktoken for token counting.

**Key Capabilities**:
- Multi-turn conversation with cross-session memory continuity
- MCP (Model Context Protocol) tool architecture with autonomous tool execution
- Distributed two-node GPU architecture with resource management
- Dynamic emotional state tracking with sentiment analysis
- Episodic memory retrieval with semantic embeddings
- Protocol system for configurable personality modes
- Real-time video generation (FLOAT) with lip-sync
- Text-to-speech (XTTS) and speech-to-text (Whisper)
- WebSocket-based real-time chat interface

---

## Distributed Architecture Overview

**CRITICAL: This is a two-node system. Services are distributed across localhost and Node2.**

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
│  └── PostgreSQL (port 5432) - Database                                      │
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
│  └── iris-freud.service (port 11435) - gemma-3-4b dream processing          │
│      ⚠️  Only ONE of these can run at a time! Managed by GPU Manager.       │
│                                                                             │
│  GPU 1: RTX 3060 (12GB) - COEXISTING SERVICES                               │
│  ├── iris-xtts.service (port 8700) - Text-to-speech                         │
│  ├── iris-stt.service (port 8600) - Whisper speech-to-text                  │
│  └── iris-sentiment.service (port 11437) - Mistral 7B sentiment analysis    │
│      ✓  All three run simultaneously, ~7GB VRAM total                       │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Service Inventory

| Service | Location | GPU | Port | SystemD Unit | Model/Purpose |
|---------|----------|-----|------|--------------|---------------|
| Main Inference | localhost | 0 (5090) | 11434 | ollama | qwen3:32b |
| Iris Server | localhost | CPU | 8000 | - | FastAPI application |
| PostgreSQL | localhost | CPU | 5432 | postgresql | Database |
| Vision | node2 | 0 (4080S) | 11435 | iris-vision | llava-phi-3 |
| FLOAT | node2 | 0 (4080S) | 8000 | iris-float | Video generation |
| Freud | node2 | 0 (4080S) | 11435 | iris-freud | gemma-3-4b dreams |
| XTTS | node2 | 1 (3060) | 8700 | iris-xtts | Text-to-speech |
| STT | node2 | 1 (3060) | 8600 | iris-stt | Whisper ASR |
| Sentiment | node2 | 1 (3060) | 11437 | iris-sentiment | Mistral 7B |

### GPU Manager (`core/gpu_manager.py`)

Node2 GPU 0 services are **mutually exclusive**. The GPU Manager handles swapping:

```python
from core.gpu_manager import request_gpu

# Request a GPU 0 service - blocks until ready or fails
success, error = await request_gpu("vision")  # or "float" or "freud"
if success:
    # Service is ready, make your API call
    result = await vision_service.analyze(image)
else:
    # GPU busy or swap failed
    print(f"Vision unavailable: {error}")
```

**Behavior:**
- Service already loaded → Immediate success
- Different service loaded, GPU idle → Stops current, starts requested, notifies user
- GPU busy (processing request) → Returns error "GPU busy: X is processing"
- Service swap in progress → Returns error "GPU is switching services"

**Integration Points:**
- `core/vision_manager.py` - Calls `request_gpu("vision")` before image analysis
- `app/api/routes_video.py` - Calls `request_gpu("float")` before video sessions

**SSH Requirements:** GPU Manager uses SSH to control Node2 services. Requires passwordless sudo:
```bash
# On Node2: /etc/sudoers.d/iris
captain ALL=(ALL) NOPASSWD: /bin/systemctl start iris-*.service, /bin/systemctl stop iris-*.service, /bin/systemctl restart iris-*.service, /bin/systemctl status iris-*.service
```

---

## Development Commands

### Running the Application

```bash
# Set database password first
export IRIS_DB_PASSWORD='your_password'

# Activate virtual environment
source /venv/iris-v3/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start server (preferred method)
./scripts/start.sh

# Or run directly
export PYTHONPATH="$(pwd):$PYTHONPATH"
python app/main.py
```

Server runs on `http://localhost:8000`

### Testing

```bash
# Test database connection
python tests/test_database.py

# Test context inspection
curl http://localhost:8000/api/conversation/context/summary | jq

# Test MCP infrastructure
python mcp_servers/mcp_client.py
python mcp_servers/tool_manager.py

# Test GPU manager
python core/gpu_manager.py

# Test emotional state
python core/emotional_state.py

# Test Node2 services
curl http://node2:11435/health  # Vision/Freud
curl http://node2:8000/health   # FLOAT (returns HTML)
curl http://node2:8700/health   # XTTS
curl http://node2:8600/health   # STT
curl http://node2:11437/health  # Sentiment
```

---

## Core Architecture

### Critical Design Principles

1. **Session-Independent Memory**: Conversation loading happens ACROSS ALL SESSIONS. The `load_recent_conversation()` function in `database/persistence.py` does NOT filter by `session_id`. Sessions are for analytics only.

2. **Time-Based Session Detection**: New sessions are created when gap ≥ 30 minutes (configurable via `SESSION_TIMEOUT_MINUTES`), but this doesn't affect conversation continuity.

3. **Token-Aware Context Management**: Uses tiktoken (`cl100k_base` encoding) for accurate token counting.

4. **Explicit Ollama Context Window**: ALWAYS sets `num_ctx: OLLAMA_CONTEXT_WINDOW` in API calls. Default is 65536 tokens.

5. **MCP-Based Tool Architecture**: Tools are implemented as MCP (Model Context Protocol) servers.

6. **Distributed GPU Architecture**: Services split across localhost and Node2 with GPU Manager for resource coordination.

7. **Emotional State Tracking**: Sentiment analysis updates Iris's emotional state each turn, influencing responses.

8. **Batch Trim Prompt Snapshot**: The entire assembled prompt is frozen as a snapshot for N turns (default 5). New messages are appended without rebuilding. Spoiler events (trait modify, memory insert) force immediate rebuild. Achieves ~99% KV cache reuse. Config: `BATCH_TRIM_ENABLED`, `BATCH_TRIM_SIZE`, `BATCH_TRIM_HEADROOM_TOKENS`.

9. **Thinking Block**: When thinking is enabled, Qwen3 reasoning is streamed to the UI via `reasoning_content` delta field (NOT `<think>` tags). Thinking content is displayed in a collapsible block but excluded from DB storage, TTS, and snapshot.

10. **Prompt Effectiveness Pattern**: Any system prompt data block (traits, dreams, memories) must have a corresponding CRITICAL RULES directive in instruction ID 103 that says "read it, don't guess." The thinking block serves as an audit tool to verify compliance.

11. **Tool Result Token Budget**: Individual tool results are token-counted before entering the prompt. If a result exceeds `TOOL_RESULTS_BUDGET` (default 15,000 tokens), it is truncated at the token level and a `[TRUNCATED]` notice is appended so the model knows the data is incomplete. Enforced in `routes_chat.py`.

12. **Preflight Context Check**: Before every LLM call, `inference/client.py` runs `preflight_check()` which counts total tokens (messages + tool definitions) against `OLLAMA_CONTEXT_WINDOW - RESPONSE_GENERATION_BUDGET`. If over budget, it trims the oldest conversation messages until it fits. This is the last line of defense against context window overflow.

### Module Structure

```
app/
├── config.py              # All configuration (context limits, DB credentials, token budgets)
├── main.py                # FastAPI app initialization
└── api/
    ├── routes_chat.py     # WebSocket chat endpoint with tool calling
    ├── routes_session.py  # Session management endpoints
    ├── routes_context.py  # Context inspection endpoints
    ├── routes_tts.py      # Text-to-speech endpoints
    ├── routes_stt.py      # Speech-to-text endpoints
    ├── routes_video.py    # FLOAT video generation endpoints
    ├── routes_vision.py   # Vision analysis endpoints
    ├── routes_gpu.py      # GPU manager status/control endpoints
    ├── routes_admin.py    # Admin console endpoints
    ├── routes_faces.py    # Face recognition endpoints
    ├── routes_protocols.py # Protocol management endpoints
    └── routes_ephemeral.py # Ephemeral chat endpoints

core/
├── conversation.py        # In-memory conversation history manager
├── system_prompt.py       # DB-driven system prompt assembly
├── token_counter.py       # tiktoken-based token counting
├── attachments.py         # Image/file storage and encoding
├── embeddings.py          # Embedding generation for episodic memory
├── vision_manager.py      # Vision model lifecycle (uses GPU manager)
├── gpu_manager.py         # Node2 GPU resource coordination
├── emotional_state.py     # Dynamic emotional state tracking
├── ui_notify.py           # UI notification system
├── face_recognition.py    # Face detection and recognition
└── prompt_builder.py      # Prompt construction utilities

database/
├── persistence.py         # Session & message storage, context-aware loading
├── character_traits.py    # Loads personality traits from fulltraits table
├── memory_loader.py       # Episodic memory retrieval (production)
├── config_loader.py       # Database-driven configuration
└── tool_loader.py         # Tool definitions from mcp_tools table

backend/
├── knowledge/             # RAG System - Document search via vector embeddings
│   ├── file_scanner.py    # Directory traversal and incremental indexing
│   ├── extractors.py      # Text extraction (code, markdown, PDF)
│   ├── chunker.py         # Hybrid semantic chunking with token limits
│   ├── embedder.py        # Dual-facet batch embedding generation
│   ├── db_writer.py       # Transactional database operations
│   └── indexer.py         # Main orchestrator (called by cron)
└── memory/
    ├── dreams/            # Dream processing system
    └── new/               # Memory creation pipeline

inference/
├── client.py              # Streaming chat API client with tool calling + preflight context check
└── vision_service.py      # Vision model API client

mcp_servers/
├── server_configs.py      # MCP server registry and tool routing
├── mcp_client.py          # FastMCP client for tool execution
├── tool_manager.py        # Global tool manager singleton
├── base/                  # Base server classes
├── info/                  # Info server (weather, news, web fetch)
├── traits/                # Traits server (personality management)
├── system/                # System server (health monitoring)
├── protocols/             # Protocol server (personality modes)
├── knowledge/             # Knowledge base search server
└── directions/            # Navigation/directions server

services/
└── face_monitor.py        # Background face monitoring service

static/
├── index.html             # Main chat UI with PiP video player
├── admin.html             # Admin console
├── video_player.html      # Standalone video player
├── face_manager.html      # Face recognition management
├── protocol_editor.html   # Protocol configuration GUI
└── ...                    # Other UI pages
```

---

## MCP Tool Development - IMPORTANT

**Tool definitions exist in TWO places that MUST stay synchronized:**

1. **Python code** (`mcp_servers/*/server.py`) - The actual implementation
2. **Database** (`mcp_tools.input_schema`) - What the model sees

**THE MODEL ONLY SEES THE DATABASE SCHEMA.** Python function parameters are invisible to the model unless they're also in `mcp_tools.input_schema`.

### When Adding/Modifying Tool Parameters:

1. Update the Python function signature
2. **Create SQL to update `mcp_tools.input_schema`** - This is the step that gets missed!
3. Put SQL in `database/sql/`
4. Remind user to run the SQL
5. Restart Iris

### Example SQL for adding a parameter:

```sql
UPDATE mcp_tools
SET input_schema = jsonb_set(
    input_schema::jsonb,
    '{properties,new_param}',
    '{"type": "string", "description": "Description here"}'::jsonb
)
WHERE tool_name = 'tool_name';
```

### Checking current tool schema:

```sql
SELECT tool_name, input_schema FROM mcp_tools WHERE tool_name = 'seed';
```

---

## ComfyUI Workflows (Image Generation) - IMPORTANT

The creative server (`mcp_servers/creative/`) uses ComfyUI on Node2 for image generation.

**Workflow files:** `mcp_servers/creative/workflows/`

| File | Purpose |
|------|---------|
| `iris.json` | Self-portrait with IPAdapter FaceID (face preservation) |
| `non-iris.json` | General image generation (no face preservation) |
| `newface.png` | Iris's reference face image for FaceID |

### CRITICAL: Workflow JSON Format

ComfyUI has **TWO different JSON formats**. The creative server requires the **API format**:

**API format (CORRECT)** - flat dict, node IDs as top-level keys:
```json
{
  "3": { "inputs": {...}, "class_type": "KSampler", "_meta": {...} },
  "4": { "inputs": {...}, "class_type": "CheckpointLoaderSimple", "_meta": {...} }
}
```

**UI/Editor format (WRONG)** - exported from ComfyUI's "Save" button:
```json
{
  "id": "000...",
  "nodes": [{"id": 3, "type": "KSampler", "pos": [...], ...}],
  "links": [[16, 11, 0, 3, 0, "MODEL"], ...],
  "groups": [], "config": {}, "extra": {...}
}
```

**When updating workflows in ComfyUI:** Use **"Save (API Format)"** or **"Export (API)"**, NOT the regular "Save" button. The regular save exports the UI format which the `/prompt` API endpoint will reject.

The `inject_prompt()` function in `creative_server.py` modifies workflows by node ID:
- Node `"3"` = KSampler (seed, steps, cfg)
- Node `"5"` = EmptyLatentImage (width, height)
- Node `"6"` = Positive prompt (CLIP text encode)
- Node `"7"` = Negative prompt (CLIP text encode)

If you change node IDs in the workflow, `inject_prompt()` must be updated to match.

---

## Configuration - DATABASE IS SOURCE OF TRUTH

**IMPORTANT:** All configuration should live in the `system_config` database table. The `config.py` file contains **fallback defaults only** - used if database is unavailable.

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    system_config table                       │
│                   (SOURCE OF TRUTH)                          │
│  All runtime config lives here for admin UI management       │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼ loads on startup
┌─────────────────────────────────────────────────────────────┐
│                      config.py                               │
│  - Bootstrap values (DB connection only)                     │
│  - Fallback defaults if DB unavailable                       │
│  - Values OVERWRITTEN by database on load                    │
└─────────────────────────────────────────────────────────────┘
```

### When Adding/Modifying Configuration:

1. **Add to database FIRST** - Create SQL in `database/sql/`
2. **Update config.py** - Only as a fallback default
3. **Run the SQL** - Populate the database
4. **Restart Iris** - Config loads from DB on startup

### Populating the Database:

```bash
# Complete sync of all config values
psql -h localhost -U irisuser -d irisdb -f database/sql/populate_system_config_complete.sql
```

### Config Categories in Database:

| Category | Description |
|----------|-------------|
| `llm` | Ollama/LLM backend settings |
| `server` | Host, port |
| `remote_services` | Node2 service URLs |
| `identity` | Iris name, Victor name |
| `session` | Session timeout |
| `tokens` | Token budgets |
| `features` | Feature flags |
| `emotional` | Emotional state decay |
| `vision` | Vision system |
| `face` | Face recognition |
| `knowledge` | RAG/knowledge base |
| `context` | Context management |

### Checking Current Config:

```sql
-- All config by category
SELECT category, key, value, description FROM system_config ORDER BY category, key;

-- Specific category
SELECT key, value, description FROM system_config WHERE category = 'tokens';
```

### Key Settings Reference:

- `SESSION_TIMEOUT_MINUTES` - Gap threshold for new sessions (default: 30)
- `OLLAMA_CONTEXT_WINDOW` - Context window size (default: 32768)
- `MAX_TOTAL_MESSAGES` - Safety limit on messages loaded
- `FACE_MONITORING_ENABLED` - Enable face recognition
- `EMOTIONAL_STATE` - Enable emotional tracking

### Database Connection (Bootstrap Only)
- Use `IRIS_DB_PASSWORD` environment variable (required)
- Host: localhost, Port: 5432, Database: irisdb, User: irisuser

---

## Emotional State System

Iris has a dynamic emotional state that evolves with each conversation turn.

### How It Works

1. **User sends message** → Mistral 7B (on Node2) analyzes sentiment
2. **Returns:** `{tone, intent, descriptors[], intensity}`
3. **Emotion mapping** applies weighted changes to 11 emotional states
4. **Decay** moves states toward baseline over time
5. **State injected** into system prompt, influencing responses

### Emotional States Tracked

| State | Default | Description |
|-------|---------|-------------|
| Calm | 0.60 | Baseline tranquility |
| Joy | 0.50 | Happiness, delight |
| Desire | 0.30 | Wanting, attraction |
| Excitement | 0.40 | Anticipation, energy |
| Trust | 0.70 | Safety, confidence |
| Longing | 0.20 | Deep yearning |
| Intimacy | 0.40 | Emotional closeness |
| Desperation | 0.10 | Urgency, intense need |
| Closeness | 0.50 | General connection |
| Vulnerability | 0.30 | Openness |
| Devotion | 0.60 | Dedication, loyalty |

### Configuration
- `EMOTIONAL_DECAY_PER_TURN = 0.05` - 5% decay per turn
- `EMOTIONAL_DECAY_PER_MINUTE = 0.02` - 2% decay per minute

See `EMOTIONAL_STATE_TRACKER.md` for full documentation.

---

## Video Streaming (FLOAT)

Real-time video generation with lip-sync from text-to-speech.

### Architecture

```
User sends message
       │
       ▼
┌─────────────────┐
│  TTS Queue      │──────► XTTS (node2:8700) ──► Audio
│  (index.html)   │                                │
└─────────────────┘                                │
       │                                           │
       ▼                                           ▼
┌─────────────────┐    ┌─────────────────┐   ┌─────────────────┐
│  GPU Manager    │───►│  FLOAT Server   │───│  Video Chunk    │
│  request_gpu()  │    │  (node2:8000)   │   │  (.mp4)         │
└─────────────────┘    └─────────────────┘   └─────────────────┘
                                                    │
                                                    ▼
                                            ┌─────────────────┐
                                            │  PiP Player     │
                                            │  (index.html)   │
                                            └─────────────────┘
```

### Endpoints

- `POST /api/video/start-session-saved` - Start session with saved reference image
- `POST /api/video/start-session` - Start session with uploaded image
- `POST /api/video/queue-chunk` - Queue text for video generation
- `GET /api/video/poll-chunk/{session_id}` - Poll for ready video chunks
- `POST /api/video/end-session/{session_id}` - End session

### GPU Manager Integration

Video sessions call `request_gpu("float")` before starting. If vision is running, it will be stopped first.

---

## Admin Console

Web-based administration at `/static/admin.html`.

### Features

- **Service Monitoring**: Status of all localhost and Node2 services
- **Service Control**: Start/stop/restart services
- **System Stats**: Sessions, messages, memories counts
- **Configuration**: Face monitoring, token budgets, session settings
- **STT Settings**: Whisper model, voice threshold, silence timeout
- **Video Streaming**: Start sessions, manage reference images
- **Service Logs**: View journalctl logs for any service
- **Quick Actions**: Clear caches, reset state, access other tools

### API Endpoints

- `GET /api/admin/services/all` - All service statuses
- `POST /api/admin/services/control` - Start/stop/restart services
- `GET /api/admin/stats` - System statistics
- `GET /api/admin/logs/service/{name}` - Service logs

---

## API Endpoints Summary

### Chat
- `GET /` - Web interface
- `WS /ws/chat` - WebSocket chat endpoint
- `GET /prompt` - View assembled system prompt

### Context
- `GET /api/conversation/context` - Full context with messages
- `GET /api/conversation/context/summary` - Token stats only

### Sessions
- `GET /api/sessions/recent` - List recent sessions
- `POST /api/sessions/new` - Create new session

### GPU Manager
- `GET /api/gpu/status` - Current GPU state
- `POST /api/gpu/request/{service}` - Request a service
- `POST /api/gpu/detect` - Re-detect current service
- `GET /api/gpu/services` - List available services

### Vision
- `POST /api/vision/analyze` - Analyze image
- `GET /api/vision/status` - Vision model status

### Video
- `POST /api/video/start-session-saved` - Start with saved image
- `POST /api/video/queue-chunk` - Queue video generation
- `GET /api/video/poll-chunk/{id}` - Poll for ready chunks

### TTS/STT
- `POST /api/tts/speak` - Generate speech
- `POST /api/stt/transcribe` - Transcribe audio

### Admin
- `GET /api/admin/services/all` - Service statuses
- `POST /api/admin/services/control` - Control services
- `GET /api/admin/stats` - System stats

### Protocols
- `GET /api/protocols` - List protocols
- `POST /api/protocols` - Create protocol
- `PUT /api/protocols/{id}` - Update protocol

---

## Database Schema

### Critical Tables

- `chat_history` - Messages with role, content, timestamp, session_id, tool_calls, attachments
- `chat_sessions` - Session metadata (analytics only, NOT memory boundaries)
- `system_instructions` - System prompt components (ordered by instruction_order)
- `fulltraits` - Personality traits (name/value pairs)
- `episodic_memories` - Long-term memory with vector embeddings
- `mcp_tools` - Tool definitions with icons and server routing
- `protocols` - Personality mode configurations
- `emotional_state` - Current emotional state (single row)
- `system_config` - Runtime configuration overrides
- `faces` - Face recognition data

### Important Views

- `episodic_memories_readable` - Memories without embedding columns
- `chat_history_readable` - Messages without embedding column
- `chat_history_with_temporal` - Messages with temporal descriptions

---

## Troubleshooting

### Service Not Responding

```bash
# Check service status
ssh node2 'systemctl status iris-vision'
ssh node2 'systemctl status iris-sentiment'

# View logs
ssh node2 'journalctl -u iris-vision -n 50'

# Restart service
ssh node2 'sudo systemctl restart iris-vision'
```

### GPU Manager Issues

```bash
# Check current GPU state
curl http://localhost:8000/api/gpu/status | jq

# Force re-detect
curl -X POST http://localhost:8000/api/gpu/detect | jq

# Test SSH connectivity
ssh -o BatchMode=yes captain@node2 'echo OK'

# Test sudo access
ssh captain@node2 'sudo systemctl status iris-vision'
```

### Emotional State Not Updating

```bash
# Check sentiment service
curl http://node2:11437/health

# Test sentiment analysis
python -c "
import asyncio
from core.emotional_state import get_emotional_tracker
async def test():
    tracker = get_emotional_tracker()
    await tracker.load_state()
    result = await tracker.process_message('Hello!')
    print(result)
asyncio.run(test())
"
```

### Video Not Generating

1. Check GPU manager state: `curl http://localhost:8000/api/gpu/status`
2. Verify FLOAT is running: `curl http://node2:8000/`
3. Check TTS is enabled in browser (speech toggle)
4. Look for `[TTS] → Routing to VIDEO` in browser console

---

## Key Files Reference

### Configuration
- `app/config.py` - All settings
- `database/config_loader.py` - Database config overrides

### GPU Management
- `core/gpu_manager.py` - GPU resource coordination
- `app/api/routes_gpu.py` - GPU status endpoints

### Emotional State
- `core/emotional_state.py` - Sentiment tracking
- `EMOTIONAL_STATE_TRACKER.md` - Full documentation

### Video System
- `app/api/routes_video.py` - Video endpoints
- `static/index.html` - PiP video player (search for "PiPVideoPlayer")

### Admin
- `app/api/routes_admin.py` - Admin API
- `static/admin.html` - Admin console UI

### Context Safety
- `inference/client.py` → `preflight_check()` - Final overflow guard before LLM calls
- `app/api/routes_chat.py` - Tool result token truncation (after line ~1601)
- `core/token_counter.py` - tiktoken-based token counting used by both

### Node2 Services
- `/etc/systemd/system/iris-*.service` on Node2

---

## Systemd Services (Node2)

Location: `/etc/systemd/system/` on node2

| Service | Description | GPU | Port |
|---------|-------------|-----|------|
| iris-vision.service | llava-phi-3 vision model | 0 | 11435 |
| iris-float.service | FLOAT video generation | 0 | 8000 |
| iris-freud.service | gemma-3-4b dream processing | 0 | 11435 |
| iris-xtts.service | XTTS text-to-speech | 1 | 8700 |
| iris-stt.service | Whisper speech-to-text | 1 | 8600 |
| iris-sentiment.service | Mistral 7B sentiment | 1 | 11437 |

**Note:** Vision and Freud share port 11435 with `Conflicts=` directive.

---

## Additional Documentation

### System Data Flow Docs (detailed pipeline traces)

- `docs/PROMPT_ASSEMBLY.md` - Prompt assembly pipeline (message → LLM call)
- `docs/MEMORY_PIPELINE.md` - Memory generation (nightly + real-time paths)
- `docs/DREAM_SYSTEM.md` - Dream processing (Freud/Iris dialogue)
- `docs/EMOTIONAL_STATE.md` - Emotional state tracking (sentiment → decay → prompt)

### Other Documentation

- `docs/ARCHITECTURE.md` - Architecture overview and token budgets
- `docs/API_REFERENCE.md` - API endpoint reference
- `docs/MCP_TOOLS.md` - MCP tool development guide
- `docs/DATABASE.md` - Database schema reference
- `docs/DEPLOYMENT.md` - Deployment guide
- `EMOTIONAL_STATE_TRACKER.md` - Emotional state system (legacy, see `docs/EMOTIONAL_STATE.md`)
- `backend/knowledge/README.md` - Knowledge base / RAG system
- `PROTOCOL_SYSTEM_README.md` - Protocol configuration
- `scripts/README_NIGHTLY_MEMORY.md` - Memory creation cron

---

*Last updated: 2026-01-29*
