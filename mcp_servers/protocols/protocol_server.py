"""
Iris Protocol Management Server - MCP Server for Protocol Management
Provides unified protocol control with action-based routing
"""

import sys
import os
from pathlib import Path
from typing import Dict, Any, Optional
import re
from datetime import datetime, timedelta
import psycopg2
import psycopg2.extras

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from mcp_servers.base.base_server import IrisMCPServer
from app import config

# ============================================================================
# SERVER INITIALIZATION
# ============================================================================

server = IrisMCPServer(
    name="Iris Protocol Server",
    description="Unified protocol management with action-based routing"
)

# ============================================================================
# DATABASE CONNECTION
# ============================================================================

def get_db_connection():
    """Get database connection with password from environment"""
    password = os.environ.get('AIRIS_DB_PASSWORD') or getattr(config, 'DB_PASSWORD', None)
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
# HELPER FUNCTIONS
# ============================================================================

def parse_duration(text: str) -> Optional[int]:
    """Parse duration from natural language text (e.g., '8 hours' -> 480)"""
    patterns = [
        (r'(\d+)\s*h(?:our)?s?', 60),
        (r'(\d+)\s*m(?:in)?(?:ute)?s?', 1),
        (r'(\d+)\s*d(?:ay)?s?', 1440),
    ]
    for pattern, multiplier in patterns:
        match = re.search(pattern, text.lower())
        if match:
            return int(match.group(1)) * multiplier
    return None


