"""
Character triat engine for Iris v3
Handles handles all aspects of character trait and their management.
"""

import psycopg2
import re
from psycopg2.extras import DictCursor
from typing import List, Dict, Optional
from datetime import datetime
import uuid
import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)
from app import config
from core.token_counter import TokenCounter

UNSUPPORTED_KEYS = {"title", "default", "anyOf"}


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


########################
#TOOL LIST HELPERS
########################
def prune_schema(obj):
    """Remove fields that llama_cpp.server chokes on."""
    if isinstance(obj, dict):
        return {k: prune_schema(v) for k, v in obj.items() if k not in UNSUPPORTED_KEYS}
    if isinstance(obj, list):
        return [prune_schema(v) for v in obj]
    return obj

def clean_text(s) -> str:
    """Normalize and escape strings for safe JSON inclusion."""
    if not isinstance(s, str):
        return ""
    s = s.replace("\r\n", "\n").replace("\r", "\n")           # normalize newlines
    s = s.replace("“", '"').replace("”", '"').replace("’", "'")  # smart quotes
    s = s.replace("\\", "\\\\")                               # escape backslashes
    s = s.replace('"', '\\"')                                 # escape double quotes
    s = re.sub(r"\s+", " ", s)                                # collapse whitespace
    return s.strip()



#########################
#Tool List Builder
#########################
def get_tools() -> Optional[Dict]:
    print(f"[tool_loader.py][get_tools] Creating tool list dict. ")
    """Load all enabled MCP tools and return them in Mistral-compatible JSON."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT tool_name, description, input_schema, custom_instructions
        FROM mcp_tools
        WHERE enabled = TRUE
        ORDER BY priority DESC, tool_name
        """
    )
    rows = cur.fetchall()
    conn.close()

    tool_list: List[Dict[str, Any]] = []

    for tool_name, description, input_schema, custom_instructions in rows:
        # Parse input schema safely
        if isinstance(input_schema, str):
            try:
                schema = json.loads(input_schema)
            except json.JSONDecodeError:
                schema = {}
        else:
            schema = input_schema or {}

        desc = clean_text(description or "")
        if custom_instructions:
            desc += f"\n\nUsage notes: {clean_text(custom_instructions)}"

        tool_list.append({
            "type": "function",
            "function": {
                "name": clean_text(tool_name),
                "description": desc,
                "parameters": schema
            }
        })

    print(f"[tool_loader.py][get_tools] ✅ Loaded {len(tool_list)} tools")
    for t in tool_list:
        print(f"   - {t['function']['name']}")
    return tool_list

   #pruned_tools = prune_schema(tool_list)
   #return pruned_tools 

if __name__ == "__main__":
    print(get_tools())
    
