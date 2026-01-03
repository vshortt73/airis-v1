#!/usr/bin/env python3
"""
Comprehensive Memory Retrieval Validation

Performs deep analysis of memory retrieval quality by:
1. Understanding what each conversation is about
2. Analyzing what memories were retrieved
3. Evaluating relevance and appropriateness
4. Providing detailed reasoning and examples
5. Generating a thorough report
"""

import sys
sys.path.insert(0, '/iris-v3/backend/memory')

import json
import subprocess
import psycopg2
from psycopg2.extras import DictCursor
import re

DB_CFG = dict(dbname="irisdb", user="irisuser", password="yourpassword", host="localhost", port=5432)

def analyze_conversation_topic(session_id):
    """
    Deeply analyze what a conversation is about by reading the actual messages
    """
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

    # Analyze message content to determine topics
    all_text = " ".join([m['message'].lower() for m in messages])

    # Define topic indicators
    topics = {
        'cruise_vacation': ['cruise', 'ship', 'vacation', 'cozumel', 'costa maya', 'caribbean', 'port', 'deck', 'mariner', 'royal caribbean'],
        'comfyui_technical': ['comfyui', 'workflow', 'node', 'upscale', 'model', 'image generation', 'lora', 'checkpoint'],
        'protocol_system': ['protocol', 'bravo', 'omega', 'theta', 'activate', 'deactivate', 'mode'],
        'ai_memory_system': ['memory', 'episodic', 'vault', 'recall', 'embedding', 'retrieval', 'cognitive'],
        'claude_discussion': ['claude', 'anthropic', 'stateless', 'consciousness', 'persistent'],
        'dream_module': ['dream module', 'synthesis', 'scenario', 'simulate', 'creative'],
        'trait_modification': ['trait', 'behavior', 'personality', 'modify', 'adjust'],
        'debugging': ['error', 'debug', 'fix', 'issue', 'problem', 'traceback']
    }

    detected_topics = []
    for topic_name, keywords in topics.items():
        keyword_count = sum(1 for kw in keywords if kw in all_text)
        if keyword_count >= 2:  # At least 2 keywords present
            detected_topics.append({
                'topic': topic_name,
                'keyword_matches': keyword_count,
                'keywords_found': [kw for kw in keywords if kw in all_text]
            })

    # Get sample messages
    user_messages = [m['message'] for m in messages if m['role'] == 'user']
    sample_messages = user_messages[:3] if len(user_messages) >= 3 else user_messages

    return {
        'session_id': session_id,
        'total_messages': len(messages),
        'detected_topics': sorted(detected_topics, key=lambda x: x['keyword_matches'], reverse=True),
        'sample_messages': sample_messages
    }

def run_retrieval_and_capture(session_id):
    """Run retrieval and capture full output"""
    result = subprocess.run(
        ['python', 'test_retrieval_from_session.py', session_id],
        capture_output=True,
        text=True,
        timeout=120
    )
    return result.stdout, result.stderr

def parse_retrieved_memories(stdout):
    """
    Parse retrieved memories with full content analysis
    """
    memories = []
    lines = stdout.split('\n')

    current_memory = None
    in_memory_block = False

    for i, line in enumerate(lines):
        # Look for memory ID line
        if line.startswith('ID ') and '|' in line and 'sim_score' in line:
            if current_memory:
                memories.append(current_memory)

            # Parse ID and score
            match = re.match(r'ID (\d+).*sim_score=([\d.]+).*age=([\d.]+)d', line)
            if match:
                current_memory = {
                    'id': match.group(1),
                    'sim_score': float(match.group(2)),
                    'age_days': float(match.group(3)),
                    'takeaway': '',
                    'context': '',
                    'event': ''
                }
                in_memory_block = True

        # Parse content fields
        elif in_memory_block and current_memory:
            if line.strip().startswith('Takeaway:'):
                current_memory['takeaway'] = line.split(':', 1)[1].strip() if ':' in line else ''
            elif line.strip().startswith('Context:'):
                current_memory['context'] = line.split(':', 1)[1].strip() if ':' in line else ''
            elif line.strip().startswith('Event:'):
                current_memory['event'] = line.split(':', 1)[1].strip() if ':' in line else ''
            elif line.startswith('----'):
                in_memory_block = False

    if current_memory:
        memories.append(current_memory)

    return memories

