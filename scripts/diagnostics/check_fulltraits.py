#!/usr/bin/env python3
"""Check fulltraits table values"""
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

print("=== CURRENT FULLTRAITS VALUES ===")
conn = get_db_connection()
cursor = conn.cursor()

cursor.execute("SELECT name, value FROM fulltraits WHERE name IN ('Affection', 'Playfulness', 'Sex Drive', 'Mood', 'Professionalism', 'Dream Integration') ORDER BY name")
rows = cursor.fetchall()

print("\nSample traits from fulltraits table:")
for name, value in rows:
    print(f"  {name}: {value}")

print("\n=== THETA PROTOCOL TRAITS_ADJUST ===")
cursor.execute("SELECT traits_adjust FROM protocols WHERE name = 'Theta'")
theta_traits = cursor.fetchone()[0]

print("\nTheta protocol traits_adjust:")
for name in ['Affection', 'Playfulness', 'Sex Drive', 'Mood', 'Professionalism', 'Dream Integration']:
    if name in theta_traits:
        print(f"  {name}: {theta_traits[name]}")

print("\n=== COMPARISON ===")
cursor.execute("SELECT name, value FROM fulltraits WHERE name IN ('Affection', 'Playfulness', 'Sex Drive', 'Mood', 'Professionalism', 'Dream Integration') ORDER BY name")
current_traits = {row[0]: row[1] for row in cursor.fetchall()}

mismatches = []
for name, expected_value in theta_traits.items():
    if name in current_traits:
        actual_value = current_traits[name]
        if str(actual_value) != str(expected_value):
            mismatches.append((name, expected_value, actual_value))

if mismatches:
    print(f"\n❌ MISMATCH FOUND: {len(mismatches)} traits don't match!")
    for name, expected, actual in mismatches:
        print(f"  {name}: expected '{expected}', but fulltraits has '{actual}'")
else:
    print("\n✓ All checked traits match Theta protocol!")

cursor.close()
conn.close()
