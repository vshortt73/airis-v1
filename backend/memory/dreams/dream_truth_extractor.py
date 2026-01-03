"""
Dream Truth Extractor
Extracts high-impact takeaways from dreams for temporary system prompt influence
"""
import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
sys.path.insert(0, PROJECT_ROOT)

import psycopg2
from datetime import date
from typing import Optional
from app import config

# ============================================
# CONFIGURATION
# ============================================

class TruthExtractionConfig:
    """Thresholds for determining if a dream creates a lasting truth"""

    # Score thresholds (start conservative - high bar for qualification)
    MIN_EMOTIONAL_DEPTH = 0.75  # Emotional depth score must be >= this
    MIN_OVERALL_SCORE = 0.70    # Overall dream score must be >= this

    # Dream types that can contribute truths
    QUALIFYING_DREAM_TYPES = [
        'daily_consolidation',   # High-value realizations about significant days
        'identity_exploration',  # Core self-insights
        'emotional_processing',  # Emotional growth insights
        'memory_consolidation'   # Pattern recognition insights
    ]

    # Creative random dreams are excluded (just play, not meaningful takeaways)

def get_db_connection():
    """Create database connection"""
    password = os.environ.get('IRIS_DB_PASSWORD') or getattr(config, 'DB_PASSWORD', None)
    conn_params = {
        'host': config.DB_HOST,
        'port': config.DB_PORT,
        'database': config.DB_NAME,
        'user': config.DB_USER
    }
    if password:
        conn_params['password'] = password
    return psycopg2.connect(**conn_params)

def check_and_extract_truth(
    dream_id: int,
    dream_date: date,
    dream_type: str,
    reflection_data: dict,
    scores: dict
) -> bool:
    """
    Check if a dream qualifies for truth extraction and store if it does

    Args:
        dream_id: ID of the dream in episodic_dreams
        dream_date: Date the dream occurred
        dream_type: Type of dream
        reflection_data: Reflection data containing 'takeaway'
        scores: Score dict containing 'emotional_depth' and 'overall_score'

    Returns:
        True if truth was extracted and stored, False otherwise
    """
    print(f"[dream_truth_extractor.py][check_and_extract_truth] Checking dream {dream_id}")

    # Check if dream type qualifies
    if dream_type not in TruthExtractionConfig.QUALIFYING_DREAM_TYPES:
        print(f"[dream_truth_extractor.py] ✗ Dream type '{dream_type}' does not qualify for truth extraction")
        return False

    # Check score thresholds
    emotional_depth = scores.get('emotional_depth', 0.0)
    overall_score = scores.get('overall_score', 0.0)

    print(f"[dream_truth_extractor.py] Scores: emotional_depth={emotional_depth:.3f}, overall={overall_score:.3f}")

    if emotional_depth < TruthExtractionConfig.MIN_EMOTIONAL_DEPTH:
        print(f"[dream_truth_extractor.py] ✗ Emotional depth {emotional_depth:.3f} < {TruthExtractionConfig.MIN_EMOTIONAL_DEPTH}")
        return False

    if overall_score < TruthExtractionConfig.MIN_OVERALL_SCORE:
        print(f"[dream_truth_extractor.py] ✗ Overall score {overall_score:.3f} < {TruthExtractionConfig.MIN_OVERALL_SCORE}")
        return False

    # Extract takeaway
    takeaway = reflection_data.get('takeaway', '')

    if not takeaway or len(takeaway.strip()) < 10:
        print(f"[dream_truth_extractor.py] ✗ Takeaway is empty or too short")
        return False

    # Store the truth
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO dream_truths (dream_id, dream_date, takeaway, emotional_score, overall_score)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
        """, (dream_id, dream_date, takeaway, emotional_depth, overall_score))

        truth_id = cursor.fetchone()[0]
        conn.commit()
        cursor.close()
        conn.close()

        print(f"[dream_truth_extractor.py] ✓ Extracted dream truth (ID: {truth_id})")
        print(f"[dream_truth_extractor.py]   Takeaway: {takeaway[:100]}...")

        return True

    except Exception as e:
        print(f"[dream_truth_extractor.py] ✗ Error storing dream truth: {e}")
        return False

def get_recent_dream_truths(limit: int = 5, max_days: int = 7) -> list:
    """
    Get recent dream truths for system prompt

    Args:
        limit: Maximum number of truths to return
        max_days: Only include truths from last N days

    Returns:
        List of dicts with 'date', 'takeaway', 'score'
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT dream_date, takeaway, overall_score
            FROM dream_truths
            WHERE created_at >= NOW() - INTERVAL '%s days'
            ORDER BY created_at DESC
            LIMIT %s
        """, (max_days, limit))

        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        truths = [
            {
                'date': row[0],
                'takeaway': row[1],
                'score': row[2]
            }
            for row in rows
        ]

        print(f"[dream_truth_extractor.py][get_recent_dream_truths] Retrieved {len(truths)} recent truths")

        return truths

    except Exception as e:
        print(f"[dream_truth_extractor.py][get_recent_dream_truths] ✗ Error: {e}")
        return []

def cleanup_expired_truths() -> int:
    """
    Remove dream truths older than 7 days (cleanup maintenance)

    Returns:
        Number of truths deleted
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            DELETE FROM dream_truths
            WHERE expires_at < NOW()
            RETURNING id
        """)

        deleted_ids = cursor.fetchall()
        count = len(deleted_ids)

        conn.commit()
        cursor.close()
        conn.close()

        print(f"[dream_truth_extractor.py][cleanup_expired_truths] Deleted {count} expired truths")

        return count

    except Exception as e:
        print(f"[dream_truth_extractor.py][cleanup_expired_truths] ✗ Error: {e}")
        return 0

if __name__ == "__main__":
    """Test truth extraction system"""
    print("=== Testing Dream Truth Extractor ===\n")

    # Test 1: Get recent truths
    print("\n--- Test 1: Get Recent Truths ---")
    truths = get_recent_dream_truths()

    if truths:
        for truth in truths:
            print(f"  [{truth['date']}] (score: {truth['score']:.2f})")
            print(f"  → {truth['takeaway']}")
            print()
    else:
        print("  No recent dream truths found")

    # Test 2: Cleanup expired
    print("\n--- Test 2: Cleanup Expired Truths ---")
    deleted = cleanup_expired_truths()
    print(f"  Deleted {deleted} expired truths")
