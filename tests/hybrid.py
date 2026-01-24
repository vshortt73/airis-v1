"""
HYBRID MEMORY SYSTEM - TEST HARNESS

Tests the conceptual two-tier memory architecture:
- Fast Reactive: Runs on EVERY message (<2s)
- Deep Proactive: Runs every N turns in background (25-30s)

This simulates how the system would behave in real conversations
"""

import psycopg2
from sentence_transformers import SentenceTransformer
import time
from typing import List, Dict, Optional
from datetime import datetime


class FastReactiveMemory:
    """
    Tier 1: Fast reactive search
    Runs on EVERY user message
    Provides immediate "we've discussed this" awareness
    """
    
    def __init__(self, db_params: Dict):
        self.conn = psycopg2.connect(**db_params)
        self.cursor = self.conn.cursor()
        print("  Loading SentenceTransformer (all-mpnet-base-v2)...")
        self.embedder = SentenceTransformer("all-mpnet-base-v2")
        print("  ✓ Fast reactive layer ready")
    
    def check_relevance(self, user_message: str, recent_turns: List[str]) -> Dict:
        """
        Fast check: Have we discussed this before?
        
        Returns immediate context to prevent hallucination
        Time budget: <2 seconds
        """
        
        timing = {}
        
        # Step 1: Embed current context
        start = time.time()
        context = " ".join(recent_turns[-3:] + [user_message])
        query_embedding = self.embedder.encode(context, normalize_embeddings=True).tolist()
        timing['embedding'] = time.time() - start
        
        # Step 2: Fast vector search (top 5)
        start = time.time()
        embedding_str = '[' + ','.join(map(str, query_embedding)) + ']'
        
        self.cursor.execute("""
            SELECT 
                id,
                segment_id,
                takeaway,
                summary_context,
                category,
                valence,
                arousal,
                1 - (emb_minilm <=> %s::vector) AS similarity
            FROM episodic_memories_with_age
            ORDER BY emb_minilm <=> %s::vector
            LIMIT 5
        """, (embedding_str, embedding_str))
        
        results = []
        for row in self.cursor.fetchall():
            results.append({
                'id': row[0],
                'segment_id': row[1],
                'takeaway': row[2],
                'summary_context': row[3],
                'category': row[4],
                'valence': float(row[5]) if row[5] else 0.0,
                'arousal': float(row[6]) if row[6] else 0.0,
                'similarity': float(row[7])
            })
        
        timing['search'] = time.time() - start
        timing['total'] = timing['embedding'] + timing['search']
        
        # Step 3: Generate context hint
        if results and results[0]['similarity'] > 0.5:
            hint = self._generate_hint(results[0])
            return {
                'relevant': True,
                'top_match': results[0],
                'related_memories': results[:3],
                'context_hint': hint,
                'timing': timing
            }
        else:
            return {
                'relevant': False,
                'top_match': None,
                'related_memories': [],
                'context_hint': None,
                'timing': timing
            }
    
    def _generate_hint(self, memory: Dict) -> str:
        """Generate brief context hint for Iris"""
        
        takeaway = memory['takeaway'][:80] if memory['takeaway'] else memory['summary_context'][:80]
        valence = "positive" if memory['valence'] > 0 else "negative" if memory['valence'] < 0 else "neutral"
        
        return f"Past context: {takeaway}... (tone: {valence}, similarity: {memory['similarity']:.2f})"
    
    def cleanup(self):
        self.cursor.close()
        self.conn.close()


