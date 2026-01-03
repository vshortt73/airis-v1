"""
Psychological Scoring System for Memory Formation
Based on 2024 psychology research and established computational methods

Implements 6 key metrics for determining memory worthiness:
1. Arousal (0-1) - Emotional intensity [HIGHEST PRIORITY]
2. Valence (-1 to +1) - Emotional positivity/negativity [HIGH PRIORITY]
3. Novelty (0-1) - Uniqueness vs existing memories [HIGH PRIORITY]
4. Coherence (0-1) - Semantic flow between messages [MEDIUM PRIORITY]
5. Cohesion (0-1) - Internal connectedness [MEDIUM PRIORITY]
6. Recurrence (0-1) - Similarity to existing memories [LOWER PRIORITY]

References:
- Russell's Circumplex Model (1980)
- Memory enhancement study (2024): https://pubmed.ncbi.nlm.nih.gov/38613855/
- Novelty detection: https://pmc.ncbi.nlm.nih.gov/articles/PMC6565889/
- Semantic coherence: https://pmc.ncbi.nlm.nih.gov/articles/PMC6476707/
"""

import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
sys.path.insert(0, PROJECT_ROOT)

import psycopg2
import psycopg2.extras
import numpy as np
from typing import List, Dict, Tuple, Optional
import re
import json
from collections import Counter
from app import config
from core.embeddings import generate_embedding as generate_embedding_sync, generate_embeddings_batch

from afinn import Afinn
import pandas as pd

# ============================================
# DATABASE CONNECTION
# ============================================

def get_db_connection():
    """Get database connection with password from environment"""
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

# ============================================
# EMOTION LEXICONS
# ============================================

# High-arousal emotion words (from circumplex model)
HIGH_AROUSAL_WORDS = {
    'excited', 'thrilled', 'ecstatic', 'elated', 'exhilarated',
    'terrified', 'panicked', 'furious', 'enraged', 'livid',
    'anxious', 'nervous', 'stressed', 'tense', 'alarmed',
    'urgent', 'critical', 'emergency', 'immediate', 'asap',
    'amazing', 'incredible', 'awesome', 'shocking', 'stunning'
}

# Simplified AFINN-style sentiment lexicon (positive/negative words)
POSITIVE_WORDS = {
    'good', 'great', 'excellent', 'wonderful', 'fantastic', 'amazing',
    'love', 'like', 'enjoy', 'happy', 'glad', 'pleased', 'delighted',
    'success', 'successful', 'win', 'winning', 'best', 'better',
    'beautiful', 'perfect', 'brilliant', 'awesome', 'thanks', 'thank'
}

NEGATIVE_WORDS = {
    'bad', 'terrible', 'awful', 'horrible', 'worst', 'hate', 'dislike',
    'sad', 'angry', 'upset', 'annoyed', 'frustrated', 'disappointed',
    'fail', 'failure', 'failed', 'wrong', 'error', 'problem', 'issue',
    'difficult', 'hard', 'impossible', 'broken', 'buggy', 'stuck'
}

# ============================================
# TEXT ANALYSIS HELPERS
# ============================================

def count_tokens(text: str) -> int:
    """Approximate token count (words * 1.3 for subword tokens)"""
    return int(len(text.split()) * 1.3)

def extract_words(text: str) -> List[str]:
    """Extract words from text, lowercase, no punctuation"""
    return re.findall(r'\b[a-z]+\b', text.lower())

def calculate_punctuation_density(text: str) -> float:
    """Calculate density of exclamation marks and question marks"""
    if not text:
        return 0.0
    exclamations = text.count('!') + text.count('?')
    ellipsis = text.count('...')
    total = exclamations + ellipsis
    # Normalize by character count
    density = total / max(len(text), 1)
    return min(density * 100, 1.0)  # Scale and cap at 1.0

