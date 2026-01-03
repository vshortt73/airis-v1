# Protocol Management Tools - Skeleton Implementation

## Overview

This is a **SKELETON IMPLEMENTATION** of the protocol activation/deactivation tools. The tools are fully functional for testing the natural language interface and parameter parsing, but they **DO NOT** actually change system state yet.

## What Was Created

### 1. MCP Server
**File:** `/iris-v3/mcp_servers/protocols/protocol_server.py`

A fully functional MCP server with 4 tools:
- `protocol_activate` - Activate a protocol with optional duration and passphrase
- `protocol_deactivate` - Deactivate the current protocol
- `protocol_status` - Check current protocol status
- `protocol_list` - List all available protocols

**Features Implemented:**
- ✅ Natural language parsing for protocol names
- ✅ Duration parsing (e.g., "8 hours", "30 minutes", "2 days")
- ✅ Passphrase extraction from quotes
- ✅ Human-readable time formatting
- ✅ Comprehensive error handling
- ✅ Detailed logging
- ⚠️  **DUMMY RESPONSES** - Returns parsed data but doesn't change system state

### 2. Database Tool Definitions
**Script:** `/iris-v3/add_protocol_tools.py`

Adds tool definitions to the `mcp_tools` table with:
- Tool descriptions
- Input schemas (JSON Schema format)
- Icons (🔄, ⏹️, ℹ️, 📋)
- Priority settings

**Run it:**
```bash
source /venv/iris-v3/bin/activate
export IRIS_DB_PASSWORD='yourpassword'
python add_protocol_tools.py
```

### 3. Server Configuration
**File:** `/iris-v3/mcp_servers/server_configs.py`

Updated to include:
- Protocol server in server list
- Tool routing configuration
- Autonomous vs. confirmation-required classification
  - `protocol_activate` - Requires confirmation ✋
  - `protocol_deactivate` - Requires confirmation ✋
  - `protocol_status` - Autonomous ✅
  - `protocol_list` - Autonomous ✅

### 4. Test Suite
**File:** `/iris-v3/test_protocol_tools.py`

Comprehensive async tests covering:
- ✅ Protocol listing
- ✅ Protocol status checking
- ✅ Simple activation ("activate protocol Theta")
- ✅ Duration parsing ("activate Professional for 8 hours")
- ✅ Passphrase parsing ("activate Theta for 30 minutes with passphrase 'bank teller'")
- ✅ Simple deactivation ("deactivate protocol")
- ✅ Passphrase deactivation ("deactivate with passphrase 'bank teller'")

**Run it:**
```bash
source /venv/iris-v3/bin/activate
export IRIS_DB_PASSWORD='yourpassword'
python test_protocol_tools.py
```

## Current Capabilities

### Natural Language Parsing

The tools can understand various natural language patterns:

**Protocol Names:**
- "activate protocol Theta"
- "switch to Professional mode"
- "activate Theta"

**Durations:**
- "8 hours" → 480 minutes
- "30 minutes" → 30 minutes
- "2 days" → 2880 minutes

**Passphrases:**
- "with passphrase 'bank teller'"
- "passphrase \"override123\""

### What the Tools Return

**protocol_activate:**
```json
{
  "success": true,
  "protocol_name": "Theta",
  "duration_minutes": 480,
  "expires_at": "2025-12-20T18:44:07",
  "passphrase_required": true,
  "passphrase_set": true,
  "message": "Protocol 'Theta' would be activated for 8 hours with passphrase protection",
  "warning": "⚠️ SKELETON IMPLEMENTATION - Protocol NOT actually activated"
}
```

**protocol_deactivate:**
```json
{
  "success": true,
  "protocol_name": "Theta",
  "message": "Protocol 'Theta' would be deactivated, returning to 'Default' protocol",
  "passphrase_provided": true,
  "warning": "⚠️ SKELETON IMPLEMENTATION - Protocol NOT actually deactivated"
}
```

**protocol_status:**
```json
{
  "success": true,
  "active_protocol": "Default",
  "is_default": true,
  "activated_at": "2025-12-20T10:44:06",
  "expires_at": null,
  "time_remaining": null,
  "passphrase_protected": false,
  "message": "Currently using protocol: 'Default' (no expiration)"
}
```

