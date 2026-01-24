-- Knowledge Base / RAG System Database Schema
-- Creates tables for document indexing and semantic search
-- Author: Claude Code
-- Date: 2026-01-06

-- ============================================
-- TABLE: knowledge_documents
-- Stores document metadata for indexed files
-- ============================================
CREATE TABLE IF NOT EXISTS knowledge_documents (
    doc_id BIGSERIAL PRIMARY KEY,

    -- File identification
    file_path TEXT NOT NULL UNIQUE,              -- Absolute path to file
    file_name TEXT NOT NULL,                     -- Filename only (for display)
    file_type TEXT NOT NULL,                     -- Extension: .py, .md, .pdf, etc.
    doc_category TEXT,                           -- Category: project_code, external_docs, reference, etc.

    -- Document metadata
    title TEXT,                                  -- Extracted title (from first heading or filename)
    file_size_bytes BIGINT,                      -- File size for monitoring
    modified_time TIMESTAMP WITH TIME ZONE,      -- File mtime for incremental indexing
    indexed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Usage tracking
    last_accessed TIMESTAMP WITH TIME ZONE,      -- Track usage for optimization
    access_count INTEGER DEFAULT 0,              -- Popularity metric

    -- Indexing statistics
    chunk_count INTEGER DEFAULT 0,               -- Number of chunks for this document
    total_tokens INTEGER DEFAULT 0,              -- Total tokens across all chunks

    -- Change detection
    doc_hash TEXT,                               -- SHA256 of content for change detection

    -- Flexible metadata storage
    metadata JSONB,                              -- author, tags, links, etc.

    -- Full-text search support (PostgreSQL native)
    search_vector tsvector,

    CONSTRAINT valid_file_type CHECK (file_type ~ '^\.[a-z0-9]+$')
);

-- Indexes for knowledge_documents
CREATE INDEX IF NOT EXISTS idx_doc_file_path ON knowledge_documents(file_path);
CREATE INDEX IF NOT EXISTS idx_doc_category ON knowledge_documents(doc_category);
CREATE INDEX IF NOT EXISTS idx_doc_file_type ON knowledge_documents(file_type);
CREATE INDEX IF NOT EXISTS idx_doc_modified ON knowledge_documents(modified_time DESC);
CREATE INDEX IF NOT EXISTS idx_doc_accessed ON knowledge_documents(last_accessed DESC);
CREATE INDEX IF NOT EXISTS idx_doc_hash ON knowledge_documents(doc_hash);
CREATE INDEX IF NOT EXISTS idx_doc_search ON knowledge_documents USING gin(search_vector);

