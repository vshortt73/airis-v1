# Protocol Tracking Implementation - Complete

## Overview

The protocol management system now **actively tracks** which protocol is currently in use, stores activation/deactivation history, and displays the current protocol in the UI.

## What Was Implemented

### 1. Database Tables ✅

**Created:** `/iris-v3/create_protocol_tracking_tables.sql`

**Tables:**
- `active_protocol` - Singleton table tracking currently active protocol
  - Stores: protocol_id, protocol_name, activated_at, expires_at, passphrase_hash
  - Unique index ensures only one active protocol at a time

- `protocol_history` - Audit log of all activations/deactivations
  - Tracks: when activated, when deactivated, duration, reason, who activated

**Helper Function:**
- `get_active_protocol()` - Returns current protocol with expiration info

**Initial State:**
- Default protocol automatically activated on first run
- Logged in protocol_history

### 2. Protocol Server - Database Integration ✅

**Updated:** `/iris-v3/mcp_servers/protocols/protocol_server.py`

**Changes:**
- Added database connection with password from environment
- Added bcrypt for passphrase hashing
- **protocol_activate** now:
  - Validates protocol exists in database
  - Hashes passphrase with bcrypt if provided
  - Deactivates current protocol (moves to history)
  - Activates new protocol in `active_protocol` table
  - Logs both deactivation and activation in `protocol_history`

- **protocol_deactivate** now:
  - Queries current active protocol from database
  - Validates passphrase if protocol is protected (bcrypt.checkpw)
  - Prevents deactivation of Default protocol
  - Logs deactivation in history with duration
  - Reactivates Default protocol automatically

- **protocol_status** now:
  - Queries `active_protocol` table
  - Returns real protocol name, expiration, passphrase protection status
  - Calculates time remaining for expiring protocols

- **protocol_list** now:
  - Queries `protocols` table for all available protocols
  - Marks which protocol is currently active
  - Orders Default first

### 3. Backend API Endpoint ✅

**Updated:** `/iris-v3/app/api/routes_protocols.py`

**New Endpoint:**
```
GET /api/protocols/status/active
```

Returns current protocol status for UI consumption:
```json
{
  "success": true,
  "active_protocol": "Theta",
  "is_default": false,
  "activated_at": "2025-12-20T12:00:00",
  "expires_at": "2025-12-20T20:00:00",
  "passphrase_protected": true
}
```

### 4. UI Protocol Indicator ✅

**Updated:** `/iris-v3/static/index.html`