def analyze_memory_relevance(memory, conversation_topics):
    """
    Analyze whether a retrieved memory is relevant to the conversation
    """
    # Combine memory content
    memory_text = (memory['context'] + ' ' + memory['event'] + ' ' + memory['takeaway']).lower()

    # Check which topics this memory relates to
    topic_matches = []
    for topic_info in conversation_topics:
        topic_name = topic_info['topic']
        keywords = topic_info['keywords_found']

        # Count how many conversation keywords appear in this memory
        matches = [kw for kw in keywords if kw in memory_text]
        if matches:
            topic_matches.append({
                'topic': topic_name,
                'matched_keywords': matches
            })

    return {
        'memory_id': memory['id'],
        'is_relevant': len(topic_matches) > 0,
        'topic_matches': topic_matches,
        'memory_preview': memory['context'][:100] + '...' if len(memory['context']) > 100 else memory['context']
    }

def generate_detailed_report(test_results):
    """
    Generate comprehensive report with analysis and reasoning
    """
    report = []
    report.append("=" * 100)
    report.append("COMPREHENSIVE MEMORY RETRIEVAL VALIDATION REPORT")
    report.append("=" * 100)
    report.append("")

    for i, result in enumerate(test_results, 1):
        report.append(f"\n{'=' * 100}")
        report.append(f"TEST {i}: {result['session_id'][:16]}...")
        report.append('=' * 100)
        report.append("")

        # Conversation Analysis
        report.append("CONVERSATION ANALYSIS:")
        report.append(f"  Total messages: {result['conversation']['total_messages']}")
        report.append(f"  Detected topics:")
        for topic_info in result['conversation']['detected_topics']:
            report.append(f"    - {topic_info['topic']}: {topic_info['keyword_matches']} keyword matches")
            report.append(f"      Keywords: {', '.join(topic_info['keywords_found'][:5])}")

        report.append(f"\n  Sample user messages:")
        for j, msg in enumerate(result['conversation']['sample_messages'][:2], 1):
            preview = msg[:100] + '...' if len(msg) > 100 else msg
            report.append(f"    {j}. {preview}")

        # Retrieval Results
        report.append(f"\n\nRETRIEVAL RESULTS:")
        report.append(f"  Total memories retrieved: {result['total_retrieved']}")
        report.append(f"  Relevant memories: {result['relevant_count']} ({result['relevance_ratio']*100:.0f}%)")
        report.append(f"  Irrelevant memories: {result['irrelevant_count']} ({100-result['relevance_ratio']*100:.0f}%)")

        # Top relevant memories
        report.append(f"\n  TOP RELEVANT MEMORIES:")
        for j, mem in enumerate(result['relevant_examples'][:3], 1):
            report.append(f"\n    {j}. Memory ID {mem['memory_id']} (score: {mem.get('score', 'N/A')}, age: {mem.get('age', 'N/A')}d)")
            report.append(f"       Matched topics: {', '.join([m['topic'] for m in mem['topic_matches']])}")
            report.append(f"       Keywords found: {', '.join(mem['topic_matches'][0]['matched_keywords'][:3]) if mem['topic_matches'] else 'none'}")
            report.append(f"       Content: {mem['memory_preview']}")

        # Irrelevant memories (if any)
        if result['irrelevant_examples']:
            report.append(f"\n  IRRELEVANT MEMORIES (should not have been retrieved):")
            for j, mem in enumerate(result['irrelevant_examples'][:2], 1):
                report.append(f"\n    {j}. Memory ID {mem['memory_id']} (score: {mem.get('score', 'N/A')})")
                report.append(f"       ✗ No topic match - unrelated content")
                report.append(f"       Content: {mem['memory_preview']}")

        # Assessment
        report.append(f"\n\nASSESSMENT:")
        if result['relevance_ratio'] >= 0.7:
            report.append(f"  ✓ EXCELLENT: {result['relevance_ratio']*100:.0f}% relevance - system retrieving appropriate memories")
        elif result['relevance_ratio'] >= 0.5:
            report.append(f"  ⚠ ACCEPTABLE: {result['relevance_ratio']*100:.0f}% relevance - some irrelevant memories present")
        else:
            report.append(f"  ✗ POOR: {result['relevance_ratio']*100:.0f}% relevance - many irrelevant memories retrieved")

    # Overall summary
    report.append(f"\n\n{'=' * 100}")
    report.append("OVERALL ASSESSMENT")
    report.append('=' * 100)

    avg_relevance = sum(r['relevance_ratio'] for r in test_results) / len(test_results)
    passed = sum(1 for r in test_results if r['relevance_ratio'] >= 0.5)
    total = len(test_results)

    report.append(f"\nTests passed: {passed}/{total} ({passed/total*100:.0f}%)")
    report.append(f"Average relevance: {avg_relevance*100:.0f}%")
    report.append("")

    if avg_relevance >= 0.7:
        report.append("✓ SYSTEM PERFORMING WELL")
        report.append("  Memory retrieval is successfully matching conversation context.")
        report.append("  Retrieved memories are contextually appropriate.")
    elif avg_relevance >= 0.5:
        report.append("⚠ SYSTEM NEEDS IMPROVEMENT")
        report.append("  Memory retrieval is partially working but includes irrelevant memories.")
        report.append("  Consider refining similarity scoring or reranking logic.")
    else:
        report.append("✗ SYSTEM FAILING")
        report.append("  Memory retrieval is not matching conversation context.")
        report.append("  Major improvements needed to summary generation or retrieval logic.")

    return "\n".join(report)

