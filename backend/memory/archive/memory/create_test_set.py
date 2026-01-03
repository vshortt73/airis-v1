"""
Create a balanced, stratified test set of memories for reproducible testing
Saves memory IDs to a JSON file that can be used for consistent A/B testing
"""

import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, PROJECT_ROOT)

import psycopg2
from psycopg2.extras import DictCursor
import json
from collections import defaultdict

DB_CFG = dict(dbname="irisdb", user="irisuser", password="yourpassword", host="localhost", port=5432)

def create_stratified_test_set(memories_per_category=10, output_file="test_set.json"):
    """
    Create a balanced test set with equal representation from each category

    Args:
        memories_per_category: Number of memories to sample from each category
        output_file: Where to save the test set
    """
    conn = psycopg2.connect(**DB_CFG)
    cur = conn.cursor(cursor_factory=DictCursor)

    # Get all categories
    cur.execute("""
        SELECT DISTINCT category
        FROM episodic_memories
        WHERE category IS NOT NULL
          AND transcript IS NOT NULL
          AND transcript <> ''
          AND LENGTH(transcript) > 100
        ORDER BY category
    """)

    categories = [row['category'] for row in cur.fetchall()]
    print(f"Found {len(categories)} categories: {', '.join(categories)}")

    test_set = {
        'metadata': {
            'total_categories': len(categories),
            'memories_per_category': memories_per_category,
            'total_memories': 0
        },
        'memories': []
    }

    # Sample from each category
    for category in categories:
        cur.execute("""
            SELECT
                id,
                category,
                takeaway,
                summary_context,
                LENGTH(transcript) as transcript_length
            FROM episodic_memories
            WHERE category = %s
              AND transcript IS NOT NULL
              AND transcript <> ''
              AND LENGTH(transcript) > 100
              AND summary_context IS NOT NULL AND summary_context <> ''
              AND summary_event IS NOT NULL AND summary_event <> ''
              AND summary_significance IS NOT NULL AND summary_significance <> ''
              AND takeaway IS NOT NULL AND takeaway <> ''
            ORDER BY RANDOM()
            LIMIT %s
        """, (category, memories_per_category))

        memories = cur.fetchall()

        print(f"\n{category}: Selected {len(memories)} memories")
        for mem in memories:
            test_set['memories'].append({
                'id': mem['id'],
                'category': mem['category'],
                'takeaway': mem['takeaway'][:100] + '...' if len(mem['takeaway']) > 100 else mem['takeaway'],
                'context': mem['summary_context'][:80] + '...' if mem['summary_context'] and len(mem['summary_context']) > 80 else mem['summary_context'],
                'transcript_length': mem['transcript_length']
            })
            print(f"  ID {mem['id']}: {mem['takeaway'][:60]}...")

    test_set['metadata']['total_memories'] = len(test_set['memories'])

    # Save to file
    output_path = os.path.join(os.path.dirname(__file__), output_file)
    with open(output_path, 'w') as f:
        json.dump(test_set, f, indent=2)

    cur.close()
    conn.close()

    print(f"\n{'='*80}")
    print(f"Test set created: {output_path}")
    print(f"Total memories: {test_set['metadata']['total_memories']}")
    print(f"Categories: {len(categories)}")
    print(f"Memories per category: ~{memories_per_category}")
    print(f"{'='*80}")

    return test_set

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Create stratified test set')
    parser.add_argument('--per-category', type=int, default=10,
                       help='Number of memories per category (default: 10)')
    parser.add_argument('--output', type=str, default='test_set.json',
                       help='Output file name (default: test_set.json)')

    args = parser.parse_args()

    create_stratified_test_set(
        memories_per_category=args.per_category,
        output_file=args.output
    )
