"""
Add Protocol Management Tools to Database

Adds the protocol_activate, protocol_deactivate, protocol_status, and protocol_list
tools to the mcp_tools table so they are available to Iris.
"""

import os
import sys
import json

PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, PROJECT_ROOT)

import psycopg2
import psycopg2.extras
from app import config

# ============================================
# DATABASE CONNECTION
# ============================================

def get_db_connection():
    """Get database connection with password from environment"""
    password = os.environ.get('IRIS_DB_PASSWORD') or getattr(config, 'IRIS_DB_PASSWORD', None)
    conn_params = {
        'host': config.DB_HOST,
        'port': config.DB_PORT,
        'database': config.DB_NAME,
        'user': config.DB_USER
    }
    if password:
        conn_params['password'] = password
    return psycopg2.connect(**conn_params)

# ============================================
# TOOL DEFINITIONS
# ============================================

PROTOCOL_TOOLS = [
    {
        "tool_name": "protocol_activate",
        "description": """Activate a protocol with optional duration and passphrase

This tool allows natural language protocol activation with security features.

Args:
    request: Full natural language request (e.g., "activate protocol Theta for 8 hours with passphrase 'bank teller'")
    protocol_name: Optional explicit protocol name (if not in request)
    duration_minutes: Optional explicit duration in minutes (if not in request)
    passphrase: Optional explicit passphrase (if not in request)

Returns:
    dict: Activation result with protocol name, duration, expiration, passphrase status, and confirmation message

Examples:
    - "activate protocol Theta"
    - "switch to Professional mode for 8 hours"
    - "activate Theta for 30 minutes with passphrase 'override123'"

⚠️ WARNING: This is currently a SKELETON implementation for testing - it does NOT actually change system state.
""",
        "input_schema": {
            "type": "object",
            "title": "protocol_activateArguments",
            "required": ["request"],
            "properties": {
                "request": {
                    "type": "string",
                    "title": "Request",
                    "description": "Natural language activation request"
                },
                "protocol_name": {
                    "type": "string",
                    "title": "Protocol Name",
                    "description": "Optional explicit protocol name"
                },
                "duration_minutes": {
                    "type": "integer",
                    "title": "Duration Minutes",
                    "description": "Optional explicit duration in minutes"
                },
                "passphrase": {
                    "type": "string",
                    "title": "Passphrase",
                    "description": "Optional explicit passphrase for deactivation"
                },
                "confirm_defaults": {
                    "type": "boolean",
                    "title": "Confirm Defaults",
                    "description": "Set to true to proceed with defaults if parameters missing",
                    "default": False
                }
            }
        },
        "enabled": True,
        "icon": "🔄",
        "priority": 10
    },
    {
        "tool_name": "protocol_deactivate",
        "description": """Deactivate the currently active protocol

This tool allows natural language protocol deactivation with passphrase validation.

Args:
    request: Full natural language request (e.g., "deactivate protocol" or "deactivate with passphrase 'bank teller'")
    passphrase: Optional passphrase for protected protocols
    force: Force deactivation (admin override, not exposed to users)

Returns:
    dict: Deactivation result with protocol name and confirmation message

Examples:
    - "deactivate protocol"
    - "deactivate with passphrase 'override123'"
    - "return to default mode"

⚠️ WARNING: This is currently a SKELETON implementation for testing - it does NOT actually change system state.
""",
        "input_schema": {
            "type": "object",
            "title": "protocol_deactivateArguments",
            "required": ["request"],
            "properties": {
                "request": {
                    "type": "string",
                    "title": "Request",
                    "description": "Natural language deactivation request"
                },
                "passphrase": {
                    "type": "string",
                    "title": "Passphrase",
                    "description": "Optional passphrase for protected protocols"
                },
                "force": {
                    "type": "boolean",
                    "title": "Force",
                    "description": "Force deactivation (admin override)",
                    "default": False
                }
            }
        },
        "enabled": True,
        "icon": "⏹️",
        "priority": 10
    },
    {
        "tool_name": "protocol_status",
        "description": """Get the status of the currently active protocol

This tool returns information about which protocol is currently active, when it was activated,
when it expires (if duration was set), and whether it's passphrase protected.

Returns:
    dict: Protocol status with:
        - active_protocol: Name of current protocol
        - is_default: Whether using default protocol
        - activated_at: When protocol was activated
        - expires_at: When it expires (if duration set)
        - time_remaining: Human-readable time left
        - passphrase_protected: Whether passphrase required to deactivate

Examples:
    - "what protocol is active?"
    - "check protocol status"
    - "how long until protocol expires?"

⚠️ WARNING: This is currently a SKELETON implementation for testing - it returns dummy data.
""",
        "input_schema": {
            "type": "object",
            "title": "protocol_statusArguments",
            "properties": {}
        },
        "enabled": True,
        "icon": "ℹ️",
        "priority": 5
    },
    {
        "tool_name": "protocol_list",
        "description": """List all available protocols

This tool returns a list of all protocols that can be activated, along with their
descriptions and whether they are currently active.

Returns:
    dict: Available protocols with:
        - protocols: List of protocol objects (name, description, is_active)
        - count: Number of available protocols
        - message: Human-readable list

Examples:
    - "what protocols are available?"
    - "list all protocols"
    - "show me the protocol options"

⚠️ WARNING: This is currently a SKELETON implementation for testing - it returns dummy data.
""",
        "input_schema": {
            "type": "object",
            "title": "protocol_listArguments",
            "properties": {}
        },
        "enabled": True,
        "icon": "📋",
        "priority": 5
    }
]

