"""
Systematic threshold testing across multiple conversation types
Tests thresholds: 0.15, 0.20, 0.25, 0.30
Helps determine optimal threshold empirically
"""

import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, PROJECT_ROOT)

from sentence_transformers import SentenceTransformer
import psycopg2
from psycopg2.extras import DictCursor
import numpy as np
from Colors import Colors

DB_CFG = dict(dbname="irisdb", user="irisuser", password="yourpassword", host="localhost", port=5432)

# Test conversations covering different topics
TEST_SCENARIOS = [
    {
        "name": "Cruise/Travel",
        "conversation": """
USER: I'm thinking about booking a cruise to Mexico.
ASSISTANT: That sounds exciting! Mexican Riviera or Baja?
USER: Looking at Cabo and Puerto Vallarta. It's my first cruise.
ASSISTANT: First cruises can be nerve-wracking! The waters are usually calm there.
USER: Good to know. What about excursions?
ASSISTANT: Book through the cruise line for peace of mind, especially first time.
""",
        "expected_keywords": ["cruise", "mexico", "cozumel", "travel", "vacation", "beach"],
        "expect_results": True
    },

    {
        "name": "Technical/Programming",
        "conversation": """
USER: I'm having issues with Python async/await. My code keeps hanging.
ASSISTANT: Can you share what you're trying to do?
USER: Fetching data from multiple APIs concurrently.
ASSISTANT: Are you using requests or httpx?
USER: Using requests library.
ASSISTANT: That's the issue - requests is synchronous and blocks the event loop. Use httpx for async.
""",
        "expected_keywords": ["python", "async", "programming", "httpx", "api", "technical"],
        "expect_results": True
    },

    {
        "name": "Food/Dining",
        "conversation": """
USER: We should try that new Mexican restaurant tonight.
ASSISTANT: The one with the amazing fish tacos you mentioned?
USER: Yeah! I heard they have great margaritas too.
ASSISTANT: Perfect! What time were you thinking?
USER: Maybe around 7pm? I'm craving their guacamole.
""",
        "expected_keywords": ["restaurant", "mexican food", "tacos", "dining", "food"],
        "expect_results": True
    },

    {
        "name": "Weather/Local",
        "conversation": """
USER: What's the weather looking like this weekend in Oklahoma?
ASSISTANT: Let me check the forecast for you.
USER: I'm hoping to go to the lake if it's nice.
ASSISTANT: Looks like sunny and 85 degrees on Saturday!
USER: Perfect swimming weather.
""",
        "expected_keywords": ["weather", "oklahoma", "lake", "swimming", "local"],
        "expect_results": True
    },

    {
        "name": "Greeting/Small Talk",
        "conversation": """
USER: Hey Iris, good morning!
ASSISTANT: Good morning! How are you today?
USER: Doing well, thanks. How about you?
ASSISTANT: I'm great! Ready to help with whatever you need.
USER: Awesome, thanks!
""",
        "expected_keywords": ["greeting", "small talk"],
        "expect_results": False  # Should NOT retrieve much for pure greetings
    },

    {
        "name": "Image/Creative",
        "conversation": """
USER: Can you help me design an image of a futuristic robot?
ASSISTANT: Sure! What kind of aesthetic are you going for?
USER: Something sleek and feminine, maybe with glowing accents.
ASSISTANT: I can create that. Any specific pose or setting?
USER: Standing confidently, maybe in a tech lab environment.
""",
        "expected_keywords": ["image", "design", "robot", "creative", "visual"],
        "expect_results": True
    },

    {
        "name": "Personal/Emotional",
        "conversation": """
USER: I'm feeling really stressed about this project deadline.
ASSISTANT: I can hear that in your message. What's weighing on you most?
USER: Just feels like too much to finish in time.
ASSISTANT: Let's break it down into smaller pieces. What needs to happen first?
USER: Good idea. I think I need to finish the documentation.
ASSISTANT: That's manageable. One step at a time.
""",
        "expected_keywords": ["stress", "emotional", "support", "project", "deadline"],
        "expect_results": True
    }
]


