# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## ⚠️ IMPORTANT: READ THIS FIRST

**Before doing anything else, read `/iris-v3/IRIS_DEV_LOG.md`**

That file contains current session context, recent work, and what this project actually is. This file (CLAUDE.md) provides technical architecture. **Read IRIS_DEV_LOG.md first.**

---

## Project Overview

**Iris v3** is an AI assistant with PostgreSQL-backed conversation persistence, MCP tool architecture, and distributed two-node GPU management. Key capabilities: multi-turn conversation with cross-session memory, episodic memory retrieval, emotional state tracking, real-time video generation (FLOAT), TTS/STT, and meeting transcription.

---

## Distributed Architecture

**CRITICAL: Two-node system.** Services are distributed across localhost (iris-desktop) and Node2 (iris-node2).

**Localhost (RTX 5090 32GB):**
- Ollama (port 11434) - qwen3:32b primary inference
- Iris FastAPI Server (port 8000)
- PostgreSQL (port 5432)

**Node2 GPU 0 (RTX 4080S 16GB) - MUTUALLY EXCLUSIVE:**
- iris-vision (port 11435) - Pixtral 12B
- iris-float (port 8000) - FLOAT video
- iris-freud (port 11435) - gemma-3-4b dreams
- iris-transcribe (port 8500) - WhisperX
- comfyui (port 8189) - Stable Diffusion
- ⚠️ Only ONE runs at a time! Managed by GPU Manager.

**Node2 GPU 1 (RTX 3060 12GB) - COEXISTING:**
- iris-xtts (port 8700) - TTS
- iris-stt (port 8600) - Whisper ASR
- iris-sentiment (port 11437) - Mistral 7B

### GPU Manager (`core/gpu_manager.py`)

```python
from core.gpu_manager import request_gpu

success, error = await request_gpu("vision")  # or "float", "freud", "transcribe"
if success:
    result = await vision_service.analyze(image)
```

**Behavior:** Service loaded → immediate success. Different service needed → stops ALL GPU 0 services, starts requested. GPU busy → returns error.

**SSH config:** Reads `NODE2_HOST` and `NODE2_SSH_USER` from database (category `remote_services`).

### Node2 Feature Flags (`core/node2_check.py`)

```python
from core.node2_check import is_node2_service_enabled

if is_node2_service_enabled("TTS_ENABLED"):
    # TTS available
```

Master switch `NODE2_ENABLED` gates all Node2 functionality. Per-service flags: `TTS_ENABLED`, `STT_ENABLED`, `VIDEO_ENABLED`, `GPU_MANAGER_ENABLED`, `FLORENCE2_ENABLED`, `PADDLEOCR_ENABLED`, `DREAMS_ENABLED`, `TRANSCRIBE_ENABLED`.

---

## Development Commands

```bash
export IRIS_DB_PASSWORD='your_password'
source /venv/iris-v3/bin/activate
./scripts/start.sh  # Preferred method
```

Server runs on `http://localhost:8000`. See `docs/TROUBLESHOOTING.md` for testing commands.

---

## Critical Design Principles

1. **Session-Independent Memory**: `load_recent_conversation()` does NOT filter by `session_id`. Sessions are for analytics only.

2. **Time-Based Session Detection**: New sessions when gap ≥ 30 minutes, but doesn't affect conversation continuity.

3. **Token-Aware Context Management**: Uses tiktoken (`cl100k_base`) for accurate counting.

4. **Explicit Ollama Context Window**: Synced from llama-server's `/props` on startup. Current: 40,960 tokens.

5. **MCP-Based Tool Architecture**: Tools implemented as MCP servers.

6. **Distributed GPU Architecture**: Services split across localhost and Node2 with GPU Manager.

7. **Emotional State Tracking**: Sentiment analysis updates emotional state each turn.

8. **Prompt Snapshot with Per-Turn Tail**: Static prefix (instructions, traits, seeds, facts, dreams, semantic memories) frozen in snapshot — rebuilds only on spoilage or token overflow. Volatile data (datetime, emotional state, episodic memories, fast memory) lives in a per-turn tail message appended after conversation history. ~99% KV cache reuse.

9. **Thinking Block**: Qwen3 reasoning streamed via `reasoning_content` delta (NOT `<think>` tags). Excluded from DB/TTS.

10. **Prompt Effectiveness Pattern**: System prompt data blocks need CRITICAL RULES directive in instruction ID 103.

11. **Tool Result Token Budget (3-layer)**: (a) Per-result cap (15K tokens); (b) Cumulative cap (50% of context); (c) Preflight check.

12. **Preflight Context Check**: `inference/client.py` runs `preflight_check()` before every LLM call. Trims oldest messages if over budget.

13. **Autonomous Inner Drive System**: Background daemon (`services/drive_daemon.py`) tracks 7 internal state variables with drift/decay/noise. Persists to PostgreSQL. Phase 4 adds autonomous Telegram contact. All config DB-driven via category `drive`.

14. **Semantic Memory Consolidation**: Nightly pipeline clusters episodic memories by takeaway similarity, consolidates via LLM into distilled knowledge. Stored in `semantic_memories` table. Config category `semantic`.

15. **Memory Retrieval V2**: Inline episodic retrieval (~200ms) replaces 10-30s LLM-based pipeline. Direct embedding similarity across 6 facets + emotional resonance + recency decay. Config category `retrieval`.

