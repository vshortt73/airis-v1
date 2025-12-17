# Iris v3 - File-by-File Breakdown

**Generated**: December 6, 2025  
**Total Files**: 33 Python files  
**Total Lines**: ~6,100 lines

---

## Directory Structure

```
iris-v3/
├── app/                       # FastAPI application
│   ├── config.py              # All configuration settings
│   ├── main.py                # Application entry point
│   └── api/                   # API routes
│       ├── routes_chat.py     # WebSocket chat endpoint
│       ├── routes_session.py  # Session management
│       └── routes_context.py  # Context inspection
├── core/                      # Core functionality
│   ├── conversation.py        # Conversation history manager
│   ├── system_prompt.py       # System prompt assembly
│   ├── token_counter.py       # Token counting (tiktoken)
│   └── attachments.py         # Image/file handling
├── database/                  # Database operations
│   ├── persistence.py         # Session & message storage
│   ├── character_traits.py    # Trait loading
│   ├── memory_loader.py       # Memory retrieval
│   └── tool_loader.py         # Tool definition loading
├── ollama/                    # Ollama API client
│   └── client.py              # Streaming & tool calling
├── mcp_servers/               # MCP tool system
│   ├── tool_manager.py        # Tool orchestration
│   ├── tool_loader.py         # Tool discovery
│   ├── mcp_client.py          # MCP communication
│   ├── server_configs.py      # Server configuration
│   ├── base/                  # Base server class
│   ├── info/                  # Info tools (weather, etc)
|       └──info_server.py      # none system information server (weather etc..)
│   ├── traits/                # Personality management
|       └── traits_server.py   # traits management server 
│   ├── system/                # System status control
|       └── system_server.py   # system stratus tool server
|   └── creative/              # Image generation
|       └── creative_server.py # creative managemnt server 
├── static/                    # Frontend
│   └── index.html             # Chat interface
├── scripts/                   # Utility scripts
└── tests/                     # Test files



---

## app/config.py

**Purpose**: Central configuration for all system settings

**Key Settings**:
- `OLLAMA_MODEL = "qwen2.5:14b"` - Current AI model
- `OLLAMA_CONTEXT_WINDOW = 32768` - Context window size (CRITICAL!)
- `SESSION_TIMEOUT_MINUTES = 30` - Session boundary threshold
- `MAX_CONVERSATION_TURNS = 30` - Turns to load
- `MAX_CONTEXT_TOKENS = 12000` - Token limit for conversation
- Token budgets for all components

**Used By**:
- `main.py` - Server configuration
- `ollama/client.py` - Model settings
- `database/persistence.py` - Context limits
- `core/system_prompt.py` - Feature flags

**Dependencies**: None (pure configuration)

**Example**:
```python
# Change model
OLLAMA_MODEL = "llama3.3:70b"

# Adjust session timeout
SESSION_TIMEOUT_MINUTES = 60

# Increase conversation memory
MAX_CONVERSATION_TURNS = 50
```

---

## app/main.py

**Purpose**: FastAPI application entry point

**Responsibilities**:
- Initialize FastAPI app
- Create ConversationHistory instance
- Register API routers
- Serve web interface
- Health check endpoint

**Key Functions**:
- `app = FastAPI()` - Create app
- `active_conversation = ConversationHistory()` - Init conversation
- `app.include_router()` - Register routes

**API Endpoints**:
- `GET /` - Serve index.html
- `GET /api/health` - System status
- `GET /prompt` - View system prompt

**Dependencies**:
- `config` - Configuration
- `core.conversation` - History management
- `app.api` - All route modules

**Example**:
```python
# Run directly
python app/main.py

# Or via uvicorn
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

---

## app/api/routes_chat.py

**Purpose**: WebSocket chat endpoint with tool calling

**Lines**: ~329 lines  
**Complexity**: HIGH - Main conversation orchestration

**Key Functions**:
- `websocket_chat()` - Main WebSocket handler
- `ensure_tool_manager_connected()` - MCP connection
- `get_tool_icon()` - Load tool icons from DB

