"""
FAST REACTIVE MEMORY LAYER - PRODUCTION IMPLEMENTATION

Runs on EVERY user message to provide immediate context awareness.
Bridges the gap between deep memory refreshes.

Integrates with existing Iris infrastructure:
- Uses database.persistence.get_db_connection()
- Uses database.persistence.load_recent_conversation()
- Uses database.persistence.get_current_chat_table()

Usage:
    fast_memory = FastReactiveMemory()
    context = fast_memory.get_context(user_message)
    # Inject context into Iris's system prompt
"""

import os
import sys

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from database.persistence import get_db_connection, load_recent_conversation, get_current_chat_table
from core.embeddings import get_embedding_model
from typing import List, Dict, Optional
import time


class FastReactiveMemory:
    """
    Fast reactive memory layer for Iris
    
    Provides immediate context on EVERY user message
    Target: <100ms response time
    """
    
    def __init__(self):
        """
        Initialize the fast reactive layer
        
        Uses existing Iris database infrastructure and shared embedder
        """
        print("Initializing Fast Reactive Memory Layer...")
        
        # Database connection (using your existing connection manager)
        self.conn = get_db_connection()
        self.cursor = self.conn.cursor()
        
        # Use shared embedder (singleton from core.embeddings)
        print("  Getting shared embedding model...")
        self.embedder = get_embedding_model()
        
        # Configuration
        self.similarity_threshold = 0.4  # Minimum similarity to consider relevant
        self.max_results = 3  # Top N memories to return
        self.context_turns = 3  # How many recent turns to include in search context
        
        print("✓ Fast Reactive Memory Layer ready")
    
    def get_context(self, user_message: str, load_conversation: bool = False) -> Optional[str]:
        """
        Get immediate context for the current message
        
        Args:
            user_message: The current user message
            load_conversation: If True, loads recent turns from DB. 
                              DEFAULT FALSE - fast reactive searches just the current message
                              for best topic matching. Deep refresh handles multi-turn context.
        
        Returns:
            Context string to inject into system prompt, or None if no relevant context
        """
        
        # Step 1: Get recent turns (if in production mode)
        if load_conversation:
            recent_messages = load_recent_conversation(max_messages=self.context_turns * 2)  # Load extra to ensure we get enough user messages
            
            # Format recent conversation - ONLY USER MESSAGES
            context_parts = []
            user_msg_count = 0
            for msg in reversed(recent_messages):  # Start from most recent
                if msg.get('role') == 'user':
                    content = msg.get('content', '')[:200]
                    if content:
                        context_parts.insert(0, content)  # Add to beginning (chronological)
                        user_msg_count += 1
                        if user_msg_count >= self.context_turns:
                            break
            
            # Add current message
            context_parts.append(user_message)
            context_text = " ".join(context_parts)
        else:
            # Standalone mode: just use the message itself
            context_text = user_message
        
        # Step 3: Generate embedding
        start_time = time.time()
        query_embedding = self.embedder.encode(context_text, normalize_embeddings=True).tolist()
        embed_time = time.time() - start_time
        
        # DEBUG: Show what we're searching with
        print(f"[fast_reactive_memory] DEBUG: Searching with text: '{context_text[:300]}'")
        
        # Step 4: Vector search
        start_time = time.time()
        results = self._vector_search(query_embedding, self.max_results)
        search_time = time.time() - start_time
        
        # Step 5: Check if relevant
        if not results or results[0]['similarity'] < self.similarity_threshold:
            return None
        
        # Step 6: Format context
        context = self._format_context(results)
        
        # Optional: Log timing (useful for monitoring)
        # print(f"Fast reactive: {embed_time:.3f}s embed + {search_time:.3f}s search = {embed_time + search_time:.3f}s total")
        
        return context
    
    def _vector_search(self, query_embedding: List[float], limit: int) -> List[Dict]:
        """
        Perform fast vector search using HNSW index
        
        Returns:
            List of memory dictionaries with similarity scores
        """
        
        # Convert embedding to PostgreSQL vector format
        embedding_str = '[' + ','.join(map(str, query_embedding)) + ']'
        
        # Query using vector similarity (HNSW index makes this fast)
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
            WHERE emb_minilm IS NOT NULL
            ORDER BY emb_minilm <=> %s::vector
            LIMIT %s
        """, (embedding_str, embedding_str, limit))
        
        results = []
        for row in self.cursor.fetchall():
            results.append({
                'id': row[0],
                'segment_id': row[1],
                'takeaway': row[2],
                'summary_context': row[3],
                'category': row[4],
                'valence': float(row[5]) if row[5] is not None else 0.0,
                'arousal': float(row[6]) if row[6] is not None else 0.0,
                'similarity': float(row[7])
            })
        
        return results
    
    def _format_context(self, results: List[Dict]) -> str:
        """
        Format search results into context string for Iris
        
        This is what gets injected into her system prompt
        """
        
        top_match = results[0]
        
        # Determine emotional tone
        valence = top_match['valence']
        if valence > 0.2:
            tone = "positive"
        elif valence < -0.2:
            tone = "negative"
        else:
            tone = "neutral"
        
        # Build context string
        context = """[FAST CONTEXT - Relevant past discussion detected]
