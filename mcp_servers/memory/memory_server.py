"""
Memory Server - Unified MCP server for short-term memory management
Provides insert, retrieve, and archive actions for short-term facts
"""

from mcp.server.fastmcp import FastMCP
import psycopg2
import json
import os
import sys
from datetime import datetime
from typing import Optional

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, PROJECT_ROOT)

from app import config

mcp = FastMCP("Memory Server")


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


def _handle_insert(fact: str, category: Optional[str] = None) -> dict:
    """Store a short-term fact"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO short_term_facts (
                fact_text, category, created_date, last_referenced_date
            ) VALUES (%s, %s, NOW(), NOW())
            RETURNING fact_id, created_date;
        """, (fact, category))

        fact_id, created_date = cursor.fetchone()
        conn.commit()
        cursor.close()
        conn.close()

        print(f"[memory][insert] ✓ Stored fact {fact_id}: {fact[:60]}...")

        return {
            "success": True,
            "fact_id": fact_id,
            "fact": fact,
            "category": category,
            "message": f"Stored fact {fact_id} successfully"
        }

    except Exception as e:
        print(f"[memory][insert] ✗ Error: {e}")
        return {"success": False, "error": str(e)}


def _handle_retrieve(limit: int = 20) -> dict:
    """Retrieve active short-term facts"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT fact_id, fact_text, category, created_date,
                   last_referenced_date, reference_count
            FROM short_term_facts
            WHERE status = 'active'
              AND (created_date > NOW() - INTERVAL '90 days'
                   OR last_referenced_date > NOW() - INTERVAL '30 days')
            ORDER BY last_referenced_date DESC
            LIMIT %s;
        """, (limit,))

        facts = cursor.fetchall()
        fact_list = []
        fact_ids = []

        for row in facts:
            fact_id, text, category, created, referenced, ref_count = row
            fact_list.append({
                "fact_id": fact_id,
                "fact_text": text,
                "category": category,
                "reference_count": ref_count
            })
            fact_ids.append(fact_id)

        # Update reference tracking
        if fact_ids:
            cursor.execute("""
                UPDATE short_term_facts
                SET last_referenced_date = NOW(), reference_count = reference_count + 1
                WHERE fact_id = ANY(%s);
            """, (fact_ids,))
            conn.commit()

        cursor.close()
        conn.close()

        print(f"[memory][retrieve] ✓ Retrieved {len(fact_list)} facts")

        return {
            "success": True,
            "count": len(fact_list),
            "facts": fact_list
        }

    except Exception as e:
        print(f"[memory][retrieve] ✗ Error: {e}")
        return {"success": False, "error": str(e), "facts": []}


def _handle_archive() -> dict:
    """Archive old, unreferenced facts"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE short_term_facts
            SET status = 'archived'
            WHERE created_date < NOW() - INTERVAL '90 days'
              AND last_referenced_date < NOW() - INTERVAL '30 days'
              AND status = 'active'
            RETURNING fact_id, fact_text;
        """)

        archived = cursor.fetchall()
        conn.commit()
        cursor.close()
        conn.close()

        print(f"[memory][archive] ✓ Archived {len(archived)} facts")

        return {
            "success": True,
            "archived_count": len(archived),
            "message": f"Archived {len(archived)} old facts"
        }

    except Exception as e:
        print(f"[memory][archive] ✗ Error: {e}")
        return {"success": False, "error": str(e)}


@mcp.tool()
def memory(
    action: str,
    fact: str = None,
    category: str = None,
    limit: int = 20
) -> str:
    """
    Unified short-term memory management.

    Actions:
        - "insert": Store a new fact (requires fact parameter)
        - "retrieve": Get active facts for context
        - "archive": Archive old, unreferenced facts

    Args:
        action: "insert", "retrieve", or "archive"
        fact: The fact to store (required for insert)
        category: Category for the fact (optional, for insert)
        limit: Max facts to retrieve (default: 20, for retrieve)

    Returns:
        JSON result with action-specific data

    Examples:
        memory(action="insert", fact="Victor prefers dark mode")
        memory(action="retrieve", limit=10)
        memory(action="archive")
    """
    action = action.lower().strip()
    print(f"[memory] Action: {action}")

    if action == "insert":
        if not fact:
            return json.dumps({
                "success": False,
                "error": "fact parameter required for insert action"
            })
        return json.dumps(_handle_insert(fact, category))

    elif action == "retrieve":
        return json.dumps(_handle_retrieve(limit))

    elif action == "archive":
        return json.dumps(_handle_archive())

    else:
        return json.dumps({
            "success": False,
            "error": f"Unknown action: {action}",
            "valid_actions": ["insert", "retrieve", "archive"]
        })


if __name__ == "__main__":
    print("[memory_server] Starting Memory Server (Unified)...")
    print("Tool: memory(action, fact?, category?, limit?)")
    print("Actions: insert, retrieve, archive")
    mcp.run()
