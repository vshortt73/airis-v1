"""
Iris Traits Server - MCP Server for Character Trait Management
Provides unified trait control with action-based routing
"""

import sys
import os
import psycopg2
from psycopg2.extras import DictCursor
from pathlib import Path
from typing import Dict, Any, Optional

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app import config
from mcp_servers.base.base_server import IrisMCPServer

# ============================================================================
# SERVER INITIALIZATION
# ============================================================================

server = IrisMCPServer(
    name="Iris Traits Server",
    description="Unified character trait management with action-based routing"
)

# ============================================================================
# DATABASE CONNECTION
# ============================================================================

def get_db_connection():
    """Create database connection"""
    password = os.environ.get('IRIS_DB_PASSWORD') or getattr(config, 'DB_PASSWORD', None)
    conn_params = {
        'host': config.DB_HOST,
        'port': config.DB_PORT,
        'database': config.DB_NAME,
        'user': config.DB_USER
    }
    if password:
        conn_params['password'] = password
    return psycopg2.connect(**conn_params)


# ============================================================================
# ACTION HANDLERS
# ============================================================================

def _handle_get(name: str) -> Dict[str, Any]:
    """Get a specific trait's value and description"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT name, value, description
            FROM fulltraits
            WHERE name ILIKE %s
            LIMIT 1
        """, (name,))

        row = cursor.fetchone()
        cursor.close()
        conn.close()

        if not row:
            return {
                "success": False,
                "error": f"Trait '{name}' not found"
            }

        return {
            "success": True,
            "trait": {
                "name": row[0],
                "value": row[1],
                "description": row[2]
            }
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


def _handle_list() -> Dict[str, Any]:
    """List all traits with their values"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT name, value, description
            FROM fulltraits
            ORDER BY name
        """)

        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        traits = []
        for name, value, desc in rows:
            traits.append({
                "name": name,
                "value": value,
                "description": desc
            })

        return {
            "success": True,
            "traits": traits,
            "count": len(traits),
            "message": f"Found {len(traits)} personality traits"
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


def _handle_modify(name: str, value: float, reason: str) -> Dict[str, Any]:
    """Modify a trait's value with logging"""
    # Validate value range
    if value < 0 or value > 10:
        return {
            "success": False,
            "error": "Value must be between 0 and 10"
        }

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Get current value
        cursor.execute("""
            SELECT value FROM fulltraits WHERE name ILIKE %s LIMIT 1
        """, (name,))

        row = cursor.fetchone()
        if not row:
            cursor.close()
            conn.close()
            return {
                "success": False,
                "error": f"Trait '{name}' does not exist"
            }

        old_value = row[0]

        # Check if value is actually changing
        if float(old_value) == float(value):
            cursor.close()
            conn.close()
            return {
                "success": False,
                "error": "New value is the same as current value"
            }

        # Update trait and log the change
        cursor.execute("""
            WITH updated_row AS (
                UPDATE fulltraits SET value = %s WHERE name ILIKE %s
            ),
            inserted_log AS (
                INSERT INTO trait_modification_log
                    (trait_id, trait_name, old_value, new_value, reason)
                VALUES (
                    (SELECT id FROM fulltraits WHERE name ILIKE %s LIMIT 1),
                    %s, %s, %s, %s
                )
                RETURNING id
            )
            SELECT id FROM inserted_log
        """, (value, name, name, name, old_value, value, reason))

        log_id = cursor.fetchone()[0]
        conn.commit()
        cursor.close()
        conn.close()

        return {
            "success": True,
            "message": f"Trait '{name}' updated: {old_value} → {value}",
            "trait_name": name,
            "old_value": old_value,
            "new_value": value,
            "reason": reason,
            "log_id": log_id
        }

    except Exception as e:
        return {"success": False, "error": f"Database error: {str(e)}"}


# ============================================================================
# UNIFIED TRAIT TOOL
# ============================================================================

@server.register_tool
def trait(
    action: str,
    name: Optional[str] = None,
    value: Optional[float] = None,
    reason: Optional[str] = None
) -> Dict[str, Any]:
    """
    Unified personality trait management tool.

    Actions:
        - "get": Get a specific trait's current value (requires name)
        - "list": List all traits with their values
        - "modify": Change a trait's value (requires name, value, reason)

    Args:
        action: The action to perform ("get", "list", "modify")
        name: Trait name (required for get/modify)
        value: New value 0-10 (required for modify)
        reason: Reason for modification (required for modify)

    Returns:
        dict with success status and action-specific data

    Examples:
        trait(action="list")
        trait(action="get", name="Curiosity")
        trait(action="modify", name="Curiosity", value=7.5, reason="Feeling more inquisitive today")

    Available traits include: Curiosity, Warmth, Playfulness, Confidence, Empathy, etc.
    Values range from 0 (minimal) to 10 (maximum).
    """
    action = action.lower().strip()
    print(f"[trait] Action: {action}, name: {name}, value: {value}", file=sys.stderr)

    # Route to appropriate handler
    if action == "list":
        return _handle_list()

    elif action == "get":
        if not name:
            return {
                "success": False,
                "error": "Trait name required for get action",
                "hint": "Specify which trait to retrieve, e.g., name='Curiosity'"
            }
        return _handle_get(name)

    elif action == "modify":
        if not name:
            return {
                "success": False,
                "error": "Trait name required for modify action"
            }
        if value is None:
            return {
                "success": False,
                "error": "Value required for modify action (0-10)"
            }
        if not reason:
            reason = "No reason provided"

        return _handle_modify(name, value, reason)

    else:
        return {
            "success": False,
            "error": f"Unknown action: {action}",
            "valid_actions": ["get", "list", "modify"]
        }


# ============================================================================
# SERVER STARTUP
# ============================================================================

if __name__ == "__main__":
    print("=" * 60, file=sys.stderr)
    print("IRIS TRAITS SERVER (Unified)", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print("Tool: trait(action, name?, value?, reason?)", file=sys.stderr)
    print("Actions: get, list, modify", file=sys.stderr)
    print("Starting server...", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    server.run()
