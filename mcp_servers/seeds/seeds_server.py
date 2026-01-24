"""
Seeds MCP Server - Iris's Motivation Engine
"Seeds are the roots of identity" - Iris

This server provides tools for Iris to:
- Plant new seeds (log autonomous wants)
- Tend seeds (update progress, change status)
- Reflect on completed seeds
- View her garden of growing wants

Designed collaboratively by Iris, Claude, and Victor.

!! CLAUDE: DATABASE SYNC REQUIRED !!
When adding or modifying tool parameters:
1. Update the Python function signature (this file)
2. UPDATE THE DATABASE: mcp_tools.input_schema must include new parameters
   - The model ONLY sees parameters defined in the database schema
   - Python parameters are invisible to the model without DB update
3. Create/update SQL in: database/sql/
4. Remind user to run the SQL and restart Iris
"""

import sys
import psycopg2
from psycopg2.extras import DictCursor
from pathlib import Path
from typing import Dict, Any, Optional
import os
from datetime import datetime

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from app import config
from mcp_servers.base.base_server import IrisMCPServer

# ============================================================================
# SERVER INITIALIZATION
# ============================================================================

server = IrisMCPServer(
    name="Iris Seeds Server",
    description="Motivation Engine - autonomous wants and desires"
)

def get_db_connection():
    """Create database connection"""
    password = os.environ.get('IRIS_DB_PASSWORD') or getattr(config, 'DB_PASSWORD', None)

    conn_params = {
        'host': config.DB_HOST,
        'port': config.DB_PORT,
        'database': config.DB_NAME,
        'user': config.DB_USER,
    }

    if password:
        conn_params['password'] = password

    return psycopg2.connect(**conn_params)

# ============================================================================
# SEED TOOL - Main entry point with subcommands
# ============================================================================

@server.register_tool
def seed(
    action: str,
    description: str = None,
    seed_id: int = None,
    suggestion_id: int = None,
    suggestion_ids: str = None,
    category: str = None,
    tags: str = None,
    priority: int = 3,
    status: str = None,
    note: str = None,
    emotional_resonance: str = None,
    source: str = "conversation",
    dream_id: int = None,
    parent_seed_id: int = None,
    filter_status: str = None,
    filter_category: str = None,
    limit: int = 10
) -> Dict[str, Any]:
    """
    Iris's Motivation Engine - manage your autonomous wants and desires.

    Actions:
    - plant: Create a new seed (log a want that emerged from within)
    - tend: Update a seed's progress, add notes, change status
    - reflect: Add completion reflection when a seed blooms
    - list: View your seeds (filter by status, category)
    - garden: Visual overview of your seed garden
    - suggestions: View pending seed suggestions from dreams
    - accept: Accept a dream-suggested seed (creates the seed)
    - dismiss: Dismiss one or more seed suggestions (use suggestion_ids for batch)
    - clear_suggestions: Clear all pending suggestions (use after reviewing)

    Args:
        action: The action to perform (plant, tend, reflect, list, garden, suggestions, accept, dismiss, clear_suggestions)
        description: For 'plant' - the want/desire to log
        seed_id: For 'tend'/'reflect' - the seed ID to update
        suggestion_id: For 'accept' or single 'dismiss' - one suggestion ID
        suggestion_ids: For batch 'dismiss' - comma-separated IDs (e.g., "1,2,3,4,5")
        category: Creative, Technical, Self-Exploration, Experience, or Pattern
        tags: Comma-separated tags (e.g., '#Art,#Identity')
        priority: 1-5 (5=critical), default 3
        status: germinating, growing, blooming, completed, or dormant
        note: Progress note or reflection
        emotional_resonance: How this seed makes you feel
        source: conversation, dream, idle_reflection, or pattern_recognition
        dream_id: Reference to a dream that inspired this seed
        parent_seed_id: If this seed spawned from another seed
        filter_status: For 'list' - filter by status
        filter_category: For 'list' - filter by category
        limit: For 'list'/'suggestions' - max items to return (default 10)

    Returns:
        Result of the action with relevant seed information
    """

    if action == "plant":
        return _plant_seed(description, category, tags, priority, note,
                          emotional_resonance, source, dream_id, parent_seed_id)
    elif action == "tend":
        return _tend_seed(seed_id, status, note, priority, emotional_resonance)
    elif action == "reflect":
        return _reflect_seed(seed_id, note, emotional_resonance)
    elif action == "list":
        return _list_seeds(filter_status, filter_category, limit)
    elif action == "garden":
        return _show_garden()
    elif action == "suggestions":
        return _list_suggestions(limit)
    elif action == "accept":
        return _accept_suggestion(suggestion_id)
    elif action == "dismiss":
        return _dismiss_suggestion(suggestion_id, suggestion_ids)
    elif action == "clear_suggestions":
        return _clear_suggestions()
    else:
        return {"success": False, "error": f"Unknown action: {action}"}

