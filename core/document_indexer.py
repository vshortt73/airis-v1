"""
Document Indexer - Background indexing of uploaded documents to knowledge base

When a user uploads a document through chat, the full text is saved here
so the complete content is searchable via knowledge(action="search"),
even though only a truncated version appears in the chat context.
"""

import asyncio
import os
import sys
from datetime import datetime
from typing import Optional

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)


async def index_document_to_knowledge_base(
    title: str,
    full_text: str,
    file_type: str = ".pdf",
    category: str = "uploaded_documents"
) -> Optional[int]:
    """
    Index a document into the knowledge base in the background.

    Runs CPU-bound chunking/embedding work in an executor to avoid
    blocking the event loop. Reuses the embedding model singleton
    already loaded in the main process.

    Args:
        title: Document title
        full_text: Complete extracted text
        file_type: File extension (e.g. ".pdf", ".docx")
        category: Knowledge base category

    Returns:
        doc_id on success, None on failure
    """
    loop = asyncio.get_event_loop()

    try:
        doc_id = await loop.run_in_executor(None, _index_sync, title, full_text, file_type, category)
        if doc_id:
            print(f"[document_indexer] Saved '{title}' as doc {doc_id}")
            # Send UI notification
            try:
                from core.ui_notify import ui_msg
                ui_msg(f"Document '{title}' indexed to knowledge base", "success")
            except Exception:
                pass
        return doc_id

    except Exception as e:
        print(f"[document_indexer] Failed to index '{title}': {e}")
        import traceback
        traceback.print_exc()
        return None


def _index_sync(
    title: str,
    full_text: str,
    file_type: str,
    category: str
) -> Optional[int]:
    """Synchronous indexing work — runs in executor thread."""
    from backend.knowledge.extractors import ExtractedDocument
    from backend.knowledge.chunker import DocumentChunker
    from backend.knowledge.embedder import generate_chunk_embeddings
    from backend.knowledge.db_writer import index_document
    from backend.knowledge.file_scanner import FileInfo

    # Build pseudo file path (matches knowledge_server._handle_save pattern)
    safe_title = title.replace(' ', '_').replace('/', '_')
    file_path = f"/uploaded/{category}/{safe_title}{file_type}"

    file_info = FileInfo(
        file_path=file_path,
        file_name=f"{safe_title}{file_type}",
        file_type=file_type,
        file_size_bytes=len(full_text.encode('utf-8')),
        modified_time=datetime.now(),
        doc_category=category
    )

    extracted = ExtractedDocument(
        text=full_text,
        title=title,
        metadata={
            'file_type': 'uploaded',
            'source': 'chat_auto_index',
            'category': category
        },
        sections=[{'title': 'content', 'line_number': 1, 'type': 'file'}]
    )

    # Chunk
    chunker = DocumentChunker()
    chunks = chunker.chunk_document(extracted)
    if not chunks:
        print(f"[document_indexer] No chunks produced for '{title}'")
        return None

    print(f"[document_indexer] '{title}': {len(chunks)} chunks, generating embeddings...")

    # Embed (force CPU — GPU 0 VRAM is consumed by Ollama)
    embeddings = generate_chunk_embeddings(chunks, title, force_cpu=True)
    if not embeddings or len(embeddings) != len(chunks):
        print(f"[document_indexer] Embedding generation failed for '{title}'")
        return None

    # Save (UPSERT on file_path)
    doc_id = index_document(file_info, extracted, chunks, embeddings)

    if doc_id:
        print(f"[document_indexer] Saved '{title}' as doc {doc_id} ({len(chunks)} chunks)")
    else:
        print(f"[document_indexer] Database write failed for '{title}'")

    return doc_id
