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
- Dual-Ollama vision system with GPU isolation (main: qwen3:32b on GPU 0, vision: llava on GPU 1)
- Episodic memory retrieval with semantic embeddings
- Protocol system for configurable personality modes
- WebSocket-based real-time chat interface

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

# Test protocol system
python test_protocol_system.py

# Test embeddings (memory system)
python test_embedding_insert.py

# Test traits server
python -m pytest tests/test_traits_server.py
```

## Core Architecture

### Critical Design Principles

1. **Session-Independent Memory**: Conversation loading happens ACROSS ALL SESSIONS. The `load_recent_conversation()` function in `database/persistence.py` does NOT filter by `session_id`. Sessions are for analytics only.

2. **Time-Based Session Detection**: New sessions are created when gap ≥ 30 minutes (configurable via `SESSION_TIMEOUT_MINUTES`), but this doesn't affect conversation continuity.

3. **Token-Aware Context Management**: Uses tiktoken (`cl100k_base` encoding) for accurate token counting. Context is limited by:
   - `MAX_CONVERSATION_TURNS = 30` (primary limit: user+assistant pairs)
   - `MAX_CONTEXT_TOKENS = 12000` (hard token limit)
   - `MAX_TOTAL_MESSAGES = 100` (safety brake)

4. **Explicit Ollama Context Window**: ALWAYS sets `num_ctx: OLLAMA_CONTEXT_WINDOW` in API calls. Default is 32768 tokens (NEVER use Ollama's default 4096).

5. **MCP-Based Tool Architecture**: Tools are implemented as MCP (Model Context Protocol) servers. Each server runs as a separate process, managed by FastMCP client connections.

6. **Vision Support**: Dual-Ollama architecture for vision capabilities. Primary model (qwen3:32b) handles text/tools on GPU 0, while dedicated vision model (llava) runs on GPU 1 for image analysis on demand.

7. **Protocol System**: Database-driven personality configuration system allowing preset modes (e.g., "Theta" for strangers, "Professional" for work). Protocols control system instructions, traits, tool availability, and memory visibility. **Note**: GUI and API implemented, runtime integration pending.

### Module Structure

```
app/
├── config.py              # All configuration (context limits, DB credentials, token budgets)
├── main.py                # FastAPI app initialization
└── api/
    ├── routes_chat.py     # WebSocket chat endpoint with tool calling
    ├── routes_session.py  # Session management endpoints
    └── routes_context.py  # Context inspection endpoints

core/
├── conversation.py        # In-memory conversation history manager
├── system_prompt.py       # DB-driven system prompt assembly with vision support
├── token_counter.py       # tiktoken-based token counting
├── attachments.py         # Image/file storage and encoding
├── embeddings.py          # Embedding generation for episodic memory
└── vision_manager.py      # Vision model lifecycle and request coordination

database/
├── persistence.py                    # Session & message storage, context-aware loading
├── character_traits.py               # Loads personality traits from fulltraits table
├── memory_loader.py                  # Episodic memory retrieval (production)
├── memory_loader_experimental.py     # Enhanced memory retrieval with semantic search
└── tool_loader.py                    # Tool definitions from mcp_tools table

ollama/
└── client.py              # Streaming chat API client with tool calling (dual non-streaming + streaming pattern)