**Visual Changes:**
- Added `Protocol: Default` indicator next to "Messages" and "Session ID"
- Color-coded:
  - **Green** (#4CAF50) for Default protocol
  - **Orange** (#FF9800) for non-default protocols
  - **Gray** (#999) if status unknown
- Shows 🔒 icon when passphrase-protected

**JavaScript:**
- `updateProtocolStatus()` - Fetches and updates protocol display
- Calls API endpoint `/api/protocols/status/active`
- Updates every 5 seconds automatically
- Runs on page load

### 5. Dependencies ✅

**Updated:** `/iris-v3/requirements.txt`

Added:
- `bcrypt==4.1.2` - For secure passphrase hashing

## How It Works

### Activation Flow

1. User says: **"Iris, activate protocol Theta for 8 hours with passphrase 'test123'"**
2. Iris calls `protocol_activate` tool
3. Tool asks for missing parameters if needed (multi-step gathering)
4. Once all parameters provided:
   - Validates "Theta" exists in `protocols` table
   - Hashes passphrase with bcrypt
   - Deactivates current protocol → logs to `protocol_history`
   - Inserts new row in `active_protocol` table
   - Logs activation to `protocol_history`
5. Returns success message
6. UI automatically refreshes (within 5 seconds) and shows:
   - **Protocol: Theta 🔒** (in orange)

### Deactivation Flow

1. User says: **"Iris, deactivate protocol with passphrase 'test123'"**
2. Iris calls `protocol_deactivate` tool
3. Tool:
   - Queries `active_protocol` table
   - Checks passphrase_hash field
   - If protected, validates passphrase with bcrypt.checkpw
   - If valid:
     - Calculates actual duration
     - Logs deactivation to `protocol_history`
     - Deletes from `active_protocol`
     - Reactivates Default protocol
4. Returns success message
5. UI refreshes and shows:
   - **Protocol: Default** (in green)

### Security Features

**Passphrase Protection:**
- Passphrases hashed with bcrypt (cost factor 12)
- Never stored in plain text
- Validated with bcrypt.checkpw on deactivation
- Cannot deactivate without correct passphrase

**Audit Trail:**
- Every activation/deactivation logged in `protocol_history`
- Tracks: who, when, duration, reason
- Permanent record for compliance

**Database Constraints:**
- Only one active protocol at a time (unique index)
- Cannot delete protocol if currently active (foreign key)
- Default protocol cannot be deactivated

## Testing

### Test Protocol Activation

```
User: "Iris, activate protocol Theta for 30 minutes"
Expected:
- Iris asks for passphrase (multi-step)
- After providing answers, activates successfully
- UI shows "Protocol: Theta" in orange
- Database has entry in active_protocol
```

### Test Protocol Deactivation

```
User: "Iris, deactivate protocol"
Expected:
- If passphrase protected, asks for passphrase
- Deactivates and returns to Default
- UI shows "Protocol: Default" in green
```

### Test Protocol Status

```
User: "Iris, what protocol is active?"
Expected:
- Iris calls protocol_status tool
- Returns current protocol with expiration info
```

### Test Protocol List

```
User: "Iris, what protocols are available?"
Expected:
- Iris calls protocol_list tool
- Shows all protocols from database
- Marks which one is active
```

### Test UI Indicator

1. Open `http://localhost:8000/`
2. Look at top bar: "Messages: X | Protocol: Default | Session: ..."
3. Activate a different protocol via chat
4. Watch UI update within 5 seconds
5. Should change color from green to orange
6. If passphrase set, shows 🔒 icon

## Database Queries

**Check active protocol:**
```sql
SELECT * FROM active_protocol;
```

**Check activation history:**
```sql
SELECT * FROM protocol_history ORDER BY created_at DESC LIMIT 10;
```

**Check protocol with expiration:**
```sql
SELECT protocol_name,
       activated_at,
       expires_at,
       expires_at - NOW() as time_remaining
FROM active_protocol;
```

## Files Modified

1. `/iris-v3/create_protocol_tracking_tables.sql` - Database schema (NEW)
2. `/iris-v3/mcp_servers/protocols/protocol_server.py` - Real database operations
3. `/iris-v3/app/api/routes_protocols.py` - Added status endpoint
4. `/iris-v3/static/index.html` - UI indicator and auto-refresh
5. `/iris-v3/requirements.txt` - Added bcrypt

## What's NOT Implemented Yet

❌ **Protocol rules are NOT yet applied:**
- System instructions filtering (rules_include/rules_exclude)
- Trait overrides
- Tool restrictions
- Chat history switching
- Memory injection control

The protocol is tracked, but Iris still behaves the same regardless of which protocol is active. This is the next step!

## Next Steps

To make protocols actually change Iris's behavior:

1. Modify `core/system_prompt.py`:
   - Query active protocol
   - Filter system instructions based on rules_include/rules_exclude
   - Apply trait overrides from protocols.traits_adjust

2. Modify tool loading:
   - Check active protocol's tool_usage field
   - Enable/disable tools accordingly

3. Implement chat history switching:
   - Use different table based on protocols.show_chat_history

4. Implement memory control:
   - Conditional memory injection based on protocols.show_memories

5. Add auto-expiration:
   - Background task to check expires_at
   - Auto-deactivate when time expires

## Status Summary

✅ **Database tables created and populated**
✅ **Protocol activation writes to database**
✅ **Protocol deactivation with passphrase validation**
✅ **Protocol status queries real data**
✅ **Protocol list queries database**
✅ **UI indicator shows current protocol**
✅ **Auto-refresh every 5 seconds**
✅ **Passphrase hashing with bcrypt**
✅ **Audit logging in protocol_history**
⏳ **Protocol rules NOT yet applied to system behavior**

The foundation is complete! You can now activate/deactivate protocols and see which one is active, but they don't change Iris's behavior yet.