# ============================================
# DATABASE OPERATIONS
# ============================================

def add_protocol_tools():
    """Add protocol management tools to mcp_tools table"""
    print("="*60)
    print("ADDING PROTOCOL MANAGEMENT TOOLS")
    print("="*60)

    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            for tool in PROTOCOL_TOOLS:
                print(f"\n[{tool['tool_name']}] Checking if exists...")

                # Check if tool already exists
                cur.execute("SELECT id, enabled FROM mcp_tools WHERE tool_name = %s", (tool['tool_name'],))
                existing = cur.fetchone()

                if existing:
                    print(f"  ⚠ Tool already exists (ID: {existing['id']}, enabled: {existing['enabled']})")
                    print(f"  Updating existing tool...")

                    cur.execute("""
                        UPDATE mcp_tools
                        SET description = %s,
                            input_schema = %s,
                            icon = %s,
                            priority = %s,
                            enabled = %s,
                            updated_at = now()
                        WHERE tool_name = %s
                        RETURNING id
                    """, (
                        tool['description'],
                        json.dumps(tool['input_schema']),
                        tool['icon'],
                        tool['priority'],
                        tool['enabled'],
                        tool['tool_name']
                    ))

                    tool_id = cur.fetchone()['id']
                    print(f"  ✓ Tool updated (ID: {tool_id})")

                else:
                    print(f"  Creating new tool...")

                    cur.execute("""
                        INSERT INTO mcp_tools (
                            tool_name, description, input_schema,
                            icon, priority, enabled
                        )
                        VALUES (%s, %s, %s, %s, %s, %s)
                        RETURNING id
                    """, (
                        tool['tool_name'],
                        tool['description'],
                        json.dumps(tool['input_schema']),
                        tool['icon'],
                        tool['priority'],
                        tool['enabled']
                    ))

                    tool_id = cur.fetchone()['id']
                    print(f"  ✓ Tool created (ID: {tool_id})")

            conn.commit()

    finally:
        conn.close()

    print("\n" + "="*60)
    print("✓ PROTOCOL TOOLS ADDED SUCCESSFULLY")
    print("="*60)
    print(f"\nAdded/updated {len(PROTOCOL_TOOLS)} tools:")
    for tool in PROTOCOL_TOOLS:
        print(f"  {tool['icon']} {tool['tool_name']}")

    print("\nThese are SKELETON implementations for testing.")
    print("They parse parameters but do NOT change system state.")

# ============================================
# MAIN EXECUTION
# ============================================

if __name__ == "__main__":
    try:
        add_protocol_tools()
        print("\nYou can now test the tools via Iris chat interface.")
        print("Example: 'Iris, activate protocol Theta for 8 hours'")
    except Exception as e:
        print(f"\n✗ Error adding protocol tools: {e}")
        import traceback
        traceback.print_exc()
