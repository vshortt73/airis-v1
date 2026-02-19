"""
Iris Knowledge Server - Unified MCP Server for Document Search
Provides semantic search and stats over indexed code and documentation
"""

import sys
import os
import json
from pathlib import Path
from typing import Optional, Dict

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from mcp_servers.base.base_server import IrisMCPServer
import psycopg2
from app import config
from core.embeddings import generate_embedding

server = IrisMCPServer(
    name="Iris Knowledge Server",
    description="Unified document search and knowledge base stats"
)


def get_db_connection():
    """Standard database connection"""
    password = os.environ.get('AIRIS_DB_PASSWORD') or getattr(config, 'DB_PASSWORD', None)
    conn_params = {
        'host': config.DB_HOST,
        'port': config.DB_PORT,
        'database': config.DB_NAME,
        'user': config.DB_USER
    }
    if password:
        conn_params['password'] = password
    return psycopg2.connect(**conn_params)


def calculate_tier(similarity: float, thresholds: Dict[int, float]) -> Optional[int]:
    """Calculate result tier based on similarity"""
    if similarity >= thresholds[1]:
        return 1
    elif similarity >= thresholds[2]:
        return 2
    elif similarity >= thresholds[3]:
        return 3
    elif similarity >= thresholds[4]:
        return 4
    return None


