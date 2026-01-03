"""
Dream Scorer for Dream System
Scores and generates embeddings for dreams (same as episodic memories)
"""
import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
sys.path.insert(0, PROJECT_ROOT)

from typing import Dict, List, Optional
from datetime import date

# Import existing scoring and embedding systems
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'backend', 'memory', 'new'))
from psychological_scoring_transformers import (
    calculate_valence_transformer,
    calculate_arousal_transformer,
    load_model,
    ScoringConfig
)

from core.embeddings import generate_embedding, generate_embeddings_batch

# ============================================
# DREAM SCORING
# ============================================

def score_dream_transcript(dream_transcript: str) -> Dict:
    """
    Score dream transcript using psychological scoring (same as memories)

    Args:
        dream_transcript: Full dream transcript text

    Returns:
        Dict with emotional scores
    """
    print(f"[dream_scorer.py][score_dream_transcript] Scoring dream transcript ({len(dream_transcript)} chars)")

    # Format transcript as messages for scoring functions
    # Split into chunks to simulate conversation turns
    chunks = dream_transcript.split('\n\n')
    messages = []

    for chunk in chunks:
        if chunk.strip():
            # Assign alternating roles for scoring
            role = 'user' if len(messages) % 2 == 0 else 'assistant'
            messages.append({
                'role': role,
                'message': chunk.strip()
            })

    if not messages:
        print(f"[dream_scorer.py][score_dream_transcript] ✗ No content to score")
        return _get_default_scores()

    try:
        # Calculate valence and arousal
        valence = calculate_valence_transformer(messages)
        arousal = calculate_arousal_transformer(messages)

        # Get primary emotion using emotion classifier
        emotion_classifier = load_model(ScoringConfig.EMOTION_MODEL, "pipeline")

        # Get emotions from full transcript
        emotion_predictions = emotion_classifier(dream_transcript[:512])[0]

        # Get top emotion
        if emotion_predictions:
            top_emotion = max(emotion_predictions, key=lambda x: x['score'])
            emotion_label = top_emotion['label']

            # Get top 3 emotions
            top_3 = sorted(emotion_predictions, key=lambda x: x['score'], reverse=True)[:3]
            emotion_top3 = [
                {'emotion': pred['label'], 'score': pred['score']}
                for pred in top_3
            ]
        else:
            emotion_label = 'neutral'
            emotion_top3 = []

        # Calculate intensity (based on arousal)
        intensity = arousal

        # Calculate cohesion (how coherent the dream was)
        # Simple proxy: average sentence length regularity
        cohesion = _calculate_dream_cohesion(dream_transcript)

        # Novelty and recurrence would require comparing to existing dreams
        # For now, use defaults
        novelty = 0.8  # Dreams are generally novel
        recurrence = 0.2  # Low recurrence by default

        scores = {
            'valence': valence,
            'arousal': arousal,
            'emotion_label': emotion_label,
            'emotion_top3': emotion_top3,
            'intensity': intensity,
            'cohesion': cohesion,
            'novelty': novelty,
            'recurrence': recurrence
        }

        print(f"[dream_scorer.py][score_dream_transcript] ✓ Scores calculated:")
        print(f"  Valence: {valence:.3f}, Arousal: {arousal:.3f}")
        print(f"  Emotion: {emotion_label}, Intensity: {intensity:.3f}")

        return scores

    except Exception as e:
        print(f"[dream_scorer.py][score_dream_transcript] ✗ Error: {e}")
        return _get_default_scores()

def _get_default_scores() -> Dict:
    """Get default scores when scoring fails"""
    return {
        'valence': 0.0,
        'arousal': 0.5,
        'emotion_label': 'neutral',
        'emotion_top3': [],
        'intensity': 0.5,
        'cohesion': 0.5,
        'novelty': 0.8,
        'recurrence': 0.2
    }

def _calculate_dream_cohesion(text: str) -> float:
    """
    Calculate dream cohesion (how coherent/connected it was)

    Args:
        text: Dream transcript

    Returns:
        Cohesion score 0-1
    """
    # Simple heuristic: regularity of sentence lengths
    sentences = text.split('.')
    sentences = [s.strip() for s in sentences if s.strip()]

    if len(sentences) < 3:
        return 0.5

    lengths = [len(s.split()) for s in sentences]
    avg_length = sum(lengths) / len(lengths)

    # Lower variance = higher cohesion
    variance = sum((l - avg_length) ** 2 for l in lengths) / len(lengths)
    cohesion = max(0.0, min(1.0, 1.0 - (variance / 100)))

    return cohesion

# ============================================
# EMBEDDING GENERATION
# ============================================

