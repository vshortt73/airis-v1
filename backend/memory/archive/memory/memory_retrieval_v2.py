"""
Iris Memory Retrieval System v2
Clean implementation based on human memory retrieval mechanisms

Architecture:
  1. Embed current conversation directly (no transformations)
  2. Query against stored multi-faceted embeddings
  3. Rerank using psychological factors
  4. Return memories for injection into context

Key Principles:
  - Deterministic: same input = same results
  - Psychologically grounded: emotional resonance, recency, frequency
  - Simple: no unnecessary complexity
  - Fast: minimal LLM calls
"""

import os
import sys
import math
import numpy as np
import psycopg2
from psycopg2.extras import DictCursor
from sentence_transformers import SentenceTransformer
from transformers import pipeline
import torch
from typing import List, Dict, Tuple
import argparse

# ============================================
# CONFIGURATION
# ============================================

# Database
DB_CONFIG = {
    'host': 'localhost',
    'port': 5432,
    'database': 'irisdb',
    'user': 'irisuser',
    'password': os.environ.get('IRIS_DB_PASSWORD', 'yourpassword')
}

# Model paths
EMBEDDING_MODEL_PATH = "/models/llm_models/huggingface/models/all-mpnet-base-v2/"
EMOTION_MODEL_NAME = "SamLowe/roberta-base-go_emotions"  # Match memory creation!

# Emotion mappings (from GoEmotions dataset - MUST match memory creation!)
HIGH_AROUSAL_EMOTIONS = {
    'anger', 'annoyance', 'excitement', 'fear', 'surprise',
    'nervousness', 'joy', 'realization'
}

LOW_AROUSAL_EMOTIONS = {
    'sadness', 'grief', 'relief', 'disappointment', 'embarrassment'
}

POSITIVE_EMOTIONS = {
    'joy', 'excitement', 'gratitude', 'love', 'amusement',
    'admiration', 'approval', 'caring', 'desire', 'optimism',
    'pride', 'relief'
}

NEGATIVE_EMOTIONS = {
    'anger', 'annoyance', 'disappointment', 'disapproval', 'disgust',
    'embarrassment', 'fear', 'grief', 'nervousness', 'remorse',
    'sadness'
}

# Retrieval parameters
CANDIDATE_MULTIPLIER = 3  # Fetch 3x memories for reranking
MIN_SIMILARITY = 0.10     # Minimum semantic similarity threshold (lowered from 0.15)

# Memory strength weights (total = 1.00)
# Back to baseline for threshold testing
WEIGHTS = {
    'semantic': 0.45,      # Semantic similarity to query
    'emotional': 0.20,     # Emotional resonance with current state
    'recency': 0.15,       # Recent memories more accessible
    'frequency': 0.10,     # Retrieval count strengthening
    'intensity': 0.10,     # Original emotional intensity
}

# Embedding weights for 5-facet comparison (added key_details)
EMBEDDING_WEIGHTS = {
    'context': 0.20,
    'event': 0.20,
    'significance': 0.20,
    'takeaway': 0.20,
    'key_details': 0.20,  # NEW: Specific visual/emotional/relational details
}

# Time decay parameters
HALF_LIFE_DAYS = 30  # Memory strength halves every 30 days

# Device
DEVICE = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

# ============================================
# MODEL LOADING
# ============================================

class ModelLoader:
    """Lazy-load models only when needed"""

    def __init__(self):
        self._embedding_model = None
        self._emotion_classifier = None

    @property
    def embedding_model(self):
        if self._embedding_model is None:
            print("[ModelLoader] Loading embedding model...")
            self._embedding_model = SentenceTransformer(
                EMBEDDING_MODEL_PATH,
                local_files_only=True
            )
        return self._embedding_model

    @property
    def emotion_classifier(self):
        if self._emotion_classifier is None:
            print(f"[ModelLoader] Loading emotion model: {EMOTION_MODEL_NAME}")
            # Use HuggingFace pipeline - same as memory creation
            self._emotion_classifier = pipeline(
                "text-classification",
                model=EMOTION_MODEL_NAME,
                top_k=None,  # Return all emotion scores
                device=0 if DEVICE.type == 'cuda' else -1
            )
            print("[ModelLoader] ✓ Emotion model loaded")
        return self._emotion_classifier

# Global model loader
models = ModelLoader()

# ============================================
# EMOTION SCORING
# ============================================

