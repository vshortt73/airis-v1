"""
Database Writer - Store documents and chunks in PostgreSQL
Handles transactional insert/update operations with embeddings
"""

import os
import sys
from typing import List, Tuple, Optional, Dict
import json

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, PROJECT_ROOT)

from app import config
import psycopg2
from psycopg2.extras import execute_values
from backend.knowledge.file_scanner import FileInfo, calculate_file_hash
from backend.knowledge.extractors import ExtractedDocument
from backend.knowledge.chunker import Chunk


def get_db_connection():
    """Get database connection (standard Iris pattern)"""
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


def index_document(
    file_info: FileInfo,
    extracted: ExtractedDocument,
    chunks: List[Chunk],
    embeddings: List[Tuple[List[float], List[float]]]
) -> Optional[int]:
    """
    Insert or update document and chunks in database

    Transaction steps:
    1. BEGIN
    2. UPSERT knowledge_documents (INSERT ... ON CONFLICT DO UPDATE)
    3. DELETE old chunks for this doc_id
    4. INSERT new chunks with embeddings
    5. UPDATE chunk link chain (prev_chunk_id, next_chunk_id)
    6. UPDATE document statistics (chunk_count, total_tokens)
    7. COMMIT

    Args:
        file_info: File metadata from scanner
        extracted: Extracted document with text and metadata
        chunks: List of chunks
        embeddings: List of (content_emb, context_emb) tuples

    Returns:
        doc_id on success, None on error
    """
    if len(chunks) != len(embeddings):
        print(f"[db_writer][index_document] ✗ Chunk/embedding count mismatch: {len(chunks)} vs {len(embeddings)}")
        return None

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Calculate file hash for change detection
        doc_hash = calculate_file_hash(file_info.file_path)

        # Step 1: UPSERT document
        cursor.execute("""
            INSERT INTO knowledge_documents (
                file_path, file_name, file_type, doc_category, title,
                file_size_bytes, modified_time, doc_hash, metadata,
                indexed_at, chunk_count, total_tokens
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                NOW(), 0, 0
            )
            ON CONFLICT (file_path) DO UPDATE SET
                file_name = EXCLUDED.file_name,
                file_type = EXCLUDED.file_type,
                doc_category = EXCLUDED.doc_category,
                title = EXCLUDED.title,
                file_size_bytes = EXCLUDED.file_size_bytes,
                modified_time = EXCLUDED.modified_time,
                doc_hash = EXCLUDED.doc_hash,
                metadata = EXCLUDED.metadata,
                indexed_at = NOW()
            RETURNING doc_id
        """, (
            file_info.file_path,
            file_info.file_name,
            file_info.file_type,
            file_info.doc_category,
            extracted.title,
            file_info.file_size_bytes,
            file_info.modified_time,
            doc_hash,
            json.dumps(extracted.metadata)
        ))

        doc_id = cursor.fetchone()[0]

        # Step 2: Delete old chunks
        cursor.execute("DELETE FROM knowledge_chunks WHERE doc_id = %s", (doc_id,))

        # Step 3: Prepare chunk data for bulk insert
        chunk_data = []
        for i, (chunk, (content_emb, context_emb)) in enumerate(zip(chunks, embeddings)):
            chunk_data.append((
                doc_id,
                i,  # chunk_index
                chunk.text,
                chunk.chunk_type,
                chunk.language,
                chunk.token_count,
                chunk.section_title,
                None,  # prev_chunk_id (will update later)
                None,  # next_chunk_id (will update later)
                content_emb,  # emb_content
                context_emb,  # emb_context
                chunk.line_start,
                chunk.line_end,
                chunk.char_start,
                chunk.char_end,
                json.dumps({})  # metadata (placeholder)
            ))

        # Step 4: Bulk insert chunks
        execute_values(
            cursor,
            """
            INSERT INTO knowledge_chunks (
                doc_id, chunk_index, chunk_text, chunk_type, language,
                token_count, section_title, prev_chunk_id, next_chunk_id,
                emb_content, emb_context,
                line_start, line_end, char_start, char_end, metadata
            ) VALUES %s
            RETURNING chunk_id
            """,
            chunk_data,
            template="""(
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s,
                %s, %s, %s, %s, %s
            )"""
        )

        # Get inserted chunk IDs
        chunk_ids = [row[0] for row in cursor.fetchall()]

        # Step 5: Update chunk link chain (prev/next)
        for i, chunk_id in enumerate(chunk_ids):
            prev_id = chunk_ids[i - 1] if i > 0 else None
            next_id = chunk_ids[i + 1] if i < len(chunk_ids) - 1 else None

            cursor.execute("""
                UPDATE knowledge_chunks
                SET prev_chunk_id = %s, next_chunk_id = %s
                WHERE chunk_id = %s
            """, (prev_id, next_id, chunk_id))

        # Step 6: Update document statistics
        total_tokens = sum(chunk.token_count for chunk in chunks)

        cursor.execute("""
            UPDATE knowledge_documents
            SET chunk_count = %s, total_tokens = %s
            WHERE doc_id = %s
        """, (len(chunks), total_tokens, doc_id))

        # Commit transaction
        conn.commit()
        cursor.close()
        conn.close()

        print(f"[db_writer][index_document] ✓ Indexed doc_id={doc_id}: {file_info.file_name} ({len(chunks)} chunks, {total_tokens} tokens)")

        return doc_id

    except Exception as e:
        print(f"[db_writer][index_document] ✗ Error indexing {file_info.file_name}: {e}")
        if conn:
            conn.rollback()
            conn.close()
        return None