class DeepProactiveMemory:
    """
    Tier 2: Deep proactive search (SIMULATED)
    Runs every N turns in background
    Your existing 25-30s system
    """
    
    def __init__(self, db_params: Dict):
        self.conn = psycopg2.connect(**db_params)
        self.cursor = self.conn.cursor()
        self.embedder = SentenceTransformer("all-mpnet-base-v2")
        print("  ✓ Deep proactive layer ready")
    
    def refresh(self, recent_turns: List[str]) -> Dict:
        """
        Deep refresh (simulated)
        
        In reality: 25-30s with psychological scoring
        In test: We'll just do vector search + fetch more details
        """
        
        timing = {}
        
        print("      [DEEP REFRESH TRIGGERED]")
        
        # Simulate the expensive operations
        start = time.time()
        
        # Embed conversation
        context = " ".join(recent_turns[-5:])
        query_embedding = self.embedder.encode(context, normalize_embeddings=True).tolist()
        timing['embedding'] = time.time() - start
        
        # Search (fetch more results)
        start = time.time()
        embedding_str = '[' + ','.join(map(str, query_embedding)) + ']'
        
        self.cursor.execute("""
            SELECT 
                id,
                segment_id,
                transcript,
                takeaway,
                summary_context,
                category,
                valence,
                arousal,
                recurrence,
                novelty,
                cohesion,
                1 - (emb_minilm <=> %s::vector) AS similarity
            FROM episodic_memories_with_age
            ORDER BY emb_minilm <=> %s::vector
            LIMIT 20
        """, (embedding_str, embedding_str))
        
        results = []
        for row in self.cursor.fetchall():
            results.append({
                'id': row[0],
                'segment_id': row[1],
                'transcript': row[2][:500] if row[2] else "",
                'takeaway': row[3],
                'summary_context': row[4],
                'category': row[5],
                'valence': float(row[6]) if row[6] else 0.0,
                'arousal': float(row[7]) if row[7] else 0.0,
                'recurrence': float(row[8]) if row[8] else 0.0,
                'novelty': float(row[9]) if row[9] else 0.0,
                'cohesion': float(row[10]) if row[10] else 0.0,
                'similarity': float(row[11])
            })
        
        timing['search'] = time.time() - start
        
        # Simulate psychological scoring time
        # (In reality this is where the 20-25 seconds come from)
        print(f"      [Simulating psychological scoring... in reality: 20-25s]")
        timing['scoring'] = 0.1  # Simulated
        
        timing['total'] = sum(timing.values())
        
        print(f"      [DEEP REFRESH COMPLETE - Found {len(results)} memories]")
        
        return {
            'memories': results,
            'timing': timing
        }
    
    def cleanup(self):
        self.cursor.close()
        self.conn.close()


