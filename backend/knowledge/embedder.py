"""
Embedder - Generate dual-facet embeddings for document chunks
Reuses existing sentence-transformers singleton from core/embeddings.py
"""

import os
import sys
from typing import List, Tuple, Optional

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, PROJECT_ROOT)

from app import config
from core.embeddings import generate_embeddings_batch
from backend.knowledge.chunker import Chunk
from backend.knowledge.extractors import ExtractedDocument


def generate_chunk_embeddings(
    chunks: List[Chunk],
    doc_title: str,
    batch_size: int = None
) -> List[Tuple[List[float], List[float]]]:
    """
    Generate dual-facet embeddings for chunks using batch processing

    Like episodic memory, we generate TWO embeddings per chunk:
    1. Content embedding (60% weight): Raw chunk text
    2. Context embedding (40% weight): Document title + section + chunk preview

    Uses existing sentence-transformers model (all-mpnet-base-v2, 768 dimensions)

    Args:
        chunks: List of Chunk objects
        doc_title: Document title for context
        batch_size: Batch size for embedding generation (default from config)

    Returns:
        List of tuples (content_embedding, context_embedding)
        Each embedding is a list of 768 floats
    """
    batch_size = batch_size or config.KNOWLEDGE_EMBEDDING_BATCH_SIZE

    if not chunks:
        return []

    print(f"[embedder][generate_chunk_embeddings] Generating embeddings for {len(chunks)} chunks...")

    # Prepare content texts (raw chunk text)
    content_texts = [chunk.text for chunk in chunks]

    # Prepare context texts (enriched with document/section info)
    context_texts = []
    for chunk in chunks:
        # Build context string: "Document Title - Section: Preview..."
        parts = []

        if doc_title:
            parts.append(doc_title)

        if chunk.section_title:
            parts.append(chunk.section_title)

        # Add chunk preview (first 200 chars)
        preview = chunk.text[:200].replace('\n', ' ').strip()
        parts.append(preview)

        context_text = " - ".join(parts)
        context_texts.append(context_text)

    # Generate embeddings in batches for efficiency
    print(f"[embedder][generate_chunk_embeddings] Generating content embeddings (batch_size={batch_size})...")
    content_embeddings = generate_embeddings_batch(content_texts)

    print(f"[embedder][generate_chunk_embeddings] Generating context embeddings (batch_size={batch_size})...")
    context_embeddings = generate_embeddings_batch(context_texts)

    # Validate
    if not content_embeddings or not context_embeddings:
        print(f"[embedder][generate_chunk_embeddings] ✗ Failed to generate embeddings")
        return []

    if len(content_embeddings) != len(chunks) or len(context_embeddings) != len(chunks):
        print(f"[embedder][generate_chunk_embeddings] ✗ Embedding count mismatch")
        return []

    # Combine into tuples
    embeddings = list(zip(content_embeddings, context_embeddings))

    print(f"[embedder][generate_chunk_embeddings] ✓ Generated {len(embeddings)} dual-facet embeddings")

    return embeddings


def generate_single_embedding(text: str) -> Optional[List[float]]:
    """
    Generate a single embedding (for search queries)

    Args:
        text: Text to embed

    Returns:
        768-dimensional embedding vector or None on error
    """
    from core.embeddings import generate_embedding
    return generate_embedding(text)


if __name__ == "__main__":
    # Test embedder
    print("Testing embedder...")

    from backend.knowledge.chunker import Chunk

    # Create sample chunks
    sample_chunks = [
        Chunk(
            text="This is the first chunk of text about Python programming.",
            chunk_index=0,
            token_count=12,
            chunk_type='text',
            section_title="Python Basics",
            language=None,
            line_start=1,
            line_end=1,
            char_start=0,
            char_end=58
        ),
        Chunk(
            text="This is the second chunk covering advanced topics in Python.",
            chunk_index=1,
            token_count=11,
            chunk_type='text',
            section_title="Advanced Python",
            language=None,
            line_start=2,
            line_end=2,
            char_start=59,
            char_end=120
        )
    ]

    # Generate embeddings
    embeddings = generate_chunk_embeddings(sample_chunks, "Python Tutorial")

    print(f"\n✓ Generated embeddings for {len(embeddings)} chunks")

    if embeddings:
        content_emb, context_emb = embeddings[0]
        print(f"\n  Chunk 0:")
        print(f"    Content embedding: {len(content_emb)} dimensions")
        print(f"    Context embedding: {len(context_emb)} dimensions")
        print(f"    Content sample: {content_emb[:5]}")
        print(f"    Context sample: {context_emb[:5]}")
