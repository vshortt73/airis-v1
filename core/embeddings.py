"""
Embedding generation for Iris v3
Generates vector embeddings for message text using SentenceTransformer

FIXED: Added thread-safe locking to prevent race conditions when multiple
       processes/threads try to load the model simultaneously

Updated 2026-01-24: Use CUDA GPU for faster embeddings with CPU fallback.
       When qwen3:32b is loaded on the RTX 5090, CUDA may OOM - falls back to CPU.
"""
import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)

from sentence_transformers import SentenceTransformer
from typing import Optional, List
import numpy as np
import threading
import torch

from app import config

# Global model instance (lazy loaded)
_embedding_model = None
_model_lock = threading.Lock()

def get_embedding_model(force_cpu: bool = False):
    """
    Get or initialize the embedding model (singleton pattern with thread safety)

    Thread-safe implementation prevents race conditions when multiple
    processes try to load the model simultaneously.

    Args:
        force_cpu: If True, skip CUDA entirely. Use this in MCP subprocesses
                   where CUDA OOM recovery can write binary to stdout and
                   corrupt the JSON-RPC protocol.

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
                # Determine device: force_cpu for MCP subprocesses, otherwise try CUDA
                if force_cpu:
                    device = 'cpu'
                else:
                    device = 'cuda' if torch.cuda.is_available() else 'cpu'
                print(f"[embeddings.py][get_embedding_model] Loading all-mpnet-base-v2 model on {device}...", file=sys.stderr)

                try:
                    _embedding_model = SentenceTransformer(
                        "all-mpnet-base-v2",
                        device=device,
                        cache_folder=config.HF_CACHE_DIR
                    )
                    # Run a small test encode to verify CUDA actually works
                    _embedding_model.encode("test", convert_to_numpy=True)
                    print(f"[embeddings.py][get_embedding_model] ✓ Loaded all-mpnet-base-v2 model on {device}", file=sys.stderr)
                except Exception as cuda_err:
                    if device == 'cuda':
                        print(f"[embeddings.py][get_embedding_model] CUDA failed ({cuda_err}), falling back to CPU...", file=sys.stderr)
                        torch.cuda.empty_cache()
                        device = 'cpu'
                        _embedding_model = SentenceTransformer(
                            "all-mpnet-base-v2",
                            device=device,
                            cache_folder=config.HF_CACHE_DIR
                        )
                        print(f"[embeddings.py][get_embedding_model] ✓ Loaded all-mpnet-base-v2 model on CPU (fallback)", file=sys.stderr)
                    else:
                        raise
            except Exception as e:
                print(f"[embeddings.py][get_embedding_model] ✗ Error loading model: {e}", file=sys.stderr)
                raise

    return _embedding_model

def generate_embedding(text: str, force_cpu: bool = False) -> Optional[List[float]]:
    """
    Generate embedding vector for text

    Args:
        text: Input text to embed
        force_cpu: If True, force CPU device (for MCP subprocesses)

    Returns:
        List of 768 floats, or None on error
    """
    if not text or not text.strip():
        return None

    try:
        model = get_embedding_model(force_cpu=force_cpu)
        embedding = model.encode(text, convert_to_numpy=True)
        return embedding.tolist()
    except Exception as e:
        print(f"[embeddings.py][generate_embedding] ✗ Error generating embedding: {e}", file=sys.stderr)
        return None

def generate_embeddings_batch(
    texts: List[str],
    batch_size: int = 32,
    show_progress: bool = True,
    force_cpu: bool = False
) -> List[Optional[List[float]]]:
    """
    Generate embeddings for multiple texts with proper batching

    Args:
        texts: List of input texts
        batch_size: Number of texts to process per batch (default 32)
        show_progress: Whether to show progress for large batches
        force_cpu: If True, temporarily move model to CPU for encoding.
                   Use when CUDA VRAM is exhausted (e.g., Ollama using most GPU memory).

    Returns:
        List of embedding vectors (768 floats each), or None for failed embeddings
    """
    if not texts:
        return []

    try:
        model = get_embedding_model()

        # If force_cpu requested and model is on CUDA, temporarily move to CPU
        moved_to_cpu = False
        if force_cpu and hasattr(model, 'device') and str(model.device).startswith('cuda'):
            with _model_lock:
                print(f"[embeddings.py][generate_embeddings_batch] Moving model to CPU for batch encoding...", file=sys.stderr)
                model.to('cpu')
                moved_to_cpu = True

        try:
            # For small batches, just encode directly
            if len(texts) <= batch_size:
                embeddings = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
                return [emb.tolist() for emb in embeddings]

            # For large batches, process in chunks to avoid memory issues
            all_embeddings = []
            total_batches = (len(texts) + batch_size - 1) // batch_size

            if show_progress:
                print(f"[embeddings.py][generate_embeddings_batch] Processing {len(texts)} texts in {total_batches} batches...", file=sys.stderr)

            for i in range(0, len(texts), batch_size):
                batch_texts = texts[i:i + batch_size]
                batch_num = i // batch_size + 1

                if show_progress and total_batches > 1:
                    print(f"[embeddings.py][generate_embeddings_batch] Batch {batch_num}/{total_batches}...", file=sys.stderr)

                batch_embeddings = model.encode(batch_texts, convert_to_numpy=True, show_progress_bar=False)
                all_embeddings.extend([emb.tolist() for emb in batch_embeddings])

            if show_progress:
                print(f"[embeddings.py][generate_embeddings_batch] ✓ Generated {len(all_embeddings)} embeddings", file=sys.stderr)

            return all_embeddings
        finally:
            # Move model back to CUDA if we moved it
            if moved_to_cpu:
                with _model_lock:
                    try:
                        model.to('cuda')
                        print(f"[embeddings.py][generate_embeddings_batch] Moved model back to CUDA", file=sys.stderr)
                    except Exception:
                        print(f"[embeddings.py][generate_embeddings_batch] Could not move model back to CUDA, staying on CPU", file=sys.stderr)

    except Exception as e:
        print(f"[embeddings.py][generate_embeddings_batch] ✗ Error generating embeddings: {e}", file=sys.stderr)
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