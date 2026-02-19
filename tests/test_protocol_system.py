#!/usr/bin/env python3
"""
Test script for protocol activation/deactivation system
Tests the full cycle: snapshot → load → verify → restore
"""
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, PROJECT_ROOT)

from mcp_servers.protocols.protocol_loader import snapshot_to_default, load_protocol
import psycopg2
import psycopg2.extras
from app import config
import json

def get_db_connection():
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

def get_active_protocol_info():
    """Get current protocol state from database"""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    ap.protocol_name,
                    ap.current_chat_table,
                    p.show_memories,
                    p.show_chat_history
                FROM active_protocol ap
                JOIN protocols p ON ap.protocol_name = p.name
                LIMIT 1
            """)
            return cur.fetchone()
    finally:
        conn.close()

def get_trait_value(trait_name):
    """Get a specific trait value"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT value FROM fulltraits WHERE name = %s", (trait_name,))
            result = cur.fetchone()
            return result[0] if result else None
    finally:
        conn.close()

def get_instruction_active_status(instruction_id):
    """Check if a specific instruction is active"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT active FROM system_instructions WHERE id = %s", (instruction_id,))
            result = cur.fetchone()
            return result[0] if result else None
    finally:
        conn.close()

def get_chat_history_count(table_name='chat_history'):
    """Get message count from a chat table"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {table_name}")
            return cur.fetchone()[0]
    finally:
        conn.close()

def print_separator(title):
    print("\n" + "="*70)
    print(f"  {title}")
    print("="*70)

