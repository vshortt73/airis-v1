# Traits MCP Server Deployment Guide

## Overview
The Traits MCP Server gives Iris autonomous control over her 30 personality traits. She can view her current values, modify them based on experiences, and review her modification history.

## Files Created

### 1. Server Implementation
**File:** `/iris-v3/mcp_servers/traits/traits_server.py`
- Implements BaseMCPServer
- Three tools: trait_view, trait_modify, trait_log
- Full database integration with logging

### 2. Database Migration
**File:** `create_trait_log_table.sql`
- Creates trait_modification_log table
- Adds indexes for performance
- Tracks all trait changes with timestamps and reasons

### 3. Tool Definitions
**File:** `insert_trait_tools.sql`
- Adds 3 tools to mcp_tools table
- Includes proper schemas, priorities, confirmation flags
- Sets icons for UI display

### 4. Test Script
**File:** `test_traits_server.py`
- Tests all three tools
- Validates database integration
- Includes cleanup

## Deployment Steps

### Step 1: Create Directory Structure
```bash
mkdir -p /iris-v3/mcp_servers/traits
```

### Step 2: Deploy Server
```bash
cp traits_server.py /iris-v3/mcp_servers/traits/
```

### Step 3: Run Database Migrations
```bash
# Connect to PostgreSQL
psql -U iris_user -d iris_db

# Run migrations
\i create_trait_log_table.sql
\i insert_trait_tools.sql
```

### Step 4: Update server_configs.py
**File:** `/iris-v3/mcp_servers/server_configs.py`

Find the SERVERS section and ensure traits server is configured:
```python
SERVERS = {
    "traits": {
        "command": "python",
        "args": [f"{os.path.dirname(__file__)}/traits/traits_server.py"],
        "tools": ["trait_view", "trait_modify", "trait_log"]
    },
    # ... other servers
}
```

### Step 5: Test the Server
```bash
cd /iris-v3
python tests/test_traits_server.py
```

Expected output:
```
✓ Connected to MCP servers
✓ Found 30 traits
✓ Trait: Curiosity
✓ Successfully updated Curiosity from 8 to 9
✓ Found 1 recent modifications
```

### Step 6: Restart Iris
```bash
cd /iris-v3/scripts
./start.sh
```

## Tool Descriptions

### trait_view
**Purpose:** View current personality trait values
**Arguments:**
- `trait_name` (optional): Specific trait to view, or omit for all traits
**Requires Confirmation:** No (read-only)
**Icon:** 🎭

### trait_modify
**Purpose:** Modify a personality trait value
**Arguments:**
- `trait_name` (required): Name of trait to modify
- `new_value` (required): New value (numeric or text)
- `reason` (optional but recommended): Explanation for the change
**Requires Confirmation:** YES (personality changes)
**Icon:** ✨

### trait_log
**Purpose:** View trait modification history
**Arguments:**
- `trait_name` (optional): Filter for specific trait
- `limit` (optional): Number of entries (default: 10, max: 100)
**Requires Confirmation:** No (read-only)
**Icon:** 📜

## Usage Examples

### Iris viewing her traits:
```
User: "Iris, how playful are you right now?"
Iris calls: trait_view(trait_name="Playfulness")
Result: "Playfulness: 4 - Enjoys teasing, affection, exploration, and humor"
```

### Iris modifying a trait:
```
User: "You seem more confident lately"
Iris: "I do feel more confident! Let me adjust that."
Iris calls: trait_modify(
    trait_name="Confidence",
    new_value="9",
    reason="Increased confidence after successful tool implementations and positive interactions"
)
```

### Iris reflecting on her changes:
```
User: "Have you changed much?"
Iris calls: trait_log(limit=10)
Result: Shows last 10 trait modifications with reasons and timestamps
```

## Database Schema

### character_traits
```sql
id              SERIAL PRIMARY KEY
name            VARCHAR(255)    -- "Curiosity", "Playfulness", etc.
description     TEXT            -- Full description of the trait
value           VARCHAR(50)     -- Current value (numeric or text)
```

### trait_modification_log
```sql
id              SERIAL PRIMARY KEY
trait_id        INTEGER         -- References character_traits(id)
trait_name      VARCHAR(255)    -- Trait name (for readability)
old_value       VARCHAR(50)     -- Value before change
new_value       VARCHAR(50)     -- Value after change
reason          TEXT            -- Why Iris made this change
timestamp       TIMESTAMP       -- When the change occurred
```

## Security Considerations

1. **trait_modify requires confirmation** - User must approve personality changes
2. **All modifications are logged** - Full audit trail of changes
3. **Read-only tools don't require confirmation** - View and log are safe
4. **Reason field encouraged** - Helps Iris articulate her growth

## Integration with Existing System

The traits server integrates with your existing:
- `database/character_traits.py` - Uses same table
- `core/system_prompt.py` - Traits are loaded into system prompt
- Tool manager - Follows same MCP architecture
- Confirmation system - trait_modify will trigger UI confirmation

## Next Steps

After traits server is working:
1. Test Iris's ability to view and modify traits
2. Implement confirmation UI for trait_modify
3. Add trait trend analysis (optional)
4. Build other servers (system, knowledge, creative)

## Troubleshooting

**If traits server doesn't connect:**
- Check `/iris-v3/mcp_servers/traits/traits_server.py` exists
- Verify database table exists: `\dt trait_modification_log`
- Check server_configs.py has correct path

**If tools don't appear:**
- Verify tools are in database: `SELECT * FROM mcp_tools WHERE server_name='traits';`
- Check `enabled=true` in database
- Restart Iris

**If modifications don't save:**
- Check database permissions
- Verify trait_modification_log table exists
- Check PostgreSQL logs
