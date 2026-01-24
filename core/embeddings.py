"""
Embedding generation for Iris v3
Generates vector embeddings for message text using SentenceTransformer

FIXED: Added thread-safe locking to prevent race conditions when multiple
       processes/threads try to load the model simultaneously
"""
import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)

from sentence_transformers import SentenceTransformer
from typing import Optional, List
import numpy as np
import threading

# Global model instance (lazy loaded)
_embedding_model = None
_model_lock = threading.Lock()

def get_embedding_model():
    """
    Get or initialize the embedding model (singleton pattern with thread safety)
    
    Thread-safe implementation prevents race conditions when multiple
    processes try to load the model simultaneously.
    
    Returns:
        SentenceTransformer model instance
    """
    global _embedding_model
    
    # Fast path: model already loaded
    if _embedding_model is not None:
        return _embedding_model
    
    # Slow path: need to load model (thread-safe)
    with _model_lock:
        # Double-check inside lock (another thread may have loaded it)
        if _embedding_model is None:
            try:
                print("[embeddings.py][get_embedding_model] Loading all-mpnet-base-v2 model...")
                # Use the same model as the memory system: all-mpnet-base-v2 (768 dimensions)
                # Force CPU usage to avoid competing with 70B model for GPU VRAM
                _embedding_model = SentenceTransformer(
                    "all-mpnet-base-v2",
                    device='cpu',
                    cache_folder="/home/captain/.cache/huggingface/hub"
                )
                print("[embeddings.py][get_embedding_model] ✓ Loaded all-mpnet-base-v2 model")
            except Exception as e:
                print(f"[embeddings.py][get_embedding_model] ✗ Error loading model: {e}")
                raise
    
    return _embedding_model

def generate_embedding(text: str) -> Optional[List[float]]:
    """
    Generate embedding vector for text

    Args:
        text: Input text to embed

    Returns:
        List of 768 floats, or None on error
    """
    if not text or not text.strip():
        return None

    try:
        model = get_embedding_model()
        embedding = model.encode(text, convert_to_numpy=True)
        return embedding.tolist()
    except Exception as e:
        print(f"[embeddings.py][generate_embedding] ✗ Error generating embedding: {e}")
        return None

def generate_embeddings_batch(texts: List[str]) -> List[Optional[List[float]]]:
    """
    Generate embeddings for multiple texts (more efficient than one-by-one)

    Args:
        texts: List of input texts

    Returns:
        List of embedding vectors (768 floats each), or None for failed embeddings
    """
    if not texts:
        return []

    try:
        model = get_embedding_model()
        embeddings = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
        return [emb.tolist() for emb in embeddings]
    except Exception as e:
        print(f"[embeddings.py][generate_embeddings_batch] ✗ Error generating embeddings: {e}")
        return [None] * len(texts)

if __name__ == "__main__":
    # Test embedding generation
    test_text = "Hello, this is a test message for embedding generation."
    print(f"Generating embedding for: {test_text}")
    embedding = generate_embedding(test_text)
    if embedding:
        print(f"✓ Generated embedding with {len(embedding)} dimensions")
        print(f"  First 5 values: {embedding[:5]}")
    else:
        print("✗ Failed to generate embedding")