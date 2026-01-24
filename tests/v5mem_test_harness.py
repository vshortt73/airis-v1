"""
V5 Memory System - FAST TOPIC-AWARE SEARCH (USING REAL INFRASTRUCTURE)

Uses Iris's existing memory system properly:
- fetch_memory_candidates() function (pre-computed embeddings + HNSW index)
- Topic detection + query generation (LLM)
- Fast vector search on existing infrastructure

Goal: <2 seconds total (vs 25-30s deep search)
"""

import psycopg2
import requests
import json
import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from sentence_transformers import SentenceTransformer


class OllamaClient:
    """Interface to local Ollama instance with SentenceTransformer for embeddings"""
    
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "qwen2.5:32b"):
        self.base_url = base_url
        self.model = model
        # Use SentenceTransformer for embeddings (matches database emb_minilm)
        print("  Loading SentenceTransformer model (all-mpnet-base-v2)...")
        self.embedder = SentenceTransformer("all-mpnet-base-v2")
        print("  ✓ Embedder loaded")
    
    def generate(self, prompt: str, temperature: float = 0.3) -> str:
        """Generate text using Ollama"""
        url = f"{self.base_url}/api/generate"
        
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature}
        }
        
        try:
            response = requests.post(url, json=payload, timeout=120)
            response.raise_for_status()
            result = response.json()
            return result.get('response', '').strip()
        except requests.exceptions.RequestException as e:
            print(f"Ollama error: {e}")
            return ""
    
    def embed(self, text: str) -> List[float]:
        """Generate embedding using SentenceTransformer (768 dims, matches database)"""
        return self.embedder.encode(text, normalize_embeddings=True).tolist()


class ConversationAnalyzer:
    """Analyze conversation context to detect topics and generate search queries"""
    
    def __init__(self, llm: OllamaClient):
        self.llm = llm
    
    def detect_conversation_topics(self, conversation_turns: List[str]) -> List[str]:
        """Analyze conversation to detect what they're talking about"""
        
        conversation_text = "\n".join(conversation_turns)
        
        prompt = f"""Analyze this conversation and identify the main topics being discussed.

Conversation:
{conversation_text}

Extract 5-10 specific topic keywords or short phrases that capture what they're talking about.
Use technical terms when relevant. Use underscores for multi-word topics.

Examples:
- If discussing flexible 3D printing: ["flexible_printing", "sla_resin", "tpu", "elastomeric_materials"]
- If discussing GPIO circuits: ["gpio_control", "relay_driver", "logic_level", "microcontroller"]

Return ONLY a JSON array of topic strings:
["topic1", "topic2", "topic3"]"""

        response = self.llm.generate(prompt, temperature=0.3)
        
        try:
            cleaned = response.strip()
            
            # Try to extract JSON array from response
            # Look for ["..."] pattern
            import re
            json_match = re.search(r'\[[\s\S]*?\]', cleaned)
            if json_match:
                json_str = json_match.group(0)
                topics = json.loads(json_str)
                if isinstance(topics, list):
                    return [t.strip() for t in topics if t.strip()]
            
            # Fallback: try parsing entire response
            if cleaned.startswith('```'):
                lines = cleaned.split('\n')
                cleaned = '\n'.join(lines[1:-1]) if len(lines) > 2 else cleaned
            
            topics = json.loads(cleaned)
            
            if isinstance(topics, list):
                return [t.strip() for t in topics if t.strip()]
            else:
                return []
        except (json.JSONDecodeError, AttributeError) as e:
            print(f"Failed to parse topics: {response[:200]}...")
            return []
    
    def generate_search_query(self, topics: List[str], conversation_turns: List[str]) -> str:
        """Generate a search query optimized for semantic similarity"""
        
        topics_str = ", ".join(topics)
        conversation_text = "\n".join(conversation_turns[-3:])
        
        prompt = f"""Generate a search query to find relevant memories about this conversation.

Conversation topics: {topics_str}

Recent context:
{conversation_text}

Create a search query with 10-15 terms that would appear in relevant memories.
Include:
- The main topics
- Related technical terms
- Synonyms and variations
- Specific details mentioned

Return ONLY the search terms separated by spaces:"""

        response = self.llm.generate(prompt, temperature=0.3)
        
        cleaned = response.strip()
        lines = cleaned.split('\n')
        for line in lines:
            line = line.strip()
            if line and not any(marker in line.lower() for marker in ['query:', 'terms:', 'search']):
                if len(line.split()) >= 5:
                    return line
        
        return cleaned