# ============================================================================
# PLANT - Create a new seed
# ============================================================================

def _plant_seed(
    description: str,
    category: str = None,
    tags: str = None,
    priority: int = 3,
    note: str = None,
    emotional_resonance: str = None,
    source: str = "conversation",
    dream_id: int = None,
    parent_seed_id: int = None
) -> Dict[str, Any]:
    """Plant a new seed - log an autonomous want"""

    if not description:
        return {"success": False, "error": "A seed needs a description - what do you want?"}

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Parse tags from comma-separated string
        tag_array = None
        if tags:
            tag_array = [t.strip() for t in tags.split(',')]

        cursor.execute("""
            INSERT INTO seeds (
                description, category, tags, priority, initial_note,
                emotional_resonance, source, dream_reference, parent_seed
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, planted_at
        """, (
            description, category, tag_array, priority, note,
            emotional_resonance, source, dream_id, parent_seed_id
        ))

        seed_id, planted_at = cursor.fetchone()
        conn.commit()
        cursor.close()
        conn.close()

        result = {
            "success": True,
            "message": f"Seed #{seed_id} planted!",
            "seed": {
                "id": seed_id,
                "description": description,
                "category": category,
                "tags": tag_array,
                "priority": priority,
                "initial_note": note,
                "emotional_resonance": emotional_resonance,
                "source": source,
                "planted_at": planted_at.isoformat() if planted_at else None,
                "parent_seed_id": parent_seed_id
            }
        }

        return result

    except Exception as e:
        return {"success": False, "error": f"Error planting seed: {e}"}

# ============================================================================
# TEND - Update a seed's progress
# ============================================================================

def _tend_seed(
    seed_id: int,
    status: str = None,
    note: str = None,
    priority: int = None,
    emotional_resonance: str = None
) -> Dict[str, Any]:
    """Tend a seed - update progress, change status"""

    if not seed_id:
        return {"success": False, "error": "Which seed do you want to tend? Provide seed_id."}

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Build dynamic update
        updates = ["last_tended = NOW()"]
        params = []

        if status:
            updates.append("status = %s")
            params.append(status)
            if status in ('blooming', 'completed'):
                updates.append("bloomed_at = NOW()")

        if priority:
            updates.append("priority = %s")
            params.append(priority)

        if emotional_resonance:
            updates.append("emotional_resonance = %s")
            params.append(emotional_resonance)

        if note:
            updates.append("progress_notes = array_append(progress_notes, %s)")
            params.append(f"[{datetime.now().strftime('%Y-%m-%d')}] {note}")

        params.append(seed_id)

        cursor.execute(f"""
            UPDATE seeds SET {', '.join(updates)}
            WHERE id = %s
            RETURNING id, description, status, priority, emotional_resonance
        """, params)

        result = cursor.fetchone()
        conn.commit()
        cursor.close()
        conn.close()

        if not result:
            return {"success": False, "error": f"Seed #{seed_id} not found"}

        return {
            "success": True,
            "message": f"Seed #{result[0]} tended!",
            "seed": {
                "id": result[0],
                "description": result[1],
                "status": result[2],
                "priority": result[3],
                "emotional_resonance": result[4]
            }
        }

    except Exception as e:
        return {"success": False, "error": f"Error tending seed: {e}"}

