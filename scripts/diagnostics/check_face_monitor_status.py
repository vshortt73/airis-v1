#!/usr/bin/env python3
"""Check face monitor and presence status"""
import os
import sys
sys.path.insert(0, '/iris-v3')

import psycopg2
import psycopg2.extras
from app import config
from datetime import datetime

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

print("\n=== Face Monitor Status ===\n")

# Check config
print("Configuration:")
print(f"  FACE_MONITORING_ENABLED: {getattr(config, 'FACE_MONITORING_ENABLED', 'NOT SET')}")
print(f"  FACE_MONITORING_INTERVAL_SECONDS: {getattr(config, 'FACE_MONITORING_INTERVAL_SECONDS', 'NOT SET')}")
print(f"  FACE_SIMILARITY_THRESHOLD: {getattr(config, 'FACE_SIMILARITY_THRESHOLD', 'NOT SET')}")
print(f"  FACE_DETECTION_CONFIDENCE: {getattr(config, 'FACE_DETECTION_CONFIDENCE', 'NOT SET')}")

# Check presence state
print("\n=== Current Presence State ===")
cursor.execute("""
    SELECT
        ps.person_id,
        p.name,
        ps.is_present,
        ps.entered_at,
        ps.exited_at,
        ps.last_seen_at
    FROM face_presence_state ps
    JOIN face_persons p ON ps.person_id = p.person_id
    ORDER BY ps.last_seen_at DESC NULLS LAST
""")

presence = cursor.fetchall()
if not presence:
    print("  No presence records")
else:
    for p in presence:
        status = "PRESENT" if p['is_present'] else "ABSENT"
        last_seen = p['last_seen_at'].strftime("%Y-%m-%d %H:%M:%S") if p['last_seen_at'] else "Never"
        print(f"  {p['name']:15s} - {status:8s} (last seen: {last_seen})")

# Check recent recognition log
print("\n=== Recent Recognition Events (last 24h) ===")
cursor.execute("""
    SELECT
        l.recognized_at,
        COALESCE(p.name, 'UNKNOWN') as name,
        l.confidence,
        l.trigger_type,
        l.is_unknown
    FROM face_recognition_log l
    LEFT JOIN face_persons p ON l.person_id = p.person_id
    WHERE l.recognized_at > NOW() - INTERVAL '24 hours'
    ORDER BY l.recognized_at DESC
    LIMIT 20
""")

logs = cursor.fetchall()
if not logs:
    print("  No recognition events in last 24 hours")
else:
    for log in logs:
        status = "UNKNOWN" if log['is_unknown'] else log['name']
        print(f"  {log['recognized_at']} - {status:15s} (conf: {log['confidence']:.3f}, trigger: {log['trigger_type']})")

cursor.close()
conn.close()

print("\n=== Check Complete ===\n")