def main():
    print_separator("PROTOCOL SYSTEM TEST")

    # STEP 1: Check initial state
    print_separator("STEP 1: Initial State (should be 'default')")
    initial_state = get_active_protocol_info()
    print(f"Active Protocol: {initial_state['protocol_name']}")
    print(f"Current Chat Table: {initial_state['current_chat_table']}")
    print(f"Show Memories: {initial_state['show_memories']}")
    print(f"Show Chat History: {initial_state['show_chat_history']}")

    # Check some trait values before snapshot
    print("\nSample Trait Values:")
    affection_before = get_trait_value("Affection")
    professionalism_before = get_trait_value("Professionalism")
    print(f"  Affection: {affection_before}")
    print(f"  Professionalism: {professionalism_before}")

    # Check instruction active status
    print("\nSample Instruction Active Status:")
    inst4_before = get_instruction_active_status(4)
    inst8_before = get_instruction_active_status(8)
    print(f"  Instruction 4: {inst4_before}")
    print(f"  Instruction 8: {inst8_before}")

    # STEP 2: Take snapshot to default
    print_separator("STEP 2: Taking Snapshot to 'default' Protocol")
    try:
        snapshot_to_default()
        print("✓ Snapshot completed successfully")
    except Exception as e:
        print(f"✗ Snapshot failed: {e}")
        return

    # STEP 3: Activate Bravo protocol
    print_separator("STEP 3: Activating 'Bravo' Protocol")
    result = load_protocol("Bravo")
    if result["success"]:
        print(f"✓ {result['message']}")
    else:
        print(f"✗ Failed: {result.get('error', 'Unknown error')}")
        return

    # STEP 4: Verify Bravo protocol changes
    print_separator("STEP 4: Verifying 'Bravo' Protocol Changes")
    bravo_state = get_active_protocol_info()
    print(f"Active Protocol: {bravo_state['protocol_name']}")
    print(f"Current Chat Table: {bravo_state['current_chat_table']}")
    print(f"Show Memories: {bravo_state['show_memories']}")
    print(f"Show Chat History: {bravo_state['show_chat_history']}")

    # Check trait changes
    print("\nTrait Changes:")
    affection_bravo = get_trait_value("Affection")
    professionalism_bravo = get_trait_value("Professionalism")
    print(f"  Affection: {affection_before} → {affection_bravo} (expected: 2)")
    print(f"  Professionalism: {professionalism_before} → {professionalism_bravo} (expected: 10)")

    # Check instruction exclusions
    print("\nInstruction Exclusions (should be deactivated):")
    inst4_bravo = get_instruction_active_status(4)
    inst8_bravo = get_instruction_active_status(8)
    print(f"  Instruction 4: {inst4_before} → {inst4_bravo} (expected: False)")
    print(f"  Instruction 8: {inst8_before} → {inst8_bravo} (expected: False)")

    # Check chat table
    print("\nChat Table Status:")
    generic_count = get_chat_history_count('chat_history_generic')
    print(f"  chat_history_generic message count: {generic_count} (should be 0 - truncated on switch)")

    # Verification
    print("\n" + "-"*70)
    all_checks_passed = True

    if bravo_state['protocol_name'] != 'Bravo':
        print("✗ Protocol name not changed")
        all_checks_passed = False
    else:
        print("✓ Protocol name changed correctly")

    if bravo_state['current_chat_table'] != 'chat_history_generic':
        print("✗ Chat table not switched")
        all_checks_passed = False
    else:
        print("✓ Chat table switched correctly")

    if bravo_state['show_memories'] != False:
        print("✗ show_memories not set to False")
        all_checks_passed = False
    else:
        print("✓ show_memories disabled correctly")

    if str(affection_bravo) != "2":
        print(f"✗ Affection trait not changed (got {affection_bravo}, expected 2)")
        all_checks_passed = False
    else:
        print("✓ Affection trait changed correctly")

    if inst4_bravo != False or inst8_bravo != False:
        print(f"✗ Instructions not deactivated correctly (4={inst4_bravo}, 8={inst8_bravo})")
        all_checks_passed = False
    else:
        print("✓ Instructions deactivated correctly")

    # STEP 5: Deactivate (restore default)
    print_separator("STEP 5: Deactivating Protocol (Restore 'default')")
    result = load_protocol("default")
    if result["success"]:
        print(f"✓ {result['message']}")
    else:
        print(f"✗ Failed: {result.get('error', 'Unknown error')}")
        return

    # STEP 6: Verify restoration
    print_separator("STEP 6: Verifying Restoration to 'default'")
    restored_state = get_active_protocol_info()
    print(f"Active Protocol: {restored_state['protocol_name']}")
    print(f"Current Chat Table: {restored_state['current_chat_table']}")
    print(f"Show Memories: {restored_state['show_memories']}")
    print(f"Show Chat History: {restored_state['show_chat_history']}")

    # Check trait restoration
    print("\nTrait Restoration:")
    affection_restored = get_trait_value("Affection")
    professionalism_restored = get_trait_value("Professionalism")
    print(f"  Affection: {affection_bravo} → {affection_restored} (expected: {affection_before})")
    print(f"  Professionalism: {professionalism_bravo} → {professionalism_restored} (expected: {professionalism_before})")

    # Check instruction restoration
    print("\nInstruction Restoration:")
    inst4_restored = get_instruction_active_status(4)
    inst8_restored = get_instruction_active_status(8)
    print(f"  Instruction 4: {inst4_bravo} → {inst4_restored} (expected: {inst4_before})")
    print(f"  Instruction 8: {inst8_bravo} → {inst8_restored} (expected: {inst8_before})")

    # Final verification
    print("\n" + "-"*70)
    restoration_passed = True

    if restored_state['protocol_name'] != 'default':
        print("✗ Protocol not restored to default")
        restoration_passed = False
    else:
        print("✓ Protocol restored to default")

    if restored_state['current_chat_table'] != 'chat_history':
        print("✗ Chat table not restored")
        restoration_passed = False
    else:
        print("✓ Chat table restored correctly")

    if str(affection_restored) != str(affection_before):
        print(f"✗ Affection not restored (got {affection_restored}, expected {affection_before})")
        restoration_passed = False
    else:
        print("✓ Affection trait restored correctly")

    if inst4_restored != inst4_before or inst8_restored != inst8_before:
        print(f"✗ Instructions not restored (4: {inst4_restored}, 8: {inst8_restored})")
        restoration_passed = False
    else:
        print("✓ Instructions restored correctly")

    # FINAL RESULT
    print_separator("TEST RESULTS")
    if all_checks_passed and restoration_passed:
        print("✅ ALL TESTS PASSED")
        print("\nProtocol system is working correctly:")
        print("  ✓ Snapshot captures current state")
        print("  ✓ Protocol activation applies all changes")
        print("  ✓ Protocol deactivation restores snapshot")
        return 0
    else:
        print("❌ SOME TESTS FAILED")
        if not all_checks_passed:
            print("  ✗ Protocol activation had issues")
        if not restoration_passed:
            print("  ✗ Protocol restoration had issues")
        return 1

if __name__ == "__main__":
    exit(main())
