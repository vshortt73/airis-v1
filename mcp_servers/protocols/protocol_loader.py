"""
Protocol Loading System for Iris v3

Handles protocol activation/deactivation with state snapshots:
- Snapshots current system state to "default" protocol before activation
- Loads protocol settings and applies changes to system tables
- Deactivation restores from "default" snapshot
"""

import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, PROJECT_ROOT)

import psycopg2
import psycopg2.extras
import json
from app import config
from core.websocket_broadcast import broadcast_sync


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


def snapshot_to_default():
    """
    Capture complete current system state and save to 'default' protocol

    This creates a restore point by saving:
    - ALL character trait values (complete dump)
    - ALL system instruction active states
    - Current memory and chat history settings
    """
    print("[protocol_loader] Snapshotting current state to 'default' protocol...")

    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Get ALL current trait values
            cur.execute("SELECT name, value FROM fulltraits ORDER BY name")
            traits = cur.fetchall()
            traits_snapshot = {trait['name']: trait['value'] for trait in traits}

            # Get ALL currently active instruction IDs
            cur.execute("SELECT id FROM system_instructions WHERE active = true ORDER BY id")
            active_instructions = cur.fetchall()
            rules_include = [str(inst['id']) for inst in active_instructions]

            # Get current protocol settings (join with protocols table for show_memories)
            cur.execute("""
                SELECT p.show_memories, ap.current_chat_table
                FROM active_protocol ap
                JOIN protocols p ON ap.protocol_name = p.name
                LIMIT 1
            """)
            current = cur.fetchone()

            if current:
                show_memories = current['show_memories']
                show_chat_history = (current['current_chat_table'] == 'chat_history')
            else:
                # Fallback defaults
                show_memories = True
                show_chat_history = True

            # Update "default" protocol with complete snapshot
            cur.execute("""
                UPDATE protocols SET
                    traits_adjust = %s,
                    rules_include = %s,
                    rules_exclude = %s,
                    show_memories = %s,
                    show_chat_history = %s
                WHERE LOWER(name) = 'default'
            """, (
                json.dumps(traits_snapshot),
                json.dumps(rules_include),
                json.dumps([]),  # Empty exclude list for default
                show_memories,
                show_chat_history
            ))

            conn.commit()
            print(f"[protocol_loader] ✓ Snapshot saved: {len(traits_snapshot)} traits, {len(rules_include)} active rules")

    except Exception as e:
        conn.rollback()
        print(f"[protocol_loader] ✗ Snapshot failed: {e}")
        raise
    finally:
        conn.close()


def load_protocol(protocol_name: str):
    """
    Load a protocol and apply all its settings to the system

    Steps:
    1. Load protocol settings from database
    2. Apply trait changes to fulltraits table
    3. Apply instruction changes to system_instructions table
    4. Handle chat history table switching
    5. Update active_protocol table

    Args:
        protocol_name: Name of protocol to load (case-insensitive)

    Returns:
        dict with success status and message
    """
    print(f"[protocol_loader] Loading protocol '{protocol_name}'...")

    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Load protocol settings
            cur.execute("""
                SELECT id, name, traits_adjust, rules_include, rules_exclude,
                       show_chat_history, show_memories
                FROM protocols
                WHERE LOWER(name) = LOWER(%s)
            """, (protocol_name,))

            protocol = cur.fetchone()

            if not protocol:
                return {
                    "success": False,
                    "error": f"Protocol '{protocol_name}' not found in database"
                }

            protocol_id = protocol['id']
            protocol_name = protocol['name']  # Use actual case from database
            traits_adjust = protocol['traits_adjust'] or {}
            rules_include = protocol['rules_include'] or []
            rules_exclude = protocol['rules_exclude'] or []
            show_chat_history = protocol['show_chat_history']
            show_memories = protocol['show_memories']

            print(f"[protocol_loader] Protocol loaded: {len(traits_adjust)} trait changes, {len(rules_include)} rules to activate")

            # STEP 1: Apply trait changes
            for trait_name, new_value in traits_adjust.items():
                cur.execute("""
                    UPDATE fulltraits
                    SET value = %s
                    WHERE name = %s
                """, (new_value, trait_name))
                print(f"[protocol_loader]   Trait: {trait_name} = {new_value}")

            # STEP 2: Apply instruction changes
            # First, deactivate ALL instructions to start with a clean slate
            cur.execute("UPDATE system_instructions SET active = false")

            # Then activate only the rules specified in rules_include
            # This makes each protocol fully self-contained
            activated_count = 0
            for rule_id in rules_include:
                cur.execute("""
                    UPDATE system_instructions
                    SET active = true
                    WHERE id = %s
                """, (int(rule_id),))
                activated_count += cur.rowcount

            print(f"[protocol_loader]   Reset all rules, then activated {activated_count} rules")

            # STEP 3: Handle chat history table switching
            if show_chat_history:
                current_chat_table = 'chat_history'
                print(f"[protocol_loader]   Chat history: ENABLED (using chat_history)")
            else:
                # Clear generic table and switch to it
                cur.execute("TRUNCATE TABLE chat_history_generic")
                current_chat_table = 'chat_history_generic'
                print(f"[protocol_loader]   Chat history: DISABLED (using chat_history_generic, cleared)")

            # STEP 4: Update active_protocol table
            cur.execute("DELETE FROM active_protocol")
            cur.execute("""
                INSERT INTO active_protocol (
                    protocol_id, protocol_name, activated_at, activated_by,
                    show_memories, current_chat_table
                )
                VALUES (%s, %s, NOW(), 'Victor', %s, %s)
            """, (protocol_id, protocol_name, show_memories, current_chat_table))

            # Log to history
            cur.execute("""
                INSERT INTO protocol_history (
                    protocol_id, protocol_name, action, activated_at,
                    duration_minutes, activated_by
                )
                VALUES (%s, %s, 'activate', NOW(), 0, 'Victor')
            """, (protocol_id, protocol_name))

            conn.commit()

            print(f"[protocol_loader] ✓ Protocol '{protocol_name}' loaded successfully")
            print(f"[protocol_loader]   Memories: {'ENABLED' if show_memories else 'DISABLED'}")
            print(f"[protocol_loader]   Chat table: {current_chat_table}")

            # Push protocol status to WebSocket clients
            broadcast_sync({
                "type": "protocol_status",
                "active_protocol": protocol_name,
                "is_default": protocol_name.lower() == 'default',
                "show_memories": show_memories,
                "show_chat_history": show_chat_history
            })

            return {
                "success": True,
                "protocol_name": protocol_name,
                "message": f"Protocol '{protocol_name}' loaded successfully"
            }

    except Exception as e:
        conn.rollback()
        print(f"[protocol_loader] ✗ Load failed: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "error": f"Failed to load protocol: {str(e)}"
        }
    finally:
        conn.close()