**protocol_list:**
```json
{
  "success": true,
  "protocols": [
    {"name": "Default", "description": "...", "is_active": true},
    {"name": "Theta", "description": "...", "is_active": false},
    {"name": "Professional", "description": "...", "is_active": false}
  ],
  "count": 3,
  "message": "Found 3 available protocols: Default, Theta, Professional"
}
```

## Testing via Chat Interface

You can now test these tools through Iris:

```
User: "Iris, what protocols are available?"
→ Iris calls protocol_list tool

User: "Iris, activate protocol Theta for 8 hours with passphrase 'bank teller'"
→ Iris calls protocol_activate with parsed parameters

User: "Iris, check protocol status"
→ Iris calls protocol_status

User: "Iris, deactivate protocol with passphrase 'bank teller'"
→ Iris calls protocol_deactivate with passphrase
```

⚠️ **IMPORTANT:** The tools will parse your request and return confirmation messages, but they will **NOT** actually change Iris's behavior yet. This is intentional to keep the scope manageable.

## What's NOT Implemented Yet

The following features are planned but not yet implemented:

### 1. Database Tables
- `active_protocol` - Track currently active protocol
- `protocol_history` - Audit log of activations/deactivations
- `protocol_passphrases` - Secure passphrase storage with bcrypt hashing

### 2. Actual Protocol Switching
- Load protocol configuration from `protocols` table
- Apply instruction filtering (rules_include/rules_exclude)
- Apply trait overrides
- Apply tool usage restrictions
- Switch between main/generic chat history
- Control memory injection

### 3. Security Features
- Passphrase hashing with bcrypt
- Passphrase validation
- Rate limiting (max 5 attempts in 5 minutes)
- Account lockout after failed attempts
- Comprehensive audit logging

### 4. Time-Based Expiration
- Background task to check for expired protocols
- Automatic deactivation when duration expires
- Time remaining calculations

### 5. Runtime Integration
- Modify `core/system_prompt.py` to read active protocol
- Hook into conversation assembly to apply protocol rules
- Real-time protocol status monitoring

## Next Steps

When ready to implement the actual protocol switching logic:

1. **Create Database Tables:**
   ```sql
   CREATE TABLE active_protocol (
       id SERIAL PRIMARY KEY,
       protocol_id INTEGER REFERENCES protocols(id),
       activated_at TIMESTAMP DEFAULT NOW(),
       expires_at TIMESTAMP,
       passphrase_hash TEXT,
       created_by TEXT
   );

   CREATE TABLE protocol_history (
       id SERIAL PRIMARY KEY,
       protocol_id INTEGER REFERENCES protocols(id),
       action VARCHAR(50),  -- 'activate' or 'deactivate'
       activated_at TIMESTAMP,
       deactivated_at TIMESTAMP,
       reason TEXT,
       created_by TEXT
   );
   ```

2. **Implement Protocol Activation Logic:**
   - Query protocol from `protocols` table
   - Hash passphrase if provided (bcrypt)
   - Store in `active_protocol` table
   - Log to `protocol_history`

3. **Implement Protocol Application:**
   - Modify `build_system_message()` to read active protocol
   - Filter instructions based on rules_include/rules_exclude
   - Apply trait overrides
   - Apply tool restrictions

4. **Add Expiration Handling:**
   - Background task or middleware to check expiration
   - Automatic deactivation when time expires

5. **Test End-to-End:**
   - Activate protocol via chat
   - Verify system behavior changes
   - Verify traits are overridden
   - Verify tools are restricted
   - Test passphrase protection
   - Test time expiration

## Files Created

1. `/iris-v3/mcp_servers/protocols/protocol_server.py` - MCP server implementation
2. `/iris-v3/add_protocol_tools.py` - Database tool definition script
3. `/iris-v3/test_protocol_tools.py` - Comprehensive test suite
4. `/iris-v3/mcp_servers/server_configs.py` - Updated server configurations
5. `/iris-v3/PROTOCOL_TOOLS_SKELETON_README.md` - This documentation

## Status Summary

✅ **Completed:**
- Natural language parsing (protocol names, durations, passphrases)
- Tool definitions in database
- MCP server implementation
- Server configuration
- Comprehensive test suite
- Documentation

⏳ **Not Yet Implemented:**
- Database tables for active protocols
- Actual protocol switching logic
- Security features (hashing, rate limiting)
- Time-based expiration
- Runtime integration with Iris

This skeleton provides a solid foundation to test the tool interface and natural language interaction before implementing the actual state-changing logic.
