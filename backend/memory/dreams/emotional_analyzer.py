"""
Emotional Analyzer for Dream System
Analyzes today's emotional content to inform dream type selection
"""
import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
sys.path.insert(0, PROJECT_ROOT)

import psycopg2
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional
from app import config

# Import existing psychological scoring system
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'backend', 'memory', 'new'))
from psychological_scoring_transformers import (
    calculate_valence_transformer,
    calculate_arousal_transformer,
    load_model,
    ScoringConfig
)

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

def get_todays_messages(target_date: Optional[date] = None) -> List[Dict]:
    """
    Retrieve all messages from a specific day

    Args:
        target_date: Date to analyze (defaults to today)

    Returns:
        List of message dicts with 'role', 'message', 'timestamp'
    """
    if target_date is None:
        target_date = date.today()

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Get all messages from target date
        cursor.execute("""
            SELECT role, message, c_timestamp
            FROM chat_history
            WHERE DATE(c_timestamp) = %s
            ORDER BY c_timestamp ASC
        """, (target_date,))

        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        # Format as message dicts
        messages = []
        for row in rows:
            messages.append({
                'role': row[0],
                'message': row[1],
                'timestamp': row[2]
            })

        print(f"[emotional_analyzer.py][get_todays_messages] Retrieved {len(messages)} messages from {target_date}")
        return messages

    except Exception as e:
        print(f"[emotional_analyzer.py][get_todays_messages] ✗ Error: {e}")
        return []

def calculate_emotional_intensity(messages: List[Dict]) -> float:
    """
    Calculate overall emotional intensity based on arousal and valence variance

    Higher intensity = stronger emotions (both positive and negative count)

    Args:
        messages: List of message dicts

    Returns:
        Intensity score from 0.0 to 1.0
    """
    if not messages:
        return 0.0

    try:
        # Load emotion classifier
        emotion_classifier = load_model(ScoringConfig.EMOTION_MODEL, "pipeline")
        if emotion_classifier is None:
            print(f"[emotional_analyzer.py][calculate_emotional_intensity] ✗ Failed to load model")
            return 0.0

        total_intensity = 0.0
        count = 0

        for msg in messages:
            text = msg.get('message', '')
            if len(text.strip()) < 5:
                continue

            try:
                # Get top emotion score
                predictions = emotion_classifier(text[:512])[0]
                if predictions:
                    # Use the highest confidence score as intensity
                    max_score = max([pred['score'] for pred in predictions])
                    total_intensity += max_score
                    count += 1
            except Exception as e:
                continue

        if count == 0:
            return 0.0

        # Average intensity
        intensity = total_intensity / count
        print(f"[emotional_analyzer.py][calculate_emotional_intensity] Intensity: {intensity:.3f}")
        return intensity

    except Exception as e:
        print(f"[emotional_analyzer.py][calculate_emotional_intensity] ✗ Error: {e}")
        return 0.0

def calculate_valence_range(messages: List[Dict]) -> float:
    """
    Calculate emotional variety based on valence range

    Higher range = more emotional variety (mix of positive and negative)

    Args:
        messages: List of message dicts

    Returns:
        Valence range from 0.0 to 2.0 (theoretical max: -1 to +1 = 2.0 range)
    """
    if not messages:
        return 0.0

    try:
        emotion_classifier = load_model(ScoringConfig.EMOTION_MODEL, "pipeline")
        if emotion_classifier is None:
            return 0.0

        valences = []

        for msg in messages:
            text = msg.get('message', '')
            if len(text.strip()) < 5:
                continue

            try:
                predictions = emotion_classifier(text[:512])[0]

                # Calculate valence for this message
                positive_score = sum([pred['score'] for pred in predictions
                                     if pred['label'] in ScoringConfig.POSITIVE_EMOTIONS])
                negative_score = sum([pred['score'] for pred in predictions
                                     if pred['label'] in ScoringConfig.NEGATIVE_EMOTIONS])

                if positive_score + negative_score > 0:
                    valence = (positive_score - negative_score) / (positive_score + negative_score)
                    valences.append(valence)

            except Exception as e:
                continue

        if len(valences) < 2:
            return 0.0

        # Range = max - min
        valence_range = max(valences) - min(valences)
        print(f"[emotional_analyzer.py][calculate_valence_range] Range: {valence_range:.3f}")
        return valence_range

    except Exception as e:
        print(f"[emotional_analyzer.py][calculate_valence_range] ✗ Error: {e}")
        return 0.0

