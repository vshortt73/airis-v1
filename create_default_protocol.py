"""
Create Default Protocol
Generates the "Default" protocol based on current system configuration
"""

import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, PROJECT_ROOT)

import psycopg2
import psycopg2.extras
import json
from app import config

# ============================================
# DATABASE CONNECTION
# ============================================

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

# ============================================
# DATA COLLECTION
# ============================================

def get_current_instructions():
    """Get all active instruction IDs from system_instructions"""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id, instruction_key, active
                FROM system_instructions
                ORDER BY instruction_order
            """)
            instructions = cur.fetchall()

            # Separate active and inactive
            active_ids = [str(inst['id']) for inst in instructions if inst['active']]
            inactive_ids = [str(inst['id']) for inst in instructions if not inst['active']]

            return active_ids, inactive_ids, instructions
    finally:
        conn.close()

def get_current_traits():
    """Get all trait names and values from fulltraits"""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT name, value
                FROM fulltraits
                ORDER BY name
            """)
            traits = cur.fetchall()

            # Create dict of trait_name: value
            trait_dict = {trait['name']: trait['value'] for trait in traits}

            return trait_dict
    finally:
        conn.close()

def get_current_tools():
    """Get all enabled tool names from mcp_tools"""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT tool_name, enabled
                FROM mcp_tools
                ORDER BY tool_name
            """)
            tools = cur.fetchall()

            # Create dict of tool_name: enabled
            tool_dict = {tool['tool_name']: tool['enabled'] for tool in tools}

            return tool_dict
    finally:
        conn.close()

# ============================================
# PROTOCOL CREATION
# ============================================

def create_default_protocol():
    """Create the default protocol based on current system state"""
    print("="*60)
    print("CREATING DEFAULT PROTOCOL")
    print("="*60)

    # Gather current system state
    print("\n[Step 1/5] Gathering system instructions...")
    active_ids, inactive_ids, all_instructions = get_current_instructions()
    print(f"  Active instructions: {len(active_ids)}")
    print(f"  Inactive instructions: {len(inactive_ids)}")
    for inst in all_instructions:
        status = "✓" if inst['active'] else "✗"
        print(f"    {status} ID {inst['id']}: {inst['instruction_key']}")

    print("\n[Step 2/5] Gathering character traits...")
    traits = get_current_traits()
    print(f"  Total traits: {len(traits)}")
    print(f"  Sample: {list(traits.items())[:5]}")

    print("\n[Step 3/5] Gathering tool settings...")
    tools = get_current_tools()
    enabled_tools = [name for name, enabled in tools.items() if enabled]
    print(f"  Total tools: {len(tools)}")
    print(f"  Enabled tools: {len(enabled_tools)}")
    print(f"  Enabled: {enabled_tools}")

    # Create protocol data
    print("\n[Step 4/5] Building protocol configuration...")

    protocol_data = {
        'name': 'Default',
        'description': 'Default Iris configuration based on current system state. This represents the standard operational mode with all default settings.',
        'rules_include': active_ids,  # IDs of active instructions
        'rules_exclude': inactive_ids,  # IDs of inactive instructions
        'show_chat_history': True,  # Default: ON
        'show_memories': True,  # Default: ON
        'traits_adjust': traits,  # Current trait values
        'tool_usage': tools  # Current tool enabled/disabled state
    }

    print(f"  Protocol name: {protocol_data['name']}")
    print(f"  Chat history: {'ON' if protocol_data['show_chat_history'] else 'OFF'}")
    print(f"  Memory injection: {'ON' if protocol_data['show_memories'] else 'OFF'}")
    print(f"  Rules included: {len(protocol_data['rules_include'])}")
    print(f"  Rules excluded: {len(protocol_data['rules_exclude'])}")
    print(f"  Traits configured: {len(protocol_data['traits_adjust'])}")
    print(f"  Tools configured: {len(protocol_data['tool_usage'])}")

    # Insert into database
    print("\n[Step 5/5] Inserting into database...")
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # Check if "Default" protocol already exists
            cur.execute("SELECT id FROM protocols WHERE name = 'Default'")
            existing = cur.fetchone()

            if existing:
                print(f"  ⚠ Default protocol already exists (ID: {existing[0]})")
                print(f"  Updating existing protocol...")
                cur.execute("""
                    UPDATE protocols
                    SET description = %s,
                        rules_include = %s,
                        rules_exclude = %s,
                        show_chat_history = %s,
                        show_memories = %s,
                        traits_adjust = %s,
                        tool_usage = %s
                    WHERE name = 'Default'
                    RETURNING id
                """, (
                    protocol_data['description'],
                    json.dumps(protocol_data['rules_include']),
                    json.dumps(protocol_data['rules_exclude']),
                    protocol_data['show_chat_history'],
                    protocol_data['show_memories'],
                    json.dumps(protocol_data['traits_adjust']),
                    json.dumps(protocol_data['tool_usage'])
                ))
            else:
                print(f"  Creating new Default protocol...")
                cur.execute("""
                    INSERT INTO protocols (
                        name, description, rules_include, rules_exclude,
                        show_chat_history, show_memories, traits_adjust, tool_usage
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    protocol_data['name'],
                    protocol_data['description'],
                    json.dumps(protocol_data['rules_include']),
                    json.dumps(protocol_data['rules_exclude']),
                    protocol_data['show_chat_history'],
                    protocol_data['show_memories'],
                    json.dumps(protocol_data['traits_adjust']),
                    json.dumps(protocol_data['tool_usage'])
                ))

            protocol_id = cur.fetchone()[0]
            conn.commit()

            print(f"  ✓ Default protocol saved (ID: {protocol_id})")

    finally:
        conn.close()

    print("\n" + "="*60)
    print("✓ DEFAULT PROTOCOL CREATED SUCCESSFULLY")
    print("="*60)

    return protocol_id

# ============================================
# MAIN EXECUTION
# ============================================

if __name__ == "__main__":
    try:
        protocol_id = create_default_protocol()
        print(f"\nProtocol ID: {protocol_id}")
        print("You can now use the protocol editor to modify or create new protocols.")
    except Exception as e:
        print(f"\n✗ Error creating default protocol: {e}")
        import traceback
        traceback.print_exc()
