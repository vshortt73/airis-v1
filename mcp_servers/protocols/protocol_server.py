"""
Iris Protocol Management Server - MCP Server for Protocol Activation/Deactivation
Provides natural language protocol switching with security features
"""

import sys
import os
from pathlib import Path
from typing import Dict, Any, Optional
import re
from datetime import datetime, timedelta
import psycopg2
import psycopg2.extras
import bcrypt

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
    description="Protocol activation and management tools with security features"
)

# ============================================================================
# DATABASE CONNECTION
# ============================================================================

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

# ============================================================================
# HELPER FUNCTIONS - Natural Language Parsing
# ============================================================================

def parse_duration(text: str) -> Optional[int]:
    """
    Parse duration from natural language text

    Args:
        text: Input text (e.g., "8 hours", "30 minutes", "2 days")

    Returns:
        Duration in minutes, or None if not found

    Examples:
        >>> parse_duration("activate for 8 hours")
        480
        >>> parse_duration("30 minutes")
        30
        >>> parse_duration("2 days")
        2880
    """
    # Pattern: number + time unit
    patterns = [
        (r'(\d+)\s*h(?:our)?s?', 60),      # hours
        (r'(\d+)\s*m(?:in)?(?:ute)?s?', 1), # minutes
        (r'(\d+)\s*d(?:ay)?s?', 1440),     # days
    ]

    for pattern, multiplier in patterns:
        match = re.search(pattern, text.lower())
        if match:
            return int(match.group(1)) * multiplier

    return None


def parse_passphrase(text: str) -> Optional[str]:
    """
    Parse passphrase from natural language text

    Args:
        text: Input text with passphrase in quotes

    Returns:
        Extracted passphrase, or None if not found

    Examples:
        >>> parse_passphrase('activate with passphrase "bank teller"')
        'bank teller'
        >>> parse_passphrase("passphrase 'override123'")
        'override123'
    """
    # Pattern: passphrase "..." or passphrase '...'
    patterns = [
        r'passphrase\s+"([^"]+)"',
        r"passphrase\s+'([^']+)'",
        r'pass\s*phrase\s+"([^"]+)"',
        r"pass\s*phrase\s+'([^']+)'",
    ]

    for pattern in patterns:
        match = re.search(pattern, text.lower())
        if match:
            return match.group(1)

    return None


def parse_protocol_name(text: str) -> Optional[str]:
    """
    Parse protocol name from natural language text

    Args:
        text: Input text (e.g., "activate protocol Theta")

    Returns:
        Protocol name, or None if not found

    Examples:
        >>> parse_protocol_name("activate protocol Theta")
        'Theta'
        >>> parse_protocol_name("switch to Professional mode")
        'Professional'
    """
    # Pattern: protocol <name> or just <name> after "activate"
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
    """
    Format duration in human-readable format

    Args:
        minutes: Duration in minutes

    Returns:
        Human-readable string

    Examples:
        >>> format_duration_human(480)
        '8 hours'
        >>> format_duration_human(90)
        '1 hour 30 minutes'
    """
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"

    hours = minutes // 60
    remaining_minutes = minutes % 60

    if remaining_minutes == 0:
        return f"{hours} hour{'s' if hours != 1 else ''}"

    return f"{hours} hour{'s' if hours != 1 else ''} {remaining_minutes} minute{'s' if remaining_minutes != 1 else ''}"


# ============================================================================
# PROTOCOL ACTIVATION TOOL
# ============================================================================