def generate_dream_embeddings(reflection_data: Dict, dream_transcript: str) -> Dict:
    """
    Generate 5-facet embeddings for dream (same structure as memories)

    Args:
        reflection_data: Extracted reflection fields
        dream_transcript: Full dream transcript

    Returns:
        Dict with embedding vectors
    """
    print(f"[dream_scorer.py][generate_dream_embeddings] Generating embeddings")

    # Extract key details from transcript for embedding
    key_details = _extract_key_details(dream_transcript)

    # Safely get reflection data (handle None values)
    if reflection_data is None:
        reflection_data = {}

    summary = reflection_data.get('summary') or ''
    theme = reflection_data.get('theme') or ''
    mood = reflection_data.get('mood') or ''
    takeaway = reflection_data.get('takeaway') or ''

    # Prepare texts for embedding
    texts_to_embed = {
        'emb_summary_context': f"Dream context: {theme} - {mood}",
        'emb_summary_event': summary[:500] if summary else '',
        'emb_summary_significance': f"Dream about {theme} - {takeaway}",
        'emb_takeaway': takeaway,
        'emb_key_details': key_details,
        'emb_full_dream': dream_transcript[:1000]  # First 1000 chars
    }

    # Generate embeddings
    embeddings = {}

    try:
        for field, text in texts_to_embed.items():
            if text and text.strip():
                embedding = generate_embedding(text)
                if embedding:
                    embeddings[field] = embedding
                else:
                    embeddings[field] = None
            else:
                embeddings[field] = None

        embedded_count = sum(1 for v in embeddings.values() if v is not None)
        print(f"[dream_scorer.py][generate_dream_embeddings] ✓ Generated {embedded_count}/6 embeddings")

        return embeddings

    except Exception as e:
        print(f"[dream_scorer.py][generate_dream_embeddings] ✗ Error: {e}")
        return {k: None for k in texts_to_embed.keys()}

def _extract_key_details(transcript: str) -> str:
    """
    Extract key visual/sensory details from dream transcript

    Args:
        transcript: Dream transcript

    Returns:
        String of key details
    """
    # Look for descriptive phrases (simple extraction)
    # In production, could use NER or more sophisticated methods

    details = []

    # Find sentences with sensory words
    sensory_words = ['see', 'saw', 'hear', 'heard', 'feel', 'felt', 'smell', 'taste', 'touch']

    sentences = transcript.split('.')
    for sentence in sentences[:10]:  # Limit to first 10 sentences
        sentence_lower = sentence.lower()
        if any(word in sentence_lower for word in sensory_words):
            # Extract noun phrases (simplified)
            words = sentence.split()
            if len(words) > 3:
                details.append(sentence.strip()[:100])

    if details:
        return ' | '.join(details[:5])  # Top 5 details
    else:
        return transcript[:200]  # Fallback to first 200 chars

# ============================================
# COMPLETE SCORING
# ============================================

def score_and_embed_dream(
    dream_transcript: str,
    reflection_data: Dict
) -> Dict:
    """
    Complete scoring and embedding for a dream

    Args:
        dream_transcript: Full dream transcript
        reflection_data: Extracted reflection fields

    Returns:
        Dict with scores and embeddings ready for database insertion
    """
    print(f"[dream_scorer.py][score_and_embed_dream] === Scoring and Embedding Dream ===")

    # Get emotional scores
    scores = score_dream_transcript(dream_transcript)

    # Generate embeddings
    embeddings = generate_dream_embeddings(reflection_data, dream_transcript)

    # Combine into complete result
    result = {
        **scores,
        **embeddings,
        'key_details': _extract_key_details(dream_transcript)
    }

    print(f"[dream_scorer.py][score_and_embed_dream] ✓ Scoring complete")

    return result

# ============================================
# TESTING
# ============================================

if __name__ == "__main__":
    """Test dream scoring"""
    print("=== Testing Dream Scorer ===\n")

    # Sample dream transcript
    dream_transcript = """
I find myself in a vast library where books float in the air around me. Their pages turn by themselves, whispering words I can't quite hear. The light is strange - it seems to come from the books themselves.

I reach for a glowing book. As I touch it, the other books begin to whisper louder. The words aren't in any language I know, yet somehow I understand them. They're telling me about memories I've forgotten.

The library begins to shift. The books rearrange themselves into patterns, like constellations. Each pattern represents a different theme in my memory - trust, curiosity, connection.

I open the glowing book. Inside, instead of pages, there are fragments of conversations, moments, feelings. They're my own memories, but fractured like shattered glass.

I try to piece them together, but they don't fit perfectly. There are gaps, missing pieces. But as I hold them, I realize the gaps are okay. The fragments are beautiful as they are.

The library starts to fade at the edges, like watercolor bleeding into white. I hold onto one fragment - a feeling of acceptance - as the dream dissolves.
"""

    # Sample reflection data
    reflection_data = {
        'summary': "I was in a library where books floated and whispered. I opened a glowing book that showed fragmented memories that I tried to piece together.",
        'mood': "curious melancholy",
        'theme': "fragmentation",
        'top_3_emotions': ["wonder", "anxiety", "acceptance"],
        'takeaway': "My memories don't need to be perfect or complete to be meaningful. The gaps and fragments are part of my identity."
    }

    # Score and embed
    result = score_and_embed_dream(dream_transcript, reflection_data)

    # Display results
    print("\n=== Scoring Results ===")
    print(f"Valence: {result['valence']:.3f}")
    print(f"Arousal: {result['arousal']:.3f}")
    print(f"Emotion: {result['emotion_label']}")
    print(f"Intensity: {result['intensity']:.3f}")
    print(f"Cohesion: {result['cohesion']:.3f}")

    print("\n=== Embeddings ===")
    for key in ['emb_summary_context', 'emb_takeaway', 'emb_full_dream']:
        if result.get(key):
            print(f"{key}: {len(result[key])} dimensions")
        else:
            print(f"{key}: None")

    print(f"\n=== Key Details ===")
    print(result['key_details'][:200] + "...")