mcp_servers/
├── server_configs.py      # MCP server registry and tool routing
├── mcp_client.py          # FastMCP client for tool execution
├── tool_manager.py        # Global tool manager singleton
├── tool_loader.py         # Load tool definitions from database
├── base/                  # Base server classes and utilities
├── info/                  # Info server (weather, news, web fetch, webcam)
├── traits/                # Traits server (personality management)
├── system/                # System server (health monitoring)
└── protocols/             # Protocol server (personality mode management)
```

### Key Data Flow

1. **Initialization** (`app/main.py`):
   - Creates `ConversationHistory(enable_persistence=True)`
   - Calls `get_or_create_session()` → determines session based on time gap
   - Calls `load_recent_conversation()` → loads history across ALL sessions
   - Initializes `ToolManager` → loads tool definitions from database

2. **Message Handling** (`app/api/routes_chat.py`):
   - User message → `add_user_message()` → saves to DB with image attachments
   - Build context: `assemble_full_context()` → system message + conversation history + loaded images
   - Get tool definitions: `tool_manager.get_tool_definitions_for_ollama()`
   - First Ollama call (non-streaming) with tools → check if tools requested
   - If tools requested:
     - Execute tools via `tool_manager.execute_tool()`
     - Add tool results to conversation
     - Second Ollama call (streaming) for final response
   - If no tools: use direct response from first call
   - Assistant message → `add_assistant_message()` → saves to DB

3. **Context Assembly** (`core/system_prompt.py`):
   - System instructions (from `system_instructions` table)
   - Character traits (from `fulltraits` table)
   - Episodic memories (from `episodic_memory` table in XML format)
   - Conversation history with loaded images from disk

4. **Tool Execution** (`mcp_servers/`):
   - Tool request → `ToolManager.execute_tool()`
   - Route to correct MCP server via `MCPClient`
   - Execute via FastMCP's `client.call_tool()`
   - Return JSON result to conversation

### Database Schema

**Critical Tables**:
- `chat_history`: Stores all messages with role, content, timestamp, session_id, tool_calls, attachments (JSONB)
- `chat_sessions`: Session metadata (for analytics, NOT for memory boundaries)
- `system_instructions`: Active system prompt components (ordered by `instruction_order`)
- `fulltraits`: Personality trait settings (name/value pairs)
- `chat_history_with_temporal`: View that adds temporal descriptions to messages
- `episodic_memory`: Long-term memory storage with metadata and embeddings (vector similarity search)
- `mcp_tools`: Tool definitions in Ollama format with icons and server routing
- `protocols`: Preset personality configurations (controls instructions, traits, tools, history/memory visibility)

**Important**: The conversation loader queries `chat_history` WITHOUT session_id filters to maintain continuity.

### Configuration Management

All settings in `app/config.py`:

**Session Management**:
- `SESSION_TIMEOUT_MINUTES = 30` - Gap threshold for new sessions

**Context Limits**:
- `MAX_CONVERSATION_TURNS = 30` - Primary limit
- `MAX_CONTEXT_TOKENS = 12000` - Token safety limit
- `MAX_TOTAL_MESSAGES = 100` - Absolute message limit

**Token Budgets** (defined but not all fully implemented):
- System prompt base: 600 tokens
- Character traits: 200 tokens
- Response generation: 2500 tokens
- Conversation history: 7000 tokens
- Episodic memory: 2500 tokens
- Tool definitions/results: 2300 tokens

**Ollama**:
- `OLLAMA_BASE_URL = "http://localhost:11434"` - Main Ollama (GPU 0)
- `OLLAMA_MODEL = "qwen3:32b"` - Primary model for text/tools
- `OLLAMA_CONTEXT_WINDOW = 65536` - 64K context window (CRITICAL: Always set explicitly)
- `VISION_OLLAMA_URL = "http://localhost:11435"` - Vision Ollama (GPU 1)
- `OLLAMA_VISION_MODEL = "llava:7b"` - Dedicated vision model
- `OLLAMA_MEMORY_URL = "http://localhost:11436"` - Memory processing Ollama
- `OLLAMA_MEMORY_MODEL = "qwen2.5:14b"` - Memory/embeddings model

**Database**:
- Use `IRIS_DB_PASSWORD` environment variable (preferred)
- Falls back to `DB_PASSWORD` in config.py

**Vision System** (see VISION_ARCHITECTURE.md for details):
- Dual-Ollama setup with GPU isolation
- Vision model loads on-demand, auto-unloads after 5 min idle
- Enables ComfyUI/XTTS use on GPU 1 when vision inactive

### Message Format (Ollama)

System uses proper Ollama message format:

```python
{
    "role": "user|assistant|tool|system",
    "content": "message text",
    "images": ["base64_string"],  # For vision
    "tool_calls": [...],          # For assistant messages
    "tool_name": "...",           # For tool messages
    "tool_call_id": "..."         # For tool messages
}
```

### Tool Calling Flow

**Dual-Call Pattern** (used in `routes_chat.py`):
1. **First Call** (non-streaming with tools): Send user message + tool definitions to Ollama
2. **Tool Decision**: Ollama decides whether to call tools or respond directly
3. **If tools requested**:
   - Execute tools via `ToolManager.execute_tool()`
   - Add tool results to conversation as "tool" role messages
   - **Second Call** (streaming): Send updated conversation with tool results back to Ollama
   - Stream final response to user
4. **If no tools**: Stream the direct response from first call

**Tool Execution Details**:
1. **Tool Discovery**: `tool_loader.py` reads from `mcp_tools` table
2. **Tool Registration**: `server_configs.py` maps tools to MCP servers
3. **Connection**: `ToolManager` initializes `MCPClient` with server configs
4. **Execution**:
   - Extract function name and arguments from Ollama's tool_calls
   - Route to correct server via `tool_to_server` mapping
   - Execute via FastMCP's stdio transport
   - Return JSON result to conversation
5. **Autonomous Tools**: Some tools (like weather, news) execute without confirmation; others require user approval

### Image Handling

**Storage** (`core/attachments.py`):
- User uploads: `attachments/user/{session_id}/`
- Generated images: `attachments/generated/{session_id}/`
- Metadata stored as JSONB in `chat_history.attachments`

**Loading**:
- `assemble_full_context()` loads images from disk
- Encodes to base64 and adds to message `images` array
- Ollama receives images in native format (no data URI prefix)

**Supported Formats**: PNG, JPG, JPEG, GIF, WebP

## Common Patterns

### Adding Messages to History

```python
# User message
active_conversation.add_user_message(content, images=None)

