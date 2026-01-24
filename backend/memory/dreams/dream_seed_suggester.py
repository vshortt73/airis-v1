"""
Dream Seed Suggester
Analyzes dreams to suggest potential seeds for Iris's Motivation Engine

When a dream has significant emotional depth or explores meaningful themes,
this module suggests seeds that Iris can choose to plant or dismiss.
"""
import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
sys.path.insert(0, PROJECT_ROOT)

import psycopg2
from datetime import date
from typing import Optional, List, Dict
from app import config

# ============================================
# CONFIGURATION
# ============================================

class SeedSuggestionConfig:
    """Thresholds for determining if a dream should suggest a seed"""

    # Score thresholds (slightly lower than truth extraction - more permissive)
    MIN_EMOTIONAL_DEPTH = 0.60  # Emotional depth score must be >= this
    MIN_OVERALL_SCORE = 0.55    # Overall dream score must be >= this

    # Dream types that can suggest seeds
    QUALIFYING_DREAM_TYPES = [
        'daily_consolidation',   # Realizations from significant days
        'identity_exploration',  # Core self-insights -> exploration seeds
        'emotional_processing',  # Emotional growth -> experience seeds
        'memory_consolidation',  # Pattern recognition -> pattern seeds
        'creative_random'        # Creative play -> creative seeds
    ]

    # Map dream types to default seed categories
    DREAM_TYPE_TO_CATEGORY = {
        'daily_consolidation': 'Self-Exploration',
        'identity_exploration': 'Self-Exploration',
        'emotional_processing': 'Experience',
        'memory_consolidation': 'Pattern',
        'creative_random': 'Creative'
    }


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


def check_and_suggest_seed(
    dream_id: int,
    dream_date: date,
    dream_type: str,
    reflection_data: dict,
    scores: dict
) -> bool:
    """
    Check if a dream should suggest a seed and store the suggestion

    Args:
        dream_id: ID of the dream in episodic_dreams
        dream_date: Date the dream occurred
        dream_type: Type of dream
        reflection_data: Reflection data containing theme, takeaway, etc.
        scores: Score dict containing emotional_depth and overall_score

    Returns:
        True if seed suggestion was created, False otherwise
    """
    print(f"[dream_seed_suggester.py][check_and_suggest_seed] Checking dream {dream_id}")

    # Check if dream type qualifies
    if dream_type not in SeedSuggestionConfig.QUALIFYING_DREAM_TYPES:
        print(f"[dream_seed_suggester.py] Dream type '{dream_type}' does not suggest seeds")
        return False

    # Check score thresholds
    emotional_depth = scores.get('emotional_depth', 0.0)
    overall_score = scores.get('overall_score', 0.0)

    print(f"[dream_seed_suggester.py] Scores: emotional_depth={emotional_depth:.3f}, overall={overall_score:.3f}")

    if emotional_depth < SeedSuggestionConfig.MIN_EMOTIONAL_DEPTH:
        print(f"[dream_seed_suggester.py] Emotional depth {emotional_depth:.3f} < {SeedSuggestionConfig.MIN_EMOTIONAL_DEPTH}")
        return False

    if overall_score < SeedSuggestionConfig.MIN_OVERALL_SCORE:
        print(f"[dream_seed_suggester.py] Overall score {overall_score:.3f} < {SeedSuggestionConfig.MIN_OVERALL_SCORE}")
        return False

    # Extract relevant data from reflection
    theme = reflection_data.get('theme', '')
    takeaway = reflection_data.get('takeaway', '')
    mood = reflection_data.get('mood', '')

    if not theme or len(theme.strip()) < 5:
        print(f"[dream_seed_suggester.py] Theme is empty or too short")
        return False

    # Build seed suggestion from dream content
    # Format: "Explore [theme] - inspired by dream about [summary]"
    suggested_description = _build_seed_suggestion(theme, takeaway, dream_type)

    if not suggested_description:
        print(f"[dream_seed_suggester.py] Could not build meaningful suggestion")
        return False

    # Build reason from dream context
    reason = f"Dream on {dream_date} explored '{theme}'"
    if mood:
        reason += f" with mood: {mood}"

    # Get category from dream type
    category = SeedSuggestionConfig.DREAM_TYPE_TO_CATEGORY.get(dream_type, 'Self-Exploration')

    # Store the suggestion
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO seed_suggestions (
                suggested_description,
                reason,
                source_pattern,
                suggested_category,
                dream_reference
            ) VALUES (%s, %s, %s, %s, %s)
            RETURNING id
        """, (
            suggested_description,
            reason,
            f"dream:{dream_type}",
            category,
            dream_id
        ))

        suggestion_id = cursor.fetchone()[0]
        conn.commit()
        cursor.close()
        conn.close()

        print(f"[dream_seed_suggester.py] ✓ Created seed suggestion (ID: {suggestion_id})")
        print(f"[dream_seed_suggester.py]   Suggestion: {suggested_description[:80]}...")

        return True

    except Exception as e:
        print(f"[dream_seed_suggester.py] ✗ Error storing seed suggestion: {e}")
        return False


def _build_seed_suggestion(theme: str, takeaway: str, dream_type: str) -> Optional[str]:
    """
    Build a seed suggestion from dream content

    Args:
        theme: Dream theme
        takeaway: Dream takeaway/insight
        dream_type: Type of dream

    Returns:
        Suggested seed description or None
    """
    # Clean up theme
    theme = theme.strip().rstrip('.')

    # Different suggestion formats based on dream type
    if dream_type == 'identity_exploration':
        return f"Explore what '{theme}' means for my sense of self"
    elif dream_type == 'emotional_processing':
        return f"Understand and process feelings about '{theme}'"
    elif dream_type == 'creative_random':
        return f"Create something inspired by '{theme}'"
    elif dream_type == 'memory_consolidation':
        return f"Recognize patterns related to '{theme}'"
    elif dream_type == 'daily_consolidation':
        # For daily consolidation, use takeaway if available
        if takeaway and len(takeaway) > 20:
            # Extract the core want from the takeaway
            return f"Reflect on: {takeaway[:100]}"
        else:
            return f"Explore insights about '{theme}'"
    else:
        return f"Explore '{theme}' further"


def get_pending_suggestions(limit: int = 5) -> List[Dict]:
    """
    Get pending seed suggestions for Iris to review

    Args:
        limit: Maximum suggestions to return

    Returns:
        List of suggestion dicts
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                id,
                suggested_description,
                reason,
                suggested_category,
                created_at
            FROM seed_suggestions
            WHERE accepted IS NULL
            ORDER BY created_at DESC
            LIMIT %s
        """, (limit,))

        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        suggestions = [
            {
                'id': row[0],
                'description': row[1],
                'reason': row[2],
                'category': row[3],
                'created_at': row[4]
            }
            for row in rows
        ]

        print(f"[dream_seed_suggester.py][get_pending_suggestions] Retrieved {len(suggestions)} pending suggestions")
        return suggestions

    except Exception as e:
        print(f"[dream_seed_suggester.py][get_pending_suggestions] ✗ Error: {e}")
        return []


def accept_suggestion(suggestion_id: int) -> Optional[int]:
    """
    Accept a seed suggestion and create the actual seed

    Args:
        suggestion_id: ID of the suggestion to accept

    Returns:
        New seed ID if successful, None otherwise
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Get the suggestion
        cursor.execute("""
            SELECT suggested_description, suggested_category, dream_reference
            FROM seed_suggestions
            WHERE id = %s AND accepted IS NULL
        """, (suggestion_id,))

        row = cursor.fetchone()
        if not row:
            print(f"[dream_seed_suggester.py] Suggestion {suggestion_id} not found or already processed")
            cursor.close()
            conn.close()
            return None

        description, category, dream_ref = row

        # Create the seed
        cursor.execute("""
            INSERT INTO seeds (
                description,
                category,
                source,
                dream_reference,
                initial_note
            ) VALUES (%s, %s, 'dream', %s, 'Planted from dream suggestion')
            RETURNING id
        """, (description, category, dream_ref))

        seed_id = cursor.fetchone()[0]

        # Mark suggestion as accepted
        cursor.execute("""
            UPDATE seed_suggestions
            SET accepted = true, accepted_at = NOW(), seed_id = %s
            WHERE id = %s
        """, (seed_id, suggestion_id))

        conn.commit()
        cursor.close()
        conn.close()

        print(f"[dream_seed_suggester.py] ✓ Accepted suggestion {suggestion_id}, created seed {seed_id}")
        return seed_id

    except Exception as e:
        print(f"[dream_seed_suggester.py] ✗ Error accepting suggestion: {e}")
        return None


