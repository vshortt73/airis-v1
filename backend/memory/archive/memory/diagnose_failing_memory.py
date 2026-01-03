"""
Deep diagnostic tool for understanding why specific memories fail self-retrieval
Traces through the entire retrieval process step-by-step
"""

import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, PROJECT_ROOT)

import psycopg2
from psycopg2.extras import DictCursor
import json
from Colors import Colors

# Import retrieval components
from memory_retrieval_v2 import (
    retrieve_memories,
    score_emotion,
    compute_emotional_resonance,
    compute_recency_score,
    compute_frequency_score,
    models,
    WEIGHTS,
    EMBEDDING_WEIGHTS
)

DB_CFG = dict(dbname="irisdb", user="irisuser", password="yourpassword", host="localhost", port=5432)

class MemoryDiagnostic:
    """Deep diagnostic for failing memories"""

    def __init__(self):
        self.conn = psycopg2.connect(**DB_CFG)
        self.cur = self.conn.cursor(cursor_factory=DictCursor)

    def get_failing_memories_by_category(self, category, limit=5):
        """Get memories from test set that failed self-retrieval"""
        # Load test set
        test_set_path = os.path.join(os.path.dirname(__file__), 'test_set.json')
        with open(test_set_path, 'r') as f:
            test_set = json.load(f)

        # Get memories of this category
        category_memories = [m for m in test_set['memories'] if m['category'] == category]

        print(f"Found {len(category_memories)} {category} memories in test set")

        # Get full data and test each
        failing = []
        for mem_info in category_memories[:limit]:
            self.cur.execute("""
                SELECT
                    id, transcript, takeaway, category,
                    summary_context, summary_event, summary_significance,
                    emotion_label, valence, arousal,
                    recurrence, novelty, cohesion, age_days
                FROM episodic_memories_with_age
                WHERE id = %s
            """, (mem_info['id'],))

            memory = self.cur.fetchone()
            if memory:
                # Quick test
                results = retrieve_memories(memory['transcript'], top_k=5, verbose=False)
                retrieved_ids = [r['id'] for r in results]

                if memory['id'] not in retrieved_ids:
                    failing.append(dict(memory))

        return failing

    def diagnose_memory(self, memory_id):
        """Deep diagnostic of specific memory"""

        # Get full memory data
        self.cur.execute("""
            SELECT
                id, transcript, takeaway, category,
                summary_context, summary_event, summary_significance,
                emotion_label, valence, arousal,
                recurrence, novelty, cohesion, age_days
            FROM episodic_memories_with_age
            WHERE id = %s
        """, (memory_id,))

        memory = dict(self.cur.fetchone())

        print(f"\n{Colors.BRIGHT_MAGENTA}{'='*80}")
        print(f"DIAGNOSTIC: Memory ID {memory_id}")
        print(f"{'='*80}{Colors.RESET}\n")

        # 1. Show memory details
        print(f"{Colors.BRIGHT_CYAN}MEMORY DETAILS:{Colors.RESET}")
        print(f"Category: {memory['category']}")
        print(f"Age: {memory['age_days']:.0f} days")
        print(f"\nContext: {memory['summary_context'][:150]}...")
        print(f"\nEvent: {memory['summary_event'][:150]}...")
        print(f"\nTakeaway: {memory['takeaway'][:150]}...")
        print(f"\nTranscript (first 300 chars):")
        print(f"{memory['transcript'][:300]}...")

        # 2. Show stored emotion data
        print(f"\n{Colors.BRIGHT_CYAN}STORED EMOTION DATA:{Colors.RESET}")
        print(f"Emotion Label: {memory['emotion_label']}")
        print(f"Valence: {float(memory['valence']) if memory['valence'] else 'NULL':.3f}")
        print(f"Arousal: {float(memory['arousal']) if memory['arousal'] else 'NULL':.3f}")
        stored_intensity = abs(float(memory['valence']) if memory['valence'] else 0.0) * (float(memory['arousal']) if memory['arousal'] else 0.0)
        print(f"Intensity: {stored_intensity:.3f}")

        # 3. Score current emotion from transcript
        print(f"\n{Colors.BRIGHT_CYAN}QUERY EMOTION (from transcript):{Colors.RESET}")
        query_emotion = score_emotion(memory['transcript'])
        print(f"Emotion Label: {query_emotion['emotion_label']}")
        print(f"Valence: {query_emotion['valence']:.3f}")
        print(f"Arousal: {query_emotion['arousal']:.3f}")
        print(f"Intensity: {query_emotion['intensity']:.3f}")

        # 4. Compute emotional resonance
        memory_emotion = {
            'valence': float(memory['valence']) if memory['valence'] else 0.0,
            'arousal': float(memory['arousal']) if memory['arousal'] else 0.0,
            'emotion_label': memory['emotion_label']
        }
        resonance = compute_emotional_resonance(query_emotion, memory_emotion)
        print(f"\n{Colors.BRIGHT_CYAN}EMOTIONAL RESONANCE:{Colors.RESET}")
        print(f"Resonance Score: {resonance:.3f}")
        print(f"(1.0 = identical emotions, 0.0 = opposite emotions)")

        # 5. Run retrieval and show what actually retrieved
        print(f"\n{Colors.BRIGHT_CYAN}RETRIEVAL RESULTS:{Colors.RESET}")
        results = retrieve_memories(memory['transcript'], top_k=10, verbose=False)

        retrieved_ids = [r['id'] for r in results]
        if memory['id'] in retrieved_ids:
            rank = retrieved_ids.index(memory['id']) + 1
            self_result = next(r for r in results if r['id'] == memory['id'])
            print(f"{Colors.BRIGHT_GREEN}✓ Self-retrieved at rank #{rank}{Colors.RESET}")
            print(f"  Strength: {self_result['strength']:.3f}")
        else:
            print(f"{Colors.BRIGHT_RED}✗ NOT self-retrieved (not in top 10){Colors.RESET}")

        # 6. Show top 5 results with detailed scores
        print(f"\n{Colors.BRIGHT_CYAN}TOP 5 RETRIEVED MEMORIES:{Colors.RESET}")
        for i, result in enumerate(results[:5], 1):
            is_self = " ← SOURCE MEMORY" if result['id'] == memory['id'] else ""
            print(f"\n{i}. ID {result['id']} | {result['category']}{is_self}")
            print(f"   Takeaway: {result['takeaway'][:100]}...")
            print(f"   {Colors.YELLOW}Overall Strength: {result['strength']:.3f}{Colors.RESET}")
            print(f"   Breakdown:")
            print(f"     Semantic:  {result['semantic_similarity']:.3f} × {WEIGHTS['semantic']:.2f} = {result['semantic_similarity'] * WEIGHTS['semantic']:.3f}")
            print(f"     Emotional: {result['emotional_resonance']:.3f} × {WEIGHTS['emotional']:.2f} = {result['emotional_resonance'] * WEIGHTS['emotional']:.3f}")
            print(f"     Recency:   {result['recency']:.3f} × {WEIGHTS['recency']:.2f} = {result['recency'] * WEIGHTS['recency']:.3f}")
            print(f"     Frequency: {result['frequency']:.3f} × {WEIGHTS['frequency']:.2f} = {result['frequency'] * WEIGHTS['frequency']:.3f}")
            print(f"     Intensity: {result['intensity']:.3f} × {WEIGHTS['intensity']:.2f} = {result['intensity'] * WEIGHTS['intensity']:.3f}")

        # 7. Analysis
        print(f"\n{Colors.BRIGHT_YELLOW}ANALYSIS:{Colors.RESET}")

        if memory['id'] not in retrieved_ids:
            print("Why did this memory fail to retrieve itself?")

            # Check semantic similarity
            if results:
                top_semantic = results[0]['semantic_similarity']
                print(f"\n1. Semantic Issue?")
                print(f"   Top result has semantic similarity: {top_semantic:.3f}")
                print(f"   If source memory has low semantic match to its own transcript,")
                print(f"   this suggests embedding quality issues.")

            # Check emotional resonance
            if resonance < 0.5:
                print(f"\n2. Emotional Issue?")
                print(f"   Emotional resonance: {resonance:.3f} (LOW)")
                print(f"   Stored emotion: {memory['emotion_label']} (v={memory_emotion['valence']:.2f}, a={memory_emotion['arousal']:.2f})")
                print(f"   Query emotion: {query_emotion['emotion_label']} (v={query_emotion['valence']:.2f}, a={query_emotion['arousal']:.2f})")
                print(f"   Emotions don't match - emotion scoring may be inconsistent.")

            # Check if below similarity threshold
            print(f"\n3. Check if memory was filtered out:")
            print(f"   Minimum similarity threshold: 0.15")
            print(f"   Run manual query to see if memory appears at all...")

        return memory, results

    def close(self):
        self.cur.close()
        self.conn.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Diagnose failing memory retrieval')
    parser.add_argument('--memory-id', type=int, help='Specific memory ID to diagnose')
    parser.add_argument('--category', type=str, help='Find failing memories in this category')
    parser.add_argument('--list-failing', action='store_true', help='List all failing memories by category')

    args = parser.parse_args()

    diag = MemoryDiagnostic()

    try:
        if args.memory_id:
            # Diagnose specific memory
            diag.diagnose_memory(args.memory_id)

        elif args.category:
            # Find failing memories in category
            print(f"Finding failing {args.category} memories...")
            failing = diag.get_failing_memories_by_category(args.category, limit=10)

            print(f"\n{Colors.BRIGHT_RED}Found {len(failing)} failing memories:{Colors.RESET}")
            for mem in failing:
                print(f"  ID {mem['id']}: {mem['takeaway'][:80]}...")

            if failing:
                print(f"\n{Colors.BRIGHT_CYAN}Diagnosing first failing memory...{Colors.RESET}")
                diag.diagnose_memory(failing[0]['id'])

        elif args.list_failing:
            # List failing counts by category
            test_set_path = os.path.join(os.path.dirname(__file__), 'test_set.json')
            with open(test_set_path, 'r') as f:
                test_set = json.load(f)

            categories = set(m['category'] for m in test_set['memories'])

            print(f"\n{Colors.BRIGHT_CYAN}Failing memory counts by category:{Colors.RESET}\n")

            for cat in sorted(categories):
                failing = diag.get_failing_memories_by_category(cat, limit=100)
                cat_total = len([m for m in test_set['memories'] if m['category'] == cat])
                rate = (len(failing) / cat_total * 100) if cat_total else 0
                print(f"{cat}: {len(failing)}/{cat_total} failing ({rate:.0f}%)")

        else:
            print("Usage:")
            print("  --memory-id 12345       Diagnose specific memory")
            print("  --category Creative     Find failing memories in category")
            print("  --list-failing          List failing counts by category")

    finally:
        diag.close()
