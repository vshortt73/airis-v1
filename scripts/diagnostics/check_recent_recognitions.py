#!/usr/bin/env python3
"""Check recent face recognition events"""
import os
import sys
sys.path.insert(0, '/iris-v3')

import psycopg2
import psycopg2.extras
from app import config

def get_db_connection():
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

conn = get_db_connection()
cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

# Get recent recognition events
cursor.execute("""
    SELECT
        l.log_id,
        l.recognized_at,
        l.person_id,
        p.name,
        l.confidence,
        l.trigger_type,
        l.is_unknown
    FROM face_recognition_log l
    LEFT JOIN face_persons p ON l.person_id = p.person_id
    ORDER BY l.recognized_at DESC
    LIMIT 10
""")

events = cursor.fetchall()

print("\n=== Recent Face Recognition Events ===\n")
if not events:
    print("  No recognition events found")
else:
    for event in events:
        status = "UNKNOWN" if event['is_unknown'] else event['name']
        print(f"  {event['recognized_at']} - {status} (confidence: {event['confidence']:.3f}, trigger: {event['trigger_type']})")

cursor.close()
conn.close()
