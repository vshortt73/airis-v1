"""
Document Processor - Extract text from uploaded documents for chat context

Handles PDF, Word (.docx), and LibreOffice (.odt) documents.
Extracts text and returns it for inclusion in the conversation context.

Smart handling for large documents:
- Configurable token budget (DOCUMENT_CONTEXT_BUDGET)
- Semantic relevance filtering when user provides a question
- Keeps intro + most relevant sections for large docs
- Budget splitting across multiple documents
"""

import os
import sys
import base64
import tempfile
from typing import Optional, Dict, List, Tuple

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)

from backend.knowledge.extractors import TextExtractor
from app import config


def get_document_budget() -> int:
    """Get document token budget from config (default 8000 tokens ~ 32000 chars)"""
    return getattr(config, 'DOCUMENT_CONTEXT_BUDGET', 8000)


def estimate_tokens(text: str) -> int:
    """Rough token estimate (4 chars per token)"""
    return len(text) // 4


def chunk_text(text: str, chunk_size: int = 1000) -> List[str]:
    """Split text into chunks, trying to break at paragraph boundaries"""
    chunks = []
    paragraphs = text.split('\n\n')
    current_chunk = ""

    for para in paragraphs:
        if len(current_chunk) + len(para) > chunk_size * 4:  # chars, not tokens
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = para
        else:
            current_chunk += "\n\n" + para if current_chunk else para

    if current_chunk:
        chunks.append(current_chunk.strip())

    return chunks


async def get_relevant_chunks(chunks: List[str], query: str, max_chunks: int = 5) -> List[Tuple[int, str, float]]:
    """
    Find the most relevant chunks using embeddings.
    Returns list of (index, chunk_text, similarity_score)
    """
    try:
        from core.embeddings import generate_embedding
        import numpy as np

        query_embedding = generate_embedding(query)
        if not query_embedding:
            return [(i, c, 0.0) for i, c in enumerate(chunks[:max_chunks])]

        query_vec = np.array(query_embedding)

        scored_chunks = []
        for i, chunk in enumerate(chunks):
            chunk_embedding = generate_embedding(chunk[:2000])  # Limit chunk size for embedding
            if chunk_embedding:
                chunk_vec = np.array(chunk_embedding)
                # Cosine similarity
                similarity = np.dot(query_vec, chunk_vec) / (np.linalg.norm(query_vec) * np.linalg.norm(chunk_vec))
                scored_chunks.append((i, chunk, float(similarity)))
            else:
                scored_chunks.append((i, chunk, 0.0))

        # Sort by similarity, keep top chunks
        scored_chunks.sort(key=lambda x: x[2], reverse=True)
        return scored_chunks[:max_chunks]

    except Exception as e:
        print(f"[document_processor] Relevance scoring failed: {e}, using first chunks")
        return [(i, c, 0.0) for i, c in enumerate(chunks[:max_chunks])]


# Maximum characters fallback (used if config not available)
MAX_DOCUMENT_CHARS = 32000  # ~8,000 tokens


def extract_document_text(
    document_b64: str,
    filename: str,
    max_chars: int = MAX_DOCUMENT_CHARS
) -> Tuple[Optional[str], Optional[Dict]]:
    """
    Extract text from a base64-encoded document.

    Args:
        document_b64: Base64-encoded document content
        filename: Original filename (used to determine file type)
        max_chars: Maximum characters to extract

    Returns:
        Tuple of (extracted_text, metadata) or (None, None) on error
    """
    # Determine file type from filename
    _, ext = os.path.splitext(filename.lower())

    if ext not in ['.pdf', '.docx', '.odt', '.txt', '.md']:
        print(f"[document_processor] Unsupported document type: {ext}")
        return None, {"error": f"Unsupported document type: {ext}"}

    try:
        # Decode base64 to bytes
        # Handle data URI prefix if present
        if ',' in document_b64:
            document_b64 = document_b64.split(',', 1)[1]

        doc_bytes = base64.b64decode(document_b64)

        # Write to temp file for extraction
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(doc_bytes)
            tmp_path = tmp.name

        try:
            # Extract text using knowledge extractors
            extractor = TextExtractor()
            doc = extractor.extract_text(tmp_path, ext)

            if doc is None:
                return None, {"error": "Failed to extract text from document"}

            text = doc.text
            metadata = {
                "title": doc.title,
                "file_type": ext,
                "sections": len(doc.sections),
                **doc.metadata
            }

            # Truncate if too long
            if len(text) > max_chars:
                text = text[:max_chars] + f"\n\n[...document truncated at {max_chars:,} characters]"
                metadata["truncated"] = True
                metadata["original_length"] = len(doc.text)

            print(f"[document_processor] ✓ Extracted {len(text):,} chars from {filename}")
            return text, metadata

        finally:
            # Clean up temp file
            os.unlink(tmp_path)

    except Exception as e:
        print(f"[document_processor] ✗ Error processing {filename}: {e}")
        return None, {"error": str(e)}


