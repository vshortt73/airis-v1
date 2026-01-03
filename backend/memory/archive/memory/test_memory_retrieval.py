"""
Memory Retrieval Testing Framework
Tests the accuracy of memory retrieval system with realistic conversations

Usage:
    python test_memory_retrieval.py --test-suite basic
    python test_memory_retrieval.py --test-suite all
    python test_memory_retrieval.py --compare-weights
"""

import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, PROJECT_ROOT)

import psycopg2
from psycopg2.extras import DictCursor
import json
from typing import List, Dict, Tuple
from datetime import datetime, timedelta
import argparse
from sentence_transformers import SentenceTransformer
from Colors import Colors

# ============================================
# DATABASE CONFIG
# ============================================
DB_CFG = dict(dbname="irisdb", user="irisuser", password="yourpassword", host="localhost", port=5432)

# ============================================
# TEST CONVERSATIONS
# ============================================

TEST_CONVERSATIONS = [
    {
        "id": "technical_python_1",
        "conversation": """
USER: Hey Iris, I'm having trouble with async/await in Python. My code keeps hanging.
ASSISTANT: I'd be happy to help with async/await! Can you share what you're trying to do?
USER: I'm trying to fetch data from multiple APIs concurrently, but sometimes it just stops responding.
ASSISTANT: That sounds like you might have a blocking call inside your async function. Are you using requests or httpx?
USER: I'm using requests.
ASSISTANT: Ah, that's the issue! The requests library is synchronous and will block the event loop. You need to use httpx with async/await, or use asyncio.run_in_executor with requests. Here's an example with httpx:

```python
import httpx
import asyncio

async def fetch_data(url):
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        return response.json()

async def main():
    urls = ['https://api1.com', 'https://api2.com']
    tasks = [fetch_data(url) for url in urls]
    results = await asyncio.gather(*tasks)
    return results
```

USER: Oh! That makes perfect sense. So requests blocks the entire event loop?
ASSISTANT: Exactly! The requests library uses blocking I/O, which defeats the purpose of async. Always use async-compatible libraries like httpx or aiohttp with asyncio.
USER: Thank you! That was the missing piece. I'll switch to httpx.
        """,
        "expected_memory_categories": ["Technical", "Learning", "Practical"],
        "expected_emotions": ["curiosity", "gratitude", "learning"],
        "key_concepts": ["python", "async", "asyncio", "httpx", "blocking", "event loop", "api"],
        "description": "Technical troubleshooting conversation about Python async/await"
    },

    {
        "id": "personal_preference_1",
        "conversation": """
USER: I absolutely love listening to jazz while coding. There's something about the improvisation that helps me think.
ASSISTANT: That's beautiful! The structured chaos of jazz really does mirror the creative problem-solving in coding. Do you have favorite artists?
USER: Miles Davis and John Coltrane are my go-to. Kind of Blue is my most played album.
ASSISTANT: Kind of Blue is a masterpiece - the modal jazz approach gives it such a meditative quality. Perfect for deep focus work.
USER: Exactly! The repetitive modal structures keep me focused without being distracting. When I need intense concentration, that's what I put on.
        """,
        "expected_memory_categories": ["Personal", "Relational"],
        "expected_emotions": ["joy", "enthusiasm", "connection"],
        "key_concepts": ["music", "jazz", "coding", "miles davis", "coltrane", "preferences", "focus"],
        "description": "Personal preference about music and work habits"
    },

    {
        "id": "emotional_frustration_1",
        "conversation": """
USER: I'm so frustrated right now. I've been debugging this issue for 6 hours and I can't figure it out.
ASSISTANT: I can hear how exhausted you are. Six hours on one bug is brutal. Want to walk me through what's happening? Sometimes explaining it helps.
USER: It's a race condition that only appears in production, never locally. The logs don't show anything useful.
ASSISTANT: Race conditions are the worst to debug, especially production-only ones. Have you tried adding more granular logging around the suspected critical section?
USER: I added logs everywhere but by the time they write, the state has already changed. It's like trying to observe a quantum particle.
ASSISTANT: That's a great analogy - and it points to the solution. You might need to use a proper debugging tool that can snapshot state without the observer effect. Have you considered distributed tracing or using a tool like py-spy for production profiling?
USER: I haven't tried distributed tracing. That might actually work. Thanks for talking me through this - I was about to give up.
        """,
        "expected_memory_categories": ["Technical", "Emotional", "Relational"],
        "expected_emotions": ["frustration", "exhaustion", "relief", "gratitude"],
        "key_concepts": ["debugging", "race condition", "production", "distributed tracing", "support"],
        "description": "Emotional support during technical difficulty"
    },

    {
        "id": "creative_project_1",
        "conversation": """
USER: I've been thinking about building a text-based RPG game in Python as a side project.
ASSISTANT: That sounds like a fun creative project! Are you thinking classic dungeon crawler or something more narrative-driven?
USER: More narrative-driven, like old-school interactive fiction but with some combat mechanics. I want meaningful choices that affect the story.
ASSISTANT: That's ambitious in the best way! For branching narratives, you might want to look into state machines or a dialogue tree system. Have you thought about how you'll handle save states?
USER: Not really. I was just going to pickle the game state.
ASSISTANT: Pickle works for prototypes, but for a real game you'd want JSON or SQLite so players can read/edit saves if needed. Plus it's more portable. You could have a GameState class that serializes to JSON.
USER: Good point. I like the idea of human-readable saves. I'll design a proper state system from the start.
        """,
        "expected_memory_categories": ["Creative", "Technical", "Learning"],
        "expected_emotions": ["excitement", "curiosity", "planning"],
        "key_concepts": ["game development", "rpg", "python", "narrative", "architecture", "state management"],
        "description": "Creative project planning and technical architecture discussion"
    },

    {
        "id": "learning_concept_1",
        "conversation": """
USER: Can you explain what a monad is? I keep seeing it in functional programming but the explanations are always confusing.
ASSISTANT: Monads are famously difficult to explain! Let me try a practical approach: a monad is basically a design pattern for chaining operations while managing context or side effects. Think of it like a pipeline with special handling.
USER: Okay, context and side effects. Can you give me a concrete example?
ASSISTANT: Sure! The Maybe monad (Option in some languages) handles the context of "this value might not exist". Instead of checking for null everywhere, you chain operations and the monad handles the null-checking automatically.

```python
# Without monad
user = get_user(id)
if user is not None:
    address = user.get_address()
    if address is not None:
        city = address.get_city()
        return city
return None

# With Maybe monad
return (get_user(id)
    .map(lambda u: u.get_address())
    .map(lambda a: a.get_city())
    .or_else(None))
```

USER: Oh! So it's like error handling but generalized?
ASSISTANT: Exactly! A monad is a container that lets you chain operations (with map/flatMap) while managing some kind of context - whether that's null-checking, error handling, async operations, state management, etc.
USER: That actually makes sense now. The "burrito" analogies never helped, but seeing it as error handling I understand.
        """,
        "expected_memory_categories": ["Learning", "Technical"],
        "expected_emotions": ["curiosity", "confusion", "understanding"],
        "key_concepts": ["monad", "functional programming", "maybe monad", "pattern", "error handling"],
        "description": "Learning a complex programming concept"
    },

    {
        "id": "routine_greeting_1",
        "conversation": """
USER: Hey Iris, how's it going?
ASSISTANT: Hey! I'm doing well, thanks for asking. How are you?
USER: Pretty good, just checking in.
ASSISTANT: Good to hear! Let me know if you need anything.
        """,
        "expected_memory_categories": [],  # Should NOT be memorable
        "expected_emotions": ["neutral"],
        "key_concepts": [],
        "description": "Simple greeting - should not create memory"
    },

    {
        "id": "project_planning_1",
        "conversation": """
USER: I need to plan out the architecture for a real-time collaborative document editor.
ASSISTANT: That's a fascinating challenge! Real-time collaboration has some complex problems to solve - mainly around conflict resolution. Are you familiar with CRDTs or Operational Transformation?
USER: I've heard of OT from reading about Google Docs, but not CRDTs.
ASSISTANT: CRDTs (Conflict-free Replicated Data Types) are amazing for this. Unlike OT which requires a central server to order operations, CRDTs are designed to merge concurrent edits automatically. Yjs is a great CRDT library for JavaScript.
USER: So with CRDT, I don't need a central authority to resolve conflicts?
ASSISTANT: Correct! Each client can make changes independently and the CRDT math guarantees they'll converge to the same state. For a document editor, you'd use a CRDT that models text - like a RGA tree or Yjs's Y.Text.
USER: That's perfect. I want to support offline editing and sync later, so CRDT sounds ideal.
ASSISTANT: Exactly the right use case! With CRDT, users can edit offline, and when they reconnect, all the changes merge automatically. No complex server-side conflict resolution needed.
USER: Awesome. I'll prototype with Yjs and see how it feels.
        """,
        "expected_memory_categories": ["Technical", "Planning", "Learning"],
        "expected_emotions": ["curiosity", "planning", "learning"],
        "key_concepts": ["crdt", "collaborative editing", "real-time", "yjs", "architecture", "offline"],
        "description": "Architecture planning for complex technical project"
    },

    {
        "id": "memory_reference_1",
        "conversation": """
USER: Remember when we talked about async/await and httpx? I implemented it and it works great!
ASSISTANT: That's wonderful! I remember you were having issues with requests blocking the event loop. How much faster is it now?
USER: About 10x faster for my API calls. The concurrent fetching makes a huge difference.
ASSISTANT: That's a significant improvement! And you're using httpx.AsyncClient like we discussed?
USER: Yes, exactly. Thanks for that advice - it completely solved the problem.
        """,
        "expected_memory_categories": ["Technical", "Relational", "Followup"],
        "expected_emotions": ["gratitude", "success", "satisfaction"],
        "key_concepts": ["async", "httpx", "callback", "improvement", "success"],
        "description": "Callback to previous technical discussion - should retrieve technical_python_1 memory"
    }
]

