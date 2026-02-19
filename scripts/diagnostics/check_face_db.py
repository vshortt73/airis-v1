#!/usr/bin/env python3
import os
import sys
sys.path.insert(0, '/iris-v3')

import psycopg2
from app import config

def get_db_connection():
    """Get database connection using same pattern as rest of codebase"""
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
cursor = conn.cursor()

# First, check what columns exist in face_persons table
cursor.execute("""
    SELECT column_name
    FROM information_schema.columns
    WHERE table_name = 'face_persons'
    ORDER BY ordinal_position
""")
columns = [row[0] for row in cursor.fetchall()]
print('\n=== Face Persons Table Columns ===')
print(f'  {", ".join(columns)}')

# Check for persons in database
cursor.execute('SELECT person_id, name, relationship FROM face_persons WHERE enabled = true')
persons = cursor.fetchall()

print('\n=== Registered Persons ===')
if not persons:
    print('  ❌ NO PERSONS REGISTERED')
else:
    for p in persons:
        # Count embeddings for this person
        cursor.execute('SELECT COUNT(*) FROM face_embeddings WHERE person_id = %s', (p[0],))
        emb_count = cursor.fetchone()[0]
        print(f'  ✓ ID {p[0]}: {p[1]} ({p[2]}) - {emb_count} embeddings')

print('\n=== Config Values ===')
print(f'  FACE_SIMILARITY_THRESHOLD: {config.FACE_SIMILARITY_THRESHOLD}')
print(f'  FACE_DETECTION_CONFIDENCE: {getattr(config, "FACE_DETECTION_CONFIDENCE", "NOT SET")}')

cursor.close()
conn.close()
