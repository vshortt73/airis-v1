"""
Dream Storage for Dream System
Stores complete dream records in episodic_dreams database
"""
import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
sys.path.insert(0, PROJECT_ROOT)

import psycopg2
import psycopg2.extras
from datetime import date, datetime
from typing import Dict, List, Optional
import json
from app import config
from dream_truth_extractor import check_and_extract_truth

def get_db_connection():
    """Create database connection"""
    # Try environment variable first, then config file, then IRIS_DB_PASSWORD from config
    password = (os.environ.get('IRIS_DB_PASSWORD') or
                getattr(config, 'DB_PASSWORD', None) or
                getattr(config, 'IRIS_DB_PASSWORD', None))

    conn_params = {
        'host': config.DB_HOST,
        'port': config.DB_PORT,
        'database': config.DB_NAME,
        'user': config.DB_USER
    }
    if password:
        conn_params['password'] = password
    return psycopg2.connect(**conn_params)

# ============================================
# DREAM INSERTION
# ============================================

def store_dream(
    dream_date: date,
    dream_type: str,
    full_transcript: str,
    dream_phase_transcript: str,
    reflection_phase_transcript: str,
    reflection_data: Dict,
    scores_and_embeddings: Dict,
    metadata: Dict
) -> Optional[int]:
    """
    Store a complete dream record in the database

    Args:
        dream_date: Date the dream occurred
        dream_type: Type of dream (emotional_processing, etc.)
        full_transcript: Complete 15-turn transcript
        dream_phase_transcript: Just the 10 dream turns
        reflection_phase_transcript: Just the 5 reflection turns
        reflection_data: Extracted reflection fields (summary, mood, theme, etc.)
        scores_and_embeddings: Emotional scores and embedding vectors
        metadata: Additional metadata (source_date, duration, models used, etc.)

    Returns:
        Dream ID if successful, None otherwise
    """
    print(f"[dream_storage.py][store_dream] Storing {dream_type} dream for {dream_date}")

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Prepare data
        source_date = metadata.get('source_date')
        based_on_reality = dream_type in ['emotional_processing', 'memory_consolidation']

        # Reflection fields
        summary = reflection_data.get('summary', '')
        takeaway = reflection_data.get('takeaway', '')
        mood = reflection_data.get('mood', '')
        theme = reflection_data.get('theme', '')

        # Handle top_3_emotions (could be list or string)
        top_3_emotions = reflection_data.get('top_3_emotions', [])
        if isinstance(top_3_emotions, str):
            # Try to parse if it's a string representation
            try:
                top_3_emotions = json.loads(top_3_emotions)
            except:
                top_3_emotions = [top_3_emotions]

        # Convert list to JSON string for storage
        top_3_emotions_json = json.dumps(top_3_emotions) if isinstance(top_3_emotions, list) else top_3_emotions

        # Scores
        emotion_label = scores_and_embeddings.get('emotion_label')
        emotion_top3 = scores_and_embeddings.get('emotion_top3', [])
        valence = scores_and_embeddings.get('valence')
        arousal = scores_and_embeddings.get('arousal')
        recurrence = scores_and_embeddings.get('recurrence', 0.0)
        novelty = scores_and_embeddings.get('novelty', 1.0)
        cohesion = scores_and_embeddings.get('cohesion', 0.0)
        intensity = scores_and_embeddings.get('intensity', 0.0)

        # Key details
        key_details = scores_and_embeddings.get('key_details', '')

        # Embeddings
        emb_summary_context = scores_and_embeddings.get('emb_summary_context')
        emb_summary_event = scores_and_embeddings.get('emb_summary_event')
        emb_summary_significance = scores_and_embeddings.get('emb_summary_significance')
        emb_takeaway = scores_and_embeddings.get('emb_takeaway')
        emb_key_details = scores_and_embeddings.get('emb_key_details')
        emb_full_dream = scores_and_embeddings.get('emb_full_dream')

        # Metadata
        freud_model = metadata.get('freud_model', 'qwen2.5:14b')
        iris_model = metadata.get('iris_model', 'qwen3:32b')
        duration = metadata.get('dream_duration_seconds')

        # Insert dream
        cursor.execute("""
            INSERT INTO episodic_dreams (
                dream_date, source_date, dream_type, based_on_reality,
                full_transcript, dream_phase_transcript, reflection_phase_transcript,
                summary, takeaway, mood, theme, top_3_emotions, key_details,
                emotion_label, emotion_top3, valence, arousal,
                recurrence, novelty, cohesion, intensity,
                emb_summary_context, emb_summary_event, emb_summary_significance,
                emb_takeaway, emb_key_details, emb_full_dream,
                freud_model, iris_model, dream_duration_seconds
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s
            )
            RETURNING id
        """, (
            dream_date, source_date, dream_type, based_on_reality,
            full_transcript, dream_phase_transcript, reflection_phase_transcript,
            summary, takeaway, mood, theme, top_3_emotions_json, key_details,
            emotion_label, json.dumps(emotion_top3), valence, arousal,
            recurrence, novelty, cohesion, intensity,
            emb_summary_context, emb_summary_event, emb_summary_significance,
            emb_takeaway, emb_key_details, emb_full_dream,
            freud_model, iris_model, duration
        ))

        dream_id = cursor.fetchone()[0]

        conn.commit()
        cursor.close()
        conn.close()

        print(f"[dream_storage.py][store_dream] ✓ Dream stored successfully (ID: {dream_id})")

        # Check if this dream qualifies for truth extraction
        truth_extracted = check_and_extract_truth(
            dream_id=dream_id,
            dream_date=dream_date,
            dream_type=dream_type,
            reflection_data=reflection_data,
            scores=scores_and_embeddings
        )

        if truth_extracted:
            print(f"[dream_storage.py][store_dream] ✓ Dream truth extracted and stored")
        else:
            print(f"[dream_storage.py][store_dream] ℹ No dream truth extracted (didn't meet thresholds)")

        return dream_id

    except Exception as e:
        print(f"[dream_storage.py][store_dream] ✗ Error storing dream: {e}")
        import traceback
        traceback.print_exc()

        # Save to file as backup
        backup_file = f"/tmp/dream_backup_{dream_date}_{dream_type}.json"
        try:
            backup_data = {
                'dream_date': str(dream_date),
                'dream_type': dream_type,
                'full_transcript': full_transcript,
                'reflection_data': reflection_data,
                'metadata': metadata
            }
            with open(backup_file, 'w') as f:
                json.dump(backup_data, f, indent=2)
            print(f"[dream_storage.py][store_dream] ⚠ Saved backup to {backup_file}")
        except Exception as backup_error:
            print(f"[dream_storage.py][store_dream] ✗ Failed to save backup: {backup_error}")

        return None