def parse_transcript_to_messages(transcript: str) -> List[Dict[str, str]]:
    """
    Parse transcript back into individual messages

    Transcript format:
    USER: message text
    ASSISTANT: message text

    Returns:
        List of {'role': 'user', 'message': 'text'} dicts
    """
    messages = []
    lines = transcript.split('\n')

    current_role = None
    current_message = []

    for line in lines:
        # Check if line starts with a role
        if ':' in line:
            parts = line.split(':', 1)
            potential_role = parts[0].strip().upper()

            # Check if it's a valid role
            if potential_role in ['USER', 'ASSISTANT', 'SYSTEM', 'TOOL']:
                # Save previous message if exists
                if current_role and current_message:
                    messages.append({
                        'role': current_role.lower(),
                        'message': '\n'.join(current_message).strip()
                    })

                # Start new message
                current_role = potential_role
                current_message = [parts[1].strip()]
            else:
                # Not a role, continue current message
                if current_message is not None:
                    current_message.append(line)
        else:
            # Continue current message
            if current_message is not None:
                current_message.append(line)

    # Save last message
    if current_role and current_message:
        messages.append({
            'role': current_role.lower(),
            'message': '\n'.join(current_message).strip()
        })

    return messages


def score_emotion(text: str) -> Dict[str, float]:
    """
    Score emotional content of text using RoBERTa GoEmotions
    Returns: {valence, arousal, emotion_label, intensity}

    CRITICAL: Uses SAME model and logic as memory creation!
    - Model: SamLowe/roberta-base-go_emotions
    - Analyzes EACH message separately (not just first 512 chars!)
    - Aggregates with role weights
    - Maps 28 GoEmotions to valence/arousal dimensions
    """
    classifier = models.emotion_classifier

    # Parse transcript into individual messages
    messages = parse_transcript_to_messages(text)

    if not messages:
        # Fallback: treat entire text as one message
        messages = [{'role': 'user', 'message': text}]

    # Role weights - SAME as memory creation
    role_weights = {'user': 1.0, 'assistant': 0.8, 'system': 0.3, 'tool': 0.3}

    positive_score = 0.0
    negative_score = 0.0
    high_arousal_score = 0.0
    low_arousal_score = 0.0
    total_weight = 0.0
    all_emotions = []

    # Analyze each message separately - SAME as memory creation
    for msg in messages:
        role = msg.get('role', 'user')
        weight = role_weights.get(role, 1.0)
        message_text = msg['message']

        # Skip very short messages
        if len(message_text.strip()) < 5:
            continue

        try:
            # Truncate to 512 characters per message
            message_truncated = message_text[:512]

            # Get emotion predictions for this message
            predictions = classifier(message_truncated)[0]

            # Track all emotions with their weighted scores
            for pred in predictions:
                all_emotions.append({
                    'label': pred['label'],
                    'score': pred['score'] * weight
                })

            # Aggregate valence
            for pred in predictions:
                emotion = pred['label']
                score = pred['score']

                if emotion in POSITIVE_EMOTIONS:
                    positive_score += score * weight
                elif emotion in NEGATIVE_EMOTIONS:
                    negative_score += score * weight

            # Aggregate arousal
            for pred in predictions:
                emotion = pred['label']
                score = pred['score']

                if emotion in HIGH_AROUSAL_EMOTIONS:
                    high_arousal_score += score * weight
                elif emotion in LOW_AROUSAL_EMOTIONS:
                    low_arousal_score += score * weight

            total_weight += weight

        except Exception as e:
            print(f"[Emotion] Warning: Error processing message: {e}")
            continue

    # Calculate valence
    if total_weight == 0:
        valence = 0.0
    else:
        positive_norm = positive_score / total_weight
        negative_norm = negative_score / total_weight
        total_emotion = positive_norm + negative_norm

        if total_emotion == 0:
            valence = 0.0
        else:
            valence = (positive_norm - negative_norm) / total_emotion

    # Calculate arousal
    if total_weight == 0:
        arousal = 0.5
    else:
        high_arousal_norm = high_arousal_score / total_weight
        low_arousal_norm = low_arousal_score / total_weight
        total_arousal_emotion = high_arousal_norm + low_arousal_norm

        if total_arousal_emotion == 0:
            arousal = 0.5
        else:
            arousal = high_arousal_norm / total_arousal_emotion

    # Find dominant emotion across all messages
    if all_emotions:
        emotion_aggregated = {}
        for e in all_emotions:
            label = e['label']
            score = e['score']
            emotion_aggregated[label] = emotion_aggregated.get(label, 0.0) + score

        emotion_label = max(emotion_aggregated.items(), key=lambda x: x[1])[0]
    else:
        emotion_label = 'neutral'

    # Emotional intensity
    intensity = abs(valence) * arousal

    return {
        'valence': valence,
        'arousal': arousal,
        'emotion_label': emotion_label,
        'intensity': intensity,
    }

# ============================================
# RETRIEVAL FUNCTIONS
# ============================================

