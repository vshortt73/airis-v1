# Iris Protocol System

A comprehensive protocol management system for configuring Iris's personality and operational modes.

## Overview

Protocols are preset configurations that control:
- System prompt instructions (which rules to include/exclude)
- Chat history visibility (main vs generic history)
- Memory injection (episodic memories in context)
- Personality traits (adjustable values)
- Tool availability (enable/disable specific tools)

## Components

### 1. Database Schema

**Table: `protocols`**
```sql
- id (auto-increment)
- name (varchar 100) - Protocol name
- description (text) - Purpose and behavior description
- instructions (text) - Additional instructions
- rules_include (json) - Array of instruction IDs to include
- rules_exclude (json) - Array of instruction IDs to exclude
- show_chat_history (boolean) - Enable chat history
- show_memories (boolean) - Enable memory injection
- traits_adjust (json) - Object mapping trait names to values
- tool_usage (json) - Object mapping tool names to enabled/disabled
```

### 2. Backend API

**File:** `/iris-v3/app/api/routes_protocols.py`

**Endpoints:**
- `GET /api/protocols` - List all protocols
- `GET /api/protocols/{id}` - Get specific protocol
- `POST /api/protocols` - Create new protocol
- `PUT /api/protocols/{id}` - Update protocol
- `DELETE /api/protocols/{id}` - Delete protocol
- `POST /api/protocols/{id}/duplicate` - Duplicate protocol

**Helper Endpoints:**
- `GET /api/protocols/options/instructions` - Get all system instructions
- `GET /api/protocols/options/traits` - Get all character traits
- `GET /api/protocols/options/tools` - Get all available tools

### 3. Protocol Editor GUI

**File:** `/iris-v3/static/protocol_editor.html`

**Access:** `http://localhost:8000/static/protocol_editor.html`

**Features:**
- ✅ Modern dark theme interface
- ✅ Protocol selection dropdown
- ✅ Create/Edit/Delete/Duplicate protocols
- ✅ Basic info editor (name, description)
- ✅ System settings toggles (chat history, memory injection)
- ✅ System instructions manager with toggles
- ✅ Character traits editor with value inputs
- ✅ Tools manager with enable/disable toggles
- ✅ Real-time status messages
- ✅ Responsive design

### 4. Default Protocol Generator

**File:** `/iris-v3/create_default_protocol.py`

**Usage:**
```bash
source /venv/iris-v3/bin/activate
python create_default_protocol.py
```

**What it does:**
- Reads current system state from database
- Gathers all active instructions
- Gathers all current trait values
- Gathers all enabled tools
- Creates "Default" protocol in database

## How It Works

### Instruction Management

Instructions can be in three states:
1. **Default Active** - Included by system_instructions.active=true
2. **Explicitly Included** - ID in rules_include (overrides default)
3. **Explicitly Excluded** - ID in rules_exclude (overrides default)

Example:
```json
{
  "rules_include": ["1", "2", "4", "5"],  // Force these on
  "rules_exclude": ["3", "6"]  // Force these off
}
```

### Trait Adjustment

Traits specified in `traits_adjust` override default values from `fulltraits` table.

Example:
```json
{
  "traits_adjust": {
    "Affection": "10",
    "Professionalism": "10",
    "Warmth": "3",
    "Obedience": "5"
  }
}
```

### Tool Control

Tools specified in `tool_usage` override default enabled/disabled state from `mcp_tools` table.

Example:
```json
{
  "tool_usage": {
    "weather_get": true,
    "linux_shell": false,
    "database_query": false
  }
}
```

### Chat History Control

When `show_chat_history = false`:
- System should use alternate "generic" chat history table
- Allows running context without contaminating main history
- Useful for multi-user scenarios

### Memory Injection Control

When `show_memories = false`:
- Episodic memories not injected into system prompt
- Keeps current dialogue separate from long-term memory associations
- Useful for professional/stranger interactions

## Usage Examples

### Example 1: "Theta" Protocol

**Purpose:** Social interaction with strangers, guard personal information

