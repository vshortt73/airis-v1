"""
Test the new v2 retrieval system
Compare against old system for self-retrieval accuracy
"""

import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, PROJECT_ROOT)

import psycopg2
from psycopg2.extras import DictCursor
import random
from Colors import Colors

# Import new retrieval system
from memory_retrieval_v2 import retrieve_memories

DB_CFG = dict(dbname="irisdb", user="irisuser", password="yourpassword", host="localhost", port=5432)

class V2Tester:
    """Test new v2 retrieval system"""

    def __init__(self):
        pass

    def get_random_memories(self, limit=10):
        """Get random memories with transcripts"""
        conn = psycopg2.connect(**DB_CFG)
        cur = conn.cursor(cursor_factory=DictCursor)

        cur.execute("""
            SELECT
                id,
                transcript,
                takeaway,
                category,
                summary_context
            FROM episodic_memories
            WHERE transcript IS NOT NULL
              AND transcript <> ''
              AND LENGTH(transcript) > 100
            ORDER BY RANDOM()
            LIMIT %s
        """, (limit,))

        memories = cur.fetchall()
        cur.close()
        conn.close()
        return memories

    def test_self_retrieval(self, memory: dict, top_k: int = 5) -> bool:
        """Test if memory retrieves itself using v2 system"""

        # Use memory's transcript as query
        results = retrieve_memories(
            memory['transcript'],
            top_k=top_k,
            verbose=False
        )

        # Check if source memory is in results
        retrieved_ids = [r['id'] for r in results]
        self_retrieved = memory['id'] in retrieved_ids

        return self_retrieved, results

    def run_test(self, num_memories=10):
        """Test v2 system on random memories"""

        print(f"\n{Colors.BRIGHT_MAGENTA}{'='*80}")
        print("V2 RETRIEVAL SYSTEM TEST")
        print(f"Testing {num_memories} random memories")
        print(f"{'='*80}{Colors.RESET}\n")

        memories = self.get_random_memories(limit=num_memories)
        print(f"Testing {len(memories)} memories\n")

        results = []

        for i, memory in enumerate(memories, 1):
            print(f"{Colors.BRIGHT_CYAN}[{i}/{len(memories)}] Memory ID: {memory['id']} | {memory['category']}{Colors.RESET}")
            print(f"  Context: {memory['summary_context'][:80] if memory['summary_context'] else 'N/A'}...")
            print(f"  Transcript: {memory['transcript'][:100]}...")

            self_retrieved, retrieved = self.test_self_retrieval(memory, top_k=5)

            if self_retrieved:
                rank = [r['id'] for r in retrieved].index(memory['id']) + 1
                strength = next(r['strength'] for r in retrieved if r['id'] == memory['id'])
                print(f"  {Colors.BRIGHT_GREEN}✓ Self-retrieved at rank #{rank} (strength={strength:.3f}){Colors.RESET}")
            else:
                print(f"  {Colors.YELLOW}✗ Not self-retrieved{Colors.RESET}")
                if retrieved:
                    print(f"    Top match: ID {retrieved[0]['id']} (strength={retrieved[0]['strength']:.3f})")

            results.append({
                'memory_id': memory['id'],
                'category': memory['category'],
                'self_retrieved': self_retrieved,
                'retrieved_count': len(retrieved)
            })
            print()

        # Summary
        self.print_summary(results)

    def print_summary(self, results):
        """Print test summary"""
        print(f"\n{Colors.BRIGHT_MAGENTA}{'='*80}")
        print("TEST SUMMARY")
        print(f"{'='*80}{Colors.RESET}\n")

        total = len(results)
        self_retrieved_count = sum(1 for r in results if r['self_retrieved'])
        rate = (self_retrieved_count / total * 100) if total else 0

        print(f"Total memories tested: {total}")
        print(f"Self-retrieved: {self_retrieved_count}/{total} ({rate:.0f}%)")

        # By category
        categories = set(r['category'] for r in results)
        if len(categories) > 1:
            print(f"\nBy Category:")
            for cat in sorted(categories):
                cat_results = [r for r in results if r['category'] == cat]
                cat_retrieved = sum(1 for r in cat_results if r['self_retrieved'])
                print(f"  {cat}: {cat_retrieved}/{len(cat_results)}")

        # Copy/paste section
        print(f"\n{Colors.BRIGHT_CYAN}{'='*80}")
        print("COPY/PASTE RESULTS")
        print(f"{'='*80}{Colors.RESET}\n")

        print("=== V2 TEST RESULTS ===")
        print(f"Total tested: {total}")
        print(f"Self-retrieval rate: {self_retrieved_count}/{total} ({rate:.0f}%)")
        print("=== END RESULTS ===")

        print(f"\n{Colors.BRIGHT_YELLOW}INTERPRETATION:{Colors.RESET}")
        if rate >= 80:
            print(f"  ✓ EXCELLENT: {rate:.0f}% self-retrieval (target: ≥80%)")
        elif rate >= 60:
            print(f"  ~ GOOD: {rate:.0f}% self-retrieval (target: ≥80%)")
        elif rate >= 40:
            print(f"  ⚠ MODERATE: {rate:.0f}% self-retrieval (needs improvement)")
        else:
            print(f"  ✗ POOR: {rate:.0f}% self-retrieval (system needs work)")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Test v2 retrieval system')
    parser.add_argument('--memories', type=int, default=10, help='Number of memories to test')
    parser.add_argument('--seed', type=int, default=None, help='Random seed')

    args = parser.parse_args()

    if args.seed:
        random.seed(args.seed)

    tester = V2Tester()
    tester.run_test(num_memories=args.memories)
