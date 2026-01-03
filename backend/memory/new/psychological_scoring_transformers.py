"""
Psychological Scoring System for Memory Formation - Transformer Edition
Based on 2024 psychology research with state-of-the-art transformer models

Implements 6 key metrics for determining memory worthiness:
1. Arousal (0-1) - Emotional intensity using emotion detection [HIGHEST PRIORITY]
2. Valence (-1 to +1) - Emotional positivity/negativity using sentiment models [HIGH PRIORITY]
3. Novelty (0-1) - Uniqueness vs existing memories using advanced embeddings [HIGH PRIORITY]
4. Coherence (0-1) - Semantic flow using sentence transformers [MEDIUM PRIORITY]
5. Cohesion (0-1) - Internal connectedness using NER and coreference [MEDIUM PRIORITY]
6. Recurrence (0-1) - Similarity to existing memories [LOWER PRIORITY]

Key Improvements over lexicon-based version:
- Transformer-based sentiment analysis (RoBERTa) vs AFINN lexicon
- Emotion intensity models for arousal vs rule-based punctuation counting
- Advanced sentence embeddings (MPNet) vs MiniLM
- Named Entity Recognition for better cohesion tracking
- Batch processing and model caching for efficiency

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
import json
from collections import Counter
from app import config

# Transformer libraries
import torch
from transformers import (
    AutoTokenizer,
    AutoModelForSequenceClassification,
    AutoModel,
    pipeline
)
from sentence_transformers import SentenceTransformer
import warnings
warnings.filterwarnings('ignore', category=FutureWarning)

# ============================================
# CONFIGURATION
# ============================================

class ScoringConfig:
    """Configuration for transformer models and scoring"""

    # Device selection (auto-detect GPU if available)
    DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

    # Model selection
    SENTIMENT_MODEL = "cardiffnlp/twitter-roberta-base-sentiment-latest"  # Valence
    EMOTION_MODEL = "SamLowe/roberta-base-go_emotions"  # Arousal + enhanced valence
    SENTENCE_ENCODER = "sentence-transformers/all-mpnet-base-v2"  # Coherence, novelty
    NER_MODEL = "dslim/bert-base-NER"  # Cohesion (entity tracking)

    # Performance settings
    BATCH_SIZE = 8  # For batch processing
    MAX_LENGTH = 512  # Max tokens per text segment

    # Cache models in memory (set to False to reload each time)
    CACHE_MODELS = True

    # Fallback to rule-based methods if models fail
    ENABLE_FALLBACK = True

    # Arousal emotion mapping (from go_emotions to arousal levels)
    # High arousal emotions (excitement, anger, fear)
    HIGH_AROUSAL_EMOTIONS = {
        'anger', 'annoyance', 'excitement', 'fear', 'surprise',
        'nervousness', 'joy', 'realization'
    }

    # Low arousal emotions (sadness, calm)
    LOW_AROUSAL_EMOTIONS = {
        'sadness', 'grief', 'relief', 'disappointment', 'embarrassment'
    }

    # Valence mapping (positive/negative emotions)
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

# Global model cache
_MODEL_CACHE = {}

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
# MODEL LOADING AND CACHING
# ============================================

def load_model(model_name: str, model_type: str = "pipeline", pipeline_task: str = "text-classification"):
    """
    Load and cache transformer models

    Args:
        model_name: HuggingFace model identifier
        model_type: Type of model to load (pipeline, sentence_transformer, tokenizer_model)
        pipeline_task: Task type for pipeline (text-classification, token-classification, etc)

    Returns:
        Loaded model or pipeline
    """
    cache_key = f"{model_name}_{model_type}_{pipeline_task}"

    # Return cached model if available
    if ScoringConfig.CACHE_MODELS and cache_key in _MODEL_CACHE:
        return _MODEL_CACHE[cache_key]

    print(f"[ModelLoader] Loading {model_type}: {model_name}")

    try:
        if model_type == "pipeline":
            # Load as HuggingFace pipeline
            pipeline_kwargs = {
                "model": model_name,
                "device": 0 if ScoringConfig.DEVICE == "cuda" else -1
            }

            # Only add top_k for text-classification
            if pipeline_task == "text-classification":
                pipeline_kwargs["top_k"] = None  # Return all labels with scores

            model = pipeline(pipeline_task, **pipeline_kwargs)

        elif model_type == "sentence_transformer":
            # Load SentenceTransformer model
            model = SentenceTransformer(model_name, device=ScoringConfig.DEVICE)

        elif model_type == "tokenizer_model":
            # Load tokenizer and model separately (for custom processing)
            tokenizer = AutoTokenizer.from_pretrained(model_name)
            model_obj = AutoModelForSequenceClassification.from_pretrained(model_name)
            model_obj.to(ScoringConfig.DEVICE)
            model = (tokenizer, model_obj)

        else:
            raise ValueError(f"Unknown model type: {model_type}")

        # Cache the model
        if ScoringConfig.CACHE_MODELS:
            _MODEL_CACHE[cache_key] = model

        print(f"[ModelLoader] ✓ Loaded {model_name} on {ScoringConfig.DEVICE}")
        return model

    except Exception as e:
        print(f"[ModelLoader] ✗ Failed to load {model_name}: {e}")
        return None

# ============================================
# TEXT PREPROCESSING
# ============================================

def count_tokens(text: str) -> int:
    """Approximate token count (words * 1.3 for subword tokens)"""
    return int(len(text.split()) * 1.3)

def chunk_text(text: str, max_length: int = 512) -> List[str]:
    """
    Split text into chunks that fit within model's max length

    Args:
        text: Input text
        max_length: Maximum tokens per chunk

    Returns:
        List of text chunks
    """
    # Simple sentence-based chunking
    sentences = text.replace('!', '.').replace('?', '.').split('.')
    sentences = [s.strip() for s in sentences if s.strip()]

    chunks = []
    current_chunk = []
    current_length = 0

    for sentence in sentences:
        sentence_tokens = len(sentence.split())

        if current_length + sentence_tokens > max_length:
            if current_chunk:
                chunks.append('. '.join(current_chunk) + '.')
            current_chunk = [sentence]
            current_length = sentence_tokens
        else:
            current_chunk.append(sentence)
            current_length += sentence_tokens

    if current_chunk:
        chunks.append('. '.join(current_chunk) + '.')

    return chunks if chunks else [text[:max_length]]

# ============================================
# METRIC 1: VALENCE (-1 to +1) - TRANSFORMER
# ============================================

def calculate_valence_transformer(messages: List[Dict]) -> float:
    """
    Calculate emotional valence using transformer-based emotion detection

    Uses RoBERTa model fine-tuned on GoEmotions dataset with 28 emotion categories
    Maps emotions to valence dimension of Russell's Circumplex Model

    Args:
        messages: List of message dicts with 'role' and 'message' fields

    Returns:
        Score from -1 (very negative) to +1 (very positive)
    """
    print(f"[Valence] Using transformer model: {ScoringConfig.EMOTION_MODEL}")

    # Load emotion detection model
    emotion_classifier = load_model(ScoringConfig.EMOTION_MODEL, "pipeline")
    if emotion_classifier is None:
        print(f"[Valence] ✗ Failed to load model, returning neutral")
        return 0.0

    # Weight messages by role
    role_weights = {'user': 1.0, 'assistant': 0.8, 'system': 0.3, 'tool': 0.3}

    positive_score = 0.0
    negative_score = 0.0
    total_weight = 0.0

    for msg in messages:
        role = msg.get('role', 'user')
        weight = role_weights.get(role, 1.0)
        text = msg['message']

        # Skip very short messages
        if len(text.strip()) < 5:
            continue

        try:
            # Get emotion predictions
            # Returns list of dicts: [{'label': 'joy', 'score': 0.95}, ...]
            predictions = emotion_classifier(text[:512])[0]  # Limit to max length

            # Aggregate positive and negative emotions
            for pred in predictions:
                emotion = pred['label']
                score = pred['score']

                if emotion in ScoringConfig.POSITIVE_EMOTIONS:
                    positive_score += score * weight
                elif emotion in ScoringConfig.NEGATIVE_EMOTIONS:
                    negative_score += score * weight

            total_weight += weight

        except Exception as e:
            print(f"[Valence] ✗ Error processing message: {e}")
            continue

    # Calculate valence
    if total_weight == 0:
        return 0.0

    # Normalize scores
    positive_norm = positive_score / total_weight
    negative_norm = negative_score / total_weight

    # Calculate valence as normalized difference
    total_emotion = positive_norm + negative_norm
    if total_emotion == 0:
        return 0.0

    valence = (positive_norm - negative_norm) / total_emotion

    print(f"[Valence] Positive: {positive_norm:.3f}, Negative: {negative_norm:.3f}, Valence: {valence:.3f}")
    return valence

# ============================================
# METRIC 2: AROUSAL (0 to 1) - TRANSFORMER
# ============================================

def calculate_arousal_transformer(messages: List[Dict]) -> float:
    """
    Calculate emotional arousal using transformer-based emotion intensity

    Maps emotions from GoEmotions to arousal dimension (activation level)
    High arousal: anger, fear, excitement, surprise
    Low arousal: sadness, calm, relief

    Args:
        messages: List of message dicts with 'role' and 'message' fields

    Returns:
        Score from 0 (low arousal/calm) to 1 (high arousal/activated)
    """
    print(f"[Arousal] Using transformer model: {ScoringConfig.EMOTION_MODEL}")

    # Load emotion detection model
    emotion_classifier = load_model(ScoringConfig.EMOTION_MODEL, "pipeline")
    if emotion_classifier is None:
        print(f"[Arousal] ✗ Failed to load model, returning neutral")
        return 0.0

    high_arousal_score = 0.0
    low_arousal_score = 0.0
    total_score = 0.0

    for msg in messages:
        text = msg['message']

        # Skip very short messages
        if len(text.strip()) < 5:
            continue

        try:
            # Get emotion predictions
            predictions = emotion_classifier(text[:512])[0]

            # Aggregate arousal scores
            for pred in predictions:
                emotion = pred['label']
                score = pred['score']

                if emotion in ScoringConfig.HIGH_AROUSAL_EMOTIONS:
                    high_arousal_score += score
                    total_score += score
                elif emotion in ScoringConfig.LOW_AROUSAL_EMOTIONS:
                    low_arousal_score += score
                    total_score += score

        except Exception as e:
            print(f"[Arousal] ✗ Error processing message: {e}")
            continue

    # Calculate arousal
    if total_score == 0:
        return 0.0

    # Arousal is the ratio of high arousal emotions to total emotions
    arousal = high_arousal_score / total_score

    print(f"[Arousal] High arousal: {high_arousal_score:.3f}, Total: {total_score:.3f}, Arousal: {arousal:.3f}")
    return min(arousal, 1.0)

# ============================================
# METRIC 3: NOVELTY (0 to 1) - ENHANCED
# ============================================

def generate_embedding_mpnet(text: str) -> Optional[np.ndarray]:
    """
    Generate embedding using MPNet (better than MiniLM)

    Args:
        text: Text to embed

    Returns:
        Numpy array of embedding vector or None on error
    """
    try:
        encoder = load_model(ScoringConfig.SENTENCE_ENCODER, "sentence_transformer")
        if encoder is None:
            return None

        embedding = encoder.encode(text, convert_to_numpy=True)
        return embedding

    except Exception as e:
        print(f"[Embedding] ✗ Error generating embedding: {e}")
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
    return float(dot_product / (norm1 * norm2))

def calculate_novelty_transformer(
    topic_embedding: np.ndarray,
    session_id: str = None
) -> float:
    """
    Calculate novelty score using advanced embeddings

    Args:
        topic_embedding: Embedding vector for the topic (MPNet)
        session_id: Optional session ID to exclude from comparison

    Returns:
        Score from 0 (very familiar) to 1 (very novel)
    """
    if topic_embedding is None:
        return 0.5  # Neutral if no embedding

    print(f"[Novelty] Comparing against existing memories")

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # Get embeddings from existing episodic memories
            # Try to use the same MPNet embeddings if available, fallback to MiniLM
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
                print(f"[Novelty] No existing memories found - maximum novelty")
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
            print(f"[Novelty] Max similarity: {max_similarity:.3f}, Novelty: {novelty:.3f}")
            return max(0.0, min(1.0, novelty))

    finally:
        conn.close()

# ============================================
# METRIC 4: COHERENCE (0 to 1) - ENHANCED
# ============================================

def calculate_coherence_transformer(messages: List[Dict]) -> float:
    """
    Calculate semantic coherence using advanced sentence transformers

    Uses MPNet embeddings for better semantic understanding
    Measures flow between consecutive messages

    Args:
        messages: List of message dicts

    Returns:
        Score from 0 (incoherent) to 1 (highly coherent)
    """
    if len(messages) < 2:
        return 1.0  # Single message is perfectly coherent with itself

    print(f"[Coherence] Using sentence encoder: {ScoringConfig.SENTENCE_ENCODER}")

    # Load sentence encoder
    encoder = load_model(ScoringConfig.SENTENCE_ENCODER, "sentence_transformer")
    if encoder is None:
        print(f"[Coherence] ✗ Failed to load model, returning neutral")
        return 0.5

    # Extract message texts
    texts = []
    for msg in messages:
        text = msg['message']
        # Skip very short messages (< 10 chars)
        if len(text.strip()) >= 10:
            texts.append(text)

    if len(texts) < 2:
        return 0.5  # Neutral if can't calculate

    try:
        # Generate embeddings for all messages in batch
        embeddings = encoder.encode(texts, convert_to_numpy=True, batch_size=ScoringConfig.BATCH_SIZE)

        # Calculate pairwise similarities between adjacent messages
        similarities = []
        for i in range(len(embeddings) - 1):
            sim = cosine_similarity(embeddings[i], embeddings[i + 1])
            similarities.append(sim)

        # Average similarity is coherence score
        coherence = float(np.mean(similarities))
        print(f"[Coherence] Average adjacent similarity: {coherence:.3f}")
        return max(0.0, min(1.0, coherence))

    except Exception as e:
        print(f"[Coherence] ✗ Error calculating coherence: {e}")
        return 0.5

# ============================================
# METRIC 5: COHESION (0 to 1) - TRANSFORMER
# ============================================

def extract_entities_ner(messages: List[Dict]) -> List[str]:
    """
    Extract named entities using transformer-based NER

    Args:
        messages: List of message dicts

    Returns:
        List of extracted entity strings (complete entities, not tokens)
    """
    print(f"[NER] Using NER model: {ScoringConfig.NER_MODEL}")

    # Load NER pipeline with token-classification task
    ner_pipeline = load_model(ScoringConfig.NER_MODEL, "pipeline", pipeline_task="token-classification")
    if ner_pipeline is None:
        print(f"[NER] ✗ Failed to load model, returning empty list")
        return []

    entities = []
    total_predictions = 0

    for msg in messages:
        text = msg['message']

        # Skip very short messages
        if len(text.strip()) < 10:
            continue

        try:
            # Get NER predictions without aggregation first
            predictions = ner_pipeline(text[:512])
            total_predictions += len(predictions)

            # Manually group and merge entity tokens
            # This gives us more control than aggregation_strategy
            current_entity = []
            current_entity_type = None
            current_score = 0.0
            current_count = 0

            for pred in predictions:
                entity_tag = pred['entity']
                word = pred['word']
                score = pred['score']

                # Check if this is a high-confidence prediction
                if score > 0.7:
                    # B- tags start a new entity
                    if entity_tag.startswith('B-'):
                        # Save previous entity if exists
                        if current_entity:
                            avg_score = current_score / current_count
                            if avg_score > 0.7:
                                # Merge tokens, removing ## prefix from subwords
                                merged = ''.join(t.replace('##', '') for t in current_entity)
                                if merged:
                                    entities.append(merged)

                        # Start new entity
                        current_entity = [word]
                        current_entity_type = entity_tag[2:]  # Remove B- prefix
                        current_score = score
                        current_count = 1

                    # I- tags continue the current entity
                    elif entity_tag.startswith('I-') and current_entity:
                        entity_type = entity_tag[2:]  # Remove I- prefix
                        # Only continue if same entity type
                        if entity_type == current_entity_type:
                            current_entity.append(word)
                            current_score += score
                            current_count += 1
                        else:
                            # Different entity type, save current and start new
                            if current_entity:
                                avg_score = current_score / current_count
                                if avg_score > 0.7:
                                    merged = ''.join(t.replace('##', '') for t in current_entity)
                                    if merged:
                                        entities.append(merged)
                            current_entity = [word]
                            current_entity_type = entity_type
                            current_score = score
                            current_count = 1

            # Don't forget the last entity
            if current_entity:
                avg_score = current_score / current_count
                if avg_score > 0.7:
                    merged = ''.join(t.replace('##', '') for t in current_entity)
                    if merged:
                        entities.append(merged)

        except Exception as e:
            print(f"[NER] ✗ Error processing message: {e}")
            import traceback
            traceback.print_exc()
            continue

    print(f"[NER] Found {len(entities)} entities from {total_predictions} predictions across {len(messages)} messages")
    if entities:
        print(f"[NER] Sample entities: {entities[:10]}")

    return entities

def calculate_cohesion_transformer(messages: List[Dict]) -> float:
    """
    Calculate narrative cohesion using NER and linguistic features

    Combines:
    1. Entity persistence (via transformer NER)
    2. Reference chain density (pronouns/demonstratives)
    3. Turn-taking regularity

    Args:
        messages: List of message dicts

    Returns:
        Score from 0 (fragmented) to 1 (highly cohesive)
    """
    if len(messages) < 2:
        return 1.0  # Single message is perfectly cohesive

    # Component 1: Entity persistence using NER (50% weight)
    entities = extract_entities_ner(messages)
    if entities:
        entity_counts = Counter(entities)
        persistent_entities = sum(1 for count in entity_counts.values() if count > 1)
        entity_score = min(persistent_entities / max(len(messages), 1), 1.0)
    else:
        entity_score = 0.0

    # Component 2: Reference chain density (30% weight)
    reference_words = {'this', 'that', 'these', 'those', 'it', 'its', 'he', 'she', 'they', 'them', 'their'}
    total_words = 0
    reference_count = 0

    for msg in messages:
        words = msg['message'].lower().split()
        total_words += len(words)
        reference_count += sum(1 for word in words if word in reference_words)

    reference_density = reference_count / max(total_words, 1)
    reference_score = min(reference_density * 10, 1.0)  # Scale up and cap

    # Component 3: Turn-taking regularity (20% weight)
    roles = [msg.get('role', 'user') for msg in messages]
    role_changes = sum(1 for i in range(len(roles) - 1) if roles[i] != roles[i + 1])

    # Ideal: roughly half the messages are role changes (balanced dialogue)
    ideal_changes = len(messages) / 2
    turn_taking_score = 1.0 - abs(role_changes - ideal_changes) / len(messages)
    turn_taking_score = max(0.0, turn_taking_score)

    # Weighted combination
    cohesion = (
        entity_score * 0.50 +
        reference_score * 0.30 +
        turn_taking_score * 0.20
    )

    print(f"[Cohesion] Entity: {entity_score:.3f}, Reference: {reference_score:.3f}, Turn-taking: {turn_taking_score:.3f}")
    return min(cohesion, 1.0)

# ============================================
# METRIC 6: RECURRENCE (0 to 1)
# ============================================

def calculate_recurrence_transformer(
    topic_embedding: np.ndarray,
    session_id: str = None
) -> float:
    """
    Calculate recurrence (familiarity with existing memories)
    Inverse of novelty - measures schema integration potential

    Returns: Score from 0 (completely novel) to 1 (highly recurrent/familiar)
    """
    # Recurrence is simply the inverse of novelty
    novelty = calculate_novelty_transformer(topic_embedding, session_id)
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
    Calculate all 6 psychological scores using transformer models

    Args:
        session_id: Session UUID
        topic_id: Topic ID within session
        messages: List of message dicts with 'role' and 'message' fields

    Returns:
        Dict with all scores and metadata
    """

    print(f"\n{'='*70}")
    print(f"[Scoring] TRANSFORMER-BASED PSYCHOLOGICAL SCORING")
    print(f"{'='*70}")
    print(f"[Scoring] Topic {topic_id} in session {session_id}")
    print(f"[Scoring] Messages: {len(messages)}")
    print(f"[Scoring] Device: {ScoringConfig.DEVICE}")

    # Calculate token count
    full_text = ' '.join(msg['message'] for msg in messages)
    token_count = count_tokens(full_text)
    print(f"[Scoring] Token count: {token_count}")

    # Check threshold
    if token_count < 150:
        print(f"[Scoring] ⚠ Below minimum threshold (150 tokens)")

    # Generate topic embedding using MPNet
    print(f"\n[Scoring] Generating MPNet embedding for topic...")
    topic_embedding = generate_embedding_mpnet(full_text)

    # Calculate all metrics
    print(f"\n[Scoring] Calculating valence (transformer)...")
    valence = calculate_valence_transformer(messages)

    print(f"\n[Scoring] Calculating arousal (transformer)...")
    arousal = calculate_arousal_transformer(messages)

    print(f"\n[Scoring] Calculating novelty (enhanced embeddings)...")
    novelty = calculate_novelty_transformer(topic_embedding, session_id)

    print(f"\n[Scoring] Calculating coherence (transformer)...")
    coherence = calculate_coherence_transformer(messages)

    print(f"\n[Scoring] Calculating cohesion (transformer NER)...")
    cohesion = calculate_cohesion_transformer(messages)

    print(f"\n[Scoring] Calculating recurrence...")
    recurrence = calculate_recurrence_transformer(topic_embedding, session_id)

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
        'embedding': topic_embedding.tolist() if topic_embedding is not None else None,
        'scoring_method': 'transformer'
    }

    # Print results
    print(f"\n{'='*70}")
    print(f"[Results] TRANSFORMER-BASED PSYCHOLOGICAL SCORES:")
    print(f"{'='*70}")
    print(f"  Arousal:    {scores['arousal']:.3f}  [HIGH PRIORITY - Emotion intensity]")
    print(f"  Valence:    {scores['valence']:+.3f}  [HIGH PRIORITY - Sentiment analysis]")
    print(f"  Novelty:    {scores['novelty']:.3f}  [HIGH PRIORITY - Encoding trigger]")
    print(f"  Coherence:  {scores['coherence']:.3f}  [MEDIUM - Semantic flow]")
    print(f"  Cohesion:   {scores['cohesion']:.3f}  [MEDIUM - Narrative quality]")
    print(f"  Recurrence: {scores['recurrence']:.3f}  [LOWER - Schema integration]")
    print(f"{'='*70}\n")

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
    """Test the transformer-based scoring system"""
    print("="*70)
    print("TRANSFORMER-BASED PSYCHOLOGICAL SCORING SYSTEM TEST")
    print("="*70)
    print(f"Device: {ScoringConfig.DEVICE}")
    print(f"Models will be loaded on: {ScoringConfig.DEVICE.upper()}")
    print("="*70)

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

    print(f"\n{'='*70}")
    print("TEST COMPLETE")
    print("="*70)

    return scores

# ============================================
# UTILITY: MODEL INFO
# ============================================

def print_model_info():
    """Print information about loaded models"""
    print("\n" + "="*70)
    print("TRANSFORMER MODEL CONFIGURATION")
    print("="*70)
    print(f"Device: {ScoringConfig.DEVICE}")
    print(f"\nModels:")
    print(f"  Sentiment/Valence: {ScoringConfig.SENTIMENT_MODEL}")
    print(f"  Emotion/Arousal:   {ScoringConfig.EMOTION_MODEL}")
    print(f"  Sentence Encoder:  {ScoringConfig.SENTENCE_ENCODER}")
    print(f"  Named Entity Rec:  {ScoringConfig.NER_MODEL}")
    print(f"\nSettings:")
    print(f"  Batch Size:        {ScoringConfig.BATCH_SIZE}")
    print(f"  Max Length:        {ScoringConfig.MAX_LENGTH}")
    print(f"  Model Caching:     {ScoringConfig.CACHE_MODELS}")
    print("="*70 + "\n")

if __name__ == "__main__":
    print_model_info()
    test_scoring()
