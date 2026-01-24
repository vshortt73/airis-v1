#!/usr/bin/env python3
"""Quick script to check protocol data"""
import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, PROJECT_ROOT)

import psycopg2
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

print("Checking protocols table schema...")
conn = get_db_connection()
cursor = conn.cursor()

cursor.execute("""
    SELECT column_name, data_type
    FROM information_schema.columns
    WHERE table_name = 'protocols'
    ORDER BY ordinal_position;
""")
print("\nProtocols table schema:")
for row in cursor.fetchall():
    print(f"  {row[0]}: {row[1]}")

print("\n\nSample protocol data:")
cursor.execute("""
    SELECT name, rules_include, rules_exclude, traits_adjust
    FROM protocols
    LIMIT 2;
""")
for row in cursor.fetchall():
    print(f"\nProtocol: {row[0]}")
    print(f"  rules_include: {row[1]}")
    print(f"  rules_exclude: {row[2]}")
    print(f"  traits_adjust: {row[3]}")

cursor.close()
conn.close()
