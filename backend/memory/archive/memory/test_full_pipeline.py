#!/usr/bin/env python3
"""
Full Pipeline Validation - End-to-end memory retrieval testing

Tests the COMPLETE retrieval system:
1. Lens extraction
2. Emotion scoring
3. Summary generation
4. Embedding generation
5. Database retrieval
6. Reranking with decay
7. Final top 10 selection

For each conversation type, validates that retrieved memories are contextually appropriate.
"""

import sys
sys.path.insert(0, '/iris-v3/backend/memory')

import psycopg2
from psycopg2.extras import DictCursor
import subprocess
import tempfile
import json

DB_CFG = dict(dbname="irisdb", user="irisuser", password="yourpassword", host="localhost", port=5432)

TEST_SESSIONS = [
    {
        'id': 'b211f291-4711-4a01-895f-ad7763b49190',
        'description': 'Cruise vacation planning',
        'expected_memory_topics': ['cruise', 'vacation', 'ship', 'travel', 'costa maya', 'cozumel'],
        'inappropriate_topics': ['comfyui', 'image generation', 'python', 'coding']
    },
    {
        'id': '8f12dcff-8730-40d7-b461-81b732cf0597',
        'description': 'ComfyUI technical work',
        'expected_memory_topics': ['comfyui', 'image', 'model', 'upscal', 'workflow', 'generation'],
        'inappropriate_topics': ['cruise', 'vacation', 'travel']
    },
    {
        'id': 'c812c24e-430f-4258-bd94-47a3684d0b02',
        'description': 'Claude-Iris discussion + dream module',
        'expected_memory_topics': ['claude', 'memory', 'consciousness', 'dream', 'ai system'],
        'inappropriate_topics': ['comfyui', 'cruise', 'upscal']
    },
    {
        'id': '5aa3b0b5-4899-4dbe-83f6-4f1f70a3ac6a',
        'description': 'Protocol Bravo system testing',
        'expected_memory_topics': ['protocol', 'bravo', 'activate', 'system'],
        'inappropriate_topics': ['cruise', 'comfyui', 'image']
    }
]

def backup_recent_messages(n=30):
    """Backup the last N messages from chat_history"""
    conn = psycopg2.connect(**DB_CFG)
    cur = conn.cursor(cursor_factory=DictCursor)

    cur.execute("""
        SELECT id, role, message, session_id, c_timestamp, tool_calls, attachments
        FROM chat_history
        ORDER BY c_timestamp DESC
        LIMIT %s
    """, (n,))

    backup = cur.fetchall()
    cur.close()
    conn.close()

    return [dict(row) for row in backup]

def restore_messages(backup):
    """Restore backed up messages"""
    conn = psycopg2.connect(**DB_CFG)
    cur = conn.cursor()

    # Delete messages that were added during test
    if backup:
        oldest_backup_time = min(m['c_timestamp'] for m in backup)
        cur.execute("DELETE FROM chat_history WHERE c_timestamp >= %s", (oldest_backup_time,))

    # Restore original messages
    for msg in backup:
        cur.execute("""
            INSERT INTO chat_history (id, role, message, session_id, c_timestamp, tool_calls, attachments)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
        """, (msg['id'], msg['role'], msg['message'], msg['session_id'],
              msg['c_timestamp'], msg['tool_calls'], msg['attachments']))

    conn.commit()
    cur.close()
    conn.close()

