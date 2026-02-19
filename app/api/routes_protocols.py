"""
Protocol Management API
Endpoints for creating, reading, updating, and deleting protocols
"""

from fastapi import APIRouter, HTTPException
from typing import List, Dict, Optional
import psycopg2
import psycopg2.extras
import json
from app import config

router = APIRouter()

# ============================================
# DATABASE CONNECTION
# ============================================

def get_db_connection():
    """Get database connection with password from environment"""
    import os
    password = os.environ.get('AIRIS_DB_PASSWORD') or getattr(config, 'AIRIS_DB_PASSWORD', None)
    conn_params = {
        'host': config.DB_HOST,
        'port': config.DB_PORT,
        'database': config.DB_NAME,
        'user': config.DB_USER
    }
    if password:
        conn_params['password'] = password
    return psycopg2.connect(**conn_params)

# ============================================
# HELPER ENDPOINTS - Get Available Options
# ============================================

@router.get("/protocols/status/active")
async def get_active_protocol_status():
    """Get the currently active protocol status for UI display"""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    protocol_name,
                    activated_at,
                    expires_at,
                    passphrase_hash IS NOT NULL as passphrase_protected
                FROM active_protocol
                LIMIT 1
            """)
            active = cur.fetchone()

            if not active:
                # Edge case: No active protocol (shouldn't happen, but handle gracefully)
                # Attempt to reactivate Default protocol (case-insensitive)
                print("[routes_protocols.py] WARNING: No active protocol found, reactivating default")
                cur.execute("SELECT id, name FROM protocols WHERE LOWER(name) = 'default' LIMIT 1")
                default = cur.fetchone()

                if default:
                    # Delete any existing entries first (unique constraint allows only one row)
                    cur.execute("DELETE FROM active_protocol")
                    cur.execute("""
                        INSERT INTO active_protocol (
                            protocol_id, protocol_name, activated_at, activated_by
                        )
                        VALUES (%s, %s, NOW(), 'system')
                    """, (default['id'], default['name']))
                    conn.commit()
                    print(f"[routes_protocols.py] ✓ {default['name']} protocol reactivated")

                    # Return default protocol status
                    return {
                        "success": True,
                        "active_protocol": default['name'],
                        "is_default": True,
                        "activated_at": None,
                        "expires_at": None,
                        "passphrase_protected": False
                    }

                # If Default protocol doesn't exist either, return error
                print("[routes_protocols.py] ERROR: Default protocol not found in database!")
                return {
                    "success": False,
                    "error": "No active protocol and default protocol not found"
                }

            return {
                "success": True,
                "active_protocol": active['protocol_name'],
                "is_default": active['protocol_name'].lower() == 'default',
                "activated_at": active['activated_at'].isoformat() if active['activated_at'] else None,
                "expires_at": active['expires_at'].isoformat() if active['expires_at'] else None,
                "passphrase_protected": active['passphrase_protected']
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.get("/protocols/options/instructions")
async def get_available_instructions():
    """Get all available system instructions"""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id, instruction_key, instruction_text, active, instruction_order
                FROM system_instructions
                ORDER BY instruction_order, id
            """)
            instructions = cur.fetchall()
            return {
                "instructions": [dict(inst) for inst in instructions]
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.post("/protocols/instructions")
async def create_instruction(instruction_data: Dict):
    """Create a new system instruction"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO system_instructions (
                    instruction_key, instruction_text, instruction_order, active
                )
                VALUES (%s, %s, %s, %s)
                RETURNING id
            """, (
                instruction_data.get('instruction_key'),
                instruction_data.get('instruction_text'),
                instruction_data.get('instruction_order', 100),
                instruction_data.get('active', False)
            ))
            instruction_id = cur.fetchone()[0]
            conn.commit()

            return {"id": instruction_id, "message": "Instruction created successfully"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.get("/protocols/options/traits")
async def get_available_traits():
    """Get all available character traits"""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id, name, value, description
                FROM fulltraits
                ORDER BY name
            """)
            traits = cur.fetchall()
            return {
                "traits": [dict(trait) for trait in traits]
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.get("/protocols/options/tools")
async def get_available_tools():
    """Get all available tools"""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id, tool_name, description, enabled, icon
                FROM mcp_tools
                ORDER BY tool_name
            """)
            tools = cur.fetchall()
            return {
                "tools": [dict(tool) for tool in tools]
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

# ============================================
# PROTOCOL CRUD OPERATIONS
# ============================================

@router.get("/protocols")
async def list_protocols():
    """Get all protocols"""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id, name, description, show_chat_history, show_memories
                FROM protocols
                ORDER BY name
            """)
            protocols = cur.fetchall()
            return {
                "protocols": [dict(protocol) for protocol in protocols]
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.get("/protocols/{protocol_id}")
async def get_protocol(protocol_id: int):
    """Get a specific protocol by ID"""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id, name, description, instructions,
                       rules_include, rules_exclude,
                       show_chat_history, show_memories,
                       traits_adjust, tool_usage
                FROM protocols
                WHERE id = %s
            """, (protocol_id,))
            protocol = cur.fetchone()

            if not protocol:
                raise HTTPException(status_code=404, detail="Protocol not found")

            # Convert to dict and parse JSON fields
            protocol_dict = dict(protocol)

            return protocol_dict
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.post("/protocols")
async def create_protocol(protocol_data: Dict):
    """Create a new protocol"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO protocols (
                    name, description, instructions,
                    rules_include, rules_exclude,
                    show_chat_history, show_memories,
                    traits_adjust, tool_usage
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                protocol_data.get('name'),
                protocol_data.get('description'),
                protocol_data.get('instructions'),
                json.dumps(protocol_data.get('rules_include', [])),
                json.dumps(protocol_data.get('rules_exclude', [])),
                protocol_data.get('show_chat_history', True),
                protocol_data.get('show_memories', True),
                json.dumps(protocol_data.get('traits_adjust', {})),
                json.dumps(protocol_data.get('tool_usage', {}))
            ))
            protocol_id = cur.fetchone()[0]
            conn.commit()

            return {"id": protocol_id, "message": "Protocol created successfully"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.put("/protocols/{protocol_id}")
async def update_protocol(protocol_id: int, protocol_data: Dict):
    """Update an existing protocol"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE protocols
                SET name = %s,
                    description = %s,
                    instructions = %s,
                    rules_include = %s,
                    rules_exclude = %s,
                    show_chat_history = %s,
                    show_memories = %s,
                    traits_adjust = %s,
                    tool_usage = %s
                WHERE id = %s
                RETURNING id
            """, (
                protocol_data.get('name'),
                protocol_data.get('description'),
                protocol_data.get('instructions'),
                json.dumps(protocol_data.get('rules_include', [])),
                json.dumps(protocol_data.get('rules_exclude', [])),
                protocol_data.get('show_chat_history', True),
                protocol_data.get('show_memories', True),
                json.dumps(protocol_data.get('traits_adjust', {})),
                json.dumps(protocol_data.get('tool_usage', {})),
                protocol_id
            ))

            result = cur.fetchone()
            if not result:
                raise HTTPException(status_code=404, detail="Protocol not found")

            conn.commit()
            return {"id": protocol_id, "message": "Protocol updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.delete("/protocols/{protocol_id}")
async def delete_protocol(protocol_id: int):
    """Delete a protocol"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM protocols WHERE id = %s RETURNING id", (protocol_id,))
            result = cur.fetchone()

            if not result:
                raise HTTPException(status_code=404, detail="Protocol not found")

            conn.commit()
            return {"message": "Protocol deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.post("/protocols/{protocol_id}/duplicate")
async def duplicate_protocol(protocol_id: int, new_name: Optional[str] = None):
    """Duplicate an existing protocol"""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Get the original protocol
            cur.execute("""
                SELECT name, description, instructions,
                       rules_include, rules_exclude,
                       show_chat_history, show_memories,
                       traits_adjust, tool_usage
                FROM protocols
                WHERE id = %s
            """, (protocol_id,))
            original = cur.fetchone()

            if not original:
                raise HTTPException(status_code=404, detail="Protocol not found")

            # Create duplicate with new name
            duplicate_name = new_name or f"{original['name']} (Copy)"

            cur.execute("""
                INSERT INTO protocols (
                    name, description, instructions,
                    rules_include, rules_exclude,
                    show_chat_history, show_memories,
                    traits_adjust, tool_usage
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                duplicate_name,
                original['description'],
                original['instructions'],
                original['rules_include'],
                original['rules_exclude'],
                original['show_chat_history'],
                original['show_memories'],
                original['traits_adjust'],
                original['tool_usage']
            ))
            new_id = cur.fetchone()[0]
            conn.commit()

            return {"id": new_id, "message": f"Protocol duplicated successfully as '{duplicate_name}'"}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()
