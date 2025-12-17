# Tool Call Storage Fix

## Problem

Tool calls and tool responses were not being stored properly in the `chat_history` table.

## Root Causes

1. **JSON Serialization Missing**: In `database/persistence.py`, the `tool_calls` parameter was being inserted directly into PostgreSQL without JSON serialization, while `attachments` were properly converted.

2. **Wrong Data Structure**: In `app/api/routes_chat.py`, the code was passing `response.raw_response` (the entire Ollama response object) instead of just `response.tool_calls` (the tool_calls array).

3. **Missing Tool Call ID**: The code was not extracting and passing the `tool_call_id` from Ollama's response, so tool calls and their responses weren't linked together in the database.

## Changes Made

### 1. Fixed `database/persistence.py` (lines 155-163, 184-193)

**Before**:
```python
cursor.execute("""...""",
    (role, message, datetime.now(), session_id, '3.0',
     tool_calls,  # ← No JSON conversion!
     tool_call_id, tool_name, attachments_json))
```

**After**:
```python
# Convert tool_calls to JSON string if needed
tool_calls_json = None
if tool_calls:
    if isinstance(tool_calls, str):
        tool_calls_json = tool_calls
    elif isinstance(tool_calls, (dict, list)):
        import json
        tool_calls_json = json.dumps(tool_calls)
        print(f"[persistence.py][save_message] ✓ Serialized tool_calls to JSON ({len(tool_calls_json)} chars)")

cursor.execute("""...""",
    (role, message, datetime.now(), session_id, '3.0',
     tool_calls_json,  # ← Properly serialized!
     tool_call_id, tool_name, attachments_json))
```

### 2. Fixed `app/api/routes_chat.py` (line 183)

**Before**:
```python
active_conversation.add_assistant_message(
    content="",
    tool_calls=response.raw_response  # ← Full Ollama response object
)
```

**After**:
```python
active_conversation.add_assistant_message(
    content="",
    tool_calls=response.tool_calls  # ← Just the tool_calls array
)
```

### 3. Fixed `app/api/routes_chat.py` (lines 189, 196) - Extract tool_call_id

**Before**:
```python
for tool_call, result in zip(response.tool_calls, tool_results):
    function_info = tool_call.get("function", {})
    tool_name = function_info.get("name")

    active_conversation.add_tool_message(
        content=result_instructions + json.dumps(result.get("result", {})),
        tool_name=tool_name
        # Note: tool_call_id not provided by Ollama yet  ← WRONG!
    )
```

**After**:
```python
for tool_call, result in zip(response.tool_calls, tool_results):
    function_info = tool_call.get("function", {})
    tool_name = function_info.get("name")
    tool_call_id = tool_call.get("id")  # Extract the call ID

    active_conversation.add_tool_message(
        content=result_instructions + json.dumps(result.get("result", {})),
        tool_name=tool_name,
        tool_call_id=tool_call_id  # Pass the ID to link call and response
    )
```

### 4. Enhanced Logging (persistence.py lines 184-193)

Added detailed logging to verify tool-related data is being saved:
```python
log_details = f"{role} message ({len(message)} chars)"
if tool_calls_json:
    log_details += f" with tool_calls"
if tool_name:
    log_details += f" [tool: {tool_name}]"
if tool_call_id:
    log_details += f" [call_id: {tool_call_id}]"
```

## How It Works Now

### Saving Tool Calls (Assistant Message)

1. Ollama returns tool calls in response
2. `routes_chat.py` extracts `response.tool_calls` (just the array)
3. Passes to `conversation.add_assistant_message(tool_calls=...)`
4. `persistence.save_message()` serializes to JSON
5. Stored in `chat_history.tool_calls` as JSONB

### Saving Tool Results (Tool Message)

1. Tool execution completes
2. `routes_chat.py` calls `conversation.add_tool_message(content, tool_name)`
3. `persistence.save_message()` stores:
   - `role='tool'`
   - `message=<tool result JSON>`
   - `tool_name=<name>`
   - `tool_call_id=<id>` (if available)

### Loading from Database

1. `load_recent_conversation()` fetches from `chat_history`
2. PostgreSQL JSONB columns are automatically deserialized by psycopg2
3. Tool calls are added directly to message dict
4. `system_prompt.assemble_full_context()` handles both old and new formats

## Data Format

### Tool Calls (Assistant Message)
```json
{
  "role": "assistant",
  "content": "",
  "tool_calls": [
    {
      "function": {
        "name": "weather_get",
        "arguments": {"location": "Seattle", "units": "imperial"}
      }
    }
  ]
}
```

### Tool Result (Tool Message)
```json
{
  "role": "tool",
  "content": "{\"success\": true, \"temperature\": 65, ...}",
  "tool_name": "weather_get",
  "tool_call_id": "call_abc123"
}
```

The `tool_call_id` links the tool result back to the specific tool call in the assistant message.

## Testing

To verify the fix works:

1. Start the server: `./scripts/start.sh`
2. Make a request that triggers a tool call (e.g., ask about weather)
3. Check the logs for:
   - `✓ Serialized tool_calls to JSON`
   - `✓ Saved assistant message with tool_calls`
   - `│  Tool call ID: call_abc123`
   - `✓ Saved tool message [tool: weather_get] [call_id: call_abc123]`
4. Query the database:
   ```sql
   SELECT role, tool_calls, tool_name, tool_call_id
   FROM chat_history
   WHERE role IN ('assistant', 'tool')
   ORDER BY c_timestamp DESC
   LIMIT 5;
   ```

   You should see:
   - Assistant message with `tool_calls` JSONB containing the call with an `id`
   - Tool message with matching `tool_call_id` linking back to the call

## Compatibility

The code in `system_prompt.py` (lines 154-164) handles both:
- **New format**: `tool_calls` is the array directly
- **Old format**: `tool_calls` is nested in `{"message": {"tool_calls": [...]}}`

This ensures backward compatibility with any existing data.