@server.register_tool
def protocol_activate(
    request: str,
    protocol_name: Optional[str] = None,
    duration_minutes: Optional[int] = None,
    confirm_defaults: bool = False
) -> Dict[str, Any]:
    """
    Activate a protocol with optional duration

    This tool uses multi-turn parameter gathering. If required parameters
    are missing, it will return needs_more_info=True with prompts.

    Args:
        request: Full natural language request
                Examples: "activate protocol Theta for 8 hours"
        protocol_name: Optional explicit protocol name (if not in request)
        duration_minutes: Optional explicit duration in minutes (if not in request)
        confirm_defaults: Set to True to proceed with defaults if parameters missing

    Returns:
        dict: Activation result or parameter gathering prompts

    Examples:
        >>> result = protocol_activate("activate protocol Theta for 8 hours")
        >>> print(result['message'])
        'Protocol Theta activated for 8 hours'
    """
    try:
        print(f"[protocol_activate] Processing request: {request}")
        print(f"[protocol_activate] Params: name={protocol_name}, duration={duration_minutes}, confirm={confirm_defaults}")

        # Parse protocol name
        if not protocol_name:
            protocol_name = parse_protocol_name(request)

        if not protocol_name:
            return {
                "success": False,
                "error": "Could not determine protocol name. Please specify which protocol to activate.",
                "help": "Example: 'activate protocol Theta' or 'switch to Professional mode'"
            }

        # Parse duration if not explicitly provided
        parsed_duration = None
        if duration_minutes is None:
            parsed_duration = parse_duration(request)
            if parsed_duration is not None:
                duration_minutes = parsed_duration

        # Check if we need to gather more parameters
        missing_params = []
        prompts = {}

        # Only ask for missing parameters if they weren't parsed from request
        # and user hasn't confirmed defaults
        if not confirm_defaults:
            if duration_minutes is None and parsed_duration is None:
                missing_params.append("duration")
                prompts["duration"] = {
                    "question": f"How long should Protocol '{protocol_name}' stay active?",
                    "options": [
                        "Permanent (until manually deactivated)",
                        "8 hours",
                        "4 hours",
                        "1 hour",
                        "30 minutes"
                    ],
                    "hint": "You can specify any duration like '2 days', '6 hours', '45 minutes', or say 'permanent'"
                }


        # If we're missing parameters and haven't confirmed defaults, ask for them
        if missing_params and not confirm_defaults:
            print(f"[protocol_activate] Missing parameters: {missing_params}")
            return {
                "success": False,
                "needs_more_info": True,
                "protocol_name": protocol_name,
                "missing_parameters": missing_params,
                "prompts": prompts,
                "message": f"I need a bit more information to activate Protocol '{protocol_name}'.",
                "next_step": "Please answer the questions above, or say 'use defaults' to proceed with permanent duration."
            }

        # Set defaults if still None
        if duration_minutes is None:
            duration_minutes = 0  # Permanent

        # ==================================================================
        # PROTOCOL ACTIVATION - Using new snapshot/load system
        # ==================================================================
        from mcp_servers.protocols.protocol_loader import snapshot_to_default, load_protocol

        # STEP 1: Snapshot current state to "default" protocol
        try:
            snapshot_to_default()
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to snapshot current state: {str(e)}"
            }

        # STEP 2: Load new protocol
        result = load_protocol(protocol_name)

        if not result["success"]:
            return result

        # Add duration info to result (for now just informational)
        result["duration_minutes"] = duration_minutes
        if duration_minutes > 0:
            result["duration_human"] = format_duration_human(duration_minutes)
            result["message"] = f"Protocol '{protocol_name}' activated for {format_duration_human(duration_minutes)}"
        else:
            result["message"] = f"Protocol '{protocol_name}' activated permanently (until manually deactivated)"

        print(f"[protocol_activate] ✓ Success: {protocol_name}, {duration_minutes}min")

        return result

    except Exception as e:
        error_msg = str(e)
        print(f"[protocol_activate] ✗ Error: {error_msg}")
        return {
            "success": False,
            "error": error_msg
        }


# ============================================================================
# PROTOCOL DEACTIVATION TOOL
# ============================================================================

@server.register_tool
def protocol_deactivate(
    request: str,
    force: bool = False
) -> Dict[str, Any]:
    """
    Deactivate the currently active protocol

    Args:
        request: Full natural language request
                Examples: "deactivate protocol"
        force: Force deactivation (admin override, not exposed to users)

    Returns:
        dict: Deactivation result with:
            - success: bool
            - protocol_name: str (protocol that was active)
            - message: str (human-readable confirmation)
            - error: str (only if success=False)

    Examples:
        >>> result = protocol_deactivate("deactivate protocol")
        >>> print(result['message'])
        'Protocol deactivated, returning to Default'
    """
    try:
        print(f"[protocol_deactivate] Processing request: {request}")

        # ==================================================================
        # PROTOCOL DEACTIVATION - Load "default" protocol (no snapshot)
        # ==================================================================
        from mcp_servers.protocols.protocol_loader import load_protocol

        # Simply load "default" protocol - this restores the snapshot
        result = load_protocol("default")

        if result["success"]:
            result["message"] = "Protocol deactivated, returned to default configuration"
            print(f"[protocol_deactivate] ✓ Success: Returned to default")

        return result

    except Exception as e:
        error_msg = str(e)
        print(f"[protocol_deactivate] ✗ Error: {error_msg}")
        return {
            "success": False,
            "error": error_msg
        }


# ============================================================================
# PROTOCOL STATUS TOOL
# ============================================================================