def load_session_as_current(session_id):
    """Load a specific session's messages as the 'current' conversation"""
    conn = psycopg2.connect(**DB_CFG)
    cur = conn.cursor(cursor_factory=DictCursor)

    # Get session messages
    cur.execute("""
        SELECT role, message, c_timestamp, tool_calls, attachments
        FROM chat_history
        WHERE session_id = %s
        ORDER BY c_timestamp ASC
    """, (session_id,))

    messages = cur.fetchall()

    # Clear recent messages (last 50)
    cur.execute("""
        DELETE FROM chat_history
        WHERE id IN (
            SELECT id FROM chat_history
            ORDER BY c_timestamp DESC
            LIMIT 50
        )
    """)

    # Insert session messages as current
    import uuid
    from datetime import datetime, timedelta

    base_time = datetime.now() - timedelta(minutes=len(messages))

    for i, msg in enumerate(messages):
        cur.execute("""
            INSERT INTO chat_history (id, role, message, session_id, c_timestamp, tool_calls, attachments)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (str(uuid.uuid4()), msg['role'], msg['message'], session_id,
              base_time + timedelta(minutes=i), msg.get('tool_calls'), msg.get('attachments')))

    conn.commit()
    cur.close()
    conn.close()

    return len(messages)

def run_full_retrieval():
    """Run the full iris_memory_retrieval.py pipeline"""
    result = subprocess.run(
        ["python", "iris_memory_retrieval.py", "--top_k", "10", "--show", "true", "--insert", "false"],
        cwd="/iris-v3/backend/memory",
        capture_output=True,
        text=True,
        timeout=120
    )

    return result.stdout, result.stderr

def parse_injection_block(stdout):
    """Extract the injection block (top 10 memories) from output"""
    lines = stdout.split('\n')

    in_injection = False
    memories = []
    current_memory = []

    for line in lines:
        if '=== Injection Block ===' in line:
            in_injection = True
            continue

        if in_injection:
            if line.startswith('[Memory Score'):
                if current_memory:
                    memories.append('\n'.join(current_memory))
                current_memory = [line]
            elif line.startswith('--'):
                if current_memory:
                    memories.append('\n'.join(current_memory))
                    current_memory = []
            elif line.strip():
                current_memory.append(line)

    if current_memory:
        memories.append('\n'.join(current_memory))

    return memories

def evaluate_memories(memories, expected_topics, inappropriate_topics):
    """Evaluate if retrieved memories are appropriate"""
    relevant_count = 0
    irrelevant_count = 0

    for mem in memories:
        mem_lower = mem.lower()

        # Check if memory relates to expected topics
        if any(topic.lower() in mem_lower for topic in expected_topics):
            relevant_count += 1

        # Check if memory contains inappropriate topics
        if any(topic.lower() in mem_lower for topic in inappropriate_topics):
            irrelevant_count += 1

    total = len(memories)
    relevance_ratio = relevant_count / total if total > 0 else 0
    contamination_ratio = irrelevant_count / total if total > 0 else 0

    return {
        'total': total,
        'relevant': relevant_count,
        'irrelevant': irrelevant_count,
        'relevance_ratio': relevance_ratio,
        'contamination_ratio': contamination_ratio
    }

def test_full_pipeline():
    """Run full pipeline test across all sessions"""
    print("="*80)
    print("FULL PIPELINE VALIDATION - END-TO-END MEMORY RETRIEVAL")
    print("="*80)
    print()
    print("⚠️  WARNING: This test will temporarily modify chat_history")
    print("   All changes will be restored after testing")
    print()

    # Backup current conversation
    print("Backing up current conversation...")
    backup = backup_recent_messages(50)
    print(f"Backed up {len(backup)} messages\n")

    results = []

    try:
        for test_session in TEST_SESSIONS:
            print(f"\n{'='*80}")
            print(f"TESTING: {test_session['description']}")
            print(f"Session: {test_session['id']}")
            print('='*80)

            # Load session as current conversation
            print("Loading session messages...")
            msg_count = load_session_as_current(test_session['id'])
            print(f"Loaded {msg_count} messages as current conversation")

            # Run full retrieval pipeline
            print("\nRunning full memory retrieval pipeline...")
            stdout, stderr = run_full_retrieval()

            # Parse results
            memories = parse_injection_block(stdout)
            print(f"Retrieved {len(memories)} memories")

            # Evaluate
            eval_result = evaluate_memories(
                memories,
                test_session['expected_memory_topics'],
                test_session['inappropriate_topics']
            )

            print(f"\nRESULTS:")
            print(f"  Relevant memories: {eval_result['relevant']}/{eval_result['total']} ({eval_result['relevance_ratio']*100:.0f}%)")
            print(f"  Contamination: {eval_result['irrelevant']}/{eval_result['total']} ({eval_result['contamination_ratio']*100:.0f}%)")

            # Pass/fail criteria
            passed = eval_result['relevance_ratio'] >= 0.3 and eval_result['contamination_ratio'] < 0.3

            if passed:
                print(f"  ✓ PASS")
            else:
                print(f"  ✗ FAIL")
                if eval_result['relevance_ratio'] < 0.3:
                    print(f"     Reason: Low relevance ({eval_result['relevance_ratio']*100:.0f}% < 30%)")
                if eval_result['contamination_ratio'] >= 0.3:
                    print(f"     Reason: High contamination ({eval_result['contamination_ratio']*100:.0f}% >= 30%)")

            # Show sample memories
            print(f"\n  Sample retrieved memories:")
            for i, mem in enumerate(memories[:3], 1):
                preview = mem.split('\n')[1] if '\n' in mem else mem
                print(f"    {i}. {preview[:120]}...")

            results.append({
                'session': test_session['description'],
                'passed': passed,
                'eval': eval_result
            })

    finally:
        # Always restore original conversation
        print(f"\n\n{'='*80}")
        print("Restoring original conversation...")
        restore_messages(backup)
        print(f"Restored {len(backup)} messages")

    # Final summary
    print(f"\n\n{'='*80}")
    print("VALIDATION SUMMARY")
    print('='*80)

    passed_count = sum(1 for r in results if r['passed'])
    total_count = len(results)

    print(f"\nResults: {passed_count}/{total_count} tests passed ({passed_count/total_count*100:.0f}%)")
    print()

    for r in results:
        status = "✓ PASS" if r['passed'] else "✗ FAIL"
        print(f"{status} - {r['session']} ({r['eval']['relevance_ratio']*100:.0f}% relevant)")

    if passed_count == total_count:
        print(f"\n🎉 SUCCESS: Full pipeline works across all conversation types!")
        return 0
    elif passed_count >= total_count * 0.75:
        print(f"\n⚠️  PARTIAL: Most conversation types work well")
        return 1
    else:
        print(f"\n❌ FAILURE: Pipeline needs significant improvement")
        return 2

if __name__ == "__main__":
    import sys
    sys.exit(test_full_pipeline())
