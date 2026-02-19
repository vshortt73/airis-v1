#!/usr/bin/env python3
"""Check for duplicate presence records"""
import os
import sys
sys.path.insert(0, '/iris-v3')

import psycopg2
import psycopg2.extras
from app import config

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

conn = get_db_connection()
cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

print("\n=== All Presence State Records ===\n")
cursor.execute("""
    SELECT
        fps.state_id,
        fps.person_id,
        p.name,
        fps.person_name,
        fps.camera_id,
        fps.is_present,
        fps.entered_at,
        fps.exited_at,
        fps.last_seen_at,
        fps.last_greeting_at
    FROM face_presence_state fps
    JOIN face_persons p ON fps.person_id = p.person_id
    ORDER BY fps.person_id, fps.state_id
""")

records = cursor.fetchall()
for r in records:
    status = "PRESENT" if r['is_present'] else "ABSENT"
    print(f"  State ID {r['state_id']}: person_id={r['person_id']} ({r['name']}) - {status}")
    print(f"    entered: {r['entered_at']}, exited: {r['exited_at']}, last_seen: {r['last_seen_at']}")

# Check for duplicates
cursor.execute("""
    SELECT person_id, COUNT(*) as count
    FROM face_presence_state
    GROUP BY person_id
    HAVING COUNT(*) > 1
""")

duplicates = cursor.fetchall()
if duplicates:
    print("\n=== DUPLICATES FOUND ===")
    for d in duplicates:
        print(f"  person_id {d['person_id']}: {d['count']} records")
else:
    print("\n✓ No duplicates")

cursor.close()
conn.close()
