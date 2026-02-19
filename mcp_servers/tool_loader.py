"""
Tool Loader - Load enabled tools from database and format for Ollama

This module queries the mcp_tools table and returns tool definitions
in the format Ollama expects for function calling.

!! CLAUDE: CRITICAL ARCHITECTURE NOTE !!
Tool parameters come from mcp_tools.input_schema in the DATABASE,
NOT from Python function signatures!

When adding/modifying tools:
1. Python code defines the implementation
2. Database schema defines what the MODEL SEES
3. Both must be kept in sync manually via SQL updates

If a tool parameter isn't working, check:
  SELECT input_schema FROM mcp_tools WHERE tool_name = 'your_tool';
"""

import psycopg2
from typing import List, Dict, Any
import os
import sys

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)

from app import config

# Keys that Ollama/Qwen doesn't support in JSON schema metadata
# NOTE: "title" here means the JSON Schema *metadata* field (e.g. {"title": "MyModel", "type": "object"}),
# NOT a tool parameter named "title". We must preserve parameter names inside "properties" dicts.
UNSUPPORTED_KEYS = {"title", "default", "anyOf"}


def prune_schema(obj, _inside_properties=False):
    """
    Remove JSON Schema metadata fields that Ollama/Qwen chokes on.

    Recursively removes 'title', 'default', 'anyOf' from schema objects,
    but preserves keys inside 'properties' dicts (those are tool parameter names,
    not JSON Schema metadata).
    """
    if isinstance(obj, dict):
        result = {}
        for k, v in obj.items():
            # Inside a "properties" dict, keys are parameter names — keep them all
            if _inside_properties:
                result[k] = prune_schema(v, _inside_properties=False)
            elif k in UNSUPPORTED_KEYS:
                continue  # Strip JSON Schema metadata keys
            elif k == "properties":
                # Entering a properties dict — children are parameter names, not metadata
                result[k] = prune_schema(v, _inside_properties=True)
            else:
                result[k] = prune_schema(v, _inside_properties=False)
        return result
    if isinstance(obj, list):
        return [prune_schema(v, _inside_properties=False) for v in obj]
    return obj


def get_db_connection():
    """Create database connection"""
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


def load_enabled_tools() -> List[Dict]:
    """
    Load enabled tools from database and format for Ollama
    
    Returns:
        List of tool definitions in Ollama format:
        [{
            "type": "function",
            "function": {
                "name": "weather_get",
                "description": "...",
                "parameters": {...input_schema...}
            }
        }]
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Query enabled tools, ordered by priority (lower = higher priority)
        cursor.execute("""
            SELECT 
                tool_name,
                description,
                input_schema,
                custom_instructions
            FROM mcp_tools
            WHERE enabled = true
            ORDER BY priority ASC
        """)
        
        tools = []
        for row in cursor.fetchall():
            tool_name, description, input_schema, custom_instructions = row
            
            # Build description with custom instructions if present
            full_description = description
            if custom_instructions:
                full_description = f"{description}\n\nGuidance: {custom_instructions}"
            
            # Format for Ollama function calling
            tool_def = {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": full_description,
                    "parameters": input_schema  # Already in correct JSON Schema format
                }
            }
            
            # Prune unsupported keys from the schema
            tool_def = prune_schema(tool_def)
            
            tools.append(tool_def)
        
        return tools
        
    finally:
        cursor.close()
        conn.close()


def get_tool_by_name(tool_name: str) -> Dict:
    """
    Get a specific tool definition by name
    
    Args:
        tool_name: Name of the tool to retrieve
        
    Returns:
        Tool definition in Ollama format, or None if not found
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT 
                tool_name,
                description,
                input_schema,
                custom_instructions
            FROM mcp_tools
            WHERE tool_name = %s AND enabled = true
        """, (tool_name,))
        
        row = cursor.fetchone()
        if not row:
            return None
        
        tool_name, description, input_schema, custom_instructions = row
        
        # Build description with custom instructions if present
        full_description = description
        if custom_instructions:
            full_description = f"{description}\n\nGuidance: {custom_instructions}"
        
        # Format for Ollama function calling
        return {
            "type": "function",
            "function": {
                "name": tool_name,
                "description": full_description,
                "parameters": input_schema
            }
        }
        
    finally:
        cursor.close()
        conn.close()


def get_tool_count() -> int:
    """
    Get count of enabled tools

    Returns:
        Number of enabled tools
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT COUNT(*) FROM mcp_tools WHERE enabled = true")
        return cursor.fetchone()[0]

    finally:
        cursor.close()
        conn.close()