@server.register_tool
def protocol_status() -> Dict[str, Any]:
    """
    Get the status of the currently active protocol

    This is a SKELETON implementation for testing the tool interface.
    It returns dummy data to test the response structure.

    Returns:
        dict: Protocol status with:
            - success: bool
            - active_protocol: str (name of active protocol)
            - is_default: bool (whether using default protocol)
            - activated_at: str (ISO timestamp when activated)
            - expires_at: str (ISO timestamp when it expires, if duration set)
            - time_remaining: str (human-readable time left)
            - passphrase_protected: bool (whether passphrase required to deactivate)
            - message: str (human-readable status)
            - warning: str (skeleton implementation notice)

    Examples:
        >>> result = protocol_status()
        >>> print(result['message'])
        'Currently using protocol: Default (no expiration)'
    """
    try:
        print(f"[protocol_status] Checking protocol status...")

        # ==================================================================
        # DATABASE OPERATIONS - Query active protocol
        # ==================================================================
        conn = get_db_connection()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        protocol_id,
                        protocol_name,
                        activated_at,
                        expires_at,
                        passphrase_hash IS NOT NULL as passphrase_protected
                    FROM active_protocol
                    LIMIT 1
                """)
                active = cur.fetchone()

                if not active:
                    return {
                        "success": False,
                        "error": "No active protocol found in database.",
                        "hint": "This should not happen - Default should always be active."
                    }

        except Exception as db_error:
            return {
                "success": False,
                "error": f"Database error: {str(db_error)}"
            }
        finally:
            conn.close()

        # Build response
        protocol_name = active['protocol_name']
        is_default = protocol_name == 'Default'
        activated_at = active['activated_at']
        expires_at = active['expires_at']
        passphrase_protected = active['passphrase_protected']

        # Calculate time remaining
        time_remaining_str = None
        is_expired = False
        if expires_at:
            time_remaining = expires_at - datetime.now()
            if time_remaining.total_seconds() <= 0:
                is_expired = True
                time_remaining_str = "Expired"
            else:
                total_minutes = int(time_remaining.total_seconds() / 60)
                time_remaining_str = format_duration_human(total_minutes)

        result = {
            "success": True,
            "active_protocol": protocol_name,
            "is_default": is_default,
            "activated_at": activated_at.isoformat(),
            "expires_at": expires_at.isoformat() if expires_at else None,
            "time_remaining": time_remaining_str,
            "is_expired": is_expired,
            "passphrase_protected": passphrase_protected,
        }

        # Build message
        if is_default:
            result["message"] = "Currently using protocol: 'Default' (baseline configuration)"
        elif is_expired:
            result["message"] = f"Currently using protocol: '{protocol_name}' (EXPIRED - should auto-deactivate)"
        elif expires_at:
            result["message"] = f"Currently using protocol: '{protocol_name}' (expires in {time_remaining_str})"
        else:
            result["message"] = f"Currently using protocol: '{protocol_name}' (permanent)"

        if passphrase_protected:
            result["message"] += " [🔒 Passphrase Protected]"

        print(f"[protocol_status] ✓ Status retrieved: {protocol_name}")

        return result

    except Exception as e:
        error_msg = str(e)
        print(f"[protocol_status] ✗ Error: {error_msg}")
        return {
            "success": False,
            "error": error_msg
        }


# ============================================================================
# PROTOCOL LIST TOOL
# ============================================================================

@server.register_tool
def protocol_list() -> Dict[str, Any]:
    """
    List all available protocols

    This is a SKELETON implementation for testing the tool interface.
    It returns dummy protocol data to test the response structure.

    Returns:
        dict: Available protocols with:
            - success: bool
            - protocols: list of protocol objects with:
                - name: str
                - description: str
                - is_active: bool
            - count: int (number of protocols)
            - message: str (human-readable list)
            - warning: str (skeleton implementation notice)

    Examples:
        >>> result = protocol_list()
        >>> print(result['message'])
        'Found 3 available protocols: Default, Theta, Professional'
    """
    try:
        print(f"[protocol_list] Listing available protocols...")

        # ==================================================================
        # DATABASE OPERATIONS - Query all protocols
        # ==================================================================
        conn = get_db_connection()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                # Get active protocol name
                cur.execute("SELECT protocol_name FROM active_protocol LIMIT 1")
                active_row = cur.fetchone()
                active_name = active_row['protocol_name'] if active_row else None

                # Get all protocols
                cur.execute("""
                    SELECT id, name, description
                    FROM protocols
                    ORDER BY
                        CASE WHEN name = 'Default' THEN 0 ELSE 1 END,
                        name
                """)
                protocols_data = cur.fetchall()

        except Exception as db_error:
            return {
                "success": False,
                "error": f"Database error: {str(db_error)}"
            }
        finally:
            conn.close()

        # Build protocol list
        protocols = []
        for proto in protocols_data:
            protocols.append({
                "id": proto['id'],
                "name": proto['name'],
                "description": proto['description'] or "No description available",
                "is_active": proto['name'] == active_name
            })

        protocol_names = [p["name"] for p in protocols]

        result = {
            "success": True,
            "protocols": protocols,
            "count": len(protocols),
            "active_protocol": active_name,
            "message": f"Found {len(protocols)} available protocols: {', '.join(protocol_names)}"
        }

        print(f"[protocol_list] ✓ Listed {len(protocols)} protocols (active: {active_name})")

        return result

    except Exception as e:
        error_msg = str(e)
        print(f"[protocol_list] ✗ Error: {error_msg}")
        return {
            "success": False,
            "error": error_msg
        }


# ============================================================================
# SERVER STARTUP
# ============================================================================

if __name__ == "__main__":
    print("="*60)
    print("IRIS PROTOCOL SERVER (SKELETON)")
    print("="*60)
    print(f"⚠️ WARNING: This is a SKELETON implementation!")
    print(f"⚠️ Tools will parse requests but NOT change system state")
    print(f"")
    print(f"Tools available:")
    print(f"  - protocol_activate: Activate a protocol")
    print(f"  - protocol_deactivate: Deactivate current protocol")
    print(f"  - protocol_status: Check protocol status")
    print(f"  - protocol_list: List available protocols")
    print(f"")
    print(f"Starting server...")
    print("="*60)
    server.run()
