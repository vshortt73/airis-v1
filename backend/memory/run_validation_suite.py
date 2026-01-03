#!/usr/bin/env python3
"""
Run Validation Suite

Executes memory retrieval tests on all sessions in the test bank
and evaluates whether retrieved memories are appropriate.
"""

import sys
import json
import subprocess
import re

def load_test_sessions(filename='test_sessions.json'):
    """Load test session bank from JSON"""
    with open(filename, 'r') as f:
        data = json.load(f)
    return data['sessions']

def run_retrieval_test(session_id):
    """Run retrieval for a single session and capture output"""
    result = subprocess.run(
        ['python', 'test_retrieval_from_session.py', session_id],
        capture_output=True,
        text=True,
        timeout=120
    )
    return result.stdout, result.stderr, result.returncode

def parse_retrieval_output(stdout):
    """Parse the output to extract retrieved memories"""
    memories = []

    # Count memory blocks by looking for ID patterns
    lines = stdout.split('\n')

    for line in lines:
        # Look for memory ID lines like "ID 29761 | sim_score=0.413..."
        if line.startswith('ID ') and '|' in line and 'sim_score' in line:
            memories.append(line)

    return memories

def evaluate_session(session_id, stdout, stderr):
    """Evaluate if the retrieval was successful"""

    # Check for errors
    if stderr and ('error' in stderr.lower() or 'traceback' in stderr.lower()):
        return {
            'session_id': session_id,
            'status': 'ERROR',
            'error': stderr[:200]
        }

    # Check if retrieval completed
    if '✓ Retrieval complete' in stdout:
        # Parse summaries from output
        summaries_match = re.search(r'Context: (.{50,150})', stdout)
        context = summaries_match.group(1) if summaries_match else 'N/A'

        # Parse retrieved memories
        memories = parse_retrieval_output(stdout)

        return {
            'session_id': session_id,
            'status': 'SUCCESS',
            'summary_context': context,
            'memory_count': len(memories),
            'has_memories': len(memories) >= 5  # Should retrieve at least 5 memories
        }
    else:
        return {
            'session_id': session_id,
            'status': 'INCOMPLETE',
            'note': 'Retrieval did not complete'
        }

def run_validation_suite(test_file='test_sessions.json'):
    """Run full validation suite"""

    print("="*80)
    print("VALIDATION SUITE - FULL PIPELINE TESTING")
    print("="*80)
    print()

    # Load test sessions
    print(f"Loading test sessions from {test_file}...")
    sessions = load_test_sessions(test_file)
    print(f"Loaded {len(sessions)} test sessions\n")

    results = []

    for i, session in enumerate(sessions, 1):
        session_id = session['session_id']
        print(f"\n{'='*80}")
        print(f"TEST {i}/{len(sessions)}: Session {session_id[:16]}...")
        print(f"  Messages: {session['message_count']}, Age: {session['days_ago']:.1f} days")
        print('='*80)

        try:
            # Run retrieval
            stdout, stderr, returncode = run_retrieval_test(session_id)

            # Evaluate
            eval_result = evaluate_session(session_id, stdout, stderr)
            results.append(eval_result)

            # Print result
            if eval_result['status'] == 'SUCCESS':
                print(f"\n✓ SUCCESS")
                print(f"  Summary: {eval_result['summary_context'][:80]}...")
                print(f"  Memories retrieved: {eval_result['memory_count']}")
            elif eval_result['status'] == 'ERROR':
                print(f"\n✗ ERROR")
                print(f"  {eval_result['error'][:150]}...")
            else:
                print(f"\n⚠  {eval_result['status']}")
                print(f"  {eval_result.get('note', '')}")

        except subprocess.TimeoutExpired:
            print(f"\n✗ TIMEOUT")
            results.append({'session_id': session_id, 'status': 'TIMEOUT'})

        except Exception as e:
            print(f"\n✗ EXCEPTION: {e}")
            results.append({'session_id': session_id, 'status': 'EXCEPTION', 'error': str(e)})

    # Summary
    print(f"\n\n{'='*80}")
    print("VALIDATION SUMMARY")
    print('='*80)

    success_count = sum(1 for r in results if r['status'] == 'SUCCESS' and r.get('has_memories'))
    error_count = sum(1 for r in results if r['status'] in ['ERROR', 'TIMEOUT', 'EXCEPTION'])
    total = len(results)

    print(f"\nResults: {success_count}/{total} successful ({success_count/total*100:.0f}%)")
    print(f"  Errors: {error_count}")
    print()

    for i, r in enumerate(results, 1):
        status_icon = {
            'SUCCESS': '✓',
            'ERROR': '✗',
            'TIMEOUT': '⏱',
            'EXCEPTION': '✗',
            'INCOMPLETE': '⚠'
        }.get(r['status'], '?')

        session_short = r['session_id'][:16]
        print(f"{status_icon} Test {i}: {session_short}... - {r['status']}")

    # Overall assessment
    print()
    if success_count == total:
        print("🎉 EXCELLENT: All tests passed!")
        return 0
    elif success_count >= total * 0.8:
        print("✓ GOOD: Most tests passed")
        return 0
    elif success_count >= total * 0.6:
        print("⚠️  ACCEPTABLE: Majority passed, but needs improvement")
        return 1
    else:
        print("❌ POOR: System needs significant work")
        return 2

if __name__ == "__main__":
    test_file = sys.argv[1] if len(sys.argv) > 1 else 'test_sessions.json'

    try:
        exit_code = run_validation_suite(test_file)
        sys.exit(exit_code)
    except FileNotFoundError:
        print(f"Error: Test file '{test_file}' not found")
        print(f"Run: python generate_test_sessions.py")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