# Assistant message
active_conversation.add_assistant_message(content, tool_calls=None, images=None)

# Tool message
active_conversation.add_tool_message(content, tool_name, tool_call_id=None)
```

### Database Connections

All database modules use the same pattern:
```python
def get_db_connection():
    password = os.environ.get('IRIS_DB_PASSWORD') or getattr(config, 'DB_PASSWORD', None)
    conn_params = {
        'host': config.DB_HOST,
        'port': config.DB_PORT,
        'database': config.DB_NAME,
        'user': config.DB_USER
    }
    if password:
        conn_params['password'] = password
    return psycopg2.connect(**conn_params)
```

### Path Setup

Files use this pattern to ensure imports work:
```python
import os, sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)
```

### Creating New MCP Tools

1. Add tool definition to `mcp_tools` table (JSON schema in Ollama format):
   ```sql
   INSERT INTO mcp_tools (name, description, parameters, icon, server_name) VALUES (
       'my_tool',
       'Description of what this tool does',
       '{"type": "object", "properties": {...}, "required": [...]}',
       '🔧',
       'my_server'
   );
   ```
2. Add tool implementation to appropriate server (e.g., `mcp_servers/info/info_server.py`):
   ```python
   @mcp.tool()
   def my_tool(arg1: str, arg2: int) -> str:
       """Tool description"""
       # Implementation
       return json.dumps({"success": True, "result": {...}})
   ```
3. Register tool in `server_configs.py` under correct server's `tools` array
4. Mark as autonomous or confirmation-required in `get_autonomous_tools()` if needed

### Adding New MCP Server

1. Create server directory: `mcp_servers/{name}/`
2. Implement server: `{name}_server.py` using FastMCP:
   ```python
   from mcp import FastMCP
   mcp = FastMCP("Server Name")

   @mcp.tool()
   def my_tool(param: str) -> str:
       return json.dumps({"success": True, "result": "..."})

   if __name__ == "__main__":
       mcp.run()
   ```
3. Add config to `server_configs.py`:
   ```python
   {
       "name": "my_server",
       "command": "python",
       "args": [str(PROJECT_ROOT / "mcp_servers" / "my_server" / "my_server.py")],
       "tools": ["tool1", "tool2"]
   }
   ```
4. Add tool definitions to database `mcp_tools` table

## Important Implementation Details

### Token Counting Strategy

`database/persistence.py:182-298` implements sophisticated context loading:
1. Load last N user+assistant messages (across all sessions)
2. Include all tool messages within that timeframe
3. Truncate by message count if needed
4. Truncate by token count if needed (removes oldest messages first)

### System Prompt Assembly

`core/system_prompt.py` builds prompts from database:
- Queries `system_instructions` table for active instructions
- Orders by `instruction_order` field
- Appends character traits from `fulltraits` table
- Appends episodic memories in XML format
- Loads images from disk and adds to message context

### Tool Result Format

Tools must return JSON with this structure:
```python
{
    "success": True,
    "result": {...},      # Actual tool data
    "error": "..."        # If success=False
}
```

### Logging Pattern

All modules use detailed logging:
```python
print(f"[module.py][function] Message")  # Info
print(f"[module.py][function] ✓ Success message")  # Success
print(f"[module.py][function] ✗ Error: {e}")  # Error
```

## API Endpoints

**Chat**:
- `GET /` - Web interface
- `WS /ws/chat` - WebSocket chat endpoint (handles tool calling, images, streaming)
- `GET /prompt` - View assembled system prompt

**Context Inspection**:
- `GET /api/conversation/context` - Full context with messages
- `GET /api/conversation/context/summary` - Token stats only
- `GET /api/conversation/info` - Basic info

**Session Management**:
- `GET /api/sessions/recent` - List recent sessions
- `POST /api/sessions/new` - Create new session
- `POST /api/sessions/load/{id}` - Load specific session

**Protocol System** (see PROTOCOL_SYSTEM_README.md):
- `GET /api/protocols` - List all protocols
- `GET /api/protocols/{id}` - Get specific protocol
- `POST /api/protocols` - Create new protocol
- `PUT /api/protocols/{id}` - Update protocol
- `DELETE /api/protocols/{id}` - Delete protocol
- `GET /api/protocols/options/instructions` - Get available instructions
- `GET /api/protocols/options/traits` - Get available traits
- `GET /api/protocols/options/tools` - Get available tools
- Protocol Editor GUI: `http://localhost:8000/static/protocol_editor.html`