def calculate_caps_ratio(text: str) -> float:
    """Calculate ratio of capital letters (excluding sentence starts)"""
    if not text:
        return 0.0
    # Remove sentence-initial caps
    sentences = re.split(r'[.!?]\s+', text)
    total_chars = 0
    caps_chars = 0

    for sentence in sentences:
        if len(sentence) > 1:
            # Skip first character of each sentence
            rest = sentence[1:]
            total_chars += len(rest)
            caps_chars += sum(1 for c in rest if c.isupper())

    if total_chars == 0:
        return 0.0
    return caps_chars / total_chars

def count_emojis(text: str) -> int:
    """Count emoji-like patterns (simple heuristic)"""
    # Common text emojis and unicode emoji patterns
    emoji_patterns = [':)', ':(', ':D', ';)', ':P', '<3', '❤', '💛', '😊', '😢', '😠', '🔥', '✨']
    count = sum(text.count(emoji) for emoji in emoji_patterns)
    # Add unicode emoji range (rough estimate)
    count += len(re.findall(r'[\U0001F300-\U0001F9FF]', text))
    return count

def calculate_message_length_variance(messages: List[Dict]) -> float:
    """Calculate variance in message lengths (indicates arousal pattern)"""
    if len(messages) < 2:
        return 0.0

    lengths = [len(msg['message']) for msg in messages]
    mean_length = np.mean(lengths)
    variance = np.var(lengths)

    # Normalize by mean to get coefficient of variation
    if mean_length == 0:
        return 0.0
    cv = np.sqrt(variance) / mean_length
    return min(cv, 1.0)  # Cap at 1.0

def extract_entities(messages: List[Dict]) -> List[str]:
    """Simple entity extraction (capitalized words, not sentence-initial)"""
    entities = []
    for msg in messages:
        text = msg['message']
        # Split into sentences
        sentences = re.split(r'[.!?]\s+', text)
        for sentence in sentences:
            words = sentence.split()
            # Skip first word (sentence-initial), find capitalized words
            for word in words[1:]:
                # Check if word is capitalized and alpha
                if word and word[0].isupper() and word.isalpha():
                    entities.append(word)
    return entities

# ============================================
# EMBEDDING GENERATION
# ============================================

def generate_embedding(text: str) -> Optional[np.ndarray]:
    """
    Generate embedding vector for text using SentenceTransformer

    Args:
        text: Text to embed

    Returns:
        Numpy array of embedding vector or None on error
    """
    try:
        embedding_list = generate_embedding_sync(text)
        if embedding_list:
            return np.array(embedding_list)
        return None
    except Exception as e:
        print(f"[Embedding] Exception: {e}")
        return None

def cosine_similarity(vec1: np.ndarray, vec2: np.ndarray) -> float:
    """Calculate cosine similarity between two vectors"""
    if vec1 is None or vec2 is None:
        return 0.0
    dot_product = np.dot(vec1, vec2)
    norm1 = np.linalg.norm(vec1)
    norm2 = np.linalg.norm(vec2)
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot_product / (norm1 * norm2)

# ============================================
# METRIC 1: VALENCE (-1 to +1)
# ============================================

def calculate_valence(messages: List[Dict]) -> float:
    
    """
    Calculate emotional valence using Russell's Circumplex Model
    Based on: https://psu.pb.unizin.org/psych425/chapter/circumplex-models/

    Returns: Score from -1 (very negative) to +1 (very positive)
    """

    afn = Afinn(language = 'en')
    afn_score = afn.score(str(messages))
    print("############################")
    print(f"AFN SCORE: {afn_score} for {len(messages)} characters/words/tokens")
    print("############################")

    positive_count = 0
    negative_count = 0
    total_words = 0

    # Weight messages by role
    role_weights = {'user': 1.0, 'assistant': 0.8, 'system': 0.3, 'tool': 0.3}

    for msg in messages:
        role = msg.get('role', 'user')
        weight = role_weights.get(role, 1.0)

        words = extract_words(msg['message'])
        total_words += len(words)


        for word in words:
            if word in POSITIVE_WORDS:
                positive_count += weight
            elif word in NEGATIVE_WORDS:
                negative_count += weight

    # Avoid division by zero
    if total_words == 0:
        return 0.0

    # Calculate valence score
    emotion_words = positive_count + negative_count
    if emotion_words == 0:
        return 0.0  # Neutral

    valence = (positive_count - negative_count) / emotion_words
    return valence