def _handle_search(
    query: str,
    top_k: int = 10,
    filter_file_type: str = None,
    filter_path: str = None,
    similarity_threshold: float = None
) -> dict:
    """Semantic search over indexed documents"""
    try:
        top_k = min(max(1, top_k), config.KNOWLEDGE_MAX_SEARCH_LIMIT)
        threshold = similarity_threshold or config.KNOWLEDGE_SIMILARITY_THRESHOLD

        print(f"[knowledge][search] Query: {query[:50]}...", file=sys.stderr)

        # Force CPU: this runs as an MCP subprocess where CUDA OOM recovery
        # writes binary to stdout, corrupting the JSON-RPC protocol
        query_embedding = generate_embedding(query, force_cpu=True)
        if not query_embedding:
            return {"success": False, "error": "Failed to generate query embedding"}

        conn = get_db_connection()
        cursor = conn.cursor()

        content_weight = config.KNOWLEDGE_FACET_WEIGHTS.get('content', 0.6)
        context_weight = config.KNOWLEDGE_FACET_WEIGHTS.get('context', 0.4)

        sql = """
            SELECT
                kc.chunk_id, kc.chunk_text, kc.section_title, kc.token_count,
                kc.line_start, kc.line_end, kc.chunk_type, kc.language,
                kd.file_path, kd.file_name, kd.file_type, kd.doc_category,
                (
                    %s * (1 - (kc.emb_content <=> %s::vector)) +
                    %s * (1 - (kc.emb_context <=> %s::vector))
                )::float AS similarity
            FROM knowledge_chunks kc
            JOIN knowledge_documents kd ON kc.doc_id = kd.doc_id
            WHERE kc.emb_content IS NOT NULL AND kc.emb_context IS NOT NULL
        """

        params = [content_weight, query_embedding, context_weight, query_embedding]

        if filter_file_type:
            sql += " AND kd.file_type = %s"
            params.append(filter_file_type)

        if filter_path:
            sql += " AND kd.file_path LIKE %s"
            params.append(f"%{filter_path}%")

        sql += " ORDER BY similarity DESC LIMIT %s"
        params.append(top_k * 2)

        cursor.execute(sql, params)
        candidates = cursor.fetchall()

        results = []
        tier_thresholds = config.KNOWLEDGE_TIER_THRESHOLDS

        for row in candidates:
            (chunk_id, chunk_text, section, tokens, line_start, line_end,
             chunk_type, language, file_path, file_name, file_type,
             category, similarity) = row

            tier = calculate_tier(similarity, tier_thresholds)
            if tier is None or similarity < threshold:
                continue

            results.append({
                "chunk_id": chunk_id,
                "chunk_text": chunk_text,
                "section_title": section,
                "file_path": file_path,
                "file_name": file_name,
                "file_type": file_type,
                "line_range": [line_start, line_end] if line_start else None,
                "token_count": tokens,
                "similarity": round(similarity, 3),
                "tier": tier
            })

        results = results[:top_k]

        if results:
            chunk_ids = [r["chunk_id"] for r in results]
            cursor.execute("""
                UPDATE knowledge_documents
                SET last_accessed = NOW(), access_count = access_count + 1
                WHERE doc_id IN (
                    SELECT DISTINCT doc_id FROM knowledge_chunks WHERE chunk_id = ANY(%s)
                )
            """, (chunk_ids,))
            conn.commit()

        cursor.close()
        conn.close()

        print(f"[knowledge][search] ✓ Found {len(results)} results", file=sys.stderr)

        return {
            "success": True,
            "query": query,
            "result_count": len(results),
            "results": results
        }

    except Exception as e:
        import traceback
        print(f"[knowledge][search] ✗ Error: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return {"success": False, "error": str(e)}


def _handle_stats() -> dict:
    """Get knowledge base statistics"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT COUNT(*), COALESCE(SUM(chunk_count), 0), COALESCE(SUM(total_tokens), 0)
            FROM knowledge_documents
        """)
        doc_count, total_chunks, total_tokens = cursor.fetchone()

        cursor.execute("""
            SELECT doc_category, COUNT(*) FROM knowledge_documents
            GROUP BY doc_category ORDER BY COUNT(*) DESC
        """)
        by_category = {row[0] or 'unknown': row[1] for row in cursor.fetchall()}

        cursor.execute("""
            SELECT file_type, COUNT(*) FROM knowledge_documents
            GROUP BY file_type ORDER BY COUNT(*) DESC
        """)
        by_file_type = {row[0]: row[1] for row in cursor.fetchall()}

        cursor.execute("""
            SELECT scan_started_at, scan_completed_at, scan_status,
                   docs_indexed, docs_failed, chunks_created, duration_seconds
            FROM knowledge_index_status ORDER BY scan_started_at DESC LIMIT 1
        """)
        last_run = cursor.fetchone()

        cursor.close()
        conn.close()

        print(f"[knowledge][stats] ✓ {doc_count} docs, {total_chunks} chunks", file=sys.stderr)

        return {
            "success": True,
            "total_documents": doc_count or 0,
            "total_chunks": total_chunks or 0,
            "total_tokens": total_tokens or 0,
            "by_category": by_category,
            "by_file_type": by_file_type,
            "last_index_run": {
                "status": last_run[2] if last_run else None,
                "docs_indexed": last_run[3] if last_run else None,
                "chunks_created": last_run[5] if last_run else None
            } if last_run else None
        }

    except Exception as e:
        print(f"[knowledge][stats] ✗ Error: {e}", file=sys.stderr)
        return {"success": False, "error": str(e)}


