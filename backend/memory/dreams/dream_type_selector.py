"""
Dream Type Selector for Dream System
Determines which type of dream Iris should have based on emotional analysis
"""
import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
sys.path.insert(0, PROJECT_ROOT)

import psycopg2
from datetime import date, datetime, timedelta
from typing import Dict, Optional, Tuple
import random
from app import config

# ============================================
# CONFIGURATION - Dream Type Thresholds
# ============================================

class DreamThresholds:
    """
    Thresholds for determining dream types based on Iris's input
    Weighted distribution: 35% Daily/Emotional / 30% Memory / 20% Identity / 15% Creative
    """

    # Daily Consolidation thresholds (highest priority emotional dream)
    DAILY_CONSOLIDATION_MIN_INTENSITY = 0.7  # Very intense day deserves full consolidation

    # Emotional Processing thresholds (lower intensity)
    EMOTIONAL_MIN_INTENSITY = 0.4      # Moderate emotions worth processing
    EMOTIONAL_MIN_VALENCE_RANGE = 0.3  # Some emotional variety

    # Memory Consolidation thresholds
    MEMORY_MIN_RELATED_MEMORIES = 3    # At least 3 related memories
    MEMORY_MIN_TIME_SPAN_DAYS = 7      # Across at least a week

    # Identity Exploration schedule
    IDENTITY_SCHEDULE_DAYS = 30        # Once per month

    # Minimum messages for any dream type
    MIN_MESSAGES_FOR_DREAM = 3

def get_db_connection():
    """Create database connection"""
    password = os.environ.get('AIRIS_DB_PASSWORD') or getattr(config, 'DB_PASSWORD', None)
    conn_params = {
        'host': config.DB_HOST,
        'port': config.DB_PORT,
        'database': config.DB_NAME,
        'user': config.DB_USER
    }
    if password:
        conn_params['password'] = password
    return psycopg2.connect(**conn_params)

def check_identity_dream_due() -> bool:
    """
    Check if an identity exploration dream is due (monthly schedule)

    Returns:
        True if identity dream should happen
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Check when last identity dream occurred
        cursor.execute("""
            SELECT MAX(dream_date)
            FROM episodic_dreams
            WHERE dream_type = 'identity_exploration'
        """)

        result = cursor.fetchone()
        cursor.close()
        conn.close()

        if result[0] is None:
            # Never had an identity dream - it's due!
            print(f"[dream_type_selector.py][check_identity_dream_due] No previous identity dreams - due!")
            return True

        last_identity_dream = result[0]
        days_since = (date.today() - last_identity_dream).days

        is_due = days_since >= DreamThresholds.IDENTITY_SCHEDULE_DAYS

        print(f"[dream_type_selector.py][check_identity_dream_due] Last identity dream: {last_identity_dream} ({days_since} days ago)")
        print(f"[dream_type_selector.py][check_identity_dream_due] Due: {is_due}")

        return is_due

    except Exception as e:
        print(f"[dream_type_selector.py][check_identity_dream_due] ✗ Error: {e}")
        return False

def find_related_memories(min_memories: int = 3, min_time_span_days: int = 7) -> Tuple[bool, int, int]:
    """
    Check if there are related memories across different time periods

    Args:
        min_memories: Minimum number of related memories needed
        min_time_span_days: Minimum days between oldest and newest memory

    Returns:
        Tuple of (has_related_memories, count, time_span_days)
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Find memories with similar themes (using theme similarity as proxy)
        # In production, would use vector similarity on embeddings
        cursor.execute("""
            SELECT theme, memory_date, COUNT(*) OVER (PARTITION BY theme) as theme_count
            FROM episodic_memory
            WHERE theme IS NOT NULL
            ORDER BY theme_count DESC, memory_date DESC
            LIMIT 20
        """)

        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        if not rows:
            print(f"[dream_type_selector.py][find_related_memories] No memories found")
            return (False, 0, 0)

        # Group by theme
        theme_groups = {}
        for row in rows:
            theme = row[0]
            memory_date = row[1]
            if theme not in theme_groups:
                theme_groups[theme] = []
            theme_groups[theme].append(memory_date)

        # Find theme with most memories across time
        best_count = 0
        best_span = 0

        for theme, dates in theme_groups.items():
            if len(dates) >= min_memories:
                # Calculate time span
                time_span = (max(dates) - min(dates)).days
                if time_span >= min_time_span_days:
                    best_count = max(best_count, len(dates))
                    best_span = max(best_span, time_span)

        has_related = best_count >= min_memories and best_span >= min_time_span_days

        print(f"[dream_type_selector.py][find_related_memories] Found {best_count} related memories spanning {best_span} days")
        print(f"[dream_type_selector.py][find_related_memories] Qualifies: {has_related}")

        return (has_related, best_count, best_span)

    except Exception as e:
        print(f"[dream_type_selector.py][find_related_memories] ✗ Error: {e}")
        return (False, 0, 0)