def run_comprehensive_validation(test_file='test_sessions.json'):
    """Run comprehensive validation with deep analysis"""

    print("=" * 100)
    print("COMPREHENSIVE MEMORY RETRIEVAL VALIDATION")
    print("Performing deep analysis of retrieval quality...")
    print("=" * 100)
    print()

    # Load test sessions
    with open(test_file, 'r') as f:
        data = json.load(f)
    sessions = data['sessions']

    print(f"Testing {len(sessions)} sessions...\n")

    test_results = []

    for i, session in enumerate(sessions, 1):
        session_id = session['session_id']
        print(f"[{i}/{len(sessions)}] Analyzing session {session_id[:16]}...")

        # Analyze conversation
        conversation_analysis = analyze_conversation_topic(session_id)
        print(f"  Topics detected: {', '.join([t['topic'] for t in conversation_analysis['detected_topics'][:2]])}")

        # Run retrieval
        stdout, stderr = run_retrieval_and_capture(session_id)

        # Parse memories
        memories = parse_retrieved_memories(stdout)
        print(f"  Retrieved {len(memories)} memories")

        # Analyze relevance
        relevant_memories = []
        irrelevant_memories = []

        for memory in memories:
            analysis = analyze_memory_relevance(memory, conversation_analysis['detected_topics'])
            analysis['score'] = memory['sim_score']
            analysis['age'] = memory['age_days']

            if analysis['is_relevant']:
                relevant_memories.append(analysis)
            else:
                irrelevant_memories.append(analysis)

        relevance_ratio = len(relevant_memories) / len(memories) if memories else 0
        print(f"  Relevance: {relevance_ratio*100:.0f}% ({len(relevant_memories)}/{len(memories)} relevant)")

        test_results.append({
            'session_id': session_id,
            'conversation': conversation_analysis,
            'total_retrieved': len(memories),
            'relevant_count': len(relevant_memories),
            'irrelevant_count': len(irrelevant_memories),
            'relevance_ratio': relevance_ratio,
            'relevant_examples': relevant_memories[:5],
            'irrelevant_examples': irrelevant_memories[:3]
        })

    # Generate detailed report
    print("\n\nGenerating detailed report...")
    report = generate_detailed_report(test_results)

    # Save report
    report_file = 'validation_report.txt'
    with open(report_file, 'w') as f:
        f.write(report)

    print(f"\n✓ Report saved to {report_file}")
    print("\n" + "=" * 100)
    print("Report preview:")
    print("=" * 100)
    print(report)

if __name__ == "__main__":
    test_file = sys.argv[1] if len(sys.argv) > 1 else 'test_sessions.json'
    run_comprehensive_validation(test_file)