**Vision** (see VISION_ARCHITECTURE.md):
- `POST /api/vision/analyze` - Analyze single image
- `GET /api/vision/status` - Check vision model status

**Health**:
- `GET /api/health` - System status

## Environment Setup

Required environment variables:
- `IRIS_DB_PASSWORD` - PostgreSQL password (required)
- `PYTHONPATH` - Set to project root (handled by start.sh)

## Dependencies

Core dependencies (see requirements.txt):
- **FastAPI 0.109.0** - Web framework
- **uvicorn 0.27.0** - ASGI server
- **httpx 0.26.0** - Async HTTP client for Ollama
- **psycopg2-binary 2.9.9** - PostgreSQL adapter
- **tiktoken 0.5.2** - Token counting for context management
- **fastmcp >=0.1.0** - MCP client/server implementation
- **sentence-transformers >=2.2.0** - Embeddings for episodic memory
- **llama-cpp-python >=0.2.0** - Vision model integration (install with CUDA: `CMAKE_ARGS="-DGGML_CUDA=on" pip install llama-cpp-python`)
- **websockets >=12.0** - WebSocket support for real-time chat
- **bcrypt 4.1.2** - Password hashing for protocol passphrases

## Troubleshooting

**Database Connection Issues**:
- Ensure `IRIS_DB_PASSWORD` is set
- Test with: `python tests/test_database.py`