These facts directly connect you to your current conversation. They show immediate connection to past experiences and projects.
reference them whenever possible using terms like:
    I remember when we....
    Do you remember the time....
    I remember that project...
    Do you remember designing <object, module, outfit, clothing... > together?

 CONTEXT OBJECTS   
"""
        
        # Try summary_context first (often better than takeaway for recent memories)
        # Fall back to takeaway if summary_context is empty
        content = top_match['summary_context'] if top_match['summary_context'] else top_match['takeaway']
        context += f"Summary: {content}\n"
        context += f"Category: {top_match['category']}\n"
        context += f"Emotional tone: {tone}\n"
        context += f"Similarity: {top_match['similarity']:.2f}\n"
        
        # Related memories (if multiple found)
        if len(results) > 1:
            context += f"\nAlso related:\n"
            for i, mem in enumerate(results[1:], 2):
                snippet = mem['summary_context'] if mem['summary_context'] else mem['takeaway']
                snippet = snippet[:300] + "..." if snippet and len(snippet) > 300 else snippet
                if snippet:
                    context += f"  {i}. (sim: {mem['similarity']:.2f}) {snippet}\n"
        
        context += "\n[END FAST CONTEXT]\n"
        
        return context
    
    def cleanup(self):
        """Close database connection"""
        self.cursor.close()
        self.conn.close()


# ============================================================================
# INTEGRATION EXAMPLE
# ============================================================================

def example_integration():
    """
    Example of how to integrate Fast Reactive Memory into Iris
    """
    
    # Initialize (do this once at startup)
    fast_memory = FastReactiveMemory()
    
    # ========================================================================
    # On EVERY user message (in your main conversation loop):
    # ========================================================================
    
    def on_user_message(user_message: str):
        """
        Called for each user message
        
        Args:
            user_message: The current user message
        """
        
        # Get fast reactive context (fetches recent turns automatically)
        fast_context = fast_memory.get_context(user_message)
        
        # Build Iris's system prompt (your existing function)
        system_prompt = build_iris_system_prompt()
        
        # Inject fast context if relevant
        if fast_context:
            system_prompt += "\n\n" + fast_context
        
        # Get Iris's response (your existing LLM call)
        response = get_iris_response(system_prompt, user_message)
        
        return response
    
    # ========================================================================
    # Your existing deep refresh (runs every N turns in background)
    # ========================================================================
    
    turn_counter = 0
    
    def on_turn_complete():
        """Called after each turn completes"""
        global turn_counter
        turn_counter += 1
        
        # Trigger deep refresh every 2-3 turns
        if turn_counter % 2 == 0:
            # Run your existing 25-30s deep memory refresh
            # This can be async/background
            trigger_deep_memory_refresh()
    
    # Cleanup when shutting down
    fast_memory.cleanup()


def build_iris_system_prompt():
    """Your existing system prompt builder"""
    return "You are Iris, an AI assistant..."


def get_iris_response(system_prompt, user_message):
    """Your existing LLM call"""
    # Call Ollama/API with system_prompt
    pass


def trigger_deep_memory_refresh():
    """Your existing deep memory refresh system"""
    # Your 25-30s psychological scoring system
    pass


# ============================================================================
# STANDALONE USAGE (for testing)
# ============================================================================

def main():
    """
    Standalone test of Fast Reactive Memory
    """
    
    print("="*80)
    print("FAST REACTIVE MEMORY - STANDALONE TEST")
    print("="*80)
    print()
    
    # Initialize (uses get_db_connection from database.persistence)
    try:
        fast_memory = FastReactiveMemory()
    except ImportError:
        print("ERROR: Could not import database.persistence.get_db_connection()")
        print("Make sure you're running this from the Iris project directory")
        return
    except Exception as e:
        print(f"ERROR: Failed to initialize: {e}")
        return
    
    print()
    print("Fast Reactive Memory initialized. Type messages to test.")
    print("Type 'quit' to exit.")
    print()
    
    while True:
        user_input = input("You: ").strip()
        
        if user_input.lower() in ['quit', 'exit']:
            break
        
        if not user_input:
            continue
        
        # Get context (standalone mode - don't load conversation from DB)
        print("\nSearching for relevant context...")
        start = time.time()
        context = fast_memory.get_context(user_input, load_conversation=False)
        elapsed = time.time() - start
        
        if context:
            print(f"\n{context}")
            print(f"(Retrieved in {elapsed:.3f}s)")
        else:
            print("\nNo relevant past context found.")
            print(f"(Searched in {elapsed:.3f}s)")
        
        print()
    
    # Cleanup
    fast_memory.cleanup()
    print("\n✓ Test complete")


if __name__ == "__main__":
    main()