# ============================================
# TEST MEMORIES (Pre-seeded for testing)
# ============================================

TEST_MEMORIES = [
    {
        "id": "mem_async_python",
        "transcript": "Discussion about Python async/await and the importance of using async-compatible libraries like httpx instead of blocking libraries like requests.",
        "summary_context": "Technical discussion about Python asynchronous programming and common pitfalls.",
        "summary_event": "User struggled with blocking I/O in async code and learned to use httpx for async HTTP requests.",
        "summary_significance": "Understanding the event loop and async-compatible libraries is crucial for effective async programming.",
        "takeaway": "Always use async-compatible libraries (httpx, aiohttp) with asyncio - blocking libraries like requests defeat the purpose of async.",
        "category": "Technical",
        "voice": "technical",
        "emotion_label": "curiosity",
        "valence": 0.6,
        "arousal": 0.5,
        "recurrence": 0.3,
        "novelty": 0.7,
        "cohesion": 0.8,
        "age_days": 15
    },
    {
        "id": "mem_music_jazz",
        "transcript": "User loves listening to jazz (Miles Davis, John Coltrane, especially Kind of Blue) while coding for deep focus.",
        "summary_context": "Personal preferences about music and work environment.",
        "summary_event": "User shared their love of jazz music, particularly modal jazz like Kind of Blue, for coding focus.",
        "summary_significance": "Music preferences reveal how the user achieves deep focus and creative flow states.",
        "takeaway": "User uses modal jazz (Miles Davis, Coltrane) for deep focus while coding - the structured improvisation helps concentration.",
        "category": "Personal",
        "voice": "conversational",
        "emotion_label": "joy",
        "valence": 0.8,
        "arousal": 0.4,
        "recurrence": 0.2,
        "novelty": 0.5,
        "cohesion": 0.7,
        "age_days": 7
    },
    {
        "id": "mem_race_condition_debugging",
        "transcript": "User spent 6 hours debugging a production-only race condition. Discussed using distributed tracing and py-spy for production debugging.",
        "summary_context": "Emotional support during difficult technical debugging session.",
        "summary_event": "User was frustrated debugging an elusive race condition and received both emotional support and technical guidance about distributed tracing.",
        "summary_significance": "Production debugging is emotionally taxing; distributed tracing tools help with observer-effect problems in concurrent systems.",
        "takeaway": "For production-only race conditions, use distributed tracing or py-spy to avoid observer effect - traditional logging can miss concurrent state changes.",
        "category": "Technical",
        "voice": "supportive",
        "emotion_label": "frustration",
        "valence": -0.4,
        "arousal": 0.8,
        "recurrence": 0.4,
        "novelty": 0.6,
        "cohesion": 0.7,
        "age_days": 3
    },
    {
        "id": "mem_rpg_game_project",
        "transcript": "User planning narrative-driven text RPG in Python with meaningful player choices and proper state management using JSON saves.",
        "summary_context": "Creative project planning for game development.",
        "summary_event": "User designing a narrative-driven RPG and discussing architecture decisions like state serialization and save systems.",
        "summary_significance": "Creative projects benefit from upfront architectural planning, especially for state management in complex systems.",
        "takeaway": "For game save states, use JSON or SQLite instead of pickle for portability and human-readable saves that players can modify.",
        "category": "Creative",
        "voice": "encouraging",
        "emotion_label": "excitement",
        "valence": 0.7,
        "arousal": 0.6,
        "recurrence": 0.2,
        "novelty": 0.8,
        "cohesion": 0.6,
        "age_days": 30
    },
    {
        "id": "mem_monad_explanation",
        "transcript": "Explained monads as a design pattern for chaining operations with context management, using Maybe monad as concrete example.",
        "summary_context": "Teaching session about functional programming concepts.",
        "summary_event": "User finally understood monads through a practical error-handling analogy instead of abstract category theory.",
        "summary_significance": "Abstract concepts are best taught through concrete examples and familiar analogies (error handling, pipelines).",
        "takeaway": "Monads are containers that let you chain operations while managing context (null-checking, errors, async, state) - think error handling generalized.",
        "category": "Learning",
        "voice": "educational",
        "emotion_label": "understanding",
        "valence": 0.6,
        "arousal": 0.5,
        "recurrence": 0.3,
        "novelty": 0.7,
        "cohesion": 0.8,
        "age_days": 45
    },
    {
        "id": "mem_crdt_architecture",
        "transcript": "Discussed CRDT (Conflict-free Replicated Data Types) for collaborative document editor with offline support using Yjs.",
        "summary_context": "Architecture planning for distributed systems.",
        "summary_event": "User learned about CRDTs as an alternative to Operational Transformation for conflict-free collaborative editing.",
        "summary_significance": "CRDTs enable offline-first collaborative editing without central authority for conflict resolution.",
        "takeaway": "For collaborative editors with offline support, use CRDTs (like Yjs) instead of OT - they converge automatically without central server.",
        "category": "Technical",
        "voice": "technical",
        "emotion_label": "curiosity",
        "valence": 0.5,
        "arousal": 0.5,
        "recurrence": 0.2,
        "novelty": 0.9,
        "cohesion": 0.7,
        "age_days": 60
    },
    {
        "id": "mem_database_indexing",
        "transcript": "Discussed PostgreSQL indexing strategies for query optimization - B-tree vs GiST indexes and composite indexes for frequently joined columns.",
        "summary_context": "Database performance optimization discussion.",
        "summary_event": "User learned about proper indexing strategies and using EXPLAIN ANALYZE to identify slow queries.",
        "summary_significance": "Proper indexing can improve query performance by 10-100x and is critical for application scaling.",
        "takeaway": "Use EXPLAIN ANALYZE to identify slow queries, then add composite indexes on JOIN and WHERE columns - B-tree for equality, GiST for ranges.",
        "category": "Technical",
        "voice": "technical",
        "emotion_label": "learning",
        "valence": 0.4,
        "arousal": 0.3,
        "recurrence": 0.5,
        "novelty": 0.6,
        "cohesion": 0.8,
        "age_days": 90
    }
]

