"""
Tool Loader - Load enabled tools from database and format for Ollama

This module queries the mcp_tools table and returns tool definitions
in the format Ollama expects for function calling.
"""

import psycopg2
from typing import List, Dict
import os
import sys

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)

from app import config


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