def analyze_daily_emotions(target_date: Optional[date] = None) -> Dict:
    """
    Perform comprehensive emotional analysis of a day's conversations

    Args:
        target_date: Date to analyze (defaults to today)

    Returns:
        Dict containing:
            - message_count: Number of messages analyzed
            - valence: Average valence (-1 to +1)
            - arousal: Average arousal (0 to 1)
            - intensity: Emotional intensity (0 to 1)
            - valence_range: Emotional variety (0 to 2.0)
            - has_content: Whether there's enough data
    """
    if target_date is None:
        target_date = date.today()

    print(f"[emotional_analyzer.py][analyze_daily_emotions] Analyzing emotions for {target_date}")

    # Get messages
    messages = get_todays_messages(target_date)

    if not messages:
        print(f"[emotional_analyzer.py][analyze_daily_emotions] No messages found for {target_date}")
        return {
            'message_count': 0,
            'valence': 0.0,
            'arousal': 0.0,
            'intensity': 0.0,
            'valence_range': 0.0,
            'has_content': False,
            'date': target_date
        }

    # Calculate metrics
    valence = calculate_valence_transformer(messages)
    arousal = calculate_arousal_transformer(messages)
    intensity = calculate_emotional_intensity(messages)
    valence_range = calculate_valence_range(messages)

    result = {
        'message_count': len(messages),
        'valence': valence,
        'arousal': arousal,
        'intensity': intensity,
        'valence_range': valence_range,
        'has_content': len(messages) >= 3,  # Need at least 3 messages for meaningful analysis
        'date': target_date
    }

    print(f"[emotional_analyzer.py][analyze_daily_emotions] ✓ Analysis complete:")
    print(f"  Messages: {result['message_count']}")
    print(f"  Valence: {result['valence']:.3f}")
    print(f"  Arousal: {result['arousal']:.3f}")
    print(f"  Intensity: {result['intensity']:.3f}")
    print(f"  Valence Range: {result['valence_range']:.3f}")

    return result

def meets_daily_consolidation_threshold(emotional_analysis: Dict, threshold: float = 0.7) -> bool:
    """
    Check if a day meets the threshold for daily consolidation dream

    Daily consolidation is triggered when emotional intensity is high,
    indicating a significant day that deserves comprehensive integration.

    Args:
        emotional_analysis: Result from analyze_daily_emotions()
        threshold: Intensity threshold (0.0 to 1.0), default 0.7

    Returns:
        True if day meets threshold for daily consolidation
    """
    intensity = emotional_analysis.get('intensity', 0.0)
    has_content = emotional_analysis.get('has_content', False)

    # Need both sufficient content and high intensity
    meets_threshold = has_content and intensity >= threshold

    if meets_threshold:
        print(f"[emotional_analyzer.py][meets_daily_consolidation_threshold] ✓ Threshold met!")
        print(f"  Intensity: {intensity:.3f} >= {threshold}")
    else:
        print(f"[emotional_analyzer.py][meets_daily_consolidation_threshold] Threshold NOT met")
        print(f"  Intensity: {intensity:.3f} < {threshold} or insufficient content")

    return meets_threshold

if __name__ == "__main__":
    """Test emotional analysis on today's conversations"""
    print("=== Testing Emotional Analyzer ===\n")

    # Test with today
    result = analyze_daily_emotions()

    print("\n=== Emotional Analysis Results ===")
    print(f"Date: {result['date']}")
    print(f"Messages analyzed: {result['message_count']}")
    print(f"Valence (negativity ← 0 → positivity): {result['valence']:.3f}")
    print(f"Arousal (calm ← 0 → excited): {result['arousal']:.3f}")
    print(f"Intensity (weak ← 0 → strong): {result['intensity']:.3f}")
    print(f"Emotional variety: {result['valence_range']:.3f}")
    print(f"Has sufficient content: {result['has_content']}")