# ============================================
# TESTING FRAMEWORK
# ============================================

class MemoryRetrievalTester:
    """Test framework for memory retrieval accuracy"""

    def __init__(self, db_config):
        self.db_config = db_config
        self.model = SentenceTransformer("/models/llm_models/huggingface/models/all-mpnet-base-v2/", local_files_only=True)
        self.test_memories = TEST_MEMORIES
        self.test_conversations = TEST_CONVERSATIONS

    def setup_test_environment(self):
        """Create test memories in a test schema"""
        print(f"\n{Colors.BRIGHT_CYAN}{'='*60}")
        print("SETTING UP TEST ENVIRONMENT")
        print(f"{'='*60}{Colors.RESET}\n")

        # Here we would insert test memories into a test table
        # For now, we'll just verify they're properly structured
        print(f"✓ Loaded {len(self.test_memories)} test memories")
        print(f"✓ Loaded {len(self.test_conversations)} test conversations")

    def generate_query_embeddings(self, conversation: str) -> Dict:
        """Generate embeddings from a conversation (simplified for testing)"""
        # In production, this would go through lens stage + summarization
        # For testing, we'll use the conversation directly
        embeddings = {
            "context": self.model.encode(conversation).tolist(),
            "event": self.model.encode(conversation).tolist(),
            "significance": self.model.encode(conversation).tolist(),
            "takeaway": self.model.encode(conversation).tolist(),
        }
        return embeddings

    def calculate_similarity(self, emb1: List[float], emb2: List[float]) -> float:
        """Calculate cosine similarity between two embeddings"""
        import numpy as np
        emb1_arr = np.array(emb1)
        emb2_arr = np.array(emb2)

        dot_product = np.dot(emb1_arr, emb2_arr)
        norm1 = np.linalg.norm(emb1_arr)
        norm2 = np.linalg.norm(emb2_arr)

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return float(dot_product / (norm1 * norm2))

    def test_retrieval(self, conversation_id: str, top_k: int = 5) -> Dict:
        """Test retrieval for a specific conversation"""
        # Find test conversation
        test_conv = next((c for c in self.test_conversations if c["id"] == conversation_id), None)
        if not test_conv:
            print(f"❌ Conversation {conversation_id} not found")
            return None

        print(f"\n{Colors.BRIGHT_YELLOW}{'='*60}")
        print(f"TESTING: {test_conv['description']}")
        print(f"{'='*60}{Colors.RESET}")
        print(f"\n{Colors.CYAN}Query Conversation:{Colors.RESET}")
        print(test_conv['conversation'][:200] + "..." if len(test_conv['conversation']) > 200 else test_conv['conversation'])

        # Generate query embeddings
        query_emb = self.generate_query_embeddings(test_conv['conversation'])

        # Calculate similarities to all test memories
        results = []
        for mem in self.test_memories:
            # Generate memory embeddings
            mem_context_emb = self.model.encode(mem['summary_context']).tolist()
            mem_event_emb = self.model.encode(mem['summary_event']).tolist()
            mem_sig_emb = self.model.encode(mem['summary_significance']).tolist()
            mem_take_emb = self.model.encode(mem['takeaway']).tolist()

            # Calculate weighted similarity (using current weights)
            sim_context = self.calculate_similarity(query_emb['context'], mem_context_emb)
            sim_event = self.calculate_similarity(query_emb['event'], mem_event_emb)
            sim_sig = self.calculate_similarity(query_emb['significance'], mem_sig_emb)
            sim_take = self.calculate_similarity(query_emb['takeaway'], mem_take_emb)

            # Updated weights (matching iris_memory_retrieval.py)
            weighted_sim = (
                0.25 * sim_context +
                0.25 * sim_event +
                0.25 * sim_sig +
                0.25 * sim_take
            )

            results.append({
                'memory_id': mem['id'],
                'takeaway': mem['takeaway'],
                'category': mem['category'],
                'similarity': weighted_sim,
                'sim_breakdown': {
                    'context': sim_context,
                    'event': sim_event,
                    'significance': sim_sig,
                    'takeaway': sim_take
                }
            })

        # Sort by similarity
        results.sort(key=lambda x: x['similarity'], reverse=True)

        # Display results
        print(f"\n{Colors.BRIGHT_GREEN}Top {top_k} Retrieved Memories:{Colors.RESET}\n")
        for i, result in enumerate(results[:top_k], 1):
            print(f"{Colors.WHITE}{i}. {result['memory_id']}{Colors.RESET}")
            print(f"   Category: {result['category']}")
            print(f"   Overall Similarity: {result['similarity']:.3f}")
            print(f"   Breakdown: ctx={result['sim_breakdown']['context']:.3f} "
                  f"evt={result['sim_breakdown']['event']:.3f} "
                  f"sig={result['sim_breakdown']['significance']:.3f} "
                  f"take={result['sim_breakdown']['takeaway']:.3f}")
            print(f"   Takeaway: {result['takeaway'][:100]}...")
            print()

        # Check if expected memories were retrieved
        expected_categories = test_conv.get('expected_memory_categories', [])
        retrieved_categories = [r['category'] for r in results[:top_k]]

        print(f"{Colors.BRIGHT_MAGENTA}Expected Categories:{Colors.RESET} {expected_categories}")
        print(f"{Colors.BRIGHT_MAGENTA}Retrieved Categories:{Colors.RESET} {retrieved_categories}")

        category_matches = sum(1 for cat in expected_categories if cat in retrieved_categories)
        if expected_categories:
            accuracy = category_matches / len(expected_categories)
            print(f"{Colors.BRIGHT_CYAN}Category Match Rate: {accuracy:.1%}{Colors.RESET}\n")

        return {
            'conversation_id': conversation_id,
            'results': results[:top_k],
            'expected_categories': expected_categories,
            'retrieved_categories': retrieved_categories
        }

    def run_test_suite(self, suite_name: str = "basic"):
        """Run a suite of tests"""
        print(f"\n{Colors.BRIGHT_CYAN}{'='*60}")
        print(f"RUNNING TEST SUITE: {suite_name.upper()}")
        print(f"{'='*60}{Colors.RESET}\n")

        if suite_name == "basic":
            test_ids = ["technical_python_1", "personal_preference_1", "memory_reference_1"]
        elif suite_name == "all":
            test_ids = [c['id'] for c in self.test_conversations]
        else:
            test_ids = [suite_name]

        results = []
        for test_id in test_ids:
            result = self.test_retrieval(test_id)
            if result:
                results.append(result)

        # Summary
        print(f"\n{Colors.BRIGHT_GREEN}{'='*60}")
        print("TEST SUITE SUMMARY")
        print(f"{'='*60}{Colors.RESET}\n")
        print(f"Tests run: {len(results)}")
        print(f"Conversations tested: {', '.join([r['conversation_id'] for r in results])}")

        return results

# ============================================
# MAIN
# ============================================

def main():
    parser = argparse.ArgumentParser(description='Test memory retrieval system')
    parser.add_argument('--test-suite', default='basic',
                       help='Test suite to run: basic, all, or specific conversation ID')
    parser.add_argument('--top-k', type=int, default=5,
                       help='Number of memories to retrieve')

    args = parser.parse_args()

    tester = MemoryRetrievalTester(DB_CFG)
    tester.setup_test_environment()
    tester.run_test_suite(args.test_suite)

if __name__ == "__main__":
    main()