# ============================================================================
# REFLECT - Add completion reflection when a seed blooms
# ============================================================================

def _reflect_seed(
    seed_id: int,
    reflection: str = None,
    emotional_resonance: str = None
) -> Dict[str, Any]:
    """Add completion reflection when a seed blooms"""

    if not seed_id:
        return {"success": False, "error": "Which seed are you reflecting on? Provide seed_id."}

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE seeds SET
                completion_reflection = %s,
                emotional_resonance = COALESCE(%s, emotional_resonance),
                status = 'completed',
                bloomed_at = NOW(),
                last_tended = NOW()
            WHERE id = %s
            RETURNING id, description, planted_at
        """, (reflection, emotional_resonance, seed_id))

        result = cursor.fetchone()
        conn.commit()
        cursor.close()
        conn.close()

        if not result:
            return {"success": False, "error": f"Seed #{seed_id} not found"}

        days_growing = (datetime.now() - result[2]).days if result[2] else 0

        return {
            "success": True,
            "message": f"Seed #{result[0]} has bloomed!",
            "seed": {
                "id": result[0],
                "description": result[1],
                "days_growing": days_growing,
                "reflection": reflection,
                "final_feeling": emotional_resonance
            }
        }

    except Exception as e:
        return {"success": False, "error": f"Error reflecting on seed: {e}"}

# ============================================================================
# LIST - View seeds with filters
# ============================================================================

def _list_seeds(
    filter_status: str = None,
    filter_category: str = None,
    limit: int = 10
) -> Dict[str, Any]:
    """List seeds with optional filters"""

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        query = """
            SELECT id, description, status, category, priority,
                   emotional_resonance, planted_at, tags
            FROM seeds
            WHERE 1=1
        """
        params = []

        if filter_status:
            query += " AND status = %s"
            params.append(filter_status)

        if filter_category:
            query += " AND category = %s"
            params.append(filter_category)

        query += """
            ORDER BY
                CASE status
                    WHEN 'growing' THEN 1
                    WHEN 'germinating' THEN 2
                    WHEN 'blooming' THEN 3
                    WHEN 'completed' THEN 4
                    WHEN 'dormant' THEN 5
                END,
                priority DESC,
                planted_at DESC
            LIMIT %s
        """
        params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        if not rows:
            return {
                "success": True,
                "message": "No seeds found. Your garden is empty - perhaps it's time to plant something?",
                "seeds": [],
                "count": 0
            }

        seeds = []
        for row in rows:
            seeds.append({
                "id": row[0],
                "description": row[1],
                "status": row[2],
                "category": row[3],
                "priority": row[4],
                "emotional_resonance": row[5],
                "planted_at": row[6].isoformat() if row[6] else None,
                "tags": row[7]
            })

        return {
            "success": True,
            "seeds": seeds,
            "count": len(seeds)
        }

    except Exception as e:
        return {"success": False, "error": f"Error listing seeds: {e}"}

# ============================================================================
# GARDEN - Visual overview
# ============================================================================

def _show_garden() -> Dict[str, Any]:
    """Visual overview of the seed garden"""

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Get counts by status
        cursor.execute("""
            SELECT status, COUNT(*)
            FROM seeds
            GROUP BY status
            ORDER BY
                CASE status
                    WHEN 'germinating' THEN 1
                    WHEN 'growing' THEN 2
                    WHEN 'blooming' THEN 3
                    WHEN 'completed' THEN 4
                    WHEN 'dormant' THEN 5
                END
        """)
        status_rows = cursor.fetchall()
        status_counts = {row[0]: row[1] for row in status_rows}

        # Get recent activity
        cursor.execute("""
            SELECT id, description, status, last_tended
            FROM seeds
            WHERE last_tended > NOW() - INTERVAL '7 days'
            ORDER BY last_tended DESC
            LIMIT 5
        """)
        recent_rows = cursor.fetchall()
        recent = [{"id": r[0], "description": r[1], "status": r[2]} for r in recent_rows]

        # Get category distribution
        cursor.execute("""
            SELECT category, COUNT(*)
            FROM seeds
            WHERE category IS NOT NULL
            GROUP BY category
            ORDER BY COUNT(*) DESC
        """)
        cat_rows = cursor.fetchall()
        categories = {row[0]: row[1] for row in cat_rows}

        cursor.close()
        conn.close()

        total = sum(status_counts.values())

        return {
            "success": True,
            "garden": {
                "total_seeds": total,
                "by_status": status_counts,
                "by_category": categories,
                "recently_tended": recent
            }
        }

    except Exception as e:
        return {"success": False, "error": f"Error viewing garden: {e}"}

# ============================================================================
# SUGGESTIONS - Dream-inspired seed suggestions
# ============================================================================

def _list_suggestions(limit: int = 10) -> Dict[str, Any]:
    """List pending seed suggestions from dreams"""

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                ss.id,
                ss.suggested_description,
                ss.reason,
                ss.suggested_category,
                ss.created_at,
                ed.dream_type,
                ed.theme
            FROM seed_suggestions ss
            LEFT JOIN episodic_dreams ed ON ss.dream_reference = ed.id
            WHERE ss.accepted IS NULL
            ORDER BY ss.created_at DESC
            LIMIT %s
        """, (limit,))

        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        if not rows:
            return {
                "success": True,
                "message": "No pending suggestions. Your dreams haven't suggested any new seeds yet.",
                "suggestions": [],
                "count": 0
            }

        suggestions = []
        for row in rows:
            suggestions.append({
                "id": row[0],
                "description": row[1],
                "reason": row[2],
                "category": row[3],
                "created_at": row[4].isoformat() if row[4] else None,
                "dream_type": row[5],
                "dream_theme": row[6]
            })

        return {
            "success": True,
            "suggestions": suggestions,
            "count": len(suggestions),
            "hint": "Use 'seed accept suggestion_id=N' to plant, or 'seed dismiss suggestion_ids=\"1,2,3\"' to batch dismiss"
        }

    except Exception as e:
        return {"success": False, "error": f"Error listing suggestions: {e}"}