def _handle_save(
    title: str,
    content: str,
    category: str = "uploaded_documents",
    file_type: str = ".txt"
) -> dict:
    """
    Save a document to the knowledge base for future retrieval.

    This indexes the content by:
    1. Chunking the text into semantic segments
    2. Generating embeddings for each chunk
    3. Storing in the knowledge database

    Args:
        title: Document title
        content: Full document text
        category: Category for organizing (default: uploaded_documents)
        file_type: File type for display (default: .txt)

    Returns:
        Success status with chunk count
    """
    try:
        from backend.knowledge.extractors import ExtractedDocument
        from backend.knowledge.chunker import DocumentChunker
        from backend.knowledge.embedder import generate_chunk_embeddings
        from backend.knowledge.db_writer import index_document
        from backend.knowledge.file_scanner import FileInfo
        from datetime import datetime

        print(f"[knowledge][save] Saving document: {title} ({len(content):,} chars)", file=sys.stderr)

        # Create a pseudo file path for the document
        file_path = f"/uploaded/{category}/{title.replace(' ', '_')}{file_type}"

        # Create FileInfo for the "uploaded" document
        file_info = FileInfo(
            file_path=file_path,
            file_name=f"{title}{file_type}",
            file_type=file_type,
            file_size_bytes=len(content.encode('utf-8')),
            modified_time=datetime.now(),
            doc_category=category
        )

        # Create ExtractedDocument
        extracted = ExtractedDocument(
            text=content,
            title=title,
            metadata={
                'file_type': 'uploaded',
                'source': 'chat_upload',
                'category': category
            },
            sections=[{'title': 'content', 'line_number': 1, 'type': 'file'}]
        )

        # Chunk the document
        chunker = DocumentChunker()
        chunks = chunker.chunk_document(extracted)

        if not chunks:
            return {"success": False, "error": "Failed to chunk document (content may be too short)"}

        print(f"[knowledge][save] Created {len(chunks)} chunks", file=sys.stderr)

        # Generate embeddings for chunks
        embeddings = generate_chunk_embeddings(chunks, title)

        if not embeddings or len(embeddings) != len(chunks):
            return {"success": False, "error": "Failed to generate embeddings"}

        print(f"[knowledge][save] Generated {len(embeddings)} embeddings", file=sys.stderr)

        # Save to database
        doc_id = index_document(file_info, extracted, chunks, embeddings)

        if doc_id:
            print(f"[knowledge][save] ✓ Saved as document {doc_id} with {len(chunks)} chunks", file=sys.stderr)
            return {
                "success": True,
                "message": f"Document '{title}' saved to knowledge base",
                "document_id": doc_id,
                "chunks_created": len(chunks),
                "category": category
            }
        else:
            return {"success": False, "error": "Failed to save document to database"}

    except ImportError as e:
        print(f"[knowledge][save] ✗ Missing dependency: {e}", file=sys.stderr)
        return {"success": False, "error": f"Knowledge indexing not available: {e}"}
    except Exception as e:
        print(f"[knowledge][save] ✗ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


@server.register_tool
def knowledge(
    action: str,
    query: str = None,
    top_k: int = 10,
    filter_file_type: str = None,
    filter_path: str = None,
    title: str = None,
    content: str = None,
    category: str = "uploaded_documents"
) -> str:
    """
    Unified knowledge base tool.

    Actions:
        - "search": Semantic search over indexed documents
        - "stats": Get knowledge base statistics
        - "save": Save a document to the knowledge base for future retrieval

    Args:
        action: "search", "stats", or "save"
        query: Search query (required for search)
        top_k: Number of results (default: 10, for search)
        filter_file_type: Filter by file type e.g. ".py" (optional, for search)
        filter_path: Filter by path pattern (optional, for search)
        title: Document title (required for save)
        content: Document text content (required for save)
        category: Category for organizing saved docs (default: uploaded_documents)

    Returns:
        JSON with action-specific data

    Examples:
        knowledge(action="search", query="how to add MCP tool")
        knowledge(action="search", query="database connection", filter_file_type=".py")
        knowledge(action="stats")
        knowledge(action="save", title="Meeting Notes", content="Full document text here...")
    """
    action = action.lower().strip()
    print(f"[knowledge] Action: {action}", file=sys.stderr)

    if action == "search":
        if not query:
            return json.dumps({
                "success": False,
                "error": "query parameter required for search"
            })
        return json.dumps(_handle_search(query, top_k, filter_file_type, filter_path))

    elif action == "stats":
        return json.dumps(_handle_stats())

    elif action == "save":
        if not title or not content:
            return json.dumps({
                "success": False,
                "error": "title and content parameters required for save"
            })
        return json.dumps(_handle_save(title, content, category))

    else:
        return json.dumps({
            "success": False,
            "error": f"Unknown action: {action}",
            "valid_actions": ["search", "stats", "save"]
        })


@server.register_tool
def knowledge_save(
    title: str,
    content: str,
    category: str = "uploaded_documents",
) -> dict:
    """Save a document to the knowledge base for future retrieval."""
    return _handle_save(title=title, content=content, category=category)


if __name__ == "__main__":
    print("[knowledge_server] Starting Knowledge Server...", file=sys.stderr)
    print("Tools: knowledge(action, ...), knowledge_save(title, content, ...)", file=sys.stderr)
    server.run()
