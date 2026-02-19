#!/usr/bin/env python3
"""Check active protocol and system prompt"""
import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, PROJECT_ROOT)

import psycopg2
from app import config
from core.system_prompt import get_active_protocol, build_system_message

def get_db_connection():
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

print("=== CONFIGURATION FLAGS ===")
print(f"SYSTEM_INSTRUCTIONS: {config.SYSTEM_INSTRUCTIONS}")
print(f"CHARACTER_TRAITS: {config.CHARACTER_TRAITS}")

print("\n=== ACTIVE PROTOCOL ===")
protocol = get_active_protocol()
print(f"Protocol Name: {protocol['protocol_name']}")
print(f"Show Chat History: {protocol['show_chat_history']}")
print(f"Show Memories: {protocol['show_memories']}")
print(f"Custom Instructions: {protocol['instructions']}")
print(f"Rules Include: {protocol['rules_include']}")
print(f"Rules Exclude: {protocol['rules_exclude']}")

print("\n=== CHECKING IF TRAITS ARE IN SYSTEM PROMPT ===")
system_msg = build_system_message(user_message="test")
content = system_msg['content']

if '[PERSONALITY TRAITS]' in content:
    print("✓ TRAITS ARE in the system prompt")
    # Extract the traits section
    start = content.find('[PERSONALITY TRAITS]')
    end = content.find('\n\n', start)
    if end == -1:
        end = start + 500
    traits_section = content[start:end]
    print("\nTraits section preview:")
    print(traits_section[:300] + "...")
else:
    print("✗ TRAITS ARE MISSING from the system prompt")
    print("\nSearching for trait-related text...")
    if 'trait' in content.lower():
        print("Found 'trait' mentioned in prompt")
    else:
        print("No mention of traits at all")

print(f"\n=== SYSTEM PROMPT STATS ===")
print(f"Total length: {len(content)} chars")
print(f"Contains '[PERSONALITY TRAITS]': {('[PERSONALITY TRAITS]' in content)}")
print(f"Contains 'trait settings control': {('trait settings control' in content)}")
