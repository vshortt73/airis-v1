#!/usr/bin/env python3
"""
Quick check: Why aren't cruise memories scoring high enough?
"""

import sys
sys.path.insert(0, '/iris-v3/backend/memory')

import psycopg2
from psycopg2.extras import DictCursor
import numpy as np

DB_CFG = dict(dbname="irisdb", user="irisuser", password="yourpassword", host="localhost", port=5432)

print("CRUISE MEMORY SIMILARITY CHECK")
print("=" * 70)

# Get the last 10 messages from conversation
conn = psycopg2.connect(**DB_CFG)
cur = conn.cursor(cursor_factory=DictCursor)

cur.execute("""
    SELECT role, message
    FROM chat_history
    ORDER BY c_timestamp DESC
    LIMIT 10
""")
messages = cur.fetchall()

# Build conversation text
convo = "\n".join([f"{m['role'].upper()}: {m['message']}" for m in reversed(messages)])

print("\nCurrent conversation excerpt:")
print("-" * 70)
print(convo[:500] + "...\n")

# Check what memories exist from June (around 180 days ago)
print("\n\nSearching for memories from June (175-190 days old):")
cur.execute("""
    SELECT id, age_days, category,
           summary_context, summary_event,
           valence, arousal, emotion_label
    FROM episodic_memories_with_age
    WHERE age_days BETWEEN 175 AND 190
      AND summary_context IS NOT NULL AND summary_context <> ''
    ORDER BY age_days ASC
    LIMIT 20
""")

june_mems = cur.fetchall()

print(f"\nFound {len(june_mems)} memories from that period:")
print(f"Looking for vacation/cruise related content...")
print("-" * 70)
for m in june_mems:
    salience = abs(m['valence'] or 0.0) * (m['arousal'] or 0.0)
    print(f"\nID {m['id']} | Age: {m['age_days']:.1f}d | Category: {m['category']}")
    print(f"  Valence: {m['valence']:.3f} | Arousal: {m['arousal']:.3f} | Salience: {salience:.3f}")
    print(f"  Emotion: {m['emotion_label']}")
    print(f"  Context: {m['summary_context'][:80]}...")
    print(f"  Event: {m['summary_event'][:80]}...")

# Calculate expected decay with current half-life settings
print("\n\n" + "=" * 70)
print("DECAY ANALYSIS")
print("=" * 70)

import math

# Category-based half-lives from iris_memory_retrieval.py
HALF_LIFE_BY_CATEGORY = {
    "Technical": 45,
    "Practical": 45,
    "Creative": 90,
    "Learning": 90,
    "Personal": 180,
    "Relational": 180,
    "Other": 60
}

for m in june_mems[:5]:
    age = m['age_days']
    category = m['category'] or "Other"
    half_life = HALF_LIFE_BY_CATEGORY.get(category, 60)

    # Base decay (convert Decimal to float)
    base_decay = math.exp(-math.log(2) * (float(age) / half_life))

    # Salience adjustment
    salience = abs(m['valence'] or 0.0) * (m['arousal'] or 0.0)
    resistance = min(0.90, salience)

    # Final decay
    effective_decay = base_decay + (1 - base_decay) * resistance

    print(f"\nMemory ID {m['id']}")
    print(f"  Category: {category} (half-life: {half_life} days)")
    print(f"  Age: {age:.1f} days")
    print(f"  Base decay: {base_decay:.4f}")
    print(f"  Salience: {salience:.3f} → Resistance: {resistance:.3f}")
    print(f"  Effective decay: {effective_decay:.4f}")
    print(f"  → If similarity = 0.5, final score = {0.5 * effective_decay:.4f}")

# Now compare to what's actually appearing in top 10
print("\n\n" + "=" * 70)
print("WHAT'S ACTUALLY RETRIEVED")
print("=" * 70)

cur.execute("""
    SELECT id, age_days, category,
           valence, arousal, emotion_label,
           SUBSTRING(summary_event, 1, 80) as event_preview
    FROM episodic_memories_with_age
    WHERE summary_context IS NOT NULL AND summary_context <> ''
    ORDER BY id DESC
    LIMIT 10
""")

recent = cur.fetchall()

print("\nMost recent 10 memories in database:")
for m in recent:
    is_cruise = 'cruise' in (m['event_preview'] or '').lower() or 'ship' in (m['event_preview'] or '').lower()
    marker = "🚢 " if is_cruise else "   "
    salience = abs(m['valence'] or 0.0) * (m['arousal'] or 0.0)
    print(f"{marker}ID {m['id']} | Age: {m['age_days']:.1f}d | Cat: {m['category']} | Salience: {salience:.3f}")

cur.close()
conn.close()

print("\n" + "=" * 70)
print("DIAGNOSIS")
print("=" * 70)
print("""
Key questions:
1. Are cruise memories (~180 days old) from June?
2. What's their emotional salience (valence * arousal)?
3. What category are they (affects half-life)?
4. With salience adjustment, should they have high enough decay multiplier?

The problem is likely:
- Summaries from CURRENT conversation don't match June cruise summaries well
- Even with salience adjustment, similarity score is still low
- Need to check: what are the actual summary texts for June cruises?
""")