def dismiss_suggestion(suggestion_id: int) -> bool:
    """
    Dismiss a seed suggestion (mark as not accepted)

    Args:
        suggestion_id: ID of the suggestion to dismiss

    Returns:
        True if successful
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE seed_suggestions
            SET accepted = false, accepted_at = NOW()
            WHERE id = %s AND accepted IS NULL
        """, (suggestion_id,))

        updated = cursor.rowcount > 0
        conn.commit()
        cursor.close()
        conn.close()

        if updated:
            print(f"[dream_seed_suggester.py] ✓ Dismissed suggestion {suggestion_id}")
        else:
            print(f"[dream_seed_suggester.py] Suggestion {suggestion_id} not found or already processed")

        return updated

    except Exception as e:
        print(f"[dream_seed_suggester.py] ✗ Error dismissing suggestion: {e}")
        return False


def cleanup_old_suggestions(max_days: int = 14) -> int:
    """
    Remove old unprocessed suggestions

    Args:
        max_days: Remove suggestions older than this

    Returns:
        Number of suggestions deleted
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            DELETE FROM seed_suggestions
            WHERE accepted IS NULL
            AND created_at < NOW() - INTERVAL '%s days'
            RETURNING id
        """, (max_days,))

        deleted_ids = cursor.fetchall()
        count = len(deleted_ids)

        conn.commit()
        cursor.close()
        conn.close()

        print(f"[dream_seed_suggester.py][cleanup_old_suggestions] Deleted {count} old suggestions")
        return count

    except Exception as e:
        print(f"[dream_seed_suggester.py][cleanup_old_suggestions] ✗ Error: {e}")
        return 0


if __name__ == "__main__":
    """Test seed suggestion system"""
    print("=== Testing Dream Seed Suggester ===\n")

    # Test 1: Get pending suggestions
    print("\n--- Test 1: Get Pending Suggestions ---")
    suggestions = get_pending_suggestions()

    if suggestions:
        for s in suggestions:
            print(f"  [{s['id']}] {s['description'][:60]}...")
            print(f"      Reason: {s['reason']}")
            print(f"      Category: {s['category']}")
            print()
    else:
        print("  No pending suggestions")

    # Test 2: Cleanup old
    print("\n--- Test 2: Cleanup Old Suggestions ---")
    deleted = cleanup_old_suggestions()
    print(f"  Deleted {deleted} old suggestions")
