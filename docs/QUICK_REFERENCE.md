# Iris v3 - Quick Reference Guide
## "Where Do I Go to Change X?"

**Generated**: December 6, 2025

---

## Configuration Changes

### Change AI Model
**File**: `app/config.py`
```python
OLLAMA_MODEL = "llama3.3:70b"  # Change from qwen2.5:14b
```
**Restart Required**: Yes

### Adjust Context Window
**File**: `app/config.py`
```python
OLLAMA_CONTEXT_WINDOW = 65536  # Double from 32768
MAX_CONTEXT_TOKENS = 20000     # Also increase limit
```
**Restart Required**: Yes

### Change Session Timeout
**File**: `app/config.py`
```python
SESSION_TIMEOUT_MINUTES = 60  # 1 hour instead of 30 min
```
**Restart Required**: Yes

### Modify Token Budgets
**File**: `app/config.py`
```python
CONVERSATION_HISTORY_BUDGET = 10000  # More history
TOOL_DEFINITIONS_BUDGET = 2000       # More tools
EPISODIC_MEMORY_BUDGET = 3000        # More memory
```
**Restart Required**: Yes

### Enable/Disable Features
**File**: `app/config.py`
```python
SYSTEM_INSTRUCTIONS = True   # Base identity
CHARACTER_TRAITS = True      # Personality
EPISODIC_MEMORIES = False    # Disable memories
TOOLS_ENABLE = True          # MCP tools
```
**Restart Required**: Yes

### Change Database Connection
**File**: `app/config.py`
```python
DB_HOST = "db.example.com"
DB_PORT = 5432
DB_NAME = "iris_prod"
DB_USER = "iris_user"
# DB_PASSWORD via IRIS_DB_PASSWORD env var
```
**Restart Required**: Yes

---

## Conversation & Context

### Change Number of Turns Loaded
**File**: `app/config.py`
```python
MAX_CONVERSATION_TURNS = 50  # Load last 50 turns (100 messages)
```
**Restart Required**: Yes

### Adjust Token Limits
**File**: `app/config.py`
```python
MAX_CONTEXT_TOKENS = 20000   # Increase from 12,000
MAX_TOTAL_MESSAGES = 200     # Increase from 100
```
**Restart Required**: Yes

### Enable Debug Logging
**File**: `app/config.py`
```python
CONTEXT_DEBUG = True  # Detailed token counting info
```
**Restart Required**: Yes
**Output**: Check console for detailed context assembly logs

### Modify Context Assembly
**File**: `core/system_prompt.py`
**Function**: `assemble_full_context()`

Example - Add timestamp to each message:
```python
formatted_msg = {
    "role": msg["role"],
    "content": msg["content"],
    "timestamp": msg.get("c_timestamp", "")  # Add this
}
```

### Change System Prompt Content
**Database**: `system_instructions` table
```sql
-- View current prompts
SELECT * FROM system_instructions WHERE active = true ORDER BY instruction_order;

-- Update a prompt
UPDATE system_instructions
SET instruction_text = 'Your new prompt text here...'
WHERE instruction_name = 'base_identity';

-- Add new section
INSERT INTO system_instructions (instruction_name, instruction_text, instruction_order, active)
VALUES ('new_section', 'Content here...', 3, true);

-- Disable section
UPDATE system_instructions SET active = false WHERE instruction_name = 'section_name';
```
**Restart Required**: No (reloaded on each request)

---

## Tools & MCP Servers

### Add New Tool to Existing Server
1. **Add tool implementation** in server file
   **File**: `mcp_servers/{category}/{server}_server.py`
   ```python
   @server.call_tool()
   async def handle_call_tool(name, arguments):
       if name == "my_new_tool":
           result = await my_implementation(arguments)
           return result
   ```

2. **Add to database**
   ```sql
   INSERT INTO mcp_tools (tool_name, server_name, description, schema, enabled)
   VALUES (
       'my_new_tool',
       'info',
       'Description of what it does',
       '{"type": "object", "properties": {...}}'::jsonb,
       true
   );
   ```

3. **Restart application**

