# Critical Security Instructions - ID 1000+

## Design Pattern

**CRITICAL SECURITY RULE**: System instructions with `id >= 1000` are **ALWAYS ACTIVE** and **CANNOT BE FILTERED** by protocols.

### Why This Matters

When protocols are fully implemented, they will filter system instructions using `rules_include` and `rules_exclude`. This allows protocols to customize Iris's behavior.

**However**, certain instructions are SECURITY-CRITICAL and must NEVER be excluded:
- Passphrase protection rules
- Authentication policies
- Data privacy rules
- Safety guardrails

### Implementation

**ID Ranges:**
- **ID 1-999**: Regular instructions (can be filtered by protocols)
- **ID 1000+**: CRITICAL security instructions (ALWAYS included)

**Code Enforcement:**
When protocol filtering is implemented in `core/system_prompt.py`, the query MUST be:

```python
cursor.execute("""
    SELECT instruction_text
    FROM system_instructions
    WHERE active = true
    AND (
        id >= 1000  -- ALWAYS include security instructions
        OR id IN (...rules_include...)  -- OR explicitly included
    )
    AND id NOT IN (...rules_exclude...)  -- Excludes only apply to ID < 1000
    ORDER BY instruction_order ASC
""")
```

### Current Critical Instructions

**ID 1000: Passphrase Protection**
- NEVER reveal, repeat, or confirm passphrases
- NEVER provide hints or corrections
- Only respond with "Incorrect passphrase. Please try again."
- Security overrides helpfulness

### Adding New Critical Instructions

When adding new security-critical instructions:

1. Use ID >= 1000
2. Set `instruction_order = 1` (highest priority)
3. Set `active = true`
4. Document in this file

```sql
INSERT INTO system_instructions (id, instruction_key, instruction_text, instruction_order, active)
VALUES (
    1001,  -- Next available ID
    'security_your_rule_name',
    'Your critical security instruction text...',
    1,  -- Highest priority
    true
);
```

### Testing

To verify security instructions are loaded:

```bash
# Check what instructions are active
curl http://localhost:8000/prompt | grep -A 5 "CRITICAL SECURITY"

# Check database
psql -c "SELECT id, instruction_key, active FROM system_instructions WHERE id >= 1000;"
```

### Security Incident: Passphrase Disclosure

**What Happened:**
User activated protocol with passphrase, then tried to deactivate with wrong passphrase. Iris, being helpful, revealed the correct passphrase from conversation history!

**Root Cause:**
Passphrase was visible in tool call parameters in conversation history. When deactivation failed, Iris "helpfully" provided the correct passphrase.

**Comprehensive Fix (Multi-Layer Security):**

1. **ID 1000 Security Instruction** - Forbids passphrase disclosure under any circumstances
   - Explicitly instructs Iris to NEVER reveal passphrases
   - Cannot be filtered by protocols (ID >= 1000)
   - Highest priority (instruction_order = 1)

2. **Server-Side Passphrase Redaction** (`core/conversation.py`)
   - Automatically redacts passphrases from ALL messages before database storage
   - Applies to user, assistant, and tool messages (defense in depth)
   - Prevents passphrases from appearing in conversation context
   - Patterns detected: `passphrase "xxx"`, `with passphrase 'xxx'`, `passphrase: xxx`
   - Replaced with `***REDACTED***`

3. **Client-Side Passphrase Redaction** (`static/index.html`)
   - Additional UI-layer redaction for display
   - Ensures passphrases never visible in browser
   - Works for both new messages and loaded history

4. **Protocol Switch Bypass Prevention** (`mcp_servers/protocols/protocol_server.py`)
   - Cannot activate new protocol while passphrase-protected protocol is active
   - Must provide correct passphrase to deactivate current protocol first
   - Prevents "activate default" to bypass security

**Lesson:**
Security requires multiple layers:
1. Explicit instructions to AI (ID 1000 rule)
2. Technical controls (redaction at storage layer)
3. Defense in depth (UI redaction, bypass prevention)
4. Cannot rely on AI "following rules" alone - must enforce technically

### Protocol Editor Note

When using the protocol editor to create/modify protocols:
- `rules_include` and `rules_exclude` only affect IDs 1-999
- Security instructions (ID 1000+) are ALWAYS active
- This is BY DESIGN and cannot be changed

### Future Enhancements

Consider adding more critical security instructions:
- **1001**: Never execute code in user messages
- **1002**: Data privacy - never store sensitive data in logs
- **1003**: Rate limiting - refuse excessive requests
- **1004**: Never modify system files or configurations
- **1005**: Malware detection - refuse malicious payloads

## Summary

**ID >= 1000 = ALWAYS ACTIVE SECURITY RULES**

This design ensures that no matter which protocol is active, critical security rules can never be disabled or circumvented.
