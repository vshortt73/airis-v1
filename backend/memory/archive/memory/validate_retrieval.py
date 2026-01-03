#!/usr/bin/env python3
"""
Validation Suite for Memory Retrieval System

Tests memory retrieval across different conversation types to ensure:
1. Appropriate memories are retrieved for each topic
2. No regressions from prompt changes
3. System works across diverse conversation types
"""

import sys
sys.path.insert(0, '/iris-v3/backend/memory')

import psycopg2
from psycopg2.extras import DictCursor
import subprocess
import json
import tempfile
import os

DB_CFG = dict(dbname="irisdb", user="irisuser", password="yourpassword", host="localhost", port=5432)

# Test sessions representing different conversation types
TEST_SESSIONS = [
    {
        "id": "5aa3b0b5-4899-4dbe-83f6-4f1f70a3ac6a",
        "description": "Protocol Bravo system testing",
        "expected_topics": ["protocol", "system features", "activation"],
        "days_ago": 1.6
    },
    {
        "id": "8f12dcff-8730-40d7-b461-81b732cf0597",
        "description": "ComfyUI technical work - models, upscaling",
        "expected_topics": ["comfyui", "image", "model", "upscal"],
        "days_ago": 6.5
    },
    {
        "id": "c812c24e-430f-4258-bd94-47a3684d0b02",
        "description": "Claude-Iris meta discussion about memory/consciousness",
        "expected_topics": ["memory", "consciousness", "claude", "dream"],
        "days_ago": 3.7
    },
    {
        "id": "b211f291-4711-4a01-895f-ad7763b49190",
        "description": "Current cruise vacation planning discussion",
        "expected_topics": ["cruise", "vacation", "june"],
        "days_ago": 0.07
    }
]

def get_session_conversation(session_id):
    """Load all messages from a session"""
    conn = psycopg2.connect(**DB_CFG)
    cur = conn.cursor(cursor_factory=DictCursor)

    cur.execute("""
        SELECT role, message, c_timestamp
        FROM chat_history
        WHERE session_id = %s
        ORDER BY c_timestamp ASC
    """, (session_id,))

    messages = cur.fetchall()
    cur.close()
    conn.close()

    # Format as conversation text
    convo = "\n".join([f"{m['role'].upper()}: {m['message']}" for m in messages])
    return convo, len(messages)

def run_retrieval_for_session(session_id):
    """
    Run memory retrieval by temporarily modifying the chat_history table
    to contain only this session's messages, then running iris_memory_retrieval.py
    """
    # Get the conversation
    convo, msg_count = get_session_conversation(session_id)

    # Write conversation to temp file for iris_memory_retrieval.py to read
    # Actually, let's just run the retrieval directly in Python by importing the module
    # But we need to override which conversation it uses...

    # Better approach: use subprocess and capture output
    # The script reads from chat_history, so we'd need to manipulate that...

    # Actually, let's parse the iris_memory_retrieval.py output when run normally
    # and check what it retrieves

    result = subprocess.run(
        ["python", "iris_memory_retrieval.py", "--top_k", "10", "--show", "false", "--insert", "false"],
        cwd="/iris-v3/backend/memory",
        capture_output=True,
        text=True,
        timeout=120
    )

    return result.stdout, result.stderr

def analyze_retrieval_results(stdout, stderr, expected_topics):
    """Analyze if retrieved memories are appropriate for the conversation"""
    # Parse the output to extract retrieved memory IDs and summaries
    lines = stdout.split('\n')

    retrieved_memories = []
    current_memory = {}

    for line in lines:
        if line.startswith('ID '):
            # New memory entry
            if current_memory:
                retrieved_memories.append(current_memory)
            current_memory = {'raw': line}
        elif line.strip().startswith('Takeaway:') or line.strip().startswith('Context:') or line.strip().startswith('Event:'):
            current_memory['raw'] = current_memory.get('raw', '') + '\n' + line

    if current_memory:
        retrieved_memories.append(current_memory)

    # Check how many retrieved memories relate to expected topics
    relevant_count = 0
    total_count = len(retrieved_memories)

    for mem in retrieved_memories:
        mem_text = mem['raw'].lower()
        if any(topic.lower() in mem_text for topic in expected_topics):
            relevant_count += 1

    return {
        'total_retrieved': total_count,
        'relevant_count': relevant_count,
        'relevance_ratio': relevant_count / total_count if total_count > 0 else 0,
        'memories': retrieved_memories[:5]  # First 5 for review
    }

def validate_all_sessions():
    """Run validation across all test sessions"""
    print("=" * 80)
    print("MEMORY RETRIEVAL VALIDATION SUITE")
    print("=" * 80)
    print()

    # First, save current conversation
    conn = psycopg2.connect(**DB_CFG)
    cur = conn.cursor()

    print("NOTE: This validation requires temporarily modifying chat_history")
    print("      to test different conversation contexts.")
    print()

    results = []

    for test_session in TEST_SESSIONS:
        print(f"\n{'='*80}")
        print(f"Testing: {test_session['description']}")
        print(f"Session: {test_session['id']}")
        print(f"Age: {test_session['days_ago']:.1f} days ago")
        print(f"Expected topics: {', '.join(test_session['expected_topics'])}")
        print('='*80)

        # Get conversation details
        convo, msg_count = get_session_conversation(test_session['id'])
        print(f"\nConversation: {msg_count} messages")
        print(f"Preview: {convo[:200]}...")

        print("\n⚠️  To properly test this session, we need to:")
        print("   1. Temporarily clear current chat_history")
        print("   2. Load this session's messages")
        print("   3. Run retrieval")
        print("   4. Restore original chat_history")
        print()
        print("   This is complex and risky. Alternative approach:")
        print("   Manually test each session by loading it in the UI.")
        print()

    cur.close()
    conn.close()

    print("\n" + "=" * 80)
    print("RECOMMENDATION")
    print("=" * 80)
    print("""
Instead of automated testing that risks data corruption, I recommend:

1. Create a test script that:
   - Takes a conversation text as input
   - Runs the retrieval pipeline directly (without DB dependency)
   - Returns retrieved memories

2. Feed it sample conversations representing different types:
   - Technical (ComfyUI)
   - Meta (AI/memory discussions)
   - Personal (cruise planning)
   - Creative projects
   - Relational conversations

3. Manually evaluate if retrieved memories make sense for each type

Would you like me to create this safer test approach instead?
    """)

if __name__ == "__main__":
    validate_all_sessions()