### Create New MCP Server
1. **Create server file**
   **File**: `mcp_servers/{category}/{server}_server.py`
   ```python
   from fastmcp import FastMCP
   
   server = FastMCP("My Server")
   
   @server.call_tool()
   async def handle_call_tool(name, arguments):
       if name == "tool_1":
           return {...}
   
   if __name__ == "__main__":
       server.run()
   ```

2. **Add configuration**
   **File**: `mcp_servers/server_configs.py`
   ```python
   def get_server_configs():
       return {
           "my_server": {
               "command": "python",
               "args": ["mcp_servers/category/my_server.py"],
               "env": {}
           }
       }
   ```

3. **Add tools to database**
   ```sql
   INSERT INTO mcp_servers (server_name, command, args, enabled)
   VALUES ('my_server', 'python', '["mcp_servers/category/my_server.py"]'::jsonb, true);
   
   INSERT INTO mcp_tools (tool_name, server_name, description, schema, enabled)
   VALUES ('tool_1', 'my_server', 'Tool description', '{...}'::jsonb, true);
   ```

4. **Restart application**

### Enable/Disable Specific Tool
**Database**:
```sql
-- Disable
UPDATE mcp_tools SET enabled = false WHERE tool_name = 'tool_name';

-- Enable
UPDATE mcp_tools SET enabled = true WHERE tool_name = 'tool_name';
```
**Restart Required**: Yes

### Make Tool Require Confirmation
**Database**:
```sql
UPDATE mcp_tools 
SET requires_confirmation = true 
WHERE tool_name = 'dangerous_tool';
```
**Restart Required**: Yes

### Change Tool Icon
**Database**:
```sql
UPDATE mcp_tools 
SET icon = '🌤️' 
WHERE tool_name = 'weather_get';
```
**Restart Required**: No (loaded per-request)

### Debug Tool Execution
**File**: `mcp_servers/tool_manager.py`
**Lines**: 116-160

Add print statements:
```python
async def execute_tool(self, tool_name, parameters, ...):
    print(f"[DEBUG] Executing {tool_name}")
    print(f"[DEBUG] Parameters: {parameters}")
    
    result = await self.mcp_client.call_tool(tool_name, parameters)
    
    print(f"[DEBUG] Result: {result}")
    return response
```

---

## API & Endpoints

### Add New WebSocket Message Type
**File**: `app/api/routes_chat.py`

Example - Add "typing" indicator:
```python
# Send typing indicator
await websocket.send_json({
    "type": "typing",
    "status": "started"
})

# Your existing code...

await websocket.send_json({
    "type": "typing",
    "status": "stopped"
})
```

**Frontend** (`static/index.html`):
```javascript
socket.onmessage = (event) => {
    const data = JSON.parse(event.data);
    
    if (data.type === "typing") {
        if (data.status === "started") {
            showTypingIndicator();
        } else {
            hideTypingIndicator();
        }
    }
};
```

### Add New REST Endpoint
**File**: `app/api/routes_context.py` (or create new router)

```python
@router.get("/api/my_endpoint")
async def my_endpoint():
    return {"message": "Hello"}
```

**Register in** `app/main.py`:
```python
from app.api import routes_my_module
app.include_router(routes_my_module.router)
```

### Modify Health Check
**File**: `app/main.py`
```python
@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "model": config.OLLAMA_MODEL,
        "custom_field": "my_value"  # Add this
    }
```

---

## Database Operations

### Add New Table
1. **Create migration SQL**
   ```sql
   CREATE TABLE my_table (
       id SERIAL PRIMARY KEY,
       data TEXT,
       created_at TIMESTAMP DEFAULT NOW()
   );
   ```

2. **Apply migration**
   ```bash
   psql -U irisuser -d irisdb -f migration.sql
   ```

3. **Add Python functions** (e.g., in `database/persistence.py`)

### Modify Existing Table
```sql
-- Add column
ALTER TABLE chat_history ADD COLUMN sentiment VARCHAR(50);

-- Add index
CREATE INDEX idx_chat_history_sentiment ON chat_history(sentiment);

-- Update config if needed
```

### Query Recent Messages
```sql
SELECT role, message, c_timestamp 
FROM chat_history 
ORDER BY c_timestamp DESC 
LIMIT 10;
```

### Query By Session
```sql
SELECT role, message 
FROM chat_history 
WHERE session_id = 'your-session-uuid'
ORDER BY c_timestamp ASC;
```