# ============================================
# DREAM RETRIEVAL
# ============================================

def get_recent_dreams(limit: int = 10, dream_type: Optional[str] = None) -> List[Dict]:
    """
    Retrieve recent dreams

    Args:
        limit: Maximum number of dreams to retrieve
        dream_type: Optional filter by dream type

    Returns:
        List of dream records
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        if dream_type:
            cursor.execute("""
                SELECT id, dream_date, dream_type, theme, mood, takeaway, based_on_reality
                FROM episodic_dreams
                WHERE dream_type = %s
                ORDER BY dream_date DESC
                LIMIT %s
            """, (dream_type, limit))
        else:
            cursor.execute("""
                SELECT id, dream_date, dream_type, theme, mood, takeaway, based_on_reality
                FROM episodic_dreams
                ORDER BY dream_date DESC
                LIMIT %s
            """, (limit,))

        dreams = cursor.fetchall()

        cursor.close()
        conn.close()

        return [dict(dream) for dream in dreams]

    except Exception as e:
        print(f"[dream_storage.py][get_recent_dreams] ✗ Error: {e}")
        return []

def get_dream_by_id(dream_id: int) -> Optional[Dict]:
    """
    Retrieve a specific dream by ID

    Args:
        dream_id: Dream ID

    Returns:
        Dream record dict, or None
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cursor.execute("""
            SELECT *
            FROM episodic_dreams
            WHERE id = %s
        """, (dream_id,))

        dream = cursor.fetchone()

        cursor.close()
        conn.close()

        return dict(dream) if dream else None

    except Exception as e:
        print(f"[dream_storage.py][get_dream_by_id] ✗ Error: {e}")
        return None