def create_index_status(directories: List[str]) -> int:
    """
    Create index status record for tracking indexing run

    Args:
        directories: List of directories being scanned

    Returns:
        status_id
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO knowledge_index_status (
                scan_started_at, scan_status, directories_scanned
            ) VALUES (
                NOW(), 'running', %s
            )
            RETURNING status_id
        """, (directories,))

        status_id = cursor.fetchone()[0]
        conn.commit()
        cursor.close()
        conn.close()

        return status_id

    except Exception as e:
        print(f"[db_writer][create_index_status] ✗ Error creating status: {e}")
        return -1


def update_index_status(
    status_id: int,
    status: str,
    stats: Dict[str, int],
    duration_seconds: int,
    errors: List[Dict] = None
) -> bool:
    """
    Update index status record with completion info

    Args:
        status_id: Status record ID
        status: 'completed', 'failed', or 'partial'
        stats: Dict with docs_scanned, docs_indexed, docs_failed, chunks_created
        duration_seconds: Total run time
        errors: Optional list of error dicts

    Returns:
        True on success
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE knowledge_index_status
            SET
                scan_completed_at = NOW(),
                scan_status = %s,
                docs_scanned = %s,
                docs_indexed = %s,
                docs_updated = %s,
                docs_failed = %s,
                chunks_created = %s,
                duration_seconds = %s,
                error_log = %s
            WHERE status_id = %s
        """, (
            status,
            stats.get('scanned', 0),
            stats.get('indexed', 0),
            stats.get('updated', 0),
            stats.get('failed', 0),
            stats.get('chunks_created', 0),
            duration_seconds,
            json.dumps(errors) if errors else None,
            status_id
        ))

        conn.commit()
        cursor.close()
        conn.close()

        return True

    except Exception as e:
        print(f"[db_writer][update_index_status] ✗ Error updating status: {e}")
        return False


if __name__ == "__main__":
    # Test database writer
    print("Testing database writer...")

    from backend.knowledge.file_scanner import FileInfo
    from backend.knowledge.extractors import ExtractedDocument
    from backend.knowledge.chunker import Chunk
    from datetime import datetime

    # Create test data
    test_file = FileInfo(
        file_path="/tmp/test_doc.txt",
        file_name="test_doc.txt",
        file_type=".txt",
        file_size_bytes=100,
        modified_time=datetime.now(),
        doc_category="test"
    )

    test_doc = ExtractedDocument(
        text="This is a test document for indexing.",
        title="Test Document",
        metadata={'file_type': 'text'},
        sections=[{'title': 'main', 'line_number': 1}]
    )

    test_chunks = [
        Chunk(
            text="This is a test chunk.",
            chunk_index=0,
            token_count=5,
            chunk_type='text',
            section_title="main",
            language=None,
            line_start=1,
            line_end=1,
            char_start=0,
            char_end=21
        )
    ]

    # Generate dummy embeddings (768 dimensions of zeros)
    test_embeddings = [([0.0] * 768, [0.0] * 768)]

    # Try to index (will fail if test file doesn't exist, but tests the SQL)
    print("\nAttempting test index (may fail if file doesn't exist)...")
    doc_id = index_document(test_file, test_doc, test_chunks, test_embeddings)

    if doc_id:
        print(f"✓ Successfully indexed test document: doc_id={doc_id}")
    else:
        print("✗ Failed to index (expected if test file doesn't exist)")
