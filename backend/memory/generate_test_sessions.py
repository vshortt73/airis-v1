#!/usr/bin/env python3
"""
Generate Test Session Bank

Creates a JSON file with randomly selected session IDs for testing.
Stratifies by:
- Message count (short, medium, long conversations)
- Recency (recent, week old, older)
"""

import sys
import psycopg2
from psycopg2.extras import DictCursor
import json
import random

DB_CFG = dict(dbname="irisdb", user="irisuser", password="yourpassword", host="localhost", port=5432)

def get_sessions_stratified(total_sessions=10):
    """Get stratified sample of sessions"""

    conn = psycopg2.connect(**DB_CFG)
    cur = conn.cursor(cursor_factory=DictCursor)

    # Get all sessions with metadata
    cur.execute("""
        SELECT
            session_id,
            COUNT(*) as message_count,
            MIN(c_timestamp) as session_start,
            MAX(c_timestamp) as session_end,
            EXTRACT(epoch FROM (NOW() - MAX(c_timestamp)))/86400 as days_ago
        FROM chat_history
        WHERE session_id IS NOT NULL
        GROUP BY session_id
        HAVING COUNT(*) >= 8  -- At least 8 messages for meaningful conversation
        ORDER BY session_start DESC
        LIMIT 100
    """)

    all_sessions = [dict(row) for row in cur.fetchall()]
    cur.close()
    conn.close()

    # Stratify by recency
    recent = [s for s in all_sessions if s['days_ago'] < 2]
    week_old = [s for s in all_sessions if 2 <= s['days_ago'] < 7]
    older = [s for s in all_sessions if s['days_ago'] >= 7]

    # Stratify by length
    short = [s for s in all_sessions if s['message_count'] < 12]
    medium = [s for s in all_sessions if 12 <= s['message_count'] < 20]
    long = [s for s in all_sessions if s['message_count'] >= 20]

    print(f"Session pool:")
    print(f"  Recent (< 2 days): {len(recent)}")
    print(f"  Week old (2-7 days): {len(week_old)}")
    print(f"  Older (> 7 days): {len(older)}")
    print(f"  Short (< 12 msgs): {len(short)}")
    print(f"  Medium (12-20 msgs): {len(medium)}")
    print(f"  Long (> 20 msgs): {len(long)}")
    print()

    # Select stratified sample
    selected = []
    sessions_per_stratum = total_sessions // 3

    # By recency
    if recent:
        selected.extend(random.sample(recent, min(sessions_per_stratum, len(recent))))
    if week_old:
        selected.extend(random.sample(week_old, min(sessions_per_stratum, len(week_old))))
    if older:
        selected.extend(random.sample(older, min(sessions_per_stratum, len(older))))

    # Deduplicate and limit to total
    selected = list({s['session_id']: s for s in selected}.values())[:total_sessions]

    return selected

def save_test_sessions(sessions, filename='test_sessions.json'):
    """Save sessions to JSON file"""
    from datetime import datetime

    test_data = {
        'generated_at': datetime.now().isoformat(),
        'total_sessions': len(sessions),
        'sessions': []
    }

    for session in sessions:
        test_data['sessions'].append({
            'session_id': session['session_id'],
            'message_count': session['message_count'],
            'days_ago': float(session['days_ago']),
            'session_start': str(session['session_start']),
            'session_end': str(session['session_end'])
        })

    with open(filename, 'w') as f:
        json.dump(test_data, f, indent=2)

    return filename

def main():
    print("="*80)
    print("GENERATE TEST SESSION BANK")
    print("="*80)
    print()

    # Get stratified sample
    sessions = get_sessions_stratified(total_sessions=10)

    print(f"Selected {len(sessions)} test sessions:")
    print()

    for i, s in enumerate(sessions, 1):
        print(f"{i:2}. Session {s['session_id'][:8]}... "
              f"| {s['message_count']:2} msgs | {s['days_ago']:5.1f} days ago")

    # Save to file
    filename = save_test_sessions(sessions)
    print()
    print(f"✓ Saved to {filename}")
    print()
    print("To run validation:")
    print(f"  python run_validation_suite.py {filename}")

if __name__ == "__main__":
    main()
