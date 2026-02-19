#!/usr/bin/env python3
"""
Reset face detection state for testing greetings
"""
import psycopg2
from datetime import datetime, timedelta
import os, sys
sys.path.insert(0, '/iris-v3')
from app import config

password = os.environ.get('AIRIS_DB_PASSWORD') or getattr(config, 'DB_PASSWORD', None)
conn = psycopg2.connect(
    host=config.DB_HOST,
    port=config.DB_PORT,
    database=config.DB_NAME,
    user=config.DB_USER,
    password=password
)
cursor = conn.cursor()

# Complete reset: delete all presence records for Victor
print("Resetting face detection state...")
cursor.execute("DELETE FROM face_presence_state WHERE person_name = 'Victor'")
deleted_count = cursor.rowcount

# Create an old "exited" record to simulate 4-hour absence
old_time = datetime.now() - timedelta(hours=4)
cursor.execute("""
    INSERT INTO face_presence_state
    (person_id, person_name, camera_id, entered_at, exited_at, last_seen_at, is_present, last_greeting_at)
    VALUES (1, 'Victor', 3, %s, %s, %s, false, NULL)
""", (old_time - timedelta(minutes=10), old_time, old_time))

conn.commit()
print(f'✓ Deleted {deleted_count} old records')
print(f'✓ Created absence record (exited 4 hours ago)')
print(f'✓ Next detection will treat as new entry with 4-hour absence')

cursor.close()
conn.close()
