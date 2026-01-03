"""
Test memory retrieval with actual conversation history from database
Pulls random real sessions and analyzes retrieval quality
"""

import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, PROJECT_ROOT)

import psycopg2
from psycopg2.extras import DictCursor
from sentence_transformers import SentenceTransformer
import numpy as np
from Colors import Colors
from datetime import datetime
import random

DB_CFG = dict(dbname="irisdb", user="irisuser", password="yourpassword", host="localhost", port=5432)

class RealConversationTester:
    def __init__(self):
        self.model = SentenceTransformer("/models/llm_models/huggingface/models/all-mpnet-base-v2/", local_files_only=True)
        self.thresholds = [0.15, 0.20, 0.25, 0.30]

    def get_random_memories(self, limit=10):
        """Get random memories with transcripts to test against"""
        conn = psycopg2.connect(**DB_CFG)
        cur = conn.cursor(cursor_factory=DictCursor)

        # Get random memories that have transcripts
        cur.execute("""
            SELECT
                id,
                transcript,
                takeaway,
                category,
                event_time,
                summary_context,
                summary_event
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

    def get_memory_conversation(self, memory):
        """Extract conversation info from memory"""
        return {
            'text': memory['transcript'],
            'memory_id': memory['id'],
            'category': memory['category'],
            'takeaway': memory['takeaway'][:100],
            'summary_context': memory['summary_context'][:100] if memory['summary_context'] else '',
            'timestamp': memory['event_time']
        }

    def retrieve_with_full_pipeline(self, conversation_text: str, threshold: float, top_k: int = 5):
        """Retrieve memories using the FULL pipeline (lens + emotion + summaries + embeddings)"""
        # Import the actual retrieval function
        from iris_memory_retrieval import cognitive_recall, SIM_WEIGHTS

        # Temporarily modify threshold for this test
        original_threshold = SIM_WEIGHTS["sim_threshold"]
        SIM_WEIGHTS["sim_threshold"] = threshold

        class SimpleEmbedder:
            def __init__(self, model):
                self.model = model

            def embed(self, text):
                return self.model.encode(text, normalize_embeddings=True).tolist()

        embedder = SimpleEmbedder(self.model)

        try:
            # Run full cognitive recall pipeline
            # This will: lens → emotion → summaries → 4 embeddings → SQL query → rerank
            result = cognitive_recall(
                convo=conversation_text,
                embedder=embedder,
                conn_params=DB_CFG,
                top_k=top_k,
                insert=False,  # Don't insert into live_memories
                show=False,    # Don't print output
                mode='replace',
                prompt=False
            )

            # Parse the result - cognitive_recall returns formatted text
            # We need to extract memory IDs and scores from it
            # For now, fall back to direct query since cognitive_recall doesn't return structured data

        finally:
            # Restore original threshold
            SIM_WEIGHTS["sim_threshold"] = original_threshold

        # Fall back to direct query for now
        # TODO: Modify cognitive_recall to return structured data
        return self._direct_query_with_threshold(conversation_text, threshold, top_k)

    def _direct_query_with_threshold(self, conversation_text: str, threshold: float, top_k: int = 5):
        """Direct query as fallback - still uses raw transcript embedding"""
        query_emb = self.model.encode(conversation_text).tolist()

        conn = psycopg2.connect(**DB_CFG)
        cur = conn.cursor(cursor_factory=DictCursor)

        cur.execute("""
            SELECT
                id,
                takeaway,
                summary_context,
                summary_event,
                category,
                emotion_label,
                age_days,
                (
                    0.25 * (1 - (emb_summary_context <=> %s::vector)) +
                    0.25 * (1 - (emb_summary_event <=> %s::vector)) +
                    0.25 * (1 - (emb_summary_significance <=> %s::vector)) +
                    0.25 * (1 - (emb_takeaway <=> %s::vector))
                )::float AS similarity
            FROM episodic_memories_with_age
            WHERE summary_context IS NOT NULL AND summary_context <> ''
              AND summary_event IS NOT NULL AND summary_event <> ''
              AND summary_significance IS NOT NULL AND summary_significance <> ''
              AND takeaway IS NOT NULL AND takeaway <> ''
            ORDER BY similarity DESC
            LIMIT %s
        """, (query_emb, query_emb, query_emb, query_emb, top_k * 3))

        results = cur.fetchall()
        cur.close()
        conn.close()

        # Filter by threshold
        filtered = [r for r in results if r['similarity'] >= threshold]
        return filtered[:top_k]

    def analyze_memory(self, memory: dict):
        """Analyze memory retrieval for one memory's transcript"""
        print(f"\n{Colors.BRIGHT_CYAN}{'='*80}")
        print(f"MEMORY ID: {memory['id']} | Category: {memory['category']}")
        print(f"{'='*80}{Colors.RESET}")

        # Get conversation
        conv = self.get_memory_conversation(memory)

        print(f"\n{Colors.YELLOW}Memory Info:{Colors.RESET}")
        print(f"  Source Memory ID: {conv['memory_id']}")
        print(f"  Category: {conv['category']}")
        print(f"  Timestamp: {conv['timestamp']}")
        print(f"  Context: {conv['summary_context']}...")
        print(f"  Takeaway: {conv['takeaway']}...")
        print()

        # Show conversation sample
        print(f"{Colors.YELLOW}Transcript Sample (first 400 chars):{Colors.RESET}")
        print(conv['text'][:400] + "...")
        print()

        # Test each threshold
        results = {}
        source_id = conv['memory_id']

        for threshold in self.thresholds:
            retrieved = self.retrieve_with_threshold(conv['text'], threshold, top_k=5)
            results[threshold] = retrieved

            # Check if source memory retrieved itself
            retrieved_ids = [m['id'] for m in retrieved]
            self_retrieved = source_id in retrieved_ids

            print(f"{Colors.BRIGHT_GREEN}Threshold {threshold:.2f}: {len(retrieved)} memories{Colors.RESET}")

            if retrieved:
                top_sim = retrieved[0]['similarity']
                print(f"  Top similarity: {top_sim:.3f}")

                if self_retrieved:
                    rank = retrieved_ids.index(source_id) + 1
                    print(f"  {Colors.BRIGHT_CYAN}✓ Source memory retrieved (rank #{rank}){Colors.RESET}")
                else:
                    print(f"  {Colors.YELLOW}✗ Source memory NOT retrieved{Colors.RESET}")

                # Show top 3
                for i, mem in enumerate(retrieved[:3], 1):
                    is_source = " ← SOURCE" if mem['id'] == source_id else ""
                    print(f"  {i}. [{mem['category']}] sim={mem['similarity']:.3f} age={mem['age_days']:.0f}d{is_source}")
                    print(f"     {mem['takeaway'][:80]}...")
            else:
                print(f"  {Colors.RED}No memories retrieved{Colors.RESET}")
            print()

        return results

    def run_batch_test(self, num_memories=5):
        """Test multiple real memory transcripts"""
        print(f"\n{Colors.BRIGHT_MAGENTA}{'='*80}")
        print("REAL CONVERSATION TESTING")
        print(f"Testing {num_memories} random memory transcripts with multiple thresholds")
        print(f"Tests if memories can retrieve themselves and related memories")
        print(f"{'='*80}{Colors.RESET}\n")

        # Get random memories
        memories = self.get_random_memories(limit=num_memories)
        print(f"Found {len(memories)} memories with transcripts\n")

        all_results = {}

        for memory in memories:
            memory_id = memory['id']
            results = self.analyze_memory(memory)
            all_results[memory_id] = {
                'results': results,
                'source_category': memory['category']
            }

        # Summary analysis
        self.print_summary(all_results)

    def print_summary(self, all_results):
        """Print summary statistics across all memories"""
        print(f"\n{Colors.BRIGHT_MAGENTA}{'='*80}")
        print("SUMMARY ANALYSIS")
        print(f"{'='*80}{Colors.RESET}\n")

        # Statistics per threshold
        for threshold in self.thresholds:
            print(f"{Colors.BRIGHT_GREEN}Threshold {threshold:.2f}:{Colors.RESET}")

            # Collect stats
            retrieval_counts = []
            top_similarities = []
            categories_found = set()
            self_retrieved_count = 0

            for memory_id, data in all_results.items():
                memories = data['results'][threshold]
                retrieval_counts.append(len(memories))

                # Check if source memory retrieved itself
                if any(m['id'] == memory_id for m in memories):
                    self_retrieved_count += 1

                if memories:
                    top_similarities.append(memories[0]['similarity'])
                    for mem in memories:
                        categories_found.add(mem['category'])

            # Calculate metrics
            memories_with_results = sum(1 for c in retrieval_counts if c > 0)
            memories_without = len(retrieval_counts) - memories_with_results
            avg_count = np.mean(retrieval_counts) if retrieval_counts else 0
            avg_top_sim = np.mean(top_similarities) if top_similarities else 0
            self_retrieval_rate = (self_retrieved_count / len(all_results) * 100) if all_results else 0

            print(f"  Memories with results: {memories_with_results}/{len(retrieval_counts)}")
            print(f"  {Colors.BRIGHT_CYAN}Self-retrieval rate: {self_retrieved_count}/{len(all_results)} ({self_retrieval_rate:.0f}%){Colors.RESET}")
            print(f"  Avg memories retrieved: {avg_count:.1f}")
            print(f"  Avg top similarity: {avg_top_sim:.3f}")
            print(f"  Categories found: {', '.join(sorted(categories_found)) if categories_found else 'none'}")

            # Distribution
            if retrieval_counts:
                print(f"  Distribution: min={min(retrieval_counts)}, max={max(retrieval_counts)}")

            print()

        # Recommendations
        print(f"{Colors.BRIGHT_YELLOW}KEY METRICS:{Colors.RESET}\n")

        # Compare self-retrieval rates
        total_memories = len(all_results)

        for threshold in [0.15, 0.20, 0.25, 0.30]:
            self_retrieved = sum(1 for mid, data in all_results.items()
                               if any(m['id'] == mid for m in data['results'][threshold]))
            rate = (self_retrieved / total_memories * 100) if total_memories else 0
            print(f"  Threshold {threshold:.2f}: {self_retrieved}/{total_memories} memories self-retrieved ({rate:.0f}%)")

        # Check quality vs quantity tradeoff
        print(f"\n{Colors.BRIGHT_YELLOW}INTERPRETATION:{Colors.RESET}")
        print(f"  Self-retrieval rate shows if similar conversations retrieve the same memory")
        print(f"  High rate (>80%) = good recall of relevant memories")
        print(f"  Low rate (<50%) = threshold too strict, missing relevant context")
        print(f"  100% rate may indicate threshold too loose (retrieving everything)")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Test memory retrieval with real memory transcripts')
    parser.add_argument('--memories', type=int, default=5,
                       help='Number of memories to test (default: 5)')
    parser.add_argument('--seed', type=int, default=None,
                       help='Random seed for reproducibility')

    args = parser.parse_args()

    if args.seed:
        random.seed(args.seed)

    tester = RealConversationTester()
    tester.run_batch_test(num_memories=args.memories)