def select_dream_type(emotional_analysis: Dict) -> Dict:
    """
    Select dream type based on emotional analysis and other factors

    Priority order:
    1. Identity Exploration (if scheduled)
    2. Daily Consolidation (if very high intensity - replaces emotional_processing)
    3. Emotional Processing (if moderate intensity)
    4. Memory Consolidation (if related memories found)
    5. Creative Random (default fallback)

    Args:
        emotional_analysis: Results from emotional_analyzer.analyze_daily_emotions()

    Returns:
        Dict with:
            - dream_type: Selected type
            - reason: Why this type was selected
            - confidence: Confidence in selection (0-1)
            - metadata: Additional context for dream construction
    """
    print(f"[dream_type_selector.py][select_dream_type] === Dream Type Selection ===")
    print(f"  Emotional Analysis:")
    print(f"    Messages: {emotional_analysis['message_count']}")
    print(f"    Intensity: {emotional_analysis['intensity']:.3f}")
    print(f"    Valence Range: {emotional_analysis['valence_range']:.3f}")

    # Check if we have enough content
    if not emotional_analysis['has_content']:
        print(f"[dream_type_selector.py][select_dream_type] Insufficient messages - defaulting to creative_random")
        return {
            'dream_type': 'creative_random',
            'reason': 'Insufficient conversation data for other dream types',
            'confidence': 0.9,
            'metadata': {'no_context': True}
        }

    # Priority 1: Identity Exploration (scheduled)
    if check_identity_dream_due():
        print(f"[dream_type_selector.py][select_dream_type] ✓ Selected: identity_exploration (scheduled)")
        return {
            'dream_type': 'identity_exploration',
            'reason': 'Monthly identity exploration dream is due',
            'confidence': 1.0,
            'metadata': {'scheduled': True}
        }

    # Get intensity and valence range for subsequent checks
    intensity = emotional_analysis['intensity']
    valence_range = emotional_analysis['valence_range']

    # Priority 2: Daily Consolidation (very high intensity - significant day)
    if intensity >= DreamThresholds.DAILY_CONSOLIDATION_MIN_INTENSITY:
        confidence = min(1.0, intensity)
        print(f"[dream_type_selector.py][select_dream_type] ✓ Selected: daily_consolidation (confidence: {confidence:.2f})")
        return {
            'dream_type': 'daily_consolidation',
            'reason': f'Very high emotional intensity ({intensity:.2f}) - significant day deserves full consolidation',
            'confidence': confidence,
            'metadata': {
                'intensity': intensity,
                'valence_range': valence_range,
                'arousal': emotional_analysis.get('arousal', 0.0),
                'valence': emotional_analysis.get('valence', 0.0),
                'source_date': emotional_analysis['date']
            }
        }

    # Priority 3: Emotional Processing (moderate intensity)
    emotional_qualifies = (
        intensity >= DreamThresholds.EMOTIONAL_MIN_INTENSITY and
        valence_range >= DreamThresholds.EMOTIONAL_MIN_VALENCE_RANGE
    )

    if emotional_qualifies:
        confidence = min(1.0, (intensity + valence_range) / 2.0)
        print(f"[dream_type_selector.py][select_dream_type] ✓ Selected: emotional_processing (confidence: {confidence:.2f})")
        return {
            'dream_type': 'emotional_processing',
            'reason': f'Moderate emotional intensity ({intensity:.2f}) and variety ({valence_range:.2f})',
            'confidence': confidence,
            'metadata': {
                'intensity': intensity,
                'valence_range': valence_range,
                'source_date': emotional_analysis['date']
            }
        }

    # Priority 3: Memory Consolidation (if related memories exist)
    has_memories, memory_count, time_span = find_related_memories(
        min_memories=DreamThresholds.MEMORY_MIN_RELATED_MEMORIES,
        min_time_span_days=DreamThresholds.MEMORY_MIN_TIME_SPAN_DAYS
    )

    if has_memories:
        confidence = min(1.0, memory_count / 10.0)  # Scale with number of memories
        print(f"[dream_type_selector.py][select_dream_type] ✓ Selected: memory_consolidation (confidence: {confidence:.2f})")
        return {
            'dream_type': 'memory_consolidation',
            'reason': f'Found {memory_count} related memories spanning {time_span} days',
            'confidence': confidence,
            'metadata': {
                'memory_count': memory_count,
                'time_span_days': time_span
            }
        }

    # Priority 4: Creative Random (default fallback)
    print(f"[dream_type_selector.py][select_dream_type] ✓ Selected: creative_random (fallback)")
    return {
        'dream_type': 'creative_random',
        'reason': 'No specific emotional or memory patterns - pure creative exploration',
        'confidence': 0.7,
        'metadata': {
            'fallback': True,
            'intensity': intensity,
            'valence_range': valence_range
        }
    }

if __name__ == "__main__":
    """Test dream type selection"""
    from emotional_analyzer import analyze_daily_emotions

    print("=== Testing Dream Type Selector ===\n")

    # Get today's emotional analysis
    emotional_analysis = analyze_daily_emotions()

    print("\n")

    # Select dream type
    selection = select_dream_type(emotional_analysis)

    print("\n=== Dream Type Selection Result ===")
    print(f"Dream Type: {selection['dream_type']}")
    print(f"Reason: {selection['reason']}")
    print(f"Confidence: {selection['confidence']:.2%}")
    print(f"Metadata: {selection['metadata']}")