# ============================================
# METRIC 2: AROUSAL (0 to 1)
# ============================================

def calculate_arousal(messages: List[Dict]) -> float:
    """
    Calculate emotional arousal (activation level)
    Based on circumplex arousal dimension

    Returns: Score from 0 (low arousal/calm) to 1 (high arousal/activated)
    """
    if not messages:
        return 0.0

    # Combine all message text
    full_text = ' '.join(msg['message'] for msg in messages)
    all_words = extract_words(full_text)

    # Component 1: Punctuation density (30%)
    punct_score = calculate_punctuation_density(full_text)

    # Component 2: Caps ratio (20%)
    caps_score = calculate_caps_ratio(full_text)

    # Component 3: Emoji intensity (15%)
    emoji_count = count_emojis(full_text)
    emoji_score = min(emoji_count / max(len(messages), 1) / 2, 1.0)  # Normalize

    # Component 4: Message length variance (20%)
    variance_score = calculate_message_length_variance(messages)

    # Component 5: High-arousal words (15%)
    arousal_word_count = sum(1 for word in all_words if word in HIGH_AROUSAL_WORDS)
    arousal_word_score = min(arousal_word_count / max(len(all_words), 1) * 50, 1.0)

    # Weighted combination
    arousal = (
        punct_score * 0.30 +
        caps_score * 0.20 +
        emoji_score * 0.15 +
        variance_score * 0.20 +
        arousal_word_score * 0.15
    )

    return min(arousal, 1.0)

# ============================================
# METRIC 3: NOVELTY (0 to 1)
# ============================================

def calculate_novelty(
    topic_embedding: np.ndarray,
    session_id: str = None
) -> float:
    """
    Calculate novelty score based on similarity to existing memories
    Based on: https://royalsocietypublishing.org/doi/10.1098/rstb.2023.0238

    Args:
        topic_embedding: Embedding vector for the topic
        session_id: Optional session ID to exclude from comparison

    Returns: Score from 0 (very familiar) to 1 (very novel)
    """
    if topic_embedding is None:
        return 0.5  # Neutral if no embedding

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # Get embeddings from existing episodic memories
            query = """
                SELECT emb_minilm
                FROM episodic_memories
                WHERE emb_minilm IS NOT NULL
            """
            params = []

            # Optionally exclude same session
            if session_id:
                query += " AND session_id != %s"
                params.append(session_id)

            query += " LIMIT 1000"  # Limit for performance

            cur.execute(query, params)
            rows = cur.fetchall()

            if not rows:
                return 1.0  # Maximum novelty if no existing memories

            # Calculate max similarity to existing memories
            max_similarity = 0.0
            for row in rows:
                existing_emb = row[0]
                if existing_emb:
                    # Convert PostgreSQL vector to numpy array
                    if isinstance(existing_emb, str):
                        existing_vec = np.array(json.loads(existing_emb))
                    else:
                        existing_vec = np.array(existing_emb)

                    similarity = cosine_similarity(topic_embedding, existing_vec)
                    max_similarity = max(max_similarity, similarity)

            # Novelty is inverse of maximum similarity
            novelty = 1.0 - max_similarity
            return max(0.0, min(1.0, novelty))

    finally:
        conn.close()

# ============================================
# METRIC 4: COHERENCE (0 to 1)
# ============================================