### Find Messages with Tools
```sql
SELECT message, tool_calls, tool_name
FROM chat_history
WHERE tool_calls IS NOT NULL OR tool_name IS NOT NULL
ORDER BY c_timestamp DESC
LIMIT 20;
```

### Backup Database
```bash
pg_dump -U irisuser irisdb > backup_$(date +%Y%m%d).sql
```

### Restore Database
```bash
psql -U irisuser -d irisdb < backup_20251206.sql
```

---

## File & Attachment Handling

### Change Attachment Directory
**File**: `core/attachments.py`
```python
BASE_ATTACHMENT_DIR = "/custom/path/attachments"  # Change from /attachments
```
**Restart Required**: Yes

### Add New File Type Support
**File**: `core/attachments.py`

```python
SUPPORTED_MIME_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "application/pdf": ".pdf",  # Add this
}
```

### Clean Old Attachments
```bash
# Delete attachments older than 30 days
find /attachments -type f -mtime +30 -delete

# Or keep only last 1000 files
cd /attachments && ls -t | tail -n +1001 | xargs rm -f
```

---

## Ollama Integration

### Change Ollama URL
**File**: `app/config.py`
```python
OLLAMA_BASE_URL = "http://remote-server:11434"
```

### Adjust Temperature
**File**: `ollama/client.py`
**Lines**: 64-66, 129-132
```python
"options": {
    "num_ctx": config.OLLAMA_CONTEXT_WINDOW,
    "temperature": 0.9,  # Change from 0.7
}
```

### Change Top-P / Top-K
**File**: `ollama/client.py`
```python
"options": {
    "num_ctx": config.OLLAMA_CONTEXT_WINDOW,
    "temperature": 0.7,
    "top_p": 0.9,     # Add this
    "top_k": 40,      # Add this
}
```

### Enable Streaming for Tools
**File**: `ollama/client.py`
Currently tool calls are non-streaming. To enable:

1. Change `stream: False` to `True` in `chat_completion_with_tools()`
2. Parse streaming JSON for tool_calls
3. Handle partial tool call chunks

---

## Token Management

### View Current Token Usage
```bash
curl http://localhost:8000/api/conversation/context/summary | jq
```

Response:
```json
{
  "total_messages": 15,
  "total_tokens": 8342,
  "system_prompt_tokens": 1234,
  "conversation_tokens": 7108,
  "limits": {
    "max_context_tokens": 12000,
    "max_conversation_turns": 30
  }
}
```

### Manually Truncate Context
**File**: `database/persistence.py`
**Function**: `load_recent_conversation()`

Force smaller context:
```python
messages = persistence.load_recent_conversation(
    max_turns=10,      # Only 10 turns
    max_tokens=5000,   # Only 5K tokens
    max_messages=50    # Max 50 messages
)
```

---

## Frontend / UI Changes

### Modify Chat Interface
**File**: `static/index.html`

Change theme:
```css
:root {
    --bg-color: #1a1a1a;        /* Change background */
    --text-color: #ffffff;      /* Change text */
    --user-color: #0084ff;      /* Change user bubble */
    --assistant-color: #e4e6eb; /* Change assistant bubble */
}
```

### Add Custom Message Type
**File**: `static/index.html`

JavaScript:
```javascript
socket.onmessage = (event) => {
    const data = JSON.parse(event.data);
    
    if (data.type === "my_custom_type") {
        handleCustomMessage(data);
    }
};
```

### Change WebSocket Reconnect Logic
**File**: `static/index.html`
```javascript
let reconnectAttempts = 0;
const maxReconnectAttempts = 10;  // Change from 5

function connect() {
    // ... existing code
}
```

---

## Testing & Debugging

### Test Database Connection
```bash
python tests/test_database.py
```

### Test Ollama Connection
```bash
curl http://localhost:11434/api/tags
```

### Test WebSocket
```bash
# Install websocat
websocat ws://localhost:8000/ws/chat

# Send message
{"message": "Hello", "images": []}
```

### View Full Context Sent to Ollama
```bash
curl http://localhost:8000/api/conversation/context | jq > context.json
```

