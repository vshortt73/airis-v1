# Iris v3 - Complete Data Flows

**Generated**: December 6, 2025

---

## Table of Contents

1. [Application Startup](#application-startup)
2. [User Message Processing](#user-message-processing)
3. [Tool Execution Flow](#tool-execution-flow)
4. [Image Upload & Attachment](#image-upload--attachment)
5. [Context Assembly](#context-assembly)
6. [Session Management](#session-management)
7. [Database Operations](#database-operations)
8. [MCP Server Communication](#mcp-server-communication)

---

## Application Startup

### Sequence

```
1. main.py imports config and modules
2. Create FastAPI app instance
3. Create ConversationHistory(enable_persistence=True)
   └─> Call database.persistence.get_or_create_session()
       ├─> Query: SELECT c_timestamp, session_id FROM chat_history ORDER BY c_timestamp DESC LIMIT 1
       ├─> Calculate time gap
       └─> If gap >= 30 min: Create new session
           If gap < 30 min: Continue existing session
   └─> Call database.persistence.load_recent_conversation()
       ├─> Get timestamps of last 30 user+assistant messages (across ALL sessions)
       ├─> Load ALL messages since oldest timestamp (includes tool messages)
       ├─> Apply message count limit (100 messages max)
       ├─> Apply token limit (12,000 tokens max, truncate oldest)
       └─> Return message list
4. Set active_conversation in route modules
5. Register API routers (chat, session, context)
6. Initialize ToolManager globally
   └─> Load tools from database: SELECT * FROM mcp_tools WHERE enabled = true
7. Start uvicorn server
```

### State After Startup

**In Memory**:
- `active_conversation.messages`: Recent conversation (across all sessions)
- `active_conversation.session_id`: Current session UUID (for analytics)
- `tool_manager.tools`: All enabled tool definitions
- `tool_manager.mcp_client`: MCP client (not yet connected)

**Database**:
- New session row in `chat_sessions` (or existing session found)
- All historical messages in `chat_history`

---

## User Message Processing

### Step-by-Step Flow

#### 1. WebSocket Message Received
```
routes_chat.py:websocket_chat()
  └─> await websocket.receive_json()
      └─> Extract: message (string), images (list of base64)
```

#### 2. Save User Message
```
active_conversation.add_user_message(message, images)
  └─> conversation.py:add_user_message()
      ├─> Create message dict: {"role": "user", "content": message}
      ├─> If images present:
      │   └─> For each image:
      │       └─> attachments.save_base64_image()
      │           ├─> Detect format (data URI or raw base64)
      │           ├─> Create directory: /attachments/user/{session_id}/
      │           ├─> Save file: user_upload_{idx}.png
      │           └─> Return metadata: {path, type, mime_type, size_bytes}
      ├─> Add attachments metadata to message
      ├─> Append message to self.messages list (in-memory)
      └─> persistence.save_message(session_id, "user", message, attachments)
          └─> INSERT INTO chat_history (...) VALUES (...)
```

#### 3. Assemble Context
```
system_prompt.assemble_full_context(active_conversation)
  └─> 3a. Build system message
      ├─> Load system_instructions: SELECT instruction_text FROM system_instructions WHERE active=true ORDER BY instruction_order
      ├─> Load traits: get_trait_list() → SELECT name, value, description FROM character_traits
      ├─> Load memories: get_memories("xml") → SELECT memory_text, metadata FROM episodic_memories
      └─> Concatenate: system_msg = {"role": "system", "content": instructions + traits + memories}
  
  └─> 3b. Process conversation messages
      ├─> Get all messages: conversation.get_messages()
      └─> For each message:
          ├─> Create base dict: {"role": role, "content": content}
          ├─> If message has tool_calls → add "tool_calls" field
          ├─> If message has tool_name → add "tool_name", "tool_call_id"
          └─> If message has attachments:
              ├─> Parse JSON: attachments.parse_attachments_json()
              ├─> For each attachment:
              │   └─> Load file: attachments.load_and_encode(path)
              │       ├─> Read file from disk
              │       └─> Encode to base64
              └─> Add "images": [base64_1, base64_2, ...]
  
  └─> Return: [system_msg, user_msg_1, assistant_msg_1, ..., user_msg_n]
```

#### 4. Get Tool Definitions
```
tool_manager.get_tool_definitions_for_ollama()
  └─> Return cached tool list (loaded at startup from database)
  └─> Format: [{"type": "function", "function": {"name": "...", "parameters": {...}}}]
```

#### 5. First Ollama Call (with tools, non-streaming)
```
ollama/client.py:chat_completion_with_tools(messages, tools)
  └─> Build payload:
      {
        "model": "qwen2.5:14b",
        "messages": [...],
        "tools": [...],
        "stream": false,
        "options": {"num_ctx": 32768, "temperature": 0.7}
      }
  └─> POST to http://localhost:11434/api/chat
  └─> Parse response:
      └─> If response.message.tool_calls → ToolCallResponse(has_tool_calls=True)
      └─> Else → ToolCallResponse(has_tool_calls=False, content="response text")
```

#### 6a. If Tool Called: Execute Tool
```
For each tool_call in response.tool_calls:
  └─> tool_manager.execute_tool(tool_name, parameters)
      ├─> Ensure MCP connected: await mcp_client.connect_all()
      │   └─> For each server in server_configs:
      │       └─> Start subprocess: python mcp_servers/{category}/{server}.py
      │       └─> Wait for ready signal
      ├─> mcp_client.call_tool(tool_name, parameters)
      │   ├─> Find server for tool_name
      │   ├─> Build JSON-RPC request: {"method": "tools/call", "params": {...}}
      │   ├─> Send to server stdin
      │   ├─> Read from server stdout
      │   └─> Parse JSON response
      └─> If tool returns image (filename in result):
          ├─> Load image file from /attachments/generated/{session_id}/
          ├─> Encode to base64
          └─> Add to tool_images list
      └─> Return: {success: true, tool_name: "...", result: {...}}
```

#### 6b. Save Tool Call & Results
```
1. Save assistant message with tool_calls:
   active_conversation.add_assistant_message(content="", tool_calls=response.tool_calls)
   └─> INSERT INTO chat_history (role='assistant', message='', tool_calls=<jsonb>)

2. For each tool result:
   active_conversation.add_tool_message(content=result, tool_name=name, images=tool_images)
   └─> Save image to disk if present
   └─> INSERT INTO chat_history (role='tool', message=result, tool_name=name, attachments=<jsonb>)
```

#### 6c. Reassemble Context with Tool Results
```
system_prompt.assemble_full_context(active_conversation)
  └─> Now includes:
      - System message
      - Previous conversation
      - User's new message
      - Assistant's tool_calls message
      - Tool result message(s) with images
```

#### 7. Second Ollama Call (streaming final response)
```
ollama/client.py:chat_completion_stream(messages)
  └─> Build payload: {... "stream": true ...}
  └─> POST to http://localhost:11434/api/chat (streaming)
  └─> For each line in response:
      ├─> Parse JSON: chunk = json.loads(line)
      ├─> Extract: chunk["message"]["content"]
      ├─> Yield text chunk
      └─> routes_chat.py sends to WebSocket: {"type": "chunk", "content": chunk}
```

#### 8. Save Final Response
```
active_conversation.add_assistant_message(full_response, images=tool_generated_images)
  └─> Save to database with any tool-generated images as attachments
```

### Data Transformations

**Input** (WebSocket):
```json
{
  "message": "What's the weather in Seattle?",
  "images": []
}
```

**After Context Assembly** (sent to Ollama):
```json
[
  {"role": "system", "content": "You are Iris..."},
  {"role": "user", "content": "Previous message"},
  {"role": "assistant", "content": "Previous response"},
  {"role": "user", "content": "What's the weather in Seattle?"}
]
```

**Ollama Response (with tool call)**:
```json
{
  "message": {
    "role": "assistant",
    "content": "",
    "tool_calls": [{
      "id": "call_123",
      "type": "function",
      "function": {
        "name": "weather_get",
        "arguments": {"location": "Seattle", "units": "imperial"}
      }
    }]
  }
}
```

**After Tool Execution**:
```json
[
  {"role": "system", "content": "..."},
  {"role": "user", "content": "What's the weather in Seattle?"},
  {"role": "assistant", "content": "", "tool_calls": [...]},
  {"role": "tool", "content": "Temperature: 45°F...", "tool_name": "weather_get"}
]
```

**Final Response (streamed)**:
```
"The current weather in Seattle is 45°F with partly cloudy skies..."
```

---

## Tool Execution Flow

### Example: Weather Tool

#### 1. Ollama Calls Tool
```json
{
  "function": {
    "name": "weather_get",
    "arguments": {"location": "Seattle", "units": "imperial"}
  }
}
```

#### 2. ToolManager Routes to MCP
```
tool_manager.execute_tool("weather_get", {location: "Seattle", units: "imperial"})
  └─> Look up server: mcp_tools table → server_name = "info"
  └─> Call mcp_client.call_tool("weather_get", params)
```

#### 3. MCP Client Sends to Server
```
MCP Request (JSON-RPC):
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "weather_get",
    "arguments": {"location": "Seattle", "units": "imperial"}
  }
}

Send to: info_server.py via stdin
```

#### 4. Server Processes Request
```python
# In info_server.py
@server.call_tool()
async def handle_call_tool(name, arguments):
    if name == "weather_get":
        location = arguments["location"]
        # Call weather API
        weather_data = await fetch_weather(location)
        return {
            "content": [{
                "type": "text",
                "text": json.dumps(weather_data)
            }]
        }
```

#### 5. MCP Client Receives Response
```
MCP Response:
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "content": [{
      "type": "text",
      "text": "{\"temperature\": 45, \"condition\": \"Partly Cloudy\"}"
    }]
  }
}
```

#### 6. Format for Conversation
```
Tool result message:
{
  "role": "tool",
  "content": "Temperature: 45°F, Condition: Partly Cloudy",
  "tool_name": "weather_get",
  "tool_call_id": "call_123"
}
```

---

## Image Upload & Attachment

### User Upload Flow

#### 1. Frontend Encodes Image
```javascript
// In static/index.html
const file = input.files[0];
const reader = new FileReader();
reader.onload = (e) => {
  const base64 = e.target.result;  // data:image/png;base64,iVBORw0K...
  images.push(base64);
};
```

#### 2. Send via WebSocket
```json
{
  "message": "What do you see in this image?",
  "images": ["data:image/png;base64,iVBORw0K..."]
}
```

#### 3. Save to Disk
```python
# In attachments.py:save_base64_image()
session_dir = f"/attachments/user/{session_id}"
os.makedirs(session_dir, exist_ok=True)

# Decode base64
if image_data.startswith("data:"):
    base64_data = image_data.split(",")[1]
else:
    base64_data = image_data

image_bytes = base64.b64decode(base64_data)

# Save file
filepath = f"{session_dir}/user_upload_0.png"
with open(filepath, 'wb') as f:
    f.write(image_bytes)
```

#### 4. Create Metadata
```python
metadata = {
    "path": filepath,
    "type": "image",
    "mime_type": "image/png",
    "size_bytes": len(image_bytes),
    "session_id": session_id,
    "is_user_upload": True
}
```

#### 5. Save to Database
```sql
INSERT INTO attachments (path, session_id, mime_type, filename, uploaded_at, attachment_type, is_user_upload)
VALUES ('/attachments/user/{uuid}/user_upload_0.png', '{uuid}', 'image/png', 'user_upload_0.png', NOW(), 'image', true);

-- Also save in chat_history
UPDATE chat_history 
SET attachments = '[{"path": "...", "type": "image", ...}]'::jsonb
WHERE id = <message_id>;
```

### Tool-Generated Image Flow

#### 1. Tool Returns Filename
```python
# In creative_server.py
return {
    "content": [{
        "type": "text",
        "text": json.dumps({
            "filename": "generated_image_123.png",
            "session_id": session_id,
            "response_instructions": "Here's the image you requested"
        })
    }]
}
```

#### 2. Load and Encode
```python
# In routes_chat.py
if "filename" in tool_result_data:
    filename = tool_result_data["filename"]
    session_id = tool_result_data["session_id"]
    image_path = f"/attachments/generated/{session_id}/{filename}"
    
    with open(image_path, 'rb') as f:
        image_base64 = base64.b64encode(f.read()).decode('utf-8')
        tool_images = [image_base64]
```

#### 3. Send to Frontend
```python
await websocket.send_json({
    "type": "image",
    "tool_name": tool_name,
    "image": image_base64,
    "filename": filename
})
```

#### 4. Attach to Message
```python
active_conversation.add_tool_message(
    content=tool_result,
    tool_name=tool_name,
    images=tool_images  # Saved to attachments/
)
```

---

## Context Assembly

### Complete Process

#### Input State
```python
conversation.messages = [
    {"role": "user", "content": "Hello", "attachments": null},
    {"role": "assistant", "content": "Hi!", "attachments": null},
    {"role": "user", "content": "Look at this", "attachments": '[{"path": "/attachments/user/..."}]'}
]
```

#### Step 1: Build System Message
```python
# Query database
instructions = """You are Iris, an AI assistant..."""
traits = """Traits: Curiosity=85, Humor=70..."""
memories = """<episodic_memories>...</episodic_memories>"""

system_msg = {
    "role": "system",
    "content": instructions + "\n\n" + traits + "\n\n" + memories
}
```

#### Step 2: Process Each Message
```python
formatted_messages = [system_msg]

for msg in conversation.messages:
    formatted = {
        "role": msg["role"],
        "content": msg["content"]
    }
    
    # Add tool fields if present
    if "tool_calls" in msg:
        formatted["tool_calls"] = msg["tool_calls"]
    if "tool_name" in msg:
        formatted["tool_name"] = msg["tool_name"]
    
    # Load images if present
    if msg.get("attachments"):
        attachments_list = json.loads(msg["attachments"])
        images = []
        
        for att in attachments_list:
            if att["type"] == "image":
                with open(att["path"], 'rb') as f:
                    base64_img = base64.b64encode(f.read()).decode()
                    images.append(base64_img)
        
        if images:
            formatted["images"] = images
    
    formatted_messages.append(formatted)
```

#### Output
```python
[
    {"role": "system", "content": "System prompt..."},
    {"role": "user", "content": "Hello"},
    {"role": "assistant", "content": "Hi!"},
    {"role": "user", "content": "Look at this", "images": ["base64..."]}
]
```

---

## Session Management

### Time-Based Session Creation

#### Scenario 1: Continuing Session
```
Current time: 2025-12-06 15:00:00
Last message: 2025-12-06 14:45:00
Time gap: 15 minutes

Action:
  └─> Gap < 30 minutes → Continue existing session
  └─> Return: existing session_id
  └─> No new row in chat_sessions
```

#### Scenario 2: New Session
```
Current time: 2025-12-06 15:00:00
Last message: 2025-12-06 14:15:00
Time gap: 45 minutes

Action:
  └─> Gap >= 30 minutes → Create new session
  └─> Generate new UUID: "f47ac10b-58cc-4372-a567-0e02b2c3d479"
  └─> INSERT INTO chat_sessions (session_id, start_time, end_time, message_count)
      VALUES ('f47ac10b...', '2025-12-06 15:00:00', '2025-12-06 15:00:00', 0)
```

### Memory Loading (Session-Independent!)

```sql
-- CRITICAL: No WHERE session_id clause!

-- Get last 30 conversation turns (user+assistant pairs)
SELECT c_timestamp FROM chat_history
WHERE role IN ('user', 'assistant')
ORDER BY c_timestamp DESC
LIMIT 60;  -- 30 pairs * 2

-- Get ALL messages since oldest timestamp (includes tools)
SELECT role, message, tool_calls, attachments
FROM chat_history
WHERE c_timestamp >= <oldest_timestamp>
ORDER BY c_timestamp ASC;

-- Result: Messages from multiple sessions!
```

**Example Result**:
```
Session A (11:00-11:25):
  - User: "Hello"
  - Assistant: "Hi!"
  
Session B (11:50-12:15): [30 min gap → new session]
  - User: "What's the weather?"
  - Tool: "65°F"
  - Assistant: "It's 65°F"

Both loaded into context! Session boundaries are transparent to memory.
```

---

## Database Operations

### Save Message
```sql
INSERT INTO chat_history (
    role, message, c_timestamp, session_id, system_version,
    tool_calls, tool_call_id, tool_name, attachments
)
VALUES (
    'user',
    'Hello, Iris!',
    '2025-12-06 15:00:00',
    'f47ac10b-58cc-4372-a567-0e02b2c3d479',
    '3.0',
    null,
    null,
    null,
    null
);
```

### Load Tools
```sql
SELECT tool_name, server_name, description, schema, enabled, requires_confirmation, icon
FROM mcp_tools
WHERE enabled = true
ORDER BY priority DESC;
```

### Update Session
```sql
UPDATE chat_sessions
SET message_count = message_count + 1,
    end_time = NOW()
WHERE session_id = 'f47ac10b...';
```

---

## MCP Server Communication

### Server Lifecycle

#### Startup
```
1. MCPClient.connect_all()
2. For each server in server_configs:
   └─> subprocess.Popen([
        "python",
        "mcp_servers/info/info_server.py"
      ], stdin=PIPE, stdout=PIPE, stderr=PIPE)
3. Wait for server ready message
4. Store process handle
```

#### Tool Call
```
1. Build JSON-RPC request:
   {
     "jsonrpc": "2.0",
     "id": <unique_id>,
     "method": "tools/call",
     "params": {
       "name": "weather_get",
       "arguments": {"location": "Seattle"}
     }
   }

2. Send to server.stdin
3. Read from server.stdout (with timeout)
4. Parse JSON response
5. Return result to ToolManager
```

#### Shutdown
```
1. MCPClient.disconnect_all()
2. For each server process:
   └─> Send SIGTERM
   └─> Wait for exit
   └─> Close stdin/stdout/stderr
```

### Error Handling

#### Server Crash
```
1. Tool call fails with exception
2. ToolManager catches error
3. Return: {success: false, error: "Server not responding"}
4. Routes send error to WebSocket
5. User sees: "Tool execution failed"
```

#### Timeout
```
1. Server takes > 120 seconds
2. AsyncIO timeout exception
3. Kill server process
4. Restart server on next call
```

---

**Data Flows Documentation Complete**
