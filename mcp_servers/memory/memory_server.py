"""
Memory Server - MCP server for short-term memory management

Provides tools for:
- Storing short-term facts (manually flagged by user)
- Retrieving active facts for context injection
"""

from mcp.server.fastmcp import FastMCP
import psycopg2
import json
import os
import sys
from datetime import datetime

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, PROJECT_ROOT)

from app import config

# Initialize MCP server
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


@mcp.tool()
def short_term_memory_insert(fact: str, category: str = None, conversation_id: str = None) -> str:
    """
    Store a short-term fact for future reference.

    Use this tool when Victor explicitly says:
    - "Remember this: [fact]"
    - "Make a note: [fact]"
    - "Don't forget: [fact]"
    - "For future reference: [fact]"

    Args:
        fact: Single sentence factual statement to remember
        category: Optional category (ongoing_project, user_preference, discovery, user_status, other)
        conversation_id: Optional conversation/session ID for traceability

    Returns:
        JSON result with success status and fact_id
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Insert fact into database
        cursor.execute("""
            INSERT INTO short_term_facts (
                fact_text,
                category,
                conversation_id,
                created_date,
                last_referenced_date
            ) VALUES (
                %s, %s, %s, NOW(), NOW()
            ) RETURNING fact_id, created_date;
        """, (fact, category, conversation_id))

        result = cursor.fetchone()
        fact_id, created_date = result

        conn.commit()
        cursor.close()
        conn.close()

        print(f"[memory_server][insert] ✓ Stored fact {fact_id}: {fact[:60]}...")

        return json.dumps({
            "success": True,
            "fact_id": fact_id,
            "fact": fact,
            "category": category,
            "created_date": created_date.isoformat(),
            "message": f"Stored fact {fact_id} successfully"
        })

    except Exception as e:
        print(f"[memory_server][insert] ✗ Error: {e}")
        return json.dumps({
            "success": False,
            "error": str(e)
        })


@mcp.tool()
def short_term_memory_retrieve(limit: int = 20) -> str:
    """
    Retrieve active short-term facts for context injection.

    Returns facts that are:
    - Status: active (not archived)
    - Created within last 90 days OR referenced within last 30 days
    - Ordered by most recently referenced first

    Args:
        limit: Maximum number of facts to retrieve (default: 20)

    Returns:
        JSON result with list of active facts
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Retrieve active facts
        cursor.execute("""
            SELECT
                fact_id,
                fact_text,
                category,
                created_date,
                last_referenced_date,
                reference_count
            FROM short_term_facts
            WHERE status = 'active'
              AND (
                created_date > NOW() - INTERVAL '90 days'
                OR last_referenced_date > NOW() - INTERVAL '30 days'
              )
            ORDER BY last_referenced_date DESC
            LIMIT %s;
        """, (limit,))

        facts = cursor.fetchall()

        # Format facts for return
        fact_list = []
        fact_ids_to_update = []

        for row in facts:
            fact_id, text, category, created, referenced, ref_count = row

            fact_list.append({
                "fact_id": fact_id,
                "fact_text": text,
                "category": category,
                "created_date": created.isoformat() if created else None,
                "last_referenced_date": referenced.isoformat() if referenced else None,
                "reference_count": ref_count
            })

            fact_ids_to_update.append(fact_id)

        # Update reference tracking for retrieved facts
        if fact_ids_to_update:
            cursor.execute("""
                UPDATE short_term_facts
                SET
                    last_referenced_date = NOW(),
                    reference_count = reference_count + 1
                WHERE fact_id = ANY(%s);
            """, (fact_ids_to_update,))

            conn.commit()

        cursor.close()
        conn.close()

        print(f"[memory_server][retrieve] ✓ Retrieved {len(fact_list)} active facts")

        return json.dumps({
            "success": True,
            "count": len(fact_list),
            "facts": fact_list
        })

    except Exception as e:
        print(f"[memory_server][retrieve] ✗ Error: {e}")
        return json.dumps({
            "success": False,
            "error": str(e),
            "facts": []
        })


@mcp.tool()
def short_term_memory_archive_old() -> str:
    """
    Archive old, unreferenced facts.

    Archives facts that:
    - Created more than 90 days ago AND
    - Not referenced in the last 30 days AND
    - Currently have status 'active'

    Archived facts are NOT deleted - they remain in database for training data.

    Returns:
        JSON result with count of archived facts
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Archive old facts
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

        archived_list = [
            {"fact_id": fid, "fact_text": text}
            for fid, text in archived
        ]

        cursor.close()
        conn.close()

        print(f"[memory_server][archive] ✓ Archived {len(archived_list)} facts")

        return json.dumps({
            "success": True,
            "archived_count": len(archived_list),
            "archived_facts": archived_list
        })

    except Exception as e:
        print(f"[memory_server][archive] ✗ Error: {e}")
        return json.dumps({
            "success": False,
            "error": str(e)
        })


# Run server
if __name__ == "__main__":
    print("[memory_server] Starting Memory Server...")
    print("[memory_server] Available tools:")
    print("  - short_term_memory_insert")
    print("  - short_term_memory_retrieve")
    print("  - short_term_memory_archive_old")
    mcp.run()