class ThresholdTester:
    def __init__(self):
        self.model = SentenceTransformer("/models/llm_models/huggingface/models/all-mpnet-base-v2/", local_files_only=True)
        self.thresholds = [0.15, 0.20, 0.25, 0.30]

    def retrieve_with_threshold(self, conversation: str, threshold: float, top_k: int = 10):
        """Retrieve memories with a specific threshold"""
        # Generate embedding
        query_emb = self.model.encode(conversation).tolist()

        # Query database
        conn = psycopg2.connect(**DB_CFG)
        cur = conn.cursor(cursor_factory=DictCursor)

        cur.execute("""
            SELECT
                id,
                takeaway,
                summary_context,
                category,
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

    def test_scenario(self, scenario: dict):
        """Test one scenario across all thresholds"""
        print(f"\n{Colors.BRIGHT_CYAN}{'='*80}")
        print(f"SCENARIO: {scenario['name']}")
        print(f"{'='*80}{Colors.RESET}")
        print(f"\n{Colors.YELLOW}Conversation:{Colors.RESET}")
        print(scenario['conversation'][:200] + "...")
        print(f"\n{Colors.YELLOW}Expected keywords:{Colors.RESET} {', '.join(scenario['expected_keywords'])}")
        print(f"{Colors.YELLOW}Should find memories?{Colors.RESET} {scenario['expect_results']}\n")

        results_by_threshold = {}

        for threshold in self.thresholds:
            memories = self.retrieve_with_threshold(scenario['conversation'], threshold, top_k=5)
            results_by_threshold[threshold] = memories

            print(f"{Colors.BRIGHT_GREEN}Threshold {threshold:.2f}: {len(memories)} memories retrieved{Colors.RESET}")

            if len(memories) > 0:
                print(f"  Top similarity: {memories[0]['similarity']:.3f}")
                print(f"  Categories: {', '.join(set(m['category'] for m in memories[:3]))}")
                print(f"  Sample: {memories[0]['takeaway'][:80]}...")
            else:
                print(f"  No memories above threshold")
            print()

        return results_by_threshold

    def run_all_tests(self):
        """Run all test scenarios and compile report"""
        print(f"\n{Colors.BRIGHT_MAGENTA}{'='*80}")
        print("THRESHOLD TUNING TEST SUITE")
        print(f"Testing thresholds: {self.thresholds}")
        print(f"{'='*80}{Colors.RESET}\n")

        all_results = {}

        for scenario in TEST_SCENARIOS:
            results = self.test_scenario(scenario)
            all_results[scenario['name']] = {
                'scenario': scenario,
                'results': results
            }

        # Summary report
        self.print_summary(all_results)

    def print_summary(self, all_results):
        """Print comprehensive summary comparing thresholds"""
        print(f"\n{Colors.BRIGHT_MAGENTA}{'='*80}")
        print("SUMMARY COMPARISON")
        print(f"{'='*80}{Colors.RESET}\n")

        # Create comparison table
        print(f"{'Scenario':<25} | {'0.15':<10} | {'0.20':<10} | {'0.25':<10} | {'0.30':<10}")
        print("-" * 80)

        for name, data in all_results.items():
            scenario = data['scenario']
            results = data['results']

            counts = []
            for threshold in self.thresholds:
                count = len(results[threshold])
                counts.append(f"{count:>2} mems")

            expectation = "✓ expect" if scenario['expect_results'] else "✗ none"
            print(f"{name:<25} | {counts[0]:<10} | {counts[1]:<10} | {counts[2]:<10} | {counts[3]:<10} ({expectation})")

        print("\n" + "="*80)

        # Analysis
        print(f"\n{Colors.BRIGHT_YELLOW}ANALYSIS:{Colors.RESET}\n")

        for threshold in self.thresholds:
            print(f"\n{Colors.BRIGHT_GREEN}Threshold {threshold:.2f}:{Colors.RESET}")

            # Count how many scenarios got results when expected
            got_results_when_expected = 0
            got_nothing_when_expected_nothing = 0
            false_positives = 0
            false_negatives = 0

            for name, data in all_results.items():
                scenario = data['scenario']
                count = len(data['results'][threshold])

                if scenario['expect_results'] and count > 0:
                    got_results_when_expected += 1
                elif scenario['expect_results'] and count == 0:
                    false_negatives += 1
                elif not scenario['expect_results'] and count == 0:
                    got_nothing_when_expected_nothing += 1
                elif not scenario['expect_results'] and count > 0:
                    false_positives += 1

            total_expect_results = sum(1 for _, d in all_results.items() if d['scenario']['expect_results'])
            total_expect_none = sum(1 for _, d in all_results.items() if not d['scenario']['expect_results'])

            print(f"  Successes (found when expected): {got_results_when_expected}/{total_expect_results}")
            print(f"  Correctly empty: {got_nothing_when_expected_nothing}/{total_expect_none}")
            print(f"  False positives (found when shouldn't): {false_positives}")
            print(f"  False negatives (missed when should find): {false_negatives}")

            # Calculate score
            total_scenarios = len(all_results)
            accuracy = (got_results_when_expected + got_nothing_when_expected_nothing) / total_scenarios
            print(f"  {Colors.BRIGHT_CYAN}Overall accuracy: {accuracy:.1%}{Colors.RESET}")


if __name__ == "__main__":
    tester = ThresholdTester()
    tester.run_all_tests()