class V5FastMemorySearch:
    """Fast topic-aware search using Iris's existing memory infrastructure"""
    
    def __init__(self, db_params: Dict, llm: OllamaClient):
        self.conn = psycopg2.connect(**db_params)
        self.cursor = self.conn.cursor()
        self.llm = llm
        self.analyzer = ConversationAnalyzer(llm)
    
    def get_conversation_segments(self, num_segments: int = 5, turns_per_segment: int = 5) -> List[Dict]:
        """Pull real conversation segments from chat_history"""
        
        print(f"\n📚 Loading {num_segments} conversation segments from chat_history...")
        
        # Get random sessions with multiple turns
        self.cursor.execute("""
            SELECT session_id
            FROM chat_history
            WHERE session_id IS NOT NULL
            GROUP BY session_id
            HAVING COUNT(*) >= %s
            ORDER BY RANDOM()
            LIMIT %s
        """, (turns_per_segment, num_segments))
        
        session_ids = [row[0] for row in self.cursor.fetchall()]
        
        segments = []
        
        for session_id in session_ids:
            # Get segment of turns
            self.cursor.execute("""
                SELECT sender, message, c_timestamp
                FROM chat_history
                WHERE session_id = %s
                ORDER BY c_timestamp
                LIMIT %s
            """, (session_id, turns_per_segment))
            
            turns = self.cursor.fetchall()
            
            if len(turns) >= 3:
                conversation = []
                for sender, message, timestamp in turns:
                    conversation.append(f"{sender}: {message[:200]}")
                
                segments.append({
                    'session_id': session_id,
                    'conversation': conversation,
                    'time_range': (turns[0][2], turns[-1][2])
                })
        
        print(f"✓ Loaded {len(segments)} conversation segments\n")
        return segments
    
    def fast_search(self, conversation_turns: List[str]) -> Dict:
        """
        V5 Fast topic-aware search
        
        Uses:
        1. LLM topic detection (0.7s)
        2. LLM query generation (0.8s)
        3. LLM embedding (0.06s)
        4. fetch_memory_candidates() with HNSW index (FAST!)
        
        Target: <2 seconds total
        """
        
        timing = {}
        
        # Step 1: Detect topics
        print("  🔍 Detecting conversation topics...")
        start = time.time()
        topics = self.analyzer.detect_conversation_topics(conversation_turns)
        timing['topic_detection'] = time.time() - start
        print(f"     Topics: {topics}")
        print(f"     Time: {timing['topic_detection']:.2f}s")
        
        if not topics:
            print("     ⚠️  No topics detected")
            timing['total'] = timing['topic_detection']
            return {'memories': [], 'timing': timing, 'topics': []}
        
        # Step 2: Generate search query
        print("  🎯 Generating search query...")
        start = time.time()
        search_query = self.analyzer.generate_search_query(topics, conversation_turns)
        timing['query_generation'] = time.time() - start
        print(f"     Query: {search_query[:100]}...")
        print(f"     Time: {timing['query_generation']:.2f}s")
        
        # Step 3: Embed search query
        print("  🔢 Embedding search query...")
        start = time.time()
        query_embedding = self.llm.embed(search_query)
        timing['query_embedding'] = time.time() - start
        print(f"     Time: {timing['query_embedding']:.2f}s")
        
        if not query_embedding:
            print("     ⚠️  Failed to generate embedding")
            timing['total'] = sum(timing.values())
            return {'memories': [], 'timing': timing, 'topics': topics, 'search_query': search_query}
        
        # Step 4: Use fetch_memory_candidates() - FAST with HNSW index!
        print("  ⚡ Searching with fetch_memory_candidates()...")
        start = time.time()
        
        # Convert embedding list to PostgreSQL vector format
        embedding_str = '[' + ','.join(map(str, query_embedding)) + ']'
        
        self.cursor.execute("""
            SELECT 
                session_id,
                segment_id,
                topic_id,
                transcript,
                summary_context,
                takeaway,
                emotion_label,
                category,
                sim_score
            FROM fetch_memory_candidates(%s::vector, 10)
        """, (embedding_str,))
        
        results = []
        for row in self.cursor.fetchall():
            results.append({
                'session_id': str(row[0]),
                'segment_id': row[1],
                'topic_id': row[2],
                'transcript': row[3],
                'summary_context': row[4],
                'takeaway': row[5],
                'emotion_label': row[6],
                'category': row[7],
                'similarity': float(row[8])
            })
        
        timing['vector_search'] = time.time() - start
        print(f"     Found {len(results)} memories")
        print(f"     Time: {timing['vector_search']:.2f}s")
        
        timing['total'] = sum(timing.values())
        
        return {
            'memories': results,
            'timing': timing,
            'topics': topics,
            'search_query': search_query
        }
    
    def baseline_search(self, conversation_turns: List[str]) -> Dict:
        """
        Baseline: Use fetch_memory_candidates() with raw conversation embedding
        (Simpler, no topic extraction)
        """
        
        timing = {}
        
        print("  🐢 Baseline: Raw conversation embedding...")
        
        # Embed entire conversation
        conversation_text = " ".join(conversation_turns)
        start = time.time()
        query_embedding = self.llm.embed(conversation_text[:2000])
        timing['query_embedding'] = time.time() - start
        
        if not query_embedding:
            return {'memories': [], 'timing': timing}
        
        # Search with raw embedding
        start = time.time()
        embedding_str = '[' + ','.join(map(str, query_embedding)) + ']'
        
        self.cursor.execute("""
            SELECT 
                session_id,
                segment_id,
                topic_id,
                transcript,
                summary_context,
                takeaway,
                emotion_label,
                category,
                sim_score
            FROM fetch_memory_candidates(%s::vector, 10)
        """, (embedding_str,))
        
        results = []
        for row in self.cursor.fetchall():
            results.append({
                'session_id': str(row[0]),
                'segment_id': row[1],
                'topic_id': row[2],
                'transcript': row[3],
                'summary_context': row[4],
                'takeaway': row[5],
                'emotion_label': row[6],
                'category': row[7],
                'similarity': float(row[8])
            })
        
        timing['vector_search'] = time.time() - start
        timing['total'] = sum(timing.values())
        
        return {
            'memories': results,
            'timing': timing
        }
    
    def run_comparison(self, num_segments: int = 5):
        """Compare V5 fast search vs baseline"""
        
        print(f"\n{'='*80}")
        print(f"V5 FAST TOPIC-AWARE vs BASELINE")
        print(f"{'='*80}\n")
        
        segments = self.get_conversation_segments(num_segments, turns_per_segment=5)
        
        results = {
            'v5_times': [],
            'baseline_times': [],
            'v5_results': [],
            'baseline_results': []
        }
        
        for i, segment in enumerate(segments, 1):
            print(f"\n{'─'*80}")
            print(f"TEST {i}/{len(segments)}")
            print(f"{'─'*80}")
            
            conversation = segment['conversation']
            print(f"\nConversation:")
            for turn in conversation[:3]:
                print(f"  {turn[:100]}...")
            
            print(f"\n{'─'*40}")
            print("METHOD 1: V5 FAST TOPIC-AWARE")
            print(f"{'─'*40}")
            
            v5_result = self.fast_search(conversation)
            results['v5_times'].append(v5_result['timing']['total'])
            results['v5_results'].append(v5_result)
            
            print(f"\n  ⏱️  Total time: {v5_result['timing']['total']:.2f}s")
            print(f"  📊 Breakdown:")
            for step, duration in v5_result['timing'].items():
                if step != 'total':
                    print(f"     {step}: {duration:.2f}s")
            
            print(f"\n  Top 3 results:")
            for j, mem in enumerate(v5_result['memories'][:3], 1):
                snippet = mem['takeaway'] if mem['takeaway'] else mem['summary_context']
                snippet = snippet[:80] if snippet else "No summary"
                print(f"     {j}. Seg {mem['segment_id']} (sim: {mem['similarity']:.3f})")
                print(f"        {snippet}...")
            
            print(f"\n{'─'*40}")
            print("METHOD 2: BASELINE (Raw Embedding)")
            print(f"{'─'*40}")
            
            baseline_result = self.baseline_search(conversation)
            results['baseline_times'].append(baseline_result['timing']['total'])
            results['baseline_results'].append(baseline_result)
            
            print(f"\n  ⏱️  Total time: {baseline_result['timing']['total']:.2f}s")
            
            print(f"\n  Top 3 results:")
            for j, mem in enumerate(baseline_result['memories'][:3], 1):
                snippet = mem['takeaway'] if mem['takeaway'] else mem['summary_context']
                snippet = snippet[:80] if snippet else "No summary"
                print(f"     {j}. Seg {mem['segment_id']} (sim: {mem['similarity']:.3f})")
                print(f"        {snippet}...")
            
            # Comparison
            speedup = baseline_result['timing']['total'] / v5_result['timing']['total'] if v5_result['timing']['total'] > 0 else 0
            print(f"\n  📈 SPEEDUP: {speedup:.1f}x {'faster' if speedup > 1 else 'slower'}")
            
            # Check overlap
            v5_ids = {(m['session_id'], m['segment_id']) for m in v5_result['memories'][:5]}
            baseline_ids = {(m['session_id'], m['segment_id']) for m in baseline_result['memories'][:5]}
            overlap = len(v5_ids & baseline_ids)
            
            print(f"  🎯 OVERLAP: {overlap}/5 memories in common")
        
        self.print_summary(results)
    
    def print_summary(self, results: Dict):
        """Print final summary"""
        
        print(f"\n{'='*80}")
        print(f"FINAL SUMMARY")
        print(f"{'='*80}\n")
        
        avg_v5 = sum(results['v5_times']) / len(results['v5_times'])
        avg_baseline = sum(results['baseline_times']) / len(results['baseline_times'])
        avg_speedup = avg_baseline / avg_v5 if avg_v5 > 0 else 0
        
        print(f"Average Times:")
        print(f"  V5 method: {avg_v5:.2f}s")
        print(f"  Baseline method: {avg_baseline:.2f}s")
        print(f"  Speedup: {avg_speedup:.1f}x {'faster' if avg_speedup > 1 else 'slower'}")
        
        # Check if under target
        under_2s = sum(1 for t in results['v5_times'] if t < 2.0)
        print(f"\n✅ V5 under 2s target: {under_2s}/{len(results['v5_times'])} tests")
        
        # Average breakdown
        print(f"\nV5 breakdown (average):")
        breakdown = {}
        for result in results['v5_results']:
            for step, duration in result['timing'].items():
                if step != 'total':
                    breakdown[step] = breakdown.get(step, []) + [duration]
        
        for step, durations in breakdown.items():
            avg = sum(durations) / len(durations)
            print(f"  {step}: {avg:.2f}s")
    
    def cleanup(self):
        """Close database connection"""
        self.cursor.close()
        self.conn.close()


