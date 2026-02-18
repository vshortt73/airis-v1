"""
MCP Server Configurations

Provides server configuration for MCP client connections.
Server configs can be loaded from database (mcp_servers table) or fallback to hardcoded defaults.
Tool-to-server mapping is derived from mcp_tools.server_name column.
"""

from pathlib import Path
from typing import List, Dict, Any, Optional
import os
import sys

# Get the project root directory
PROJECT_ROOT = Path(__file__).parent.parent


def _load_servers_from_database() -> Optional[List[Dict[str, Any]]]:
    """
    Load MCP server configurations from database.

    Returns:
        List of server configs, or None if database unavailable
    """
    try:
        import psycopg2
        sys.path.insert(0, str(PROJECT_ROOT))
        from app import config

        password = os.environ.get('IRIS_DB_PASSWORD') or getattr(config, 'DB_PASSWORD', None)
        conn_params = {
            'host': config.DB_HOST,
            'port': config.DB_PORT,
            'database': config.DB_NAME,
            'user': config.DB_USER
        }
        if password:
            conn_params['password'] = password

        conn = psycopg2.connect(**conn_params)
        cursor = conn.cursor()

        # Check if mcp_servers table exists
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'mcp_servers'
            )
        """)
        if not cursor.fetchone()[0]:
            cursor.close()
            conn.close()
            return None  # Table doesn't exist, use fallback

        # Load server configs
        cursor.execute("""
            SELECT name, command, script_path
            FROM mcp_servers
            WHERE enabled = true
            ORDER BY priority
        """)

        configs = []
        for row in cursor.fetchall():
            name, command, script_path = row
            # Convert relative script_path to absolute
            full_path = str(PROJECT_ROOT / script_path)
            configs.append({
                "name": name,
                "command": command,
                "args": [full_path],
                "tools": []  # Tools mapped via mcp_tools.server_name
            })

        cursor.close()
        conn.close()

        if configs:
            print(f"[ServerConfigs] Loaded {len(configs)} servers from database")
            return configs

        return None  # Empty table, use fallback

    except Exception as e:
        print(f"[ServerConfigs] WARNING: Failed to load from database: {e}")
        return None


def _load_tool_server_mapping() -> Dict[str, str]:
    """
    Load tool-to-server mapping from mcp_tools.server_name column.

    Returns:
        Dict mapping tool_name -> server_name
    """
    try:
        import psycopg2
        sys.path.insert(0, str(PROJECT_ROOT))
        from app import config

        password = os.environ.get('IRIS_DB_PASSWORD') or getattr(config, 'DB_PASSWORD', None)
        conn_params = {
            'host': config.DB_HOST,
            'port': config.DB_PORT,
            'database': config.DB_NAME,
            'user': config.DB_USER
        }
        if password:
            conn_params['password'] = password

        conn = psycopg2.connect(**conn_params)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT tool_name, server_name
            FROM mcp_tools
            WHERE enabled = true AND server_name IS NOT NULL
        """)

        mapping = {row[0]: row[1] for row in cursor.fetchall()}

        cursor.close()
        conn.close()

        return mapping

    except Exception as e:
        print(f"[ServerConfigs] WARNING: Failed to load tool-server mapping: {e}")
        return {}


def _get_fallback_configs() -> List[Dict[str, Any]]:
    """
    Fallback hardcoded server configurations.
    Used when database is unavailable or mcp_servers table doesn't exist.
    """
    return [
        {
            "name": "info",
            "command": "python",
            "args": [str(PROJECT_ROOT / "mcp_servers" / "info" / "info_server.py")],
            "tools": [
                "weather",
                "research",
                "face",
                "news_headlines",
                "web_search",
                "url_fetch",
                "webcam_recognize"
            ]
        },
        {
            "name": "knowledge",
            "command": "python",
            "args": [str(PROJECT_ROOT / "mcp_servers" / "knowledge" / "knowledge_server.py")],
            "tools": [
                "knowledge",
                "knowledge_save",
            ]
        },
        {
            "name": "traits",
            "command": "python",
            "args": [str(PROJECT_ROOT / "mcp_servers" / "traits" / "traits_server.py")],
            "tools": [
                "trait"
            ]
        },
        {
            "name": "memory",
            "command": "python",
            "args": [str(PROJECT_ROOT / "mcp_servers" / "memory" / "memory_server.py")],
            "tools": [
                "memory"
            ]
        },
        {
            "name": "creative",
            "command": "python",
            "args": [str(PROJECT_ROOT / "mcp_servers" / "creative" / "creative_server.py")],
            "tools": [
                "image"
            ]
        },
        {
            "name": "system",
            "command": "python",
            "args": [str(PROJECT_ROOT / "mcp_servers" / "system" / "system_server.py")],
            "tools": [
                "generate_alerts",
                "get_system_health_statistics",
                "system_status_summary",
                "linux_shell",
                "database_query",
                "distributed_system_health",
            ]
        },
        {
            "name": "protocols",
            "command": "python",
            "args": [str(PROJECT_ROOT / "mcp_servers" / "protocols" / "protocol_server.py")],
            "tools": [
                "protocol"
            ]
        },
        {
            "name": "directions",
            "command": "python",
            "args": [str(PROJECT_ROOT / "mcp_servers" / "directions" / "directions_server.py")],
            "tools": [
                "ship_directions",
                "ship_locations",
            ]
        },
        {
            "name": "seeds",
            "command": "python",
            "args": [str(PROJECT_ROOT / "mcp_servers" / "seeds" / "seeds_server.py")],
            "tools": [
                "seed"
            ]
        },
        {
            "name": "calendar",
            "command": "python",
            "args": [str(PROJECT_ROOT / "mcp_servers" / "calendar" / "calendar_server.py")],
            "tools": [
                "calendar",
                "calendar_add",
            ]
        },
        {
            "name": "meeting",
            "command": "python",
            "args": [str(PROJECT_ROOT / "mcp_servers" / "meeting" / "meeting_server.py")],
            "tools": [
                "meeting",
                "meeting_start",
            ]
        },
        {
            "name": "moltbook",
            "command": "python",
            "args": [str(PROJECT_ROOT / "mcp_servers" / "moltbook" / "moltbook_server.py")],
            "tools": [
                "moltbook",
                "moltbook_post",
            ]
        }
    ]


