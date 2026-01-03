"""
Test v2 retrieval system using stratified test set
Uses fixed memory IDs from test_set.json for reproducible A/B testing
"""

import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, PROJECT_ROOT)

import psycopg2
from psycopg2.extras import DictCursor
import json
from Colors import Colors

# Import new retrieval system
from memory_retrieval_v2 import retrieve_memories

DB_CFG = dict(dbname="irisdb", user="irisuser", password="yourpassword", host="localhost", port=5432)

class StratifiedV2Tester:
    """Test new v2 retrieval system with fixed test set"""

    def __init__(self, test_set_file='test_set.json'):
        test_set_path = os.path.join(os.path.dirname(__file__), test_set_file)

        if not os.path.exists(test_set_path):
            raise FileNotFoundError(
                f"Test set not found: {test_set_path}\n"
                f"Run: python create_test_set.py first"
            )

        with open(test_set_path, 'r') as f:
            self.test_set = json.load(f)

        print(f"Loaded test set: {len(self.test_set['memories'])} memories")
        print(f"Categories: {self.test_set['metadata']['total_categories']}")

    def get_test_memories(self):
        """Load full memory data for test set IDs"""
        memory_ids = [m['id'] for m in self.test_set['memories']]

        conn = psycopg2.connect(**DB_CFG)
        cur = conn.cursor(cursor_factory=DictCursor)

        # Use ANY to get all IDs in one query
        cur.execute("""
            SELECT
                id,
                transcript,
                takeaway,
                category,
                summary_context
            FROM episodic_memories
            WHERE id = ANY(%s)
        """, (memory_ids,))

        memories = cur.fetchall()
        cur.close()
        conn.close()

        # Return in same order as test set
        id_to_memory = {m['id']: m for m in memories}
        return [id_to_memory[mid] for mid in memory_ids if mid in id_to_memory]

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

    def run_test(self):
        """Test v2 system on stratified test set"""

        memories = self.get_test_memories()

        print(f"\n{Colors.BRIGHT_MAGENTA}{'='*80}")
        print("V2 RETRIEVAL SYSTEM TEST (STRATIFIED)")
        print(f"Testing {len(memories)} memories from balanced test set")
        print(f"{'='*80}{Colors.RESET}\n")

        results = []
        category_stats = {}

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

            # Track by category
            cat = memory['category']
            if cat not in category_stats:
                category_stats[cat] = {'total': 0, 'retrieved': 0}
            category_stats[cat]['total'] += 1
            if self_retrieved:
                category_stats[cat]['retrieved'] += 1

            results.append({
                'memory_id': memory['id'],
                'category': memory['category'],
                'self_retrieved': self_retrieved,
                'retrieved_count': len(retrieved)
            })
            print()

        # Summary
        self.print_summary(results, category_stats)

    def print_summary(self, results, category_stats):
        """Print test summary"""
        print(f"\n{Colors.BRIGHT_MAGENTA}{'='*80}")
        print("TEST SUMMARY")
        print(f"{'='*80}{Colors.RESET}\n")

        total = len(results)
        self_retrieved_count = sum(1 for r in results if r['self_retrieved'])
        rate = (self_retrieved_count / total * 100) if total else 0

        print(f"Total memories tested: {total}")
        print(f"Self-retrieved: {self_retrieved_count}/{total} ({rate:.1f}%)")

        # By category
        print(f"\nBy Category:")
        for cat in sorted(category_stats.keys()):
            stats = category_stats[cat]
            cat_rate = (stats['retrieved'] / stats['total'] * 100) if stats['total'] else 0
            print(f"  {cat}: {stats['retrieved']}/{stats['total']} ({cat_rate:.0f}%)")

        # Copy/paste section
        print(f"\n{Colors.BRIGHT_CYAN}{'='*80}")
        print("COPY/PASTE RESULTS")
        print(f"{'='*80}{Colors.RESET}\n")

        print("=== V2 STRATIFIED TEST RESULTS ===")
        print(f"Total tested: {total}")
        print(f"Self-retrieval rate: {self_retrieved_count}/{total} ({rate:.1f}%)")
        print("\nBy Category:")
        for cat in sorted(category_stats.keys()):
            stats = category_stats[cat]
            cat_rate = (stats['retrieved'] / stats['total'] * 100) if stats['total'] else 0
            print(f"  {cat}: {stats['retrieved']}/{stats['total']} ({cat_rate:.0f}%)")
        print("=== END RESULTS ===")

        print(f"\n{Colors.BRIGHT_YELLOW}INTERPRETATION:{Colors.RESET}")
        if rate >= 80:
            print(f"  ✓ EXCELLENT: {rate:.1f}% self-retrieval (target: ≥80%)")
        elif rate >= 70:
            print(f"  ✓ GOOD: {rate:.1f}% self-retrieval (target: ≥70%)")
        elif rate >= 60:
            print(f"  ~ MODERATE: {rate:.1f}% self-retrieval (acceptable but could improve)")
        elif rate >= 40:
            print(f"  ⚠ FAIR: {rate:.1f}% self-retrieval (needs improvement)")
        else:
            print(f"  ✗ POOR: {rate:.1f}% self-retrieval (system needs work)")

        # Category-specific feedback
        print(f"\n{Colors.BRIGHT_YELLOW}CATEGORY ANALYSIS:{Colors.RESET}")
        for cat in sorted(category_stats.keys()):
            stats = category_stats[cat]
            cat_rate = (stats['retrieved'] / stats['total'] * 100) if stats['total'] else 0
            if cat_rate < 50:
                print(f"  ⚠ {cat} memories underperforming ({cat_rate:.0f}%)")
            elif cat_rate >= 80:
                print(f"  ✓ {cat} memories performing well ({cat_rate:.0f}%)")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Test v2 retrieval with stratified set')
    parser.add_argument('--test-set', type=str, default='test_set.json',
                       help='Test set file (default: test_set.json)')

    args = parser.parse_args()

    tester = StratifiedV2Tester(test_set_file=args.test_set)
    tester.run_test()