# ============================================
# DREAM STATISTICS
# ============================================

def get_dream_statistics() -> Dict:
    """
    Get statistics about stored dreams

    Returns:
        Dict with dream statistics
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Total dreams
        cursor.execute("SELECT COUNT(*) FROM episodic_dreams")
        total_dreams = cursor.fetchone()[0]

        # Dreams by type
        cursor.execute("""
            SELECT dream_type, COUNT(*) as count
            FROM episodic_dreams
            GROUP BY dream_type
            ORDER BY count DESC
        """)
        by_type = dict(cursor.fetchall())

        # Average emotional scores
        cursor.execute("""
            SELECT
                AVG(valence) as avg_valence,
                AVG(arousal) as avg_arousal,
                AVG(intensity) as avg_intensity,
                AVG(cohesion) as avg_cohesion
            FROM episodic_dreams
            WHERE valence IS NOT NULL
        """)
        result = cursor.fetchone()
        avg_scores = {
            'avg_valence': result[0] or 0.0,
            'avg_arousal': result[1] or 0.0,
            'avg_intensity': result[2] or 0.0,
            'avg_cohesion': result[3] or 0.0
        }

        cursor.close()
        conn.close()

        return {
            'total_dreams': total_dreams,
            'dreams_by_type': by_type,
            **avg_scores
        }

    except Exception as e:
        print(f"[dream_storage.py][get_dream_statistics] ✗ Error: {e}")
        return {}

# ============================================
# TESTING
# ============================================

if __name__ == "__main__":
    """Test dream storage"""
    print("=== Testing Dream Storage ===\n")

    # Create test dream data
    dream_date = date.today()
    dream_type = "creative_random"

    full_transcript = "Test dream transcript with 15 turns..."
    dream_phase_transcript = "Test dream phase (10 turns)..."
    reflection_phase_transcript = "Test reflection phase (5 turns)..."

    reflection_data = {
        'summary': "A test dream about libraries and memories",
        'mood': "curious",
        'theme': "testing",
        'top_3_emotions': ["wonder", "curiosity", "calm"],
        'takeaway': "Testing the storage system works!"
    }

    scores_and_embeddings = {
        'emotion_label': 'curiosity',
        'emotion_top3': [{'emotion': 'curiosity', 'score': 0.9}],
        'valence': 0.5,
        'arousal': 0.6,
        'intensity': 0.7,
        'cohesion': 0.8,
        'novelty': 0.9,
        'recurrence': 0.1,
        'key_details': "floating books, glowing pages",
        'emb_summary_context': None,  # Would be real embeddings
        'emb_summary_event': None,
        'emb_summary_significance': None,
        'emb_takeaway': None,
        'emb_key_details': None,
        'emb_full_dream': None
    }

    metadata = {
        'source_date': None,
        'freud_model': 'gemma2:9b',
        'iris_model': 'qwen3:32b',
        'dream_duration_seconds': 300
    }

    # Store dream
    print("--- Storing test dream ---")
    dream_id = store_dream(
        dream_date, dream_type,
        full_transcript, dream_phase_transcript, reflection_phase_transcript,
        reflection_data, scores_and_embeddings, metadata
    )

    if dream_id:
        print(f"\n✓ Dream stored with ID: {dream_id}")

        # Retrieve it
        print("\n--- Retrieving dream ---")
        retrieved = get_dream_by_id(dream_id)
        if retrieved:
            print(f"Dream Type: {retrieved['dream_type']}")
            print(f"Theme: {retrieved['theme']}")
            print(f"Takeaway: {retrieved['takeaway'][:50]}...")

    # Get statistics
    print("\n--- Dream Statistics ---")
    stats = get_dream_statistics()
    print(f"Total dreams: {stats.get('total_dreams', 0)}")
    print(f"By type: {stats.get('dreams_by_type', {})}")