**Request Flow**:
1. Receive user message + images
2. Save to database
3. Assemble full context
4. Get tool definitions
5. Call Ollama with tools (non-streaming)
6. If tools called: execute → save results
7. Reassemble context with results
8. Stream final response from Ollama
9. Save assistant message

**WebSocket Messages**:
- `type: "start"` - Acknowledgment
- `type: "tool_executing"` - Tool running
- `type: "tool_result"` - Tool complete
- `type: "image"` - Generated image
- `type: "chunk"` - Response text
- `type: "done"` - Turn complete
- `type: "error"` - Error occurred

**Dependencies**:
- `core.system_prompt` - Context assembly
- `ollama.client` - Ollama API
- `mcp_servers.tool_manager` - Tool execution

**Example**:
```python
# WebSocket URL
ws://localhost:8000/ws/chat

# Message format
{
  "message": "What's the weather?",
  "images": ["base64..."]  # Optional
}
```

---

## core/conversation.py

**Purpose**: In-memory conversation history with database persistence

**Lines**: ~215 lines

**Key Functions**:
- `__init__()` - Load recent conversation from DB
- `add_user_message()` - Save user message with images
- `add_assistant_message()` - Save assistant response
- `add_tool_message()` - Save tool result with images
- `get_messages()` - Return all messages
- `reload_from_database()` - Refresh from DB

**Image Handling**:
- Saves images to disk via `attachments.py`
- Stores metadata in message
- Attaches to message for context loading

**Dependencies**:
- `database.persistence` - DB operations
- `core.attachments` - Image saving
- `app.config` - Configuration

**Critical Insight**: This is an in-memory cache of database messages. It doesn't define memory boundaries - those come from the database queries.

**Example**:
```python
conv = ConversationHistory(enable_persistence=True)
conv.add_user_message("Hello", images=["base64..."])
messages = conv.get_messages()  # All messages in memory
```

---

## core/system_prompt.py

**Purpose**: Assemble system prompt and full context with vision support

**Lines**: ~199 lines

**Key Functions**:
- `get_system_prompt()` - Load from database
- `build_system_message()` - Assemble system prompt
- `assemble_full_context()` - Build complete context with images
- `get_db_connection()` - Database connection

**Context Assembly**:
1. Load system instructions from DB
2. Get character traits (144 traits)
3. Load episodic memories (XML format)
4. Concatenate with spacing
5. Load conversation messages
6. Process image attachments
7. Format for Ollama

**Image Processing**:
- Parse `attachments` JSON from messages
- Load image files from disk
- Encode to base64
- Add to message as `images` array

**Dependencies**:
- `database.character_traits` - Trait loading
- `database.memory_loader_experimental` - Memory retrieval
- `core.attachments` - Image encoding

**Example Query**:
```sql
SELECT instruction_text FROM system_instructions 
WHERE active = true 
ORDER BY instruction_order;
```

---

## core/token_counter.py

**Purpose**: Token counting using tiktoken

**Lines**: ~75 lines

**Key Functions**:
- `TokenCounter.count_text()` - Count tokens in string
- `TokenCounter.count_message_tokens()` - Count message array tokens

**Encoding**: cl100k_base (GPT-4 tokenizer)

**Dependencies**: `tiktoken`

**Example**:
```python
count = TokenCounter.count_text("Hello, world!")
# Returns integer token count

messages_count = TokenCounter.count_message_tokens([
    {"role": "user", "content": "Hello"},
    {"role": "assistant", "content": "Hi!"}
])
```

---

## core/attachments.py

**Purpose**: Image and file attachment handling

**Lines**: ~350 lines

**Key Functions**:
- `save_base64_image()` - Save image to disk
- `load_and_encode()` - Load image and encode
- `serialize_attachments()` - Convert metadata to JSON
- `parse_attachments_json()` - Parse JSON to metadata

**Directory Structure**:
```
/attachments/
  user/{session_id}/         # User uploads
  generated/{session_id}/    # Tool outputs
```

**Metadata Format**:
```json
{
  "path": "/attachments/user/{session_id}/file.png",
  "type": "image",
  "mime_type": "image/png",
  "size_bytes": 12345,
  "session_id": "uuid",
  "is_user_upload": true
}
```