-- ============================================
-- TABLE: knowledge_chunks
-- Stores document chunks with vector embeddings
-- ============================================
CREATE TABLE IF NOT EXISTS knowledge_chunks (
    chunk_id BIGSERIAL PRIMARY KEY,
    doc_id BIGINT NOT NULL REFERENCES knowledge_documents(doc_id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,                -- Sequence within document (0-based)

    -- Content
    chunk_text TEXT NOT NULL,                    -- Actual chunk content
    chunk_type TEXT DEFAULT 'text',              -- text, code, table, heading, etc.
    language TEXT,                               -- For code: python, javascript, etc.

    -- Token management
    token_count INTEGER NOT NULL,                -- Exact tiktoken count

    -- Context preservation
    section_title TEXT,                          -- Nearest heading/section
    prev_chunk_id BIGINT REFERENCES knowledge_chunks(chunk_id) ON DELETE SET NULL,
    next_chunk_id BIGINT REFERENCES knowledge_chunks(chunk_id) ON DELETE SET NULL,

    -- Multi-facet embeddings (like episodic memory)
    emb_content vector(768),                     -- Main content embedding (60% weight)
    emb_context vector(768),                     -- Section/document context (40% weight)

    -- Source location metadata
    line_start INTEGER,                          -- Source line numbers (for code)
    line_end INTEGER,
    char_start INTEGER,                          -- Character offsets
    char_end INTEGER,

    -- Flexible metadata
    metadata JSONB,                              -- code symbols, links, etc.

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    CONSTRAINT unique_doc_chunk UNIQUE (doc_id, chunk_index),
    CONSTRAINT positive_token_count CHECK (token_count > 0),
    CONSTRAINT valid_chunk_index CHECK (chunk_index >= 0)
);

-- Indexes for knowledge_chunks
CREATE INDEX IF NOT EXISTS idx_chunk_doc ON knowledge_chunks(doc_id);
CREATE INDEX IF NOT EXISTS idx_chunk_type ON knowledge_chunks(chunk_type);
CREATE INDEX IF NOT EXISTS idx_chunk_language ON knowledge_chunks(language);
CREATE INDEX IF NOT EXISTS idx_chunk_tokens ON knowledge_chunks(token_count);
CREATE INDEX IF NOT EXISTS idx_chunk_section ON knowledge_chunks(section_title);

-- Vector similarity indexes (HNSW for fast ANN search)
-- m=16: number of connections per layer (balance between speed and recall)
-- ef_construction=64: quality of index construction (higher = better but slower build)
CREATE INDEX IF NOT EXISTS idx_chunk_emb_content ON knowledge_chunks
    USING hnsw (emb_content vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS idx_chunk_emb_context ON knowledge_chunks
    USING hnsw (emb_context vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- ============================================
-- TABLE: knowledge_index_status
-- Tracks indexing run history and statistics
-- ============================================
CREATE TABLE IF NOT EXISTS knowledge_index_status (
    status_id SERIAL PRIMARY KEY,
    scan_started_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    scan_completed_at TIMESTAMP WITH TIME ZONE,
    scan_status TEXT DEFAULT 'running',          -- running, completed, failed, partial

    -- Statistics
    docs_scanned INTEGER DEFAULT 0,              -- Files discovered
    docs_indexed INTEGER DEFAULT 0,              -- Files successfully indexed
    docs_updated INTEGER DEFAULT 0,              -- Files re-indexed (modified)
    docs_failed INTEGER DEFAULT 0,               -- Files that failed indexing
    chunks_created INTEGER DEFAULT 0,            -- Total chunks created this run

    -- Directory scan info
    directories_scanned TEXT[],                  -- List of directories processed

    -- Error tracking
    error_log JSONB,                             -- Array of error details

    -- Performance metrics
    duration_seconds INTEGER,                    -- Total run time

    CONSTRAINT valid_status CHECK (scan_status IN ('running', 'completed', 'failed', 'partial'))
);

CREATE INDEX IF NOT EXISTS idx_index_status_time ON knowledge_index_status(scan_started_at DESC);
CREATE INDEX IF NOT EXISTS idx_index_status_status ON knowledge_index_status(scan_status);

-- ============================================
-- VIEWS: Readable versions without embeddings
-- Similar to episodic_memories_readable pattern
-- ============================================

-- View: knowledge_documents_readable (excludes search_vector for token efficiency)
CREATE OR REPLACE VIEW knowledge_documents_readable AS
SELECT
    doc_id,
    file_path,
    file_name,
    file_type,
    doc_category,
    title,
    file_size_bytes,
    modified_time,
    indexed_at,
    last_accessed,
    access_count,
    chunk_count,
    total_tokens,
    doc_hash,
    metadata
FROM knowledge_documents;

-- View: knowledge_chunks_readable (excludes embeddings for token efficiency)
CREATE OR REPLACE VIEW knowledge_chunks_readable AS
SELECT
    chunk_id,
    doc_id,
    chunk_index,
    chunk_text,
    chunk_type,
    language,
    token_count,
    section_title,
    prev_chunk_id,
    next_chunk_id,
    line_start,
    line_end,
    char_start,
    char_end,
    metadata,
    created_at
FROM knowledge_chunks;

-- ============================================
-- COMMENTS (PostgreSQL documentation)
-- ============================================

COMMENT ON TABLE knowledge_documents IS 'Document metadata for indexed files in knowledge base';
COMMENT ON TABLE knowledge_chunks IS 'Document chunks with vector embeddings for semantic search';
COMMENT ON TABLE knowledge_index_status IS 'Indexing run history and statistics';

COMMENT ON COLUMN knowledge_documents.doc_hash IS 'SHA256 hash for detecting content changes (incremental indexing)';
COMMENT ON COLUMN knowledge_chunks.emb_content IS '768-dim embedding of chunk content (all-mpnet-base-v2)';
COMMENT ON COLUMN knowledge_chunks.emb_context IS '768-dim embedding of document/section context (all-mpnet-base-v2)';

-- ============================================
-- GRANT PERMISSIONS
-- ============================================

-- Grant permissions to irisuser (assuming standard Iris setup)
GRANT ALL PRIVILEGES ON TABLE knowledge_documents TO irisuser;
GRANT ALL PRIVILEGES ON TABLE knowledge_chunks TO irisuser;
GRANT ALL PRIVILEGES ON TABLE knowledge_index_status TO irisuser;
GRANT ALL PRIVILEGES ON SEQUENCE knowledge_documents_doc_id_seq TO irisuser;
GRANT ALL PRIVILEGES ON SEQUENCE knowledge_chunks_chunk_id_seq TO irisuser;
GRANT ALL PRIVILEGES ON SEQUENCE knowledge_index_status_status_id_seq TO irisuser;

-- ============================================
-- SUCCESS MESSAGE
-- ============================================

DO $$
BEGIN
    RAISE NOTICE '✓ Knowledge base tables created successfully';
    RAISE NOTICE '  - knowledge_documents (file metadata)';
    RAISE NOTICE '  - knowledge_chunks (chunks with embeddings)';
    RAISE NOTICE '  - knowledge_index_status (indexing history)';
    RAISE NOTICE '  - Views: knowledge_documents_readable, knowledge_chunks_readable';
    RAISE NOTICE '  - HNSW indexes created for fast similarity search';
END $$;
