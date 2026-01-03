"""
Test memory retrieval using the ACTUAL pipeline
Calls lens → emotion → summaries → embeddings → retrieval
"""

import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, PROJECT_ROOT)

import psycopg2
from psycopg2.extras import DictCursor
from sentence_transformers import SentenceTransformer
import random
from Colors import Colors

# Import the actual retrieval system
from iris_memory_retrieval import cognitive_recall, SIM_WEIGHTS

DB_CFG = dict(dbname="irisdb", user="irisuser", password="yourpassword", host="localhost", port=5432)

class ActualPipelineTester:
    def __init__(self):
        self.model = SentenceTransformer("/models/llm_models/huggingface/models/all-mpnet-base-v2/", local_files_only=True)
        self.thresholds = [0.15, 0.20, 0.25, 0.30]

    def get_random_memories(self, limit=5):
        """Get random memories with transcripts"""
        conn = psycopg2.connect(**DB_CFG)
        cur = conn.cursor(cursor_factory=DictCursor)

        cur.execute("""
            SELECT
                id,
                transcript,
                takeaway,
                category,
                event_time,
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

    def clear_live_memories(self):
        """Clear live_memories table before test"""
        conn = psycopg2.connect(**DB_CFG)
        cur = conn.cursor()
        cur.execute("DELETE FROM live_memories")
        conn.commit()
        cur.close()
        conn.close()

    def get_live_memories(self):
        """Get what's currently in live_memories table"""
        conn = psycopg2.connect(**DB_CFG)
        cur = conn.cursor(cursor_factory=DictCursor)
        cur.execute("""
            SELECT memory_id, rank
            FROM live_memories
            ORDER BY rank ASC
        """)
        results = cur.fetchall()
        cur.close()
        conn.close()
        return results

    def test_memory_with_threshold(self, memory: dict, threshold: float):
        """Test one memory with one threshold using ACTUAL pipeline"""

        # Modify threshold
        original_threshold = SIM_WEIGHTS["sim_threshold"]
        SIM_WEIGHTS["sim_threshold"] = threshold

        class SimpleEmbedder:
            def __init__(self, model):
                self.model = model
            def embed(self, text):
                return self.model.encode(text, normalize_embeddings=True).tolist()

        embedder = SimpleEmbedder(self.model)

        # Clear live_memories
        self.clear_live_memories()

        try:
            print(f"{Colors.YELLOW}Running full pipeline with threshold {threshold:.2f}...{Colors.RESET}", end="")

            # Run ACTUAL cognitive recall pipeline
            # This does: lens → emotion → summaries → 4 embeddings → SQL → rerank → insert
            try:
                cognitive_recall(
                    convo=memory['transcript'],
                    embedder=embedder,
                    conn_params=DB_CFG,
                    top_k=5,
                    insert=True,      # Insert into live_memories
                    show=False,       # Suppress output
                    mode='replace',
                    prompt=False
                )

                # Get what was inserted into live_memories
                retrieved = self.get_live_memories()

                print(f" {Colors.GREEN}Retrieved {len(retrieved)} memories{Colors.RESET}")

                return retrieved

            except Exception as e:
                print(f" {Colors.RED}FAILED: {str(e)[:80]}{Colors.RESET}")
                return []  # Return empty list on failure

        finally:
            # Restore original threshold
            SIM_WEIGHTS["sim_threshold"] = original_threshold

    def test_memory(self, memory: dict):
        """Test one memory across all thresholds"""
        print(f"\n{Colors.BRIGHT_CYAN}{'='*80}")
        print(f"MEMORY ID: {memory['id']} | Category: {memory['category']}")
        print(f"{'='*80}{Colors.RESET}")

        print(f"\n{Colors.YELLOW}Context:{Colors.RESET} {memory['summary_context'][:100] if memory['summary_context'] else 'N/A'}...")
        print(f"{Colors.YELLOW}Takeaway:{Colors.RESET} {memory['takeaway'][:100]}...")
        print(f"\n{Colors.YELLOW}Transcript (first 300 chars):{Colors.RESET}")
        print(memory['transcript'][:300] + "...")
        print()

        results = {}

        for threshold in self.thresholds:
            retrieved = self.test_memory_with_threshold(memory, threshold)

            # Check if source memory retrieved itself
            retrieved_ids = [r['memory_id'] for r in retrieved]
            self_retrieved = memory['id'] in retrieved_ids

            results[threshold] = {
                'memories': retrieved,
                'self_retrieved': self_retrieved,
                'count': len(retrieved)
            }

            if self_retrieved:
                position = retrieved_ids.index(memory['id']) + 1
                rank_val = next(r['rank'] for r in retrieved if r['memory_id'] == memory['id'])
                print(f"  {Colors.BRIGHT_CYAN}✓ Source retrieved at position #{position} (rank={rank_val}){Colors.RESET}")
            else:
                print(f"  {Colors.YELLOW}✗ Source NOT retrieved{Colors.RESET}")
                if retrieved:
                    print(f"    Top match: ID {retrieved[0]['memory_id']} (rank={retrieved[0]['rank']})")

        return results

    def run_batch_test(self, num_memories=5):
        """Test multiple memories with actual pipeline"""
        print(f"\n{Colors.BRIGHT_MAGENTA}{'='*80}")
        print("ACTUAL PIPELINE TESTING")
        print(f"Testing {num_memories} memories using FULL retrieval pipeline")
        print("(lens → emotion → summaries → embeddings → SQL → rerank)")
        print(f"{'='*80}{Colors.RESET}\n")

        memories = self.get_random_memories(limit=num_memories)
        print(f"Testing {len(memories)} random memories\n")

        all_results = {}

        for i, memory in enumerate(memories, 1):
            print(f"\n{Colors.WHITE}[{i}/{len(memories)}]{Colors.RESET}")
            results = self.test_memory(memory)
            all_results[memory['id']] = {
                'results': results,
                'category': memory['category']
            }

        # Summary
        self.print_summary(all_results)

    def print_summary(self, all_results):
        """Print summary statistics"""
        print(f"\n{Colors.BRIGHT_MAGENTA}{'='*80}")
        print("SUMMARY ANALYSIS")
        print(f"{'='*80}{Colors.RESET}\n")

        # Detailed stats per threshold
        stats = {}
        for threshold in self.thresholds:
            self_retrieved = sum(1 for mid, data in all_results.items()
                               if data['results'][threshold]['self_retrieved'])
            total = len(all_results)
            rate = (self_retrieved / total * 100) if total else 0
            avg_count = sum(data['results'][threshold]['count'] for data in all_results.values()) / total

            stats[threshold] = {
                'self_retrieved': self_retrieved,
                'total': total,
                'rate': rate,
                'avg_count': avg_count
            }

            print(f"{Colors.BRIGHT_GREEN}Threshold {threshold:.2f}:{Colors.RESET}")
            print(f"  Self-retrieval: {self_retrieved}/{total} ({rate:.0f}%)")
            print(f"  Avg memories retrieved: {avg_count:.1f}")
            print()

        # Formatted results for copy/paste
        print(f"\n{Colors.BRIGHT_CYAN}{'='*80}")
        print("COPY/PASTE RESULTS BELOW THIS LINE")
        print(f"{'='*80}{Colors.RESET}\n")

        print("=== TEST RESULTS ===")
        print(f"Total memories tested: {len(all_results)}")
        print(f"Thresholds tested: {self.thresholds}")
        print()
        print("Self-Retrieval Rates:")
        for threshold in self.thresholds:
            s = stats[threshold]
            print(f"  Threshold {threshold:.2f}: {s['self_retrieved']}/{s['total']} ({s['rate']:.0f}%) | Avg retrieved: {s['avg_count']:.1f}")

        print()
        print("Quick Summary:")
        best_threshold = max(self.thresholds, key=lambda t: stats[t]['rate'])
        print(f"  Best self-retrieval: {best_threshold:.2f} ({stats[best_threshold]['rate']:.0f}%)")
        print(f"  Best avg count: {best_threshold:.2f} ({stats[best_threshold]['avg_count']:.1f} memories)")

        # Show breakdown by category if available
        categories = set(data['category'] for data in all_results.values())
        if len(categories) > 1:
            print()
            print("By Category:")
            for cat in sorted(categories):
                cat_mems = [mid for mid, data in all_results.items() if data['category'] == cat]
                print(f"  {cat}: {len(cat_mems)} memories tested")

        print()
        print("=== END RESULTS ===")
        print()

        print(f"{Colors.BRIGHT_YELLOW}RECOMMENDATION:{Colors.RESET}")
        if stats[best_threshold]['rate'] >= 70:
            print(f"  ✓ Threshold {best_threshold:.2f} shows good performance (≥70% self-retrieval)")
        elif stats[best_threshold]['rate'] >= 50:
            print(f"  ~ Threshold {best_threshold:.2f} shows moderate performance (50-70% self-retrieval)")
        else:
            print(f"  ✗ All thresholds show low performance (<50% self-retrieval)")
            print(f"    Consider investigating why memories don't retrieve themselves")

        print()
        print(f"{Colors.BRIGHT_YELLOW}NOTE:{Colors.RESET}")
        print("  Copy the section between the '===' markers and paste it back to Claude")
        print("  This includes all data needed for threshold recommendation")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Test with actual retrieval pipeline')
    parser.add_argument('--memories', type=int, default=5,
                       help='Number of memories to test (default: 5)')
    parser.add_argument('--seed', type=int, default=None,
                       help='Random seed for reproducibility')
    parser.add_argument('--yes', '-y', action='store_true',
                       help='Skip confirmation prompt')

    args = parser.parse_args()

    if args.seed:
        random.seed(args.seed)

    if not args.yes:
        print(f"\n{Colors.BRIGHT_CYAN}⚠️  WARNING: This will hit the LLM multiple times!{Colors.RESET}")
        print(f"   {args.memories} memories × 4 thresholds × 3 LLM calls = {args.memories * 4 * 3} total LLM calls")
        print(f"   Estimated time: ~{args.memories * 2}-{args.memories * 3} minutes\n")

        response = input("Continue? (y/n): ")
        if response.lower() != 'y':
            print("Aborted.")
            sys.exit(0)

    tester = ActualPipelineTester()
    tester.run_batch_test(num_memories=args.memories)