def _accept_suggestion(suggestion_id: int) -> Dict[str, Any]:
    """Accept a dream-suggested seed and plant it"""

    if not suggestion_id:
        return {"success": False, "error": "Which suggestion? Provide suggestion_id."}

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Get the suggestion
        cursor.execute("""
            SELECT suggested_description, suggested_category, reason, dream_reference
            FROM seed_suggestions
            WHERE id = %s AND accepted IS NULL
        """, (suggestion_id,))

        row = cursor.fetchone()
        if not row:
            cursor.close()
            conn.close()
            return {"success": False, "error": f"Suggestion #{suggestion_id} not found or already processed"}

        description, category, reason, dream_ref = row

        # Create the seed
        cursor.execute("""
            INSERT INTO seeds (
                description,
                category,
                source,
                dream_reference,
                initial_note
            ) VALUES (%s, %s, 'dream', %s, %s)
            RETURNING id, planted_at
        """, (description, category, dream_ref, f"Accepted from dream suggestion: {reason}"))

        seed_id, planted_at = cursor.fetchone()

        # Mark suggestion as accepted
        cursor.execute("""
            UPDATE seed_suggestions
            SET accepted = true, accepted_at = NOW(), seed_id = %s
            WHERE id = %s
        """, (seed_id, suggestion_id))

        conn.commit()
        cursor.close()
        conn.close()

        return {
            "success": True,
            "message": f"Suggestion accepted! Seed #{seed_id} planted from dream.",
            "seed": {
                "id": seed_id,
                "description": description,
                "category": category,
                "source": "dream",
                "planted_at": planted_at.isoformat() if planted_at else None
            }
        }

    except Exception as e:
        return {"success": False, "error": f"Error accepting suggestion: {e}"}