def main():
    """Run V5 fast topic-aware memory test"""
    
    print("="*80)
    print("V5 MEMORY SYSTEM - FAST TOPIC-AWARE SEARCH")
    print("="*80)
    print("\nUsing Iris's actual infrastructure:")
    print("  - fetch_memory_candidates() function")
    print("  - Pre-computed embeddings + HNSW index")
    print("  - Topic detection + query optimization")
    print("\nTarget: <2 seconds (vs baseline)\n")
    
    # Configuration
    print("Database Configuration:")
    db_host = input("  PostgreSQL host [localhost]: ").strip() or "localhost"
    db_name = input("  Database name [irisdb]: ").strip() or "irisdb"
    db_user = input("  Username [irisuser]: ").strip() or "irisuser"
    db_pass = input("  Password: ").strip()
    
    print("\nOllama Configuration:")
    ollama_url = input("  Ollama URL [http://localhost:11434]: ").strip() or "http://localhost:11434"
    ollama_model = input("  Model [qwen2.5:32b]: ").strip() or "qwen2.5:32b"
    
    print("\nTest Configuration:")
    num_segments = input("  Number of conversation segments [5]: ").strip()
    num_segments = int(num_segments) if num_segments else 5
    
    # Connect
    print("\n⏳ Connecting...")
    
    try:
        db_params = {
            'host': db_host,
            'database': db_name,
            'user': db_user,
            'password': db_pass
        }
        
        llm = OllamaClient(ollama_url, ollama_model)
        
        # Test connection
        test_response = llm.generate("Test", temperature=0.0)
        
        print("✓ Connected to database and Ollama\n")
        
    except Exception as e:
        print(f"✗ Connection failed: {e}")
        return
    
    # Run test
    test = V5FastMemorySearch(db_params, llm)
    
    try:
        test.run_comparison(num_segments)
    finally:
        test.cleanup()
    
    print("\n✓ Test complete")


if __name__ == "__main__":
    main()