def parse_protocol_name(text: str) -> Optional[str]:
    """Parse protocol name from natural language text"""
    patterns = [
        r'protocol\s+([A-Za-z0-9_-]+)',
        r'activate\s+([A-Za-z0-9_-]+)',
        r'switch\s+to\s+([A-Za-z0-9_-]+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def format_duration_human(minutes: int) -> str:
    """Format duration in human-readable format"""
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    hours = minutes // 60
    remaining_minutes = minutes % 60
    if remaining_minutes == 0:
        return f"{hours} hour{'s' if hours != 1 else ''}"
    return f"{hours} hour{'s' if hours != 1 else ''} {remaining_minutes} minute{'s' if remaining_minutes != 1 else ''}"


# ============================================================================
# ACTION HANDLERS
# ============================================================================

def _handle_activate(protocol_name: str, duration_minutes: Optional[int] = None) -> Dict[str, Any]:
    """Handle protocol activation"""
    try:
        from mcp_servers.protocols.protocol_loader import load_protocol

        result = load_protocol(protocol_name)
        if not result["success"]:
            return result

        result["duration_minutes"] = duration_minutes or 0
        if duration_minutes and duration_minutes > 0:
            result["duration_human"] = format_duration_human(duration_minutes)
            result["message"] = f"Protocol '{protocol_name}' activated for {format_duration_human(duration_minutes)}"
        else:
            result["message"] = f"Protocol '{protocol_name}' activated permanently (until manually deactivated)"

        print(f"[protocol] ✓ Activated: {protocol_name}", file=sys.stderr)
        return result

    except Exception as e:
        return {"success": False, "error": str(e)}


def _handle_deactivate() -> Dict[str, Any]:
    """Handle protocol deactivation (return to default)"""
    try:
        from mcp_servers.protocols.protocol_loader import load_protocol

        result = load_protocol("default")
        if result["success"]:
            result["message"] = "Protocol deactivated, returned to default configuration"
            print(f"[protocol] ✓ Deactivated, returned to default", file=sys.stderr)
        return result

    except Exception as e:
        return {"success": False, "error": str(e)}


def _handle_status() -> Dict[str, Any]:
    """Handle protocol status query"""
    try:
        conn = get_db_connection()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT protocol_id, protocol_name, activated_at, expires_at,
                           passphrase_hash IS NOT NULL as passphrase_protected
                    FROM active_protocol LIMIT 1
                """)
                active = cur.fetchone()

                if not active:
                    return {"success": False, "error": "No active protocol found"}

        finally:
            conn.close()

        protocol_name = active['protocol_name']
        is_default = protocol_name.lower() == 'default'
        expires_at = active['expires_at']

        time_remaining_str = None
        is_expired = False
        if expires_at:
            time_remaining = expires_at - datetime.now()
            if time_remaining.total_seconds() <= 0:
                is_expired = True
                time_remaining_str = "Expired"
            else:
                time_remaining_str = format_duration_human(int(time_remaining.total_seconds() / 60))

        result = {
            "success": True,
            "active_protocol": protocol_name,
            "is_default": is_default,
            "activated_at": active['activated_at'].isoformat(),
            "expires_at": expires_at.isoformat() if expires_at else None,
            "time_remaining": time_remaining_str,
            "is_expired": is_expired,
            "passphrase_protected": active['passphrase_protected'],
        }

        if is_default:
            result["message"] = "Currently using protocol: 'Default' (baseline configuration)"
        elif is_expired:
            result["message"] = f"Protocol '{protocol_name}' has EXPIRED"
        elif expires_at:
            result["message"] = f"Currently using protocol: '{protocol_name}' (expires in {time_remaining_str})"
        else:
            result["message"] = f"Currently using protocol: '{protocol_name}' (permanent)"

        if active['passphrase_protected']:
            result["message"] += " [Passphrase Protected]"

        print(f"[protocol] ✓ Status: {protocol_name}", file=sys.stderr)
        return result

    except Exception as e:
        return {"success": False, "error": str(e)}


def _handle_list() -> Dict[str, Any]:
    """Handle protocol list query"""
    try:
        conn = get_db_connection()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT protocol_name FROM active_protocol LIMIT 1")
                active_row = cur.fetchone()
                active_name = active_row['protocol_name'] if active_row else None

                cur.execute("""
                    SELECT id, name, description FROM protocols
                    ORDER BY CASE WHEN name = 'Default' THEN 0 ELSE 1 END, name
                """)
                protocols_data = cur.fetchall()

        finally:
            conn.close()

        protocols = []
        for proto in protocols_data:
            protocols.append({
                "id": proto['id'],
                "name": proto['name'],
                "description": proto['description'] or "No description",
                "is_active": proto['name'] == active_name
            })

        return {
            "success": True,
            "protocols": protocols,
            "count": len(protocols),
            "active_protocol": active_name,
            "message": f"Found {len(protocols)} protocols: {', '.join(p['name'] for p in protocols)}"
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================================
# UNIFIED PROTOCOL TOOL
# ============================================================================

@server.register_tool
def protocol(
    action: str,
    name: Optional[str] = None,
    duration: Optional[str] = None,
    request: Optional[str] = None
) -> Dict[str, Any]:
    """
    Unified protocol management tool.

    Actions:
        - "activate": Activate a protocol (requires name)
        - "deactivate": Return to default protocol
        - "status": Get current protocol status
        - "list": List all available protocols

    Args:
        action: The action to perform ("activate", "deactivate", "status", "list")
        name: Protocol name (required for activate)
        duration: Duration string like "8 hours", "30 minutes" (optional, for activate)
        request: Natural language request to parse (optional, for activate)

    Returns:
        dict with success status and action-specific data

    Examples:
        protocol(action="list")
        protocol(action="status")
        protocol(action="activate", name="Theta", duration="8 hours")
        protocol(action="deactivate")
    """
    action = action.lower().strip()
    print(f"[protocol] Action: {action}, name: {name}, duration: {duration}", file=sys.stderr)

    # Route to appropriate handler
    if action == "list":
        return _handle_list()

    elif action == "status":
        return _handle_status()

    elif action == "deactivate":
        return _handle_deactivate()

    elif action == "activate":
        # Parse protocol name from request if not provided
        if not name and request:
            name = parse_protocol_name(request)

        if not name:
            return {
                "success": False,
                "error": "Protocol name required for activation",
                "hint": "Specify name parameter or include protocol name in request"
            }

        # Parse duration
        duration_minutes = None
        if duration:
            duration_minutes = parse_duration(duration)
        elif request:
            duration_minutes = parse_duration(request)

        return _handle_activate(name, duration_minutes)

    else:
        return {
            "success": False,
            "error": f"Unknown action: {action}",
            "valid_actions": ["activate", "deactivate", "status", "list"]
        }


# ============================================================================
# SERVER STARTUP
# ============================================================================

if __name__ == "__main__":
    print("=" * 60, file=sys.stderr)
    print("IRIS PROTOCOL SERVER (Unified)", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print("Tool: protocol(action, name?, duration?, request?)", file=sys.stderr)
    print("Actions: activate, deactivate, status, list", file=sys.stderr)
    print("Starting server...", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    server.run()