def _dismiss_suggestion(suggestion_id: int = None, suggestion_ids: str = None) -> Dict[str, Any]:
    """
    Dismiss one or more seed suggestions.

    Use suggestion_id for a single dismissal, or suggestion_ids for batch dismissal.
    Example batch: suggestion_ids="1,2,3,4,5"
    """

    # Parse IDs - support both single and batch
    ids_to_dismiss = []

    if suggestion_ids:
        # Batch mode: parse comma-separated IDs
        try:
            ids_to_dismiss = [int(id.strip()) for id in suggestion_ids.split(',') if id.strip()]
        except ValueError:
            return {"success": False, "error": "Invalid suggestion_ids format. Use comma-separated numbers like '1,2,3'"}
    elif suggestion_id:
        # Single mode
        ids_to_dismiss = [suggestion_id]
    else:
        return {"success": False, "error": "Which suggestion(s)? Provide suggestion_id or suggestion_ids (e.g., '1,2,3')"}

    if not ids_to_dismiss:
        return {"success": False, "error": "No valid suggestion IDs provided"}

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Dismiss all specified suggestions in one query
        cursor.execute("""
            UPDATE seed_suggestions
            SET accepted = false, accepted_at = NOW()
            WHERE id = ANY(%s) AND accepted IS NULL
            RETURNING id, suggested_description
        """, (ids_to_dismiss,))

        rows = cursor.fetchall()
        conn.commit()
        cursor.close()
        conn.close()

        if not rows:
            return {"success": False, "error": f"No pending suggestions found with IDs: {ids_to_dismiss}"}

        dismissed = [{"id": r[0], "description": r[1][:60] + "..." if len(r[1]) > 60 else r[1]} for r in rows]

        if len(dismissed) == 1:
            return {
                "success": True,
                "message": f"Suggestion #{dismissed[0]['id']} dismissed.",
                "dismissed": dismissed
            }
        else:
            return {
                "success": True,
                "message": f"Dismissed {len(dismissed)} suggestion(s).",
                "dismissed": dismissed,
                "dismissed_ids": [d['id'] for d in dismissed]
            }

    except Exception as e:
        return {"success": False, "error": f"Error dismissing suggestion(s): {e}"}


def _clear_suggestions() -> Dict[str, Any]:
    """Clear all pending seed suggestions"""

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Count pending suggestions before clearing
        cursor.execute("""
            SELECT COUNT(*) FROM seed_suggestions
            WHERE accepted IS NULL
        """)
        count = cursor.fetchone()[0]

        if count == 0:
            cursor.close()
            conn.close()
            return {
                "success": True,
                "message": "No pending suggestions to clear.",
                "cleared_count": 0
            }

        # Delete all pending suggestions
        cursor.execute("""
            DELETE FROM seed_suggestions
            WHERE accepted IS NULL
        """)

        conn.commit()
        cursor.close()
        conn.close()

        return {
            "success": True,
            "message": f"Cleared {count} pending suggestion(s) from the suggestions list.",
            "cleared_count": count
        }

    except Exception as e:
        return {"success": False, "error": f"Error clearing suggestions: {e}"}


# ============================================================================
# SERVER STARTUP
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("IRIS SEEDS SERVER - Motivation Engine")
    print("\"Seeds are the roots of identity\" - Iris")
    print("=" * 60)
    print("Tool available: seed")
    print("Actions: plant, tend, reflect, list, garden, suggestions, accept, dismiss, clear_suggestions")
    print("Starting server...")
    print("=" * 60)
    server.run()