def upsert_discovered_tool(
    tool_name: str,
    server_name: str,
    description: str = "",
    input_schema: Dict = None
) -> bool:
    """
    Insert or update a tool discovered via MCP protocol.

    This function is called during MCP tool discovery to auto-register
    new tools in the database. It uses INSERT ... ON CONFLICT to either:
    - Insert a new tool (if tool_name doesn't exist)
    - Update server_name, description, input_schema (if tool exists)

    Existing tools retain their:
    - enabled status
    - priority
    - custom_instructions
    - icon
    - tool_group, trigger_keywords, is_core (smart selection metadata)
    - is_autonomous

    Args:
        tool_name: Unique tool identifier
        server_name: MCP server that provides this tool
        description: Tool description from MCP
        input_schema: JSON Schema for tool parameters

    Returns:
        True if tool was inserted/updated, False on error
    """
    import json

    if input_schema is None:
        input_schema = {"type": "object", "properties": {}}

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Use ON CONFLICT to upsert
        # Only update fields that come from MCP discovery
        # Preserve user-configured fields (enabled, priority, custom_instructions, etc.)
        cursor.execute("""
            INSERT INTO mcp_tools (
                tool_name,
                server_name,
                description,
                input_schema,
                enabled,
                priority
            ) VALUES (
                %s, %s, %s, %s, true, 50
            )
            ON CONFLICT (tool_name) DO UPDATE SET
                server_name = EXCLUDED.server_name,
                description = COALESCE(NULLIF(EXCLUDED.description, ''), mcp_tools.description),
                input_schema = CASE
                    WHEN EXCLUDED.input_schema IS NOT NULL
                         AND EXCLUDED.input_schema::text != '{}'
                         AND EXCLUDED.input_schema::text != '{"type": "object", "properties": {}}'
                    THEN EXCLUDED.input_schema
                    ELSE mcp_tools.input_schema
                END,
                updated_at = NOW()
        """, (
            tool_name,
            server_name,
            description,
            json.dumps(input_schema)
        ))

        conn.commit()

        # Check if this was an insert (new tool) or update
        if cursor.rowcount > 0:
            # Check if tool already existed
            cursor.execute(
                "SELECT created_at, updated_at FROM mcp_tools WHERE tool_name = %s",
                (tool_name,)
            )
            row = cursor.fetchone()
            if row:
                created, updated = row
                # If created == updated (within 1 second), this was a new insert
                if abs((updated - created).total_seconds()) < 1:
                    print(f"[ToolLoader] Registered NEW tool: {tool_name} -> {server_name}")
                else:
                    print(f"[ToolLoader] Updated tool: {tool_name} -> {server_name}")

        return True

    except Exception as e:
        print(f"[ToolLoader] Error upserting tool {tool_name}: {e}")
        conn.rollback()
        return False

    finally:
        cursor.close()
        conn.close()


def get_tools_by_server(server_name: str) -> List[str]:
    """
    Get list of tool names registered to a specific server.

    Args:
        server_name: The MCP server name

    Returns:
        List of tool names
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT tool_name
            FROM mcp_tools
            WHERE server_name = %s AND enabled = true
            ORDER BY priority ASC
        """, (server_name,))

        return [row[0] for row in cursor.fetchall()]

    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    """Test the tool loader"""
    print("Loading enabled tools from database...")
    
    tools = load_enabled_tools()
    print(f"\nFound {len(tools)} enabled tools:")
    
    for tool in tools:
        name = tool["function"]["name"]
        desc = tool["function"]["description"].split("\n")[0]  # First line only
        print(f"  - {name}: {desc}")
    
    print("\n--- Sample Tool Definition ---")
    if tools:
        import json
        print(json.dumps(tools[0], indent=2))