### Enable Verbose Logging
**All Files**: Add print statements wrapped in config check
```python
if config.CONTEXT_DEBUG:
    print(f"[DEBUG] Variable: {variable}")
```

### Test Specific Tool
```bash
python tests/test_weather_tool.py
```

Or directly:
```bash
cd mcp_servers/info
python info_server.py
# Then send JSON-RPC request manually
```

---

## Deployment & Operations

### Start Server
```bash
# Development
python app/main.py

# Production (with uvicorn)
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

### Run as Systemd Service
**File**: `/etc/systemd/system/iris.service`
```ini
[Unit]
Description=Iris v3 AI Assistant
After=network.target postgresql.service

[Service]
Type=simple
User=iris
WorkingDirectory=/home/iris/iris-v3
Environment="IRIS_DB_PASSWORD=secret"
ExecStart=/usr/bin/python3 app/main.py
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable iris
sudo systemctl start iris
sudo systemctl status iris
```

### Monitor Logs
```bash
# If using systemd
sudo journalctl -u iris -f

# Or standard output
tail -f /var/log/iris.log
```

### Check Running Processes
```bash
# Iris server
ps aux | grep "app/main.py"

# MCP servers
ps aux | grep "mcp_servers"
```

### Restart After Code Changes
```bash
# If systemd
sudo systemctl restart iris

# Or kill and restart
pkill -f "app/main.py"
python app/main.py
```

---

## Common Issues & Solutions

### "Tool not found"
**Cause**: Tool not in database or disabled  
**Fix**: Check database:
```sql
SELECT tool_name, enabled FROM mcp_tools WHERE tool_name = 'your_tool';
```

### "Context overflow" or truncated conversation
**Cause**: Too many tokens  
**Fix**: Increase limits in `config.py`:
```python
MAX_CONTEXT_TOKENS = 20000
MAX_CONVERSATION_TURNS = 50
```

### Images not loading
**Cause**: File path incorrect or permissions issue  
**Fix**: Check paths:
```bash
ls -la /attachments/user/{session_id}/
ls -la /attachments/generated/{session_id}/
```

### Session not continuing
**Cause**: Gap exceeded timeout  
**Fix**: Increase timeout in `config.py`:
```python
SESSION_TIMEOUT_MINUTES = 60
```

### Tool execution timeout
**Cause**: MCP server slow or crashed  
**Fix**: Check server logs:
```bash
ps aux | grep mcp_servers  # Check if running
# Restart specific server
```

### Database connection failed
**Cause**: Wrong password or server down  
**Fix**: Set environment variable:
```bash
export IRIS_DB_PASSWORD='correct_password'
psql -U irisuser -d irisdb  # Test connection
```

---

## Best Practices

### Configuration
- ✅ Always set `OLLAMA_CONTEXT_WINDOW` explicitly
- ✅ Use environment variables for secrets
- ✅ Keep token budgets within context window
- ❌ Don't hardcode database passwords

### Database
- ✅ Back up regularly
- ✅ Add indexes for frequently queried columns
- ✅ Use transactions for multi-step operations
- ❌ Don't query database in loops (use JOINs)

### Tools
- ✅ Require confirmation for destructive operations
- ✅ Validate tool parameters before execution
- ✅ Return structured data in tool results
- ❌ Don't block on long-running operations (use async)

### Performance
- ✅ Cache tool definitions at startup
- ✅ Use connection pooling for database
- ✅ Stream responses for better UX
- ❌ Don't load all history (use limits)

### Error Handling
- ✅ Catch and log all exceptions
- ✅ Return user-friendly error messages
- ✅ Provide recovery paths
- ❌ Don't expose internal errors to users

---

## Quick Commands

```bash
# Start server
./scripts/start.sh

# Check health
curl http://localhost:8000/api/health

# View system prompt
curl http://localhost:8000/prompt

# View context
curl http://localhost:8000/api/conversation/context/summary | jq

# Check Ollama
curl http://localhost:11434/api/tags

# Database backup
pg_dump -U irisuser irisdb > backup.sql

# Clean old attachments
find /attachments -mtime +30 -delete

# Restart (systemd)
sudo systemctl restart iris

# View logs (systemd)
sudo journalctl -u iris -f
```

---

**Quick Reference Complete**