```json
{
  "name": "Theta",
  "description": "Warm social interaction mode for strangers. Guards personal info and internal systems.",
  "rules_include": ["2", "3", "5"],  // core_identity, speaking_tone, feature_set_real
  "rules_exclude": ["7"],  // Exclude context_continuity
  "show_chat_history": false,  // Use generic history
  "show_memories": false,  // No personal memories
  "traits_adjust": {
    "Warmth": "9",
    "Professionalism": "7",
    "Affection": "5",
    "Obedience": "3"
  },
  "tool_usage": {
    "weather_get": true,
    "news_headlines": true,
    "linux_shell": false,
    "database_query": false,
    "trait_modify": false
  }
}
```

### Example 2: "Professional" Protocol

**Purpose:** Professional assistance, formal tone

```json
{
  "name": "Professional",
  "description": "Professional mode for work-related interactions.",
  "show_chat_history": true,
  "show_memories": false,
  "traits_adjust": {
    "Professionalism": "10",
    "Formality": "9",
    "Playfulness": "2",
    "Warmth": "4"
  },
  "tool_usage": {
    "database_query": true,
    "linux_shell": true,
    "web_fetch": true,
    "image_generate": false
  }
}
```

### Example 3: "Debug" Protocol

**Purpose:** System debugging and development

```json
{
  "name": "Debug",
  "description": "Full system access for debugging and development.",
  "show_chat_history": true,
  "show_memories": true,
  "rules_include": ["1", "2", "3", "4", "5", "7", "8", "9"],  // All instructions
  "traits_adjust": {
    "Verbosity": "10",
    "Technical Detail": "10"
  },
  "tool_usage": {
    // All tools enabled
    "linux_shell": true,
    "database_query": true,
    "system_logs": true,
    "system_status": true
  }
}
```

## Integration (Future)

To integrate protocols into Iris's runtime:

1. **Protocol Selection Mechanism** - Add tool or command to switch protocols
2. **System Prompt Builder** - Modify `core/system_prompt.py` to read active protocol
3. **Instruction Filtering** - Apply rules_include/rules_exclude when building prompt
4. **Trait Override** - Apply traits_adjust when loading from fulltraits
5. **Tool Filtering** - Apply tool_usage when loading tool definitions
6. **History Routing** - Switch between main/generic chat_history tables
7. **Memory Control** - Conditionally include episodic memories

## Testing

### Test Protocol Editor

1. Start Iris server:
   ```bash
   ./scripts/start.sh
   ```

2. Open protocol editor:
   ```
   http://localhost:8000/static/protocol_editor.html
   ```

3. You should see:
   - "Default" protocol in dropdown
   - All system instructions listed
   - All traits with current values
   - All tools with enabled/disabled states

### Test API Endpoints

```bash
# List protocols
curl http://localhost:8000/api/protocols

# Get specific protocol
curl http://localhost:8000/api/protocols/1

# Get available options
curl http://localhost:8000/api/protocols/options/instructions
curl http://localhost:8000/api/protocols/options/traits
curl http://localhost:8000/api/protocols/options/tools
```

## Files Created

1. `/iris-v3/create_default_protocol.py` - Script to generate default protocol
2. `/iris-v3/app/api/routes_protocols.py` - Backend API endpoints
3. `/iris-v3/static/protocol_editor.html` - Protocol management GUI
4. `/iris-v3/app/main.py` - Updated to include protocol routes
5. `/iris-v3/PROTOCOL_SYSTEM_README.md` - This documentation

## Next Steps

1. ✅ Protocol database schema created
2. ✅ Default protocol generated
3. ✅ Backend API implemented
4. ✅ Professional GUI created
5. ⏳ Integration with Iris runtime (not yet implemented)
6. ⏳ Protocol switching mechanism (not yet implemented)
7. ⏳ Generic chat history table (not yet implemented)

## Notes

- The protocol system is fully functional as a standalone editor
- Runtime integration requires modifications to core Iris components
- The GUI is production-ready with proper error handling and status messages
- All CRUD operations are implemented with proper database transactions
- The system supports an unlimited number of protocols

## Support

For issues or questions:
1. Check database connection is working
2. Verify all dependencies are installed
3. Check browser console for JavaScript errors
4. Verify API endpoints are responding
5. Review server logs for backend errors