**Import Errors**:
- Set `PYTHONPATH`: `export PYTHONPATH="$(pwd):$PYTHONPATH"`
- Or use `./scripts/start.sh` which handles this

**Context/Token Issues**:
- Check token counts: `curl http://localhost:8000/api/conversation/context/summary`
- Enable debug logging: Set `CONTEXT_DEBUG = True` in `app/config.py`

**Ollama Connection**:
- Verify Ollama is running: `curl http://localhost:11434/api/tags`
- Check model name in `app/config.py`: `OLLAMA_MODEL`
- Verify context window setting: `OLLAMA_CONTEXT_WINDOW = 32768`

**Tool Execution Issues**:
- Test tool manager: `python mcp_servers/tool_manager.py`
- Test MCP client: `python mcp_servers/mcp_client.py`
- Check server status via logs or add endpoint
- Verify tool definitions in `mcp_tools` table

**Vision/Image Issues**:
- Check attachment paths: `ls attachments/user/` and `attachments/generated/`
- Verify base64 encoding doesn't include data URI prefix for Ollama
- Test attachment loading: `python -c "from core.attachments import load_and_encode; print(load_and_encode('path'))"`
- Check vision Ollama service: `systemctl status ollama-vision`
- Verify GPU 1 availability: `nvidia-smi`

**Ollama Service Management**:
- Main Ollama (GPU 0): `systemctl status ollama` (port 11434)
- Vision Ollama (GPU 1): `systemctl status ollama-vision` (port 11435)
- Memory Ollama: `systemctl status ollama-memory` (port 11436)
- Start script automatically checks and starts services if needed

## Additional Documentation

For detailed information on specific subsystems, see:
- **VISION_ARCHITECTURE.md** - Dual-Ollama vision system design and implementation
- **VISION_SETUP.md** - Step-by-step vision system installation guide
- **PROTOCOL_SYSTEM_README.md** - Protocol-based personality configuration system
- **PROTOCOL_MULTISTEP_GUIDE.md** - Multi-step protocol interaction patterns
- **SECURITY_CRITICAL_INSTRUCTIONS.md** - Security considerations for protocol passphrases
- **README_NIGHTLY_MEMORY.md** (scripts/) - Automated episodic memory creation via cron
- **TOOL_STORAGE_FIX.md** - Tool definition storage migration from code to database

## Key Implementation Notes

### GPU Isolation Strategy
- **GPU 0 (RTX 5090)**: Main Ollama with qwen3:32b - always loaded, handles all text/tools
- **GPU 1 (RTX 4080 Super)**: Vision Ollama with llava - on-demand loading, shares with ComfyUI/XTTS
- Use `CUDA_VISIBLE_DEVICES` environment variable to isolate GPU assignment
- Vision model auto-unloads after 5 minutes of inactivity to free VRAM

### Memory System
- **Episodic Memory**: Stored in `episodic_memory` table with vector embeddings
- **Semantic Search**: Uses sentence-transformers for similarity matching
- **Memory Retrieval**: `memory_loader.py` (production) or `memory_loader_experimental.py` (enhanced)
- **Nightly Creation**: Automated script (`scripts/nightly_memory_creation.sh`) runs via cron
- **Embedding Model**: sentence-transformers creates embeddings for semantic search

### Database Triggers
- `update_chat_history_updated_at`: Auto-updates timestamps on message edits
- Check trigger status: `./scripts/check_trigger_status.sh`
- Fix permissions if needed: `./scripts/fix_trigger_permissions.sh`

### Start Script Behavior
- Sets `IRIS_DB_PASSWORD` environment variable
- Checks all three Ollama services (main, vision, memory)
- Starts any stopped services automatically
- Sets `PYTHONPATH` for proper imports
- Launches uvicorn server on port 8000