def get_server_configs() -> List[Dict[str, Any]]:
    """
    Get MCP server connection configurations.

    First tries to load from database (mcp_servers table).
    Falls back to hardcoded configs if database unavailable.

    Returns:
        List of server configs with:
        - name: Server identifier
        - command: Command to run (python, node, etc.)
        - args: Command arguments (path to server script)
        - tools: List of tool names this server provides (from DB or fallback)
    """
    # Try database first
    db_configs = _load_servers_from_database()

    if db_configs:
        # Load tool-to-server mapping to populate tools arrays
        tool_mapping = _load_tool_server_mapping()

        # Build tools list for each server from mapping
        for config in db_configs:
            config["tools"] = [
                tool_name for tool_name, server_name in tool_mapping.items()
                if server_name == config["name"]
            ]

        return db_configs

    # Fallback to hardcoded
    print("[ServerConfigs] Using fallback hardcoded configs")
    return _get_fallback_configs()


def get_tools_by_server() -> Dict[str, List[str]]:
    """
    Get mapping of server names to their tools

    Returns:
        Dict mapping server name to list of tool names
    """
    configs = get_server_configs()
    return {config["name"]: config["tools"] for config in configs}


def get_server_for_tool(tool_name: str) -> Optional[str]:
    """
    Get which server provides a specific tool

    Args:
        tool_name: Name of the tool

    Returns:
        Server name, or None if tool not found
    """
    for config in get_server_configs():
        if tool_name in config["tools"]:
            return config["name"]
    return None


def _load_autonomous_tools_from_db() -> Optional[List[str]]:
    """Load autonomous tools list from database."""
    try:
        import psycopg2
        sys.path.insert(0, str(PROJECT_ROOT))
        from app import config

        password = os.environ.get('IRIS_DB_PASSWORD') or getattr(config, 'DB_PASSWORD', None)
        conn_params = {
            'host': config.DB_HOST,
            'port': config.DB_PORT,
            'database': config.DB_NAME,
            'user': config.DB_USER
        }
        if password:
            conn_params['password'] = password

        conn = psycopg2.connect(**conn_params)
        cursor = conn.cursor()

        # Check if is_autonomous column exists
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.columns
                WHERE table_name = 'mcp_tools' AND column_name = 'is_autonomous'
            )
        """)
        if not cursor.fetchone()[0]:
            cursor.close()
            conn.close()
            return None  # Column doesn't exist, use fallback

        cursor.execute("""
            SELECT tool_name
            FROM mcp_tools
            WHERE enabled = true AND is_autonomous = true
        """)

        tools = [row[0] for row in cursor.fetchall()]
        cursor.close()
        conn.close()

        return tools if tools else None

    except Exception as e:
        return None


def get_autonomous_tools() -> List[str]:
    """
    Get list of tools that can be called autonomously without confirmation.

    First tries to load from mcp_tools.is_autonomous column.
    Falls back to hardcoded list if database unavailable.

    Returns:
        List of tool names that are safe for autonomous use
    """
    # Try database first
    db_tools = _load_autonomous_tools_from_db()
    if db_tools:
        return db_tools

    # Fallback to hardcoded
    return [
        "weather",
        "research",
        "face",
        "news_headlines",
        "web_search",
        "url_fetch",
        "webcam_recognize",
        "linux_shell",
        "knowledge",
        "knowledge_save",
        "trait",
        "memory",
        "protocol",
        "ship_directions",
        "ship_locations",
        "seed",
        "image",
        "calendar",
        "calendar_add",
        "meeting",
        "meeting_start",
        "moltbook",
        "moltbook_post",
        "database_query",
        "distributed_system_health",
    ]


def get_confirmation_required_tools() -> List[str]:
    """
    Get list of tools that require user confirmation before execution

    Returns:
        List of tool names that need confirmation
    """
    return [
        "service_start",
        "service_stop",
        "service_restart",
        "monitor_add",
        "monitor_remove",
        "trait_modify",
        "rtsp_show_named",
        "rtsp_popup_show",
        "trait"
    ]


def is_tool_autonomous(tool_name: str) -> bool:
    """
    Check if a tool can be called autonomously

    Args:
        tool_name: Name of the tool

    Returns:
        True if tool can be called without confirmation
    """
    return tool_name in get_autonomous_tools()


if __name__ == "__main__":
    """Test server configurations"""
    print("=" * 60)
    print("MCP SERVER CONFIGURATIONS")
    print("=" * 60)

    configs = get_server_configs()
    print(f"\nConfigured servers: {len(configs)}")

    for config in configs:
        print(f"\n{config['name'].upper()} Server:")
        print(f"  Command: {config['command']} {' '.join(config['args'])}")
        print(f"  Tools ({len(config['tools'])}):")
        for tool in config["tools"]:
            auto = "AUTO" if is_tool_autonomous(tool) else "CONFIRM"
            print(f"    - {tool} [{auto}]")

    print("\n" + "=" * 60)
    print(f"Total tools: {sum(len(c['tools']) for c in configs)}")
    print(f"Autonomous: {len(get_autonomous_tools())}")
    print(f"Require confirmation: {len(get_confirmation_required_tools())}")