**Dependencies**: `base64`, `PIL`, `os`

---

## database/persistence.py

**Purpose**: Session and message storage with token-aware loading

**Lines**: ~327 lines

**Key Functions**:
- `get_or_create_session()` - Time-based session management
- `save_message()` - Save to chat_history
- `load_recent_conversation()` - Load with limits
- `get_recent_sessions()` - List sessions

**Critical Function**: `load_recent_conversation()`
```python
def load_recent_conversation(
    max_turns=30,
    max_tokens=12000,
    max_messages=100
):
    # 1. Get last N user+assistant timestamps (NO session filter!)
    # 2. Load ALL messages since oldest timestamp (includes tools)
    # 3. Build message list
    # 4. Apply message count limit
    # 5. Apply token limit (truncate oldest first)
```

**Session Logic**:
- If last message < 30 min ago: continue session
- If >= 30 min: create new session
- **Critical**: Sessions don't affect memory loading!

**Dependencies**:
- `core.token_counter` - Token counting
- `app.config` - Limits

---

## database/character_traits.py

**Purpose**: Load character traits for system prompt

**Lines**: ~50 lines

**Key Functions**:
- `get_trait_list()` - Load all traits
- `format_traits_for_prompt()` - Format for Ollama

**Example Output**:
```
Character Traits:
- Curiosity: 85/100 - Eager to learn
- Humor: 70/100 - Playful and witty
...
```

**Dependencies**: `psycopg2`

---

## database/memory_loader_experimental.py

**Purpose**: Load episodic memories in XML format

**Lines**: ~150 lines

**Key Functions**:
- `get_memories(format)` - Load memories
  - `"xml"` - Structured XML format
  - `"structured"` - JSON-like format
  - `"conversational"` - Natural language

**XML Format**:
```xml
<episodic_memories>
  <memory>
    <content>Victor mentioned he loves bees</content>
    <context>Discussion about hobbies</context>
    <timestamp>2025-12-01</timestamp>
  </memory>
</episodic_memories>
```

**Dependencies**: `psycopg2`, `pgvector`

---

## ollama/client.py

**Purpose**: Ollama API client with streaming and tool calling

**Lines**: ~147 lines

**Key Functions**:
- `chat_completion_with_tools()` - Non-streaming with tools
- `chat_completion_stream()` - Streaming response
- `ToolCallResponse` - Response wrapper class

**Tool Call Flow**:
1. First call: non-streaming with tools
2. Check if `tool_calls` in response
3. If yes: execute tools, update context
4. Second call: streaming for final response

**Critical Settings**:
```python
payload = {
    "model": config.OLLAMA_MODEL,
    "messages": messages,
    "stream": True/False,
    "options": {
        "num_ctx": config.OLLAMA_CONTEXT_WINDOW,  # MUST SET!
        "temperature": 0.7
    }
}
```

**Dependencies**: `httpx`, `app.config`

---

## mcp_servers/tool_manager.py

**Purpose**: Tool orchestration and execution

**Lines**: ~245 lines

**Key Functions**:
- `get_tool_definitions_for_ollama()` - Tool schemas
- `execute_tool()` - Run tool via MCP
- `connect()` - Connect to MCP servers
- `get_tool_manager()` - Singleton instance

**Tool Execution**:
```python
result = await tool_manager.execute_tool(
    tool_name="weather_get",
    parameters={"location": "Seattle"},
    require_confirmation=False
)

# Returns:
{
    "success": True,
    "tool_name": "weather_get",
    "result": {...},
    "error": None  # If failed
}
```

**Dependencies**:
- `mcp_servers.mcp_client` - MCP communication
- `mcp_servers.tool_loader` - Tool discovery
- `mcp_servers.server_configs` - Server settings

---

## mcp_servers/mcp_client.py

**Purpose**: MCP (Model Context Protocol) client

**Lines**: ~350 lines

**Key Functions**:
- `connect_all()` - Start all MCP servers
- `call_tool()` - Execute tool on server
- `disconnect_all()` - Cleanup