class HybridMemoryTestHarness:
    """
    Test harness for hybrid reactive+proactive memory system
    
    Simulates multi-turn conversations to see how the system behaves
    """
    
    def __init__(self, db_params: Dict, refresh_interval: int = 3):
        self.fast = FastReactiveMemory(db_params)
        self.deep = DeepProactiveMemory(db_params)
        self.refresh_interval = refresh_interval
        
        # Track state
        self.turn_counter = 0
        self.deep_context = None
        self.deep_refresh_in_progress = False
    
    def get_test_conversations(self, num_conversations: int = 3) -> List[Dict]:
        """
        Pull real multi-turn conversations from chat_history
        """
        
        print(f"\n📚 Loading {num_conversations} multi-turn conversations...")
        
        # Get sessions with 5+ turns
        self.fast.cursor.execute("""
            SELECT session_id, COUNT(*) as turn_count
            FROM chat_history
            WHERE session_id IS NOT NULL
            GROUP BY session_id
            HAVING COUNT(*) >= 5
            ORDER BY RANDOM()
            LIMIT %s
        """, (num_conversations,))
        
        sessions = self.fast.cursor.fetchall()
        
        conversations = []
        
        for session_id, turn_count in sessions:
            # Get all turns for this session
            self.fast.cursor.execute("""
                SELECT sender, message, c_timestamp
                FROM chat_history
                WHERE session_id = %s
                ORDER BY c_timestamp
            """, (session_id,))
            
            turns = []
            for sender, message, timestamp in self.fast.cursor.fetchall():
                turns.append({
                    'sender': sender,
                    'message': message,
                    'timestamp': timestamp
                })
            
            conversations.append({
                'session_id': session_id,
                'turns': turns
            })
        
        print(f"✓ Loaded {len(conversations)} conversations\n")
        return conversations
    
    def simulate_conversation(self, conversation: Dict):
        """
        Simulate how the hybrid system would handle a real conversation
        """
        
        turns = conversation['turns']
        session_id = conversation['session_id']
        
        print(f"\n{'='*80}")
        print(f"SIMULATING CONVERSATION (Session: {str(session_id)[:8]}...)")
        print(f"Total turns: {len(turns)}")
        print(f"Deep refresh interval: Every {self.refresh_interval} turns")
        print(f"{'='*80}\n")
        
        recent_turns = []
        
        for i, turn in enumerate(turns, 1):
            if turn['sender'] != 'user':
                continue
            
            self.turn_counter += 1
            user_message = turn['message']
            
            print(f"{'─'*80}")
            print(f"TURN {self.turn_counter}")
            print(f"{'─'*80}")
            print(f"User: {user_message[:100]}...")
            print()
            
            # FAST REACTIVE (runs on EVERY turn)
            print("🔄 FAST REACTIVE (runs immediately):")
            reactive_result = self.fast.check_relevance(user_message, recent_turns)
            
            print(f"   Timing: {reactive_result['timing']['total']:.3f}s")
            print(f"   Relevant: {reactive_result['relevant']}")
            
            if reactive_result['relevant']:
                print(f"   Top match: Seg {reactive_result['top_match']['segment_id']}")
                print(f"   Similarity: {reactive_result['top_match']['similarity']:.3f}")
                print(f"   Related memories: {len(reactive_result['related_memories'])}")
                
                print(f"\n   💡 WHAT IRIS WOULD SEE (injected into her context):")
                print(f"   {'─'*76}")
                print(f"   [FAST CONTEXT - This topic has come up before]")
                print(f"   ")
                print(f"   Top match (similarity: {reactive_result['top_match']['similarity']:.2f}):")
                
                # Show the takeaway (what you typically use)
                if reactive_result['top_match']['takeaway']:
                    print(f"   Takeaway: {reactive_result['top_match']['takeaway']}")
                else:
                    print(f"   Summary: {reactive_result['top_match']['summary_context']}")
                
                print(f"   ")
                print(f"   Category: {reactive_result['top_match']['category']}")
                print(f"   Emotional tone: {reactive_result['context_hint'].split('tone: ')[1].split(',')[0]}")
                print(f"   ")
                
                # Show related memories (brief)
                if len(reactive_result['related_memories']) > 1:
                    print(f"   Also related ({len(reactive_result['related_memories'])-1} more):")
                    for j, mem in enumerate(reactive_result['related_memories'][1:3], 2):
                        takeaway = mem['takeaway'][:60] if mem['takeaway'] else mem['summary_context'][:60]
                        print(f"     {j}. (sim: {mem['similarity']:.2f}) {takeaway}...")
                
                print(f"   {'─'*76}")
                print(f"   [END FAST CONTEXT]")
            else:
                print(f"   No relevant past context found")
                print(f"\n   💡 WHAT IRIS WOULD SEE:")
                print(f"   {'─'*76}")
                print(f"   [No fast context available - operating on current conversation only]")
                print(f"   {'─'*76}")
            
            # DEEP PROACTIVE (runs every N turns)
            if self.turn_counter % self.refresh_interval == 0:
                print(f"\n🧠 DEEP PROACTIVE (turn {self.turn_counter} - refresh triggered):")
                deep_result = self.deep.refresh(recent_turns + [user_message])
                
                print(f"   Timing: {deep_result['timing']['total']:.3f}s (simulated - real: 25-30s)")
                print(f"   Found: {len(deep_result['memories'])} memories")
                
                print(f"\n   💡 WHAT IRIS WOULD SEE (full deep context):")
                print(f"   {'─'*76}")
                print(f"   [DEEP CONTEXT - {len(deep_result['memories'])} psychologically-scored memories]")
                print(f"   ")
                print(f"   Top 5 memories (with full details):")
                for j, mem in enumerate(deep_result['memories'][:5], 1):
                    print(f"   ")
                    print(f"   {j}. Segment {mem['segment_id']} (similarity: {mem['similarity']:.3f})")
                    if mem['takeaway']:
                        print(f"      Takeaway: {mem['takeaway']}")
                    else:
                        print(f"      Summary: {mem['summary_context'][:100]}...")
                    print(f"      Category: {mem['category']}")
                    print(f"      Psychological: valence={mem['valence']:.2f}, arousal={mem['arousal']:.2f}")
                    print(f"      Scores: recurrence={mem['recurrence']:.2f}, novelty={mem['novelty']:.2f}, cohesion={mem['cohesion']:.2f}")
                
                if len(deep_result['memories']) > 5:
                    print(f"   ")
                    print(f"   ... plus {len(deep_result['memories']) - 5} more memories available")
                
                print(f"   {'─'*76}")
                print(f"   [END DEEP CONTEXT]")
                
                self.deep_context = deep_result
            else:
                if self.deep_context:
                    print(f"\n🧠 DEEP CONTEXT: Still available from turn {(self.turn_counter // self.refresh_interval) * self.refresh_interval}")
                    print(f"   ({len(self.deep_context['memories'])} memories in context)")
                else:
                    print(f"\n🧠 DEEP CONTEXT: Not yet available")
                    print(f"   (Next refresh: turn {((self.turn_counter // self.refresh_interval) + 1) * self.refresh_interval})")
            
            # Add to recent turns
            recent_turns.append(user_message)
            if len(recent_turns) > 5:
                recent_turns.pop(0)
            
            print()
    
    def run_test(self, num_conversations: int = 3):
        """Run the full test"""
        
        conversations = self.get_test_conversations(num_conversations)
        
        for i, conversation in enumerate(conversations, 1):
            print(f"\n{'#'*80}")
            print(f"CONVERSATION {i}/{len(conversations)}")
            print(f"{'#'*80}")
            
            # Reset state for new conversation
            self.turn_counter = 0
            self.deep_context = None
            
            self.simulate_conversation(conversation)
        
        print(f"\n{'='*80}")
        print("TEST COMPLETE")
        print(f"{'='*80}\n")
        
        print("Summary:")
        print(f"  - Fast reactive runs on EVERY turn (<2s)")
        print(f"  - Deep proactive runs every {self.refresh_interval} turns (25-30s)")
        print(f"  - Iris ALWAYS has some context (fast layer)")
        print(f"  - Iris gets deep understanding periodically (deep layer)")
        print(f"  - Gap is bridged: No more hallucination windows")
    
    def cleanup(self):
        self.fast.cleanup()
        self.deep.cleanup()


