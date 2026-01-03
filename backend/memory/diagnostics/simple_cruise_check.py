#!/usr/bin/env python3
"""
Simple check: Why aren't cruise memories showing up?
"""

import sys
sys.path.insert(0, '/iris-v3/backend/memory')

import psycopg2
from psycopg2.extras import DictCursor

DB_CFG = dict(dbname="irisdb", user="irisuser", password="yourpassword", host="localhost", port=5432)

print("SIMPLE CRUISE MEMORY CHECK")
print("=" * 70)
print()

# Count cruise memories
conn = psycopg2.connect(**DB_CFG)
cur = conn.cursor(cursor_factory=DictCursor)

cur.execute("""
    SELECT COUNT(*) as total
    FROM episodic_memories_with_age
    WHERE (summary_event ILIKE '%cruise%' OR summary_context ILIKE '%cruise%'
           OR summary_event ILIKE '%ship%')
      AND summary_context IS NOT NULL AND summary_context <> ''
""")

total_cruise = cur.fetchone()['total']
print(f"Total cruise memories in database: {total_cruise}")

# Check their age distribution
cur.execute("""
    SELECT
        CASE
            WHEN age_days < 1 THEN '< 1 day'
            WHEN age_days < 3 THEN '1-3 days'
            WHEN age_days < 7 THEN '3-7 days'
            WHEN age_days < 30 THEN '7-30 days'
            ELSE '> 30 days'
        END as age_range,
        COUNT(*) as count,
        AVG(age_days) as avg_age
    FROM episodic_memories_with_age
    WHERE (summary_event ILIKE '%cruise%' OR summary_context ILIKE '%cruise%'
           OR summary_event ILIKE '%ship%')
      AND summary_context IS NOT NULL AND summary_context <> ''
    GROUP BY age_range
    ORDER BY avg_age
""")

print("\nAge distribution of cruise memories:")
print("-" * 70)
for row in cur.fetchall():
    print(f"{row['age_range']:<15} {row['count']:>5} memories (avg: {row['avg_age']:.1f} days)")

# Sample some cruise memories
print("\n\nSample cruise memories:")
print("-" * 70)

cur.execute("""
    SELECT id, age_days, category,
           SUBSTRING(summary_event, 1, 80) as event_preview
    FROM episodic_memories_with_age
    WHERE summary_event ILIKE '%cruise ship%'
    ORDER BY age_days ASC
    LIMIT 10
""")

for row in cur.fetchall():
    print(f"\nID {row['id']} | {row['age_days']:.1f} days | {row['category']}")
    print(f"  {row['event_preview']}")

# Now check what's actually being retrieved
print("\n\n" + "=" * 70)
print("WHAT'S ACTUALLY BEING RETRIEVED (Top 10)")
print("=" * 70)

cur.execute("""
    SELECT id, age_days, category,
           SUBSTRING(summary_event, 1, 80) as event_preview,
           CASE
               WHEN summary_event ILIKE '%cruise%' OR summary_context ILIKE '%cruise%' THEN 'CRUISE'
               WHEN summary_event ILIKE '%ship%' THEN 'SHIP'
               ELSE ''
           END as is_cruise
    FROM episodic_memories_with_age
    WHERE summary_context IS NOT NULL AND summary_context <> ''
    ORDER BY id DESC
    LIMIT 10
""")

cruise_count = 0
for row in cur.fetchall():
    marker = "🚢" if row['is_cruise'] else "  "
    print(f"{marker} ID {row['id']} | {row['age_days']:.1f}d | {row['category']}")
    print(f"    {row['event_preview']}")
    if row['is_cruise']:
        cruise_count += 1

print(f"\n\nCruise memories in recent 10: {cruise_count}/10")

cur.close()
conn.close()

print("\n" + "=" * 70)
print("DIAGNOSIS")
print("=" * 70)

if total_cruise > 50:
    print(f"✓ Plenty of cruise memories available ({total_cruise})")
else:
    print(f"⚠ Limited cruise memories ({total_cruise})")

print("\nKey question: Are these cruise memories getting high enough")
print("similarity scores to appear in top 10?")
print()
print("Next step: Check actual similarity scores from last retrieval run")