def calculate_coherence(messages: List[Dict]) -> float:
    """
    Calculate semantic coherence using message-to-message similarity
    Based on: https://pmc.ncbi.nlm.nih.gov/articles/PMC6476707/

    Returns: Score from 0 (incoherent) to 1 (highly coherent)
    """
    if len(messages) < 2:
        return 1.0  # Single message is perfectly coherent with itself

    # Generate embeddings for each message
    embeddings = []
    for msg in messages:
        text = msg['message']
        # Skip very short messages (< 10 chars)
        if len(text) < 10:
            continue
        emb = generate_embedding(text)
        if emb is not None:
            embeddings.append(emb)

    if len(embeddings) < 2:
        return 0.5  # Neutral if can't calculate

    # Calculate pairwise similarities between adjacent messages
    similarities = []
    for i in range(len(embeddings) - 1):
        sim = cosine_similarity(embeddings[i], embeddings[i + 1])
        similarities.append(sim)

    # Average similarity is coherence score
    coherence = np.mean(similarities)
    return max(0.0, min(1.0, coherence))

# ============================================
# METRIC 5: COHESION (0 to 1)
# ============================================

def calculate_cohesion(messages: List[Dict]) -> float:
    """
    Calculate narrative cohesion (connectedness)
    Based on reference chains, entity persistence, and turn-taking

    Returns: Score from 0 (fragmented) to 1 (highly cohesive)
    """
    if len(messages) < 2:
        return 1.0  # Single message is perfectly cohesive

    # Component 1: Reference chain density (40%)
    # Count pronouns and demonstratives (this, that, these, those, it, he, she, they)
    reference_words = {'this', 'that', 'these', 'those', 'it', 'its', 'he', 'she', 'they', 'them', 'their'}

    total_words = 0
    reference_count = 0
    for msg in messages:
        words = extract_words(msg['message'])
        total_words += len(words)
        reference_count += sum(1 for word in words if word in reference_words)

    reference_density = reference_count / max(total_words, 1)
    reference_score = min(reference_density * 10, 1.0)  # Scale up and cap

    # Component 2: Entity persistence (30%)
    # Entities that appear in multiple messages
    entities = extract_entities(messages)
    entity_counts = Counter(entities)
    persistent_entities = sum(1 for count in entity_counts.values() if count > 1)
    entity_score = min(persistent_entities / max(len(messages), 1), 1.0)

    # Component 3: Turn-taking regularity (30%)
    # Balanced conversation (not monologue, not too fragmented)
    roles = [msg['role'] for msg in messages]
    role_changes = sum(1 for i in range(len(roles) - 1) if roles[i] != roles[i + 1])

    # Ideal: roughly half the messages are role changes (balanced dialogue)
    ideal_changes = len(messages) / 2
    turn_taking_score = 1.0 - abs(role_changes - ideal_changes) / len(messages)
    turn_taking_score = max(0.0, turn_taking_score)

    # Weighted combination
    cohesion = (
        reference_score * 0.40 +
        entity_score * 0.30 +
        turn_taking_score * 0.30
    )

    return min(cohesion, 1.0)

# ============================================
# METRIC 6: RECURRENCE (0 to 1)
# ============================================

def calculate_recurrence(
    topic_embedding: np.ndarray,
    session_id: str = None
) -> float:
    """
    Calculate recurrence (familiarity with existing memories)
    Inverse of novelty - measures schema integration potential
    Based on: https://pmc.ncbi.nlm.nih.gov/articles/PMC11343309/

    Returns: Score from 0 (completely novel) to 1 (highly recurrent/familiar)
    """
    # Recurrence is simply the inverse of novelty
    novelty = calculate_novelty(topic_embedding, session_id)
    return 1.0 - novelty

# ============================================
# MAIN SCORING PIPELINE
# ============================================