def main():
    """Run the hybrid memory test harness"""
    
    print("="*80)
    print("HYBRID MEMORY SYSTEM - TEST HARNESS")
    print("="*80)
    print("\nTests the two-tier architecture:")
    print("  - Fast Reactive: Every message (<2s)")
    print("  - Deep Proactive: Every N turns (25-30s)")
    print()
    
    # Configuration
    print("Database Configuration:")
    db_host = input("  PostgreSQL host [localhost]: ").strip() or "localhost"
    db_name = input("  Database name [irisdb]: ").strip() or "irisdb"
    db_user = input("  Username [irisuser]: ").strip() or "irisuser"
    db_pass = input("  Password: ").strip()
    
    print("\nTest Configuration:")
    refresh_interval = input("  Deep refresh interval (turns) [3]: ").strip()
    refresh_interval = int(refresh_interval) if refresh_interval else 3
    
    num_conversations = input("  Number of conversations to test [3]: ").strip()
    num_conversations = int(num_conversations) if num_conversations else 3
    
    # Connect
    print("\n⏳ Initializing hybrid memory system...")
    
    try:
        db_params = {
            'host': db_host,
            'database': db_name,
            'user': db_user,
            'password': db_pass
        }
        
        harness = HybridMemoryTestHarness(db_params, refresh_interval)
        
        print("✓ System initialized\n")
        
    except Exception as e:
        print(f"✗ Initialization failed: {e}")
        return
    
    # Run test
    try:
        harness.run_test(num_conversations)
    finally:
        harness.cleanup()
    
    print("\n✓ Test complete")


if __name__ == "__main__":
    main()