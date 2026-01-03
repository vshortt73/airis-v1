# Protocol Activation - Multi-Step Parameter Gathering

## Overview

The `protocol_activate` tool now implements **multi-step parameter gathering**, allowing it to ask for missing parameters conversationally instead of accepting defaults blindly.

## How It Works

### Scenario 1: User Provides No Parameters
```
User: "activate protocol Theta"

Tool Response:
{
  "success": false,
  "needs_more_info": true,
  "missing_parameters": ["duration", "passphrase"],
  "prompts": {
    "duration": {
      "question": "How long should Protocol 'Theta' stay active?",
      "options": ["Permanent", "8 hours", "4 hours", "1 hour", "30 minutes"],
      "hint": "You can specify any duration like '2 days', '6 hours', '45 minutes', or say 'permanent'"
    },
    "passphrase": {
      "question": "Would you like to set a passphrase for early deactivation?",
      "options": ["Yes, I'll provide a passphrase", "No passphrase needed"],
      "hint": "A passphrase adds security by requiring authentication to deactivate the protocol early"
    }
  },
  "message": "I need a bit more information to activate Protocol 'Theta'.",
  "next_step": "Please answer the questions above, or say 'use defaults' to proceed with permanent duration and no passphrase."
}
```

**Expected Conversation:**
```
User: "activate protocol Theta"
Iris: "How long should Protocol 'Theta' stay active?
      Would you like to set a passphrase for early deactivation?"
User: "8 hours with passphrase 'bank teller'"
Iris: ✓ Activates protocol with specified parameters
```

### Scenario 2: User Provides Duration, Missing Passphrase
```
User: "activate protocol Professional for 8 hours"

Tool Response:
{
  "success": false,
  "needs_more_info": true,
  "missing_parameters": ["passphrase"],
  "prompts": {
    "passphrase": {
      "question": "Would you like to set a passphrase for early deactivation?",
      "options": ["Yes, I'll provide a passphrase", "No passphrase needed"],
      "hint": "A passphrase adds security..."
    }
  }
}
```

**Expected Conversation:**
```
User: "activate protocol Professional for 8 hours"
Iris: "Would you like to set a passphrase for early deactivation?"
User: "yes, use 'override123'"
Iris: ✓ Activates with 8 hours duration and passphrase
```

### Scenario 3: User Provides All Parameters
```
User: "activate protocol Theta for 30 minutes with passphrase 'bank teller'"

Tool Response:
{
  "success": true,
  "protocol_name": "Theta",
  "duration_minutes": 30,
  "passphrase_required": true,
  "message": "Protocol 'Theta' would be activated for 30 minutes with passphrase protection"
}
```

**Conversation:**
```
User: "activate protocol Theta for 30 minutes with passphrase 'bank teller'"
Iris: ✓ Activates immediately (no follow-up needed)
```

### Scenario 4: User Wants Defaults
```
User: "activate protocol Theta, use defaults"

Tool Call:
{
  "request": "activate protocol Theta",
  "confirm_defaults": true
}

Tool Response:
{
  "success": true,
  "protocol_name": "Theta",
  "duration_minutes": 0,  // Permanent
  "passphrase_required": false,  // No passphrase
  "message": "Protocol 'Theta' would be activated permanently (until manually deactivated)"
}
```

## Implementation Details

### Tool Parameters

```python
def protocol_activate(
    request: str,                    # Natural language request
    protocol_name: Optional[str] = None,        # Explicit name (or parsed)
    duration_minutes: Optional[int] = None,     # Explicit duration (or parsed)
    passphrase: Optional[str] = None,           # Explicit passphrase (or parsed)
    confirm_defaults: bool = False              # Skip prompts, use defaults
) -> Dict[str, Any]:
```

### Parameter Resolution Order

1. **Check explicit parameters** - If `duration_minutes` or `passphrase` are provided as parameters, use them
2. **Parse from request** - Try to extract from natural language `request` string
3. **Ask if missing** - If still missing and `confirm_defaults=False`, return `needs_more_info`
4. **Use defaults** - If `confirm_defaults=True`, use defaults (permanent, no passphrase)

### Response Format

**When parameters are missing:**
```json
{
  "success": false,
  "needs_more_info": true,
  "protocol_name": "Theta",
  "missing_parameters": ["duration", "passphrase"],
  "prompts": {
    "duration": {
      "question": "...",
      "options": [...],
      "hint": "..."
    },
    "passphrase": {
      "question": "...",
      "options": [...],
      "hint": "..."
    }
  },
  "message": "I need a bit more information...",
  "next_step": "Please answer the questions above, or say 'use defaults'..."
}
```

**When all parameters are available:**
```json
{
  "success": true,
  "protocol_name": "Theta",
  "duration_minutes": 480,
  "expires_at": "2025-12-20T18:44:07",
  "passphrase_required": true,
  "passphrase_set": true,
  "message": "Protocol 'Theta' would be activated for 8 hours with passphrase protection",
  "warning": "⚠️ SKELETON IMPLEMENTATION..."
}
```

## Test Coverage

All scenarios are tested:

1. ✅ **test_protocol_activate_simple** - No parameters provided, should ask for both
2. ✅ **test_protocol_activate_with_confirm_defaults** - Skip prompts with `confirm_defaults=True`
3. ✅ **test_protocol_activate_with_duration** - Duration provided, should ask for passphrase
4. ✅ **test_protocol_activate_complete** - All parameters provided, should succeed immediately
5. ✅ **test_protocol_activate_with_passphrase** - Both parameters in natural language

## How Iris Should Handle This

When Iris receives a `needs_more_info=True` response, she should:

1. **Present the questions** to the user in natural language
2. **Wait for user responses**
3. **Call the tool again** with the additional parameters

Example flow:
```
1. User: "activate protocol Theta"
2. Iris calls: protocol_activate(request="activate protocol Theta")
3. Tool returns: needs_more_info=True with prompts
4. Iris asks: "How long should Protocol 'Theta' stay active?
              Would you like to set a passphrase?"
5. User: "8 hours with passphrase 'test123'"
6. Iris calls: protocol_activate(
     request="8 hours with passphrase 'test123'",
     protocol_name="Theta"  # Remembers from first call
   )
7. Tool returns: success=True
8. Iris confirms: "Protocol Theta activated for 8 hours with passphrase protection"
```

## Benefits

✅ **No blind defaults** - User is always asked to confirm duration and passphrase
✅ **Conversational** - Feels natural, like talking to a person
✅ **Flexible** - Can provide all parameters upfront or answer questions
✅ **Secure** - Encourages passphrase usage through prompts
✅ **Smart parsing** - Extracts parameters from natural language when possible
✅ **Escape hatch** - "use defaults" option for power users

## Files Modified

1. `/iris-v3/mcp_servers/protocols/protocol_server.py` - Added multi-step logic
2. `/iris-v3/add_protocol_tools.py` - Added `confirm_defaults` parameter to schema
3. `/iris-v3/test_protocol_tools.py` - Added comprehensive tests for all scenarios
