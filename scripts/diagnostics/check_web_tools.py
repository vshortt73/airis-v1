#!/usr/bin/env python3
"""
Check web-related tools in the database
"""
import os
import sys
sys.path.insert(0, os.getcwd())

import psycopg2
from app import config
import json

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

# Check for web-related tools
conn = get_db_connection()
cur = conn.cursor()

print("="*70)
print("CHECKING MCP_TOOLS TABLE FOR WEB-RELATED TOOLS")
print("="*70)

# First check what columns exist
cur.execute("""
    SELECT column_name, data_type
    FROM information_schema.columns
    WHERE table_name = 'mcp_tools'
    ORDER BY ordinal_position
""")
columns = cur.fetchall()
print("\nTable columns:")
for col_name, data_type in columns:
    print(f"  - {col_name}: {data_type}")
print()

# Now query the tools
cur.execute("""
    SELECT *
    FROM mcp_tools
    WHERE tool_name LIKE '%web%' OR tool_name LIKE '%fetch%' OR tool_name LIKE '%url%'
    ORDER BY tool_name
""")

rows = cur.fetchall()
col_names = [desc[0] for desc in cur.description]

if not rows:
    print("\n❌ No web-related tools found in database!")
else:
    print(f"\n✓ Found {len(rows)} web-related tool(s) in database:\n")

    for row in rows:
        tool_dict = dict(zip(col_names, row))

        status = "✓ ENABLED" if tool_dict.get('enabled', False) else "✗ DISABLED"
        tool_name = tool_dict.get('tool_name', 'UNKNOWN')

        print(f"{status} - {tool_name}")

        if 'description' in tool_dict and tool_dict['description']:
            desc = tool_dict['description']
            print(f"  Description: {desc[:100]}..." if len(desc) > 100 else f"  Description: {desc}")

        # Show all available fields
        print(f"  Fields: {', '.join(col_names)}")
        print()

cur.close()
conn.close()

print("\n" + "="*70)