def compute_emotional_resonance(current_emotion: Dict, memory_emotion: Dict) -> float:
    """
    Compute emotional resonance between current state and memory
    Higher when emotions are similar in valence-arousal space
    """
    valence_dist = abs(current_emotion['valence'] - memory_emotion['valence'])
    arousal_dist = abs(current_emotion['arousal'] - memory_emotion['arousal'])

    # Euclidean distance in normalized 2D space
    distance = math.sqrt((valence_dist**2 + arousal_dist**2) / 2)

    # Convert to similarity (0 = opposite, 1 = identical)
    resonance = 1.0 - min(distance, 1.0)

    return resonance


def compute_recency_score(age_days: float) -> float:
    """
    Exponential decay based on age
    Memory strength halves every HALF_LIFE_DAYS
    """
    # Convert to float in case we get Decimal from database
    age_days = float(age_days) if age_days is not None else 0.0
    return math.exp(-math.log(2) * age_days / HALF_LIFE_DAYS)


def compute_frequency_score(retrieval_count: int) -> float:
    """
    Logarithmic scaling of retrieval frequency
    Diminishing returns for very frequent retrievals
    """
    return math.log(1 + retrieval_count) / 10.0  # Scale to ~0-1 range


def retrieve_memories(
    conversation: str,
    top_k: int = 10,
    min_similarity: float = MIN_SIMILARITY,
    verbose: bool = True
) -> List[Dict]:
    """
    Retrieve relevant memories for current conversation

    Args:
        conversation: Current conversation text
        top_k: Number of memories to return
        min_similarity: Minimum semantic similarity threshold
        verbose: Print progress messages

    Returns:
        List of memory dicts with strength scores
    """

    if verbose:
        print(f"\n[Retrieval] Processing conversation ({len(conversation)} chars)")

    # 1. Embed current conversation directly (no transformations)
    if verbose:
        print("[Retrieval] Generating query embedding...")
    query_emb = models.embedding_model.encode(conversation, normalize_embeddings=True).tolist()

    # 2. Score current emotional state
    if verbose:
        print("[Retrieval] Scoring current emotion...")
    current_emotion = score_emotion(conversation)
    if verbose:
        print(f"  Emotion: {current_emotion['emotion_label']} "
              f"(valence={current_emotion['valence']:.2f}, "
              f"arousal={current_emotion['arousal']:.2f})")

    # 3. Query database for candidates
    if verbose:
        print(f"[Retrieval] Fetching candidates (limit={top_k * CANDIDATE_MULTIPLIER})...")

    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor(cursor_factory=DictCursor)

    # Compare query embedding to all 5 stored embeddings with balanced weights
    cur.execute("""
        SELECT
            id,
            transcript,
            takeaway,
            key_details,
            summary_context,
            summary_event,
            summary_significance,
            category,
            emotion_label,
            valence,
            arousal,
            recurrence,
            novelty,
            cohesion,
            age_days,
            (
                %(w_ctx)s * (1 - (emb_summary_context <=> %(query)s::vector)) +
                %(w_evt)s * (1 - (emb_summary_event <=> %(query)s::vector)) +
                %(w_sig)s * (1 - (emb_summary_significance <=> %(query)s::vector)) +
                %(w_take)s * (1 - (emb_takeaway <=> %(query)s::vector)) +
                %(w_key)s * (1 - (emb_key_details <=> %(query)s::vector))
            )::float AS semantic_similarity
        FROM episodic_memories_with_age
        WHERE summary_context IS NOT NULL AND summary_context <> ''
          AND summary_event IS NOT NULL AND summary_event <> ''
          AND summary_significance IS NOT NULL AND summary_significance <> ''
          AND takeaway IS NOT NULL AND takeaway <> ''
          AND key_details IS NOT NULL AND key_details <> ''
        ORDER BY semantic_similarity DESC
        LIMIT %(limit)s
    """, {
        'query': query_emb,
        'w_ctx': EMBEDDING_WEIGHTS['context'],
        'w_evt': EMBEDDING_WEIGHTS['event'],
        'w_sig': EMBEDDING_WEIGHTS['significance'],
        'w_take': EMBEDDING_WEIGHTS['takeaway'],
        'w_key': EMBEDDING_WEIGHTS['key_details'],
        'limit': top_k * CANDIDATE_MULTIPLIER
    })

    candidates = cur.fetchall()
    cur.close()
    conn.close()

    if verbose:
        print(f"[Retrieval] Retrieved {len(candidates)} candidates")

    # 4. Rerank using psychological factors
    if verbose:
        print("[Retrieval] Reranking with psychological factors...")

    results = []
    for mem in candidates:
        # Skip if below minimum similarity
        if mem['semantic_similarity'] < min_similarity:
            continue

        # Emotional resonance
        memory_emotion = {
            'valence': float(mem['valence']) if mem['valence'] is not None else 0.0,
            'arousal': float(mem['arousal']) if mem['arousal'] is not None else 0.0,
            'emotion_label': mem['emotion_label'],
        }
        emotional_resonance = compute_emotional_resonance(current_emotion, memory_emotion)

        # Recency
        recency = compute_recency_score(mem['age_days'])

        # Frequency (using recurrence as proxy for retrieval count)
        frequency = compute_frequency_score(int(mem['recurrence']) if mem['recurrence'] is not None else 0)

        # Original emotional intensity
        valence_val = float(mem['valence']) if mem['valence'] is not None else 0.0
        arousal_val = float(mem['arousal']) if mem['arousal'] is not None else 0.0
        intensity = abs(valence_val) * arousal_val

        # Combined memory strength
        strength = (
            WEIGHTS['semantic'] * mem['semantic_similarity'] +
            WEIGHTS['emotional'] * emotional_resonance +
            WEIGHTS['recency'] * recency +
            WEIGHTS['frequency'] * frequency +
            WEIGHTS['intensity'] * intensity
        )

        results.append({
            'id': mem['id'],
            'transcript': mem['transcript'],
            'takeaway': mem['takeaway'],
            'category': mem['category'],
            'age_days': float(mem['age_days']) if mem['age_days'] is not None else 0.0,
            'strength': strength,
            'semantic_similarity': mem['semantic_similarity'],
            'emotional_resonance': emotional_resonance,
            'recency': recency,
            'frequency': frequency,
            'intensity': intensity,
        })

    # 5. Sort by strength and return top-k
    results.sort(key=lambda x: x['strength'], reverse=True)
    final = results[:top_k]

    if verbose:
        print(f"[Retrieval] Returning {len(final)} memories after reranking")
        if final:
            print(f"  Top memory: ID {final[0]['id']} (strength={final[0]['strength']:.3f})")

    return final