**Server Communication**:
- Stdio-based JSON-RPC
- Subprocess management
- Request/response correlation

**Dependencies**: `fastmcp`, `subprocess`, `asyncio`

---

## mcp_servers/server_configs.py

**Purpose**: MCP server configuration

**Lines**: ~150 lines

**Key Functions**:
- `get_server_configs()` - Return all configs
- `is_tool_autonomous()` - Check if tool needs confirmation

**Server Definitions**:
```python
{
    "info": {
        "command": "python",
        "args": ["mcp_servers/info/info_server.py"],
        "env": {...}
    },
    ...
}
```

**Dependencies**: None

---

## mcp_servers/tool_loader.py

**Purpose**: Load tool definitions from database

**Lines**: ~140 lines

**Key Functions**:
- `load_enabled_tools()` - Get all enabled tools
- `get_tool_by_name()` - Get specific tool

**Tool Format** (Ollama-compatible):
```python
{
    "type": "function",
    "function": {
        "name": "weather_get",
        "description": "Get current weather",
        "parameters": {
            "type": "object",
            "properties": {
                "location": {"type": "string"}
            },
            "required": ["location"]
        }
    }
}
```

**Dependencies**: `database.persistence`

---

## MCP Server Files

### mcp_servers/info/info_server.py
**Purpose**: Information retrieval tools  
**Tools**: weather_get, news_search, web_search  
**Lines**: ~200 lines

### mcp_servers/traits/traits_server.py
**Purpose**: Personality trait management  
**Tools**: view_trait, modify_trait, list_traits  
**Lines**: ~250 lines

### mcp_servers/creative/creative_server.py
**Purpose**: Image generation via ComfyUI  
**Tools**: generate_image  
**Lines**: ~400 lines  
**Complex**: ComfyUI workflow management

---

## static/index.html

**Purpose**: Web chat interface

**Lines**: ~600 lines

**Features**:
- WebSocket connection
- Message rendering
- Image upload
- Tool execution display
- Markdown rendering

**JavaScript**:
- WebSocket handling
- Base64 image encoding
- Async message streaming

---

## Common Development Tasks

### Changing the AI Model
**File**: `app/config.py`
```python
OLLAMA_MODEL = "llama3.3:70b"  # Change this
```

### Adjusting Context Window
**File**: `app/config.py`
```python
OLLAMA_CONTEXT_WINDOW = 65536  # Increase
MAX_CONTEXT_TOKENS = 20000     # Adjust limit
```

### Modifying System Prompt
**Database**: 
```sql
UPDATE system_instructions 
SET instruction_text = 'New prompt...'
WHERE instruction_name = 'base_identity';
```

### Adding New Tool
1. Create MCP server in `mcp_servers/{category}/`
2. Add to `server_configs.py`
3. Insert into database:
```sql
INSERT INTO mcp_tools (tool_name, server_name, schema, enabled)
VALUES ('new_tool', 'my_server', '...'::jsonb, true);
```
4. Restart application

### Changing Session Timeout
**File**: `app/config.py`
```python
SESSION_TIMEOUT_MINUTES = 60  # 1 hour instead of 30 min
```

### Debugging Context Issues
**File**: `app/config.py`
```python
CONTEXT_DEBUG = True  # Enable detailed logging
```

Then check logs for token counts and message details.

---

## File Statistics

| Category | Files | Lines |
|----------|-------|-------|
| App & Routes | 5 | ~600 |
| Core Logic | 4 | ~900 |
| Database | 5 | ~750 |
| Ollama | 1 | ~150 |
| MCP System | 8 | ~1,800 |
| MCP Servers | 10 | ~2,000 |
| **Total** | **33** | **~6,100** |

---

## Dependency Graph

```
main.py
  → routes_chat.py
      → conversation.py
          → persistence.py
          → attachments.py
      → system_prompt.py
          → character_traits.py
          → memory_loader_experimental.py
      → ollama/client.py
      → tool_manager.py
          → mcp_client.py
              → info_server.py
              → traits_server.py
              → creative_server.py
```

---

**Documentation Generated**: December 6, 2025