16. **Gap Report ("While You Were Away")**: On first turn after >=30min gap, `core/gap_report.py` injects `<while_you_were_away>` XML into per-turn tail. Reports memory processing, dreams, and service health from the gap. Service events logged to `service_events` table by app/main.py, gpu_manager, service_status, and nightly scripts. Config category `gap_report`.

---

## MCP Tool Development - IMPORTANT

**Tool definitions exist in TWO places that MUST stay synchronized:**

1. **Python code** (`mcp_servers/*/server.py`) - The implementation
2. **Database** (`mcp_tools.input_schema`) - What the model sees

**THE MODEL ONLY SEES THE DATABASE SCHEMA.** Python parameters are invisible unless in `mcp_tools.input_schema`.

### When Adding/Modifying Tool Parameters:

1. Update Python function signature
2. **Create SQL to update `mcp_tools.input_schema`** - This gets missed!
3. Put SQL in `database/sql/`
4. Run the SQL
5. Restart Iris

```sql
-- Example: adding a parameter
UPDATE mcp_tools
SET input_schema = jsonb_set(
    input_schema::jsonb,
    '{properties,new_param}',
    '{"type": "string", "description": "Description here"}'::jsonb
)
WHERE tool_name = 'tool_name';

-- Check current schema
SELECT tool_name, input_schema FROM mcp_tools WHERE tool_name = 'seed';
```

---

## ComfyUI Workflows - IMPORTANT

The creative server (`mcp_servers/creative/`) uses ComfyUI on Node2.

**Workflow files:** `mcp_servers/creative/workflows/` (`iris.json`, `non-iris.json`, `newface.png`)

### CRITICAL: Workflow JSON Format

ComfyUI has TWO formats. The creative server requires **API format**:

**API format (CORRECT)** - flat dict, node IDs as keys:
```json
{"3": {"inputs": {...}, "class_type": "KSampler"}}
```

**UI format (WRONG)** - has `nodes`, `links`, `groups`:
```json
{"nodes": [...], "links": [...]}
```

**Use "Save (API Format)" or "Export (API)"**, NOT regular "Save".

The `inject_prompt()` function modifies by node ID: `"3"` = KSampler, `"5"` = EmptyLatentImage, `"6"` = Positive prompt, `"7"` = Negative prompt.

---

## Configuration - DATABASE IS SOURCE OF TRUTH

All config lives in `system_config` table. `config.py` contains fallback defaults only.

### When Adding/Modifying Configuration:

1. **Add to database FIRST** - Create SQL in `database/sql/`
2. **Update config.py** - Only as fallback
3. **Run the SQL**
4. **Restart Iris**

```bash
psql -h localhost -U irisuser -d irisdb -f database/sql/populate_system_config_complete.sql
```

**Config categories:** `llm`, `server`, `remote_services`, `identity`, `session`, `tokens`, `features`, `emotional`, `vision`, `face`, `knowledge`, `calendar`, `meeting`, `context`, `drive`, `semantic`, `retrieval`

**Key settings:** `SESSION_TIMEOUT_MINUTES`, `OLLAMA_CONTEXT_WINDOW`, `MAX_TOTAL_MESSAGES`, `NODE2_ENABLED`, `NODE2_HOST`, `NODE2_SSH_USER`

**Database connection:** `IRIS_DB_PASSWORD` env var required. Host: localhost, Port: 5432, DB: irisdb, User: irisuser

---

## Database Schema (Critical Tables)

- `chat_history` - Messages with role, content, timestamp, session_id, tool_calls
- `chat_sessions` - Session metadata (analytics only, NOT memory boundaries)
- `system_instructions` - System prompt components (ordered by instruction_order)
- `fulltraits` - Personality traits
- `episodic_memories` - Long-term memory with vector embeddings
- `semantic_memories` - Distilled knowledge from episodic memory clusters
- `live_memories` - Current turn's retrieved episodic memories (refreshed by retrieval v2)
- `mcp_tools` - Tool definitions with input_schema
- `system_config` - Runtime configuration
- `drive_state` / `drive_state_history` - Inner drive system state
- `service_events` - Service lifecycle events (startups, crashes, GPU swaps) for gap reports

---

## Documentation Index

**Architecture & Data Flow:**
- `docs/ARCHITECTURE.md` - Architecture overview and token budgets
- `docs/DATA_CONTRACTS.md` - Data shapes at module boundaries
- `docs/PROMPT_ASSEMBLY.md` - Prompt assembly pipeline

**Subsystems:**
- `docs/MEMORY_PIPELINE.md` - Memory generation
- `docs/DREAM_SYSTEM.md` - Dream processing
- `docs/EMOTIONAL_STATE.md` - Emotional state tracking
- `docs/iris_autonomous_drive_system.md` - Autonomous drive system
- `docs/GAP_REPORT.md` - "While You Were Away" gap report system
- `docs/MCP_TOOLS.md` - MCP tool development

**Operations:**
- `docs/TROUBLESHOOTING.md` - Debugging and testing commands
- `docs/DEPLOYABILITY_AUDIT.md` - Hardcoded dependency manifest
- `docs/DATABASE.md` - Schema reference
- `docs/DEPLOYMENT.md` - Deployment guide

**Other:**
- `backend/knowledge/README.md` - RAG system
- `PROTOCOL_SYSTEM_README.md` - Protocol configuration
- `scripts/README_NIGHTLY_MEMORY.md` - Memory creation cron

---

*Last updated: 2026-02-07*