# ============================================
# DISPLAY & INJECTION
# ============================================

def format_for_display(memories: List[Dict]) -> str:
    """Format memories for human-readable display"""
    output = []
    output.append("\n" + "="*80)
    output.append(f"RETRIEVED {len(memories)} MEMORIES")
    output.append("="*80 + "\n")

    for i, mem in enumerate(memories, 1):
        output.append(f"{i}. Memory ID: {mem['id']} | Category: {mem['category']}")
        output.append(f"   Strength: {mem['strength']:.3f} "
                     f"(sem={mem['semantic_similarity']:.3f} "
                     f"emo={mem['emotional_resonance']:.3f} "
                     f"rec={mem['recency']:.3f})")
        output.append(f"   Age: {mem['age_days']:.0f} days")
        output.append(f"   Takeaway: {mem['takeaway'][:100]}...")
        output.append("")

    return "\n".join(output)


def format_for_injection(memories: List[Dict]) -> str:
    """Format memories as XML for system prompt injection"""
    if not memories:
        return ""

    xml = ['<episodic_memories>']

    for mem in memories:
        xml.append('  <memory>')
        xml.append(f'    <id>{mem["id"]}</id>')
        xml.append(f'    <category>{mem["category"]}</category>')
        xml.append(f'    <age_days>{mem["age_days"]:.0f}</age_days>')
        xml.append(f'    <strength>{mem["strength"]:.3f}</strength>')
        xml.append(f'    <takeaway>{mem["takeaway"]}</takeaway>')
        xml.append('  </memory>')

    xml.append('</episodic_memories>')

    return '\n'.join(xml)


# ============================================
# MAIN / CLI
# ============================================

def main():
    parser = argparse.ArgumentParser(description='Iris Memory Retrieval v2')
    parser.add_argument('--conversation', type=str, help='Conversation text to query')
    parser.add_argument('--file', type=str, help='File containing conversation text')
    parser.add_argument('--top-k', type=int, default=10, help='Number of memories to retrieve')
    parser.add_argument('--min-sim', type=float, default=MIN_SIMILARITY, help='Minimum similarity')
    parser.add_argument('--format', choices=['display', 'xml', 'both'], default='display',
                       help='Output format')
    parser.add_argument('--quiet', action='store_true', help='Suppress progress messages')

    args = parser.parse_args()

    # Get conversation text
    if args.conversation:
        conversation = args.conversation
    elif args.file:
        with open(args.file, 'r') as f:
            conversation = f.read()
    else:
        print("Error: Provide --conversation or --file")
        sys.exit(1)

    # Retrieve memories
    memories = retrieve_memories(
        conversation,
        top_k=args.top_k,
        min_similarity=args.min_sim,
        verbose=not args.quiet
    )

    # Output
    if args.format in ['display', 'both']:
        print(format_for_display(memories))

    if args.format in ['xml', 'both']:
        print("\n" + format_for_injection(memories))


if __name__ == '__main__':
    main()
