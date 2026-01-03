#!/usr/bin/env python3
"""
Memory Retrieval Validation - Test across different conversation types

This script tests the retrieval system by:
1. Loading conversations from different sessions
2. Running retrieval pipeline on each
3. Evaluating if retrieved memories are contextually appropriate
"""

import sys
sys.path.insert(0, '/iris-v3/backend/memory')

import psycopg2
from psycopg2.extras import DictCursor
from sentence_transformers import SentenceTransformer
import json

DB_CFG = dict(dbname="irisdb", user="irisuser", password="yourpassword", host="localhost", port=5432)

# Import the retrieval functions
from iris_memory_retrieval import run_lens_stage, run_emotion_stage, get_summaries

def load_session_conversation(session_id):
    """Load conversation from a specific session"""
    conn = psycopg2.connect(**DB_CFG)
    cur = conn.cursor(cursor_factory=DictCursor)

    cur.execute("""
        SELECT role, message
        FROM chat_history
        WHERE session_id = %s
        ORDER BY c_timestamp ASC
    """, (session_id,))

    messages = cur.fetchall()
    cur.close()
    conn.close()

    convo = "\n".join([f"{m['role'].upper()}: {m['message']}" for m in messages])
    return convo, len(messages)

def test_session_retrieval(session_id, description, expected_keywords):
    """Test retrieval for a specific session"""
    print(f"\n{'='*80}")
    print(f"TEST: {description}")
    print(f"Session ID: {session_id}")
    print(f"Expected keywords: {', '.join(expected_keywords)}")
    print('='*80)

    # Load conversation
    convo, msg_count = load_session_conversation(session_id)
    print(f"\nLoaded {msg_count} messages")
    print(f"Preview: {convo[:150]}...\n")

    # Run retrieval pipeline stages
    print("Running retrieval pipeline...")

    # Stage 1: Lens
    print("  1. Lens extraction...")
    lens = run_lens_stage(convo)
    print(f"     Keywords: {lens.get('keywords', [])}")
    print(f"     Facets: {lens.get('facets', [])}")

    # Stage 2: Emotion
    print("  2. Emotion scoring...")
    emo_results, valence, arousal, top_emotion, json_results = run_emotion_stage(convo)
    print(f"     Valence: {valence:.3f}, Arousal: {arousal:.3f}")
    print(f"     Emotion: {top_emotion}")

    # Stage 3: Summaries
    print("  3. Summary generation...")
    summaries = get_summaries(convo)
    mr = summaries.get('MemoryRecall', {})
    print(f"     Context: {mr.get('Context', '')[:100]}...")
    print(f"     Event: {mr.get('Event', '')[:100]}...")

    # Check if summaries contain expected keywords
    summary_text = (mr.get('Context', '') + ' ' + mr.get('Event', '') + ' ' +
                   mr.get('Significance', '') + ' ' + mr.get('Takeaway', '')).lower()

    matched_keywords = [kw for kw in expected_keywords if kw.lower() in summary_text]
    missed_keywords = [kw for kw in expected_keywords if kw.lower() not in summary_text]

    print(f"\n  ✓ Matched keywords: {matched_keywords}")
    if missed_keywords:
        print(f"  ✗ Missed keywords: {missed_keywords}")

    # Evaluate
    match_ratio = len(matched_keywords) / len(expected_keywords) if expected_keywords else 0

    print(f"\n  RESULT: {len(matched_keywords)}/{len(expected_keywords)} keywords found ({match_ratio*100:.0f}%)")

    if match_ratio >= 0.5:
        print(f"  ✓ PASS - Summaries preserve concrete details")
    else:
        print(f"  ✗ FAIL - Summaries too abstract, missing key terms")

    return {
        'session_id': session_id,
        'description': description,
        'match_ratio': match_ratio,
        'matched': matched_keywords,
        'missed': missed_keywords,
        'summaries': mr
    }

def run_validation_suite():
    """Run full validation across different conversation types"""

    print("="*80)
    print("MEMORY RETRIEVAL VALIDATION SUITE")
    print("Testing summary generation across diverse conversation types")
    print("="*80)

    test_cases = [
        {
            'session_id': 'b211f291-4711-4a01-895f-ad7763b49190',
            'description': 'Cruise vacation planning',
            'expected': ['cruise', 'vacation', 'june']
        },
        {
            'session_id': '8f12dcff-8730-40d7-b461-81b732cf0597',
            'description': 'ComfyUI technical work',
            'expected': ['comfyui', 'model', 'image', 'upscal']
        },
        {
            'session_id': 'c812c24e-430f-4258-bd94-47a3684d0b02',
            'description': 'Claude-Iris philosophical discussion',
            'expected': ['claude', 'memory', 'consciousness', 'stateless']
        },
        {
            'session_id': '5aa3b0b5-4899-4dbe-83f6-4f1f70a3ac6a',
            'description': 'Protocol Bravo system testing',
            'expected': ['protocol', 'bravo', 'activate']
        }
    ]

    results = []

    for test in test_cases:
        result = test_session_retrieval(
            test['session_id'],
            test['description'],
            test['expected']
        )
        results.append(result)

    # Summary report
    print(f"\n\n{'='*80}")
    print("VALIDATION SUMMARY")
    print('='*80)

    passed = sum(1 for r in results if r['match_ratio'] >= 0.5)
    total = len(results)

    print(f"\nResults: {passed}/{total} tests passed ({passed/total*100:.0f}%)")
    print()

    for r in results:
        status = "✓ PASS" if r['match_ratio'] >= 0.5 else "✗ FAIL"
        print(f"{status} - {r['description']} ({r['match_ratio']*100:.0f}% keywords matched)")

    if passed == total:
        print(f"\n🎉 SUCCESS: All conversation types generate appropriate concrete summaries!")
    elif passed >= total * 0.75:
        print(f"\n⚠️  PARTIAL: Most types work, but some need adjustment")
    else:
        print(f"\n❌ FAILURE: Summary generation needs further refinement")

    return results

if __name__ == "__main__":
    run_validation_suite()