def score_topic(
    session_id: str,
    topic_id: int,
    messages: List[Dict]
) -> Dict[str, float]:
    """
    Calculate all 6 psychological scores for a topic

    Args:
        session_id: Session UUID
        topic_id: Topic ID within session
        messages: List of message dicts with 'role' and 'message' fields

    Returns:
        Dict with all scores and metadata
    """

    print(f"\n[Scoring] Topic {topic_id} in session {session_id}")
    print(f"[Scoring] Messages: {len(messages)}")

    # Calculate token count
    full_text = ' '.join(msg['message'] for msg in messages)
    token_count = count_tokens(full_text)
    print(f"[Scoring] Token count: {token_count}")

    # Check threshold
    if token_count < 150:
        print(f"[Scoring] ⚠ Below minimum threshold (150 tokens)")

    # Generate topic embedding for novelty/recurrence
    topic_embedding = generate_embedding(full_text)

    # Calculate all metrics
    print(f"[Scoring] Calculating valence...")
    valence = calculate_valence(messages)

    print(f"[Scoring] Calculating arousal...")
    arousal = calculate_arousal(messages)

    print(f"[Scoring] Calculating novelty...")
    novelty = calculate_novelty(topic_embedding, session_id)

    print(f"[Scoring] Calculating coherence...")
    coherence = calculate_coherence(messages)

    print(f"[Scoring] Calculating cohesion...")
    cohesion = calculate_cohesion(messages)

    print(f"[Scoring] Calculating recurrence...")
    recurrence = calculate_recurrence(topic_embedding, session_id)

    scores = {
        'session_id': session_id,
        'topic_id': topic_id,
        'token_count': token_count,
        'message_count': len(messages),

        # Psychological scores (in priority order)
        'arousal': round(arousal, 3),
        'valence': round(valence, 3),
        'novelty': round(novelty, 3),
        'coherence': round(coherence, 3),
        'cohesion': round(cohesion, 3),
        'recurrence': round(recurrence, 3),

        # Metadata
        'embedding': topic_embedding.tolist() if topic_embedding is not None else None
    }

    # Print results
    print(f"\n[Results] Psychological Scores:")
    print(f"  Arousal:    {scores['arousal']:.3f}  [HIGH PRIORITY - Strongest memory predictor]")
    print(f"  Valence:    {scores['valence']:+.3f}  [HIGH PRIORITY - U-shaped effect]")
    print(f"  Novelty:    {scores['novelty']:.3f}  [HIGH PRIORITY - Encoding trigger]")
    print(f"  Coherence:  {scores['coherence']:.3f}  [MEDIUM - Episodic binding]")
    print(f"  Cohesion:   {scores['cohesion']:.3f}  [MEDIUM - Narrative quality]")
    print(f"  Recurrence: {scores['recurrence']:.3f}  [LOWER - Schema integration]")

    return scores

# ============================================
# DATABASE OPERATIONS
# ============================================

def get_topic_messages(session_id: str, topic_id: int) -> List[Dict]:
    """Get all messages for a specific topic"""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id, role, message, c_timestamp
                FROM chat_history
                WHERE session_id = %s AND topic_id = %s
                ORDER BY c_timestamp ASC
            """, (session_id, topic_id))

            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()

def get_all_topics() -> List[Tuple[str, int]]:
    """Get all unique (session_id, topic_id) pairs that need scoring"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT session_id, topic_id
                FROM chat_history
                WHERE topic_id IS NOT NULL
                ORDER BY session_id, topic_id
            """)

            return cur.fetchall()
    finally:
        conn.close()

# ============================================
# TESTING
# ============================================

def test_scoring():
    """Test the scoring system on a sample topic"""
    print("="*60)
    print("PSYCHOLOGICAL SCORING SYSTEM TEST")
    print("="*60)

    # Get first topic with messages
    topics = get_all_topics()
    if not topics:
        print("No topics found in database")
        return

    session_id, topic_id = topics[0]
    print(f"\nTesting with session {session_id}, topic {topic_id}")

    messages = get_topic_messages(session_id, topic_id)
    if not messages:
        print("No messages found for this topic")
        return

    scores = score_topic(session_id, topic_id, messages)

    print(f"\n" + "="*60)
    print("TEST COMPLETE")
    print("="*60)

if __name__ == "__main__":
    test_scoring()