async def process_documents_for_conversation(
    documents: List[Dict],
    user_message: Optional[str] = None
) -> Optional[str]:
    """
    Process multiple documents and return combined context for conversation.

    Smart handling:
    - Splits token budget across multiple documents
    - Uses semantic relevance when user provides a question
    - Keeps document intro + most relevant sections for large docs

    Args:
        documents: List of dicts with 'content' (base64) and 'filename'
        user_message: Optional user message for semantic relevance filtering

    Returns:
        Combined document text for context, or None if all failed
    """
    results = []
    total_budget = get_document_budget()  # tokens

    # Split budget across documents
    per_doc_budget = total_budget // len(documents) if documents else total_budget
    per_doc_chars = per_doc_budget * 4  # ~4 chars per token

    print(f"[document_processor] Processing {len(documents)} document(s), budget: {per_doc_budget} tokens/doc")

    for doc in documents:
        content = doc.get("content", "")
        filename = doc.get("filename", "document")

        # Extract full text first (no truncation)
        text, metadata = extract_document_text(content, filename, max_chars=500000)

        if not text:
            error = metadata.get('error', 'Unknown error') if metadata else 'Unknown error'
            results.append(f"=== Document: {filename} ===\n[Failed to extract: {error}]")
            continue

        doc_tokens = estimate_tokens(text)
        title = metadata.get('title', filename)
        file_type = metadata.get('file_type', 'unknown')

        # Document fits in budget - include full text
        if doc_tokens <= per_doc_budget:
            doc_header = f"=== Document: {title} ({file_type}) - {doc_tokens:,} tokens ==="
            results.append(f"{doc_header}\n\n{text}")
            print(f"[document_processor] ✓ {filename}: full text ({doc_tokens:,} tokens)")
            continue

        # Document too large - use smart extraction
        print(f"[document_processor] {filename}: {doc_tokens:,} tokens > budget {per_doc_budget}, using smart extraction")

        # Chunk the document
        chunks = chunk_text(text, chunk_size=800)  # ~200 tokens per chunk

        # Always keep the intro (first 1-2 chunks, up to 20% of budget)
        intro_budget = per_doc_budget // 5
        intro_text = ""
        intro_chunks_used = 0

        for i, chunk in enumerate(chunks):
            if estimate_tokens(intro_text + chunk) > intro_budget:
                break
            intro_text += ("\n\n" if intro_text else "") + chunk
            intro_chunks_used = i + 1

        remaining_budget = per_doc_budget - estimate_tokens(intro_text)
        remaining_chunks = chunks[intro_chunks_used:]

        # Use semantic relevance if user asked a question
        relevant_text = ""
        if user_message and remaining_chunks:
            print(f"[document_processor] Finding relevant sections for: {user_message[:50]}...")
            relevant = await get_relevant_chunks(remaining_chunks, user_message, max_chunks=10)

            # Sort by original position to maintain document flow
            relevant.sort(key=lambda x: x[0])

            for idx, chunk, score in relevant:
                if estimate_tokens(relevant_text + chunk) > remaining_budget:
                    break
                if score > 0.3:  # Only include if reasonably relevant
                    relevant_text += f"\n\n[...section {idx + intro_chunks_used + 1}...]\n\n{chunk}"

        # Fallback: just take beginning chunks if no relevance or no message
        if not relevant_text and remaining_chunks:
            for chunk in remaining_chunks:
                if estimate_tokens(relevant_text + chunk) > remaining_budget:
                    break
                relevant_text += "\n\n" + chunk

        # Combine intro + relevant sections
        combined = intro_text
        if relevant_text:
            combined += "\n\n[...]\n" + relevant_text

        actual_tokens = estimate_tokens(combined)
        omitted_tokens = doc_tokens - actual_tokens

        doc_header = f"=== Document: {title} ({file_type}) - {actual_tokens:,} of {doc_tokens:,} tokens ==="
        if omitted_tokens > 0:
            doc_header += f"\n[Note: {omitted_tokens:,} tokens omitted. Ask about specific sections if needed.]"

        results.append(f"{doc_header}\n\n{combined}")
        print(f"[document_processor] ✓ {filename}: {actual_tokens:,}/{doc_tokens:,} tokens (smart extraction)")

    if results:
        return "\n\n".join(results)

    return None


# For testing
if __name__ == "__main__":
    import asyncio

    # Test with a simple text file
    test_content = base64.b64encode(b"This is a test document.\n\nIt has multiple paragraphs.").decode()

    text, meta = extract_document_text(test_content, "test.txt")
    print(f"Extracted: {text}")
    print(f"Metadata: {meta}")
