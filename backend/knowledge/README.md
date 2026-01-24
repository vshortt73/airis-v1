# Knowledge Base / RAG System

**Semantic document search over code and documentation using vector embeddings**

## Overview

The Knowledge Base system enables Iris to search and retrieve information from indexed documents (code, markdown, PDFs) using semantic similarity search. This RAG (Retrieval Augmented Generation) system allows Iris to answer questions about the codebase, documentation, and external reference materials.

## Quick Start

### 1. Install Dependencies

```bash
pip install pypdf>=4.0.0
```

### 2. Run Initial Indexing

```bash
./scripts/index_knowledge.sh
```

This will:
- Scan configured directories (`KNOWLEDGE_SCAN_DIRECTORIES` in config.py)
- Extract text from files (Python, JavaScript, Markdown, PDFs, etc.)
- Chunk documents semantically with token limits
- Generate dual-facet embeddings (content + context)
- Store in PostgreSQL with HNSW vector indexes

**Initial run**: ~10-30 minutes for 1,000 files
**Incremental runs**: <1 minute (only changed files)

### 3. Use via Iris

Once indexed, Iris can search the knowledge base:

```
User: "Search for how to add a new MCP tool"
Iris: [uses document_search tool] → returns relevant code chunks
```

## Architecture

### Pipeline Overview

```
┌──────────────────────────────────────────────────────┐
│ 1. File Scanner                                      │
│    - Recursive directory traversal                   │
│    - Pattern matching (.py, .md, .pdf, etc.)        │
│    - Incremental detection (mtime + SHA256 hash)    │
└──────────────────────────────────────────────────────┘
                        ↓
┌──────────────────────────────────────────────────────┐
│ 2. Text Extractor                                    │
│    - Code: Preserve structure, extract docstrings    │
│    - Markdown: Parse headings, links, code blocks   │
│    - PDF: Page-by-page text extraction (pypdf)      │
└──────────────────────────────────────────────────────┘
                        ↓
┌──────────────────────────────────────────────────────┐
│ 3. Hybrid Semantic Chunker                          │
│    - Split by natural boundaries (headings,         │
│      functions, paragraphs)                          │
│    - Enforce max tokens (512, configurable)         │
│    - Add overlap (50 tokens) for continuity         │
└──────────────────────────────────────────────────────┘
                        ↓
┌──────────────────────────────────────────────────────┐
│ 4. Dual-Facet Embedder                              │
│    - Content embedding (60%): Raw chunk text        │
│    - Context embedding (40%): Doc title + section   │
│    - Model: all-mpnet-base-v2 (768 dimensions)     │
│    - Batch processing for efficiency                │
└──────────────────────────────────────────────────────┘
                        ↓
┌──────────────────────────────────────────────────────┐
│ 5. Database Writer                                   │
│    - Transactional UPSERT of documents              │
│    - Bulk insert of chunks with embeddings          │
│    - Update chunk link chain (prev/next)            │
│    - HNSW indexes for fast similarity search        │
└──────────────────────────────────────────────────────┘
```

### Database Schema

**knowledge_documents**
- File metadata (path, type, category, title, size, mtime, hash)
- Statistics (chunk_count, total_tokens)
- Usage tracking (access_count, last_accessed)

**knowledge_chunks**
- Chunk content and metadata (text, type, language, section)
- Token count and source location (line_start, line_end)
- **Dual embeddings**: emb_content, emb_context (vector(768))
- Link chain (prev_chunk_id, next_chunk_id)

**knowledge_index_status**
- Indexing run history and statistics
- Error tracking and performance metrics

### Search Strategy

**Multi-Facet Similarity** (like episodic memory):
```sql
similarity =
    0.6 * (1 - cosine_distance(emb_content, query_emb)) +
    0.4 * (1 - cosine_distance(emb_context, query_emb))
```

**Tiered Results**:
- Tier 1 (PRIMARY): 0.70+ similarity - Exact matches
- Tier 2 (SUPPORTING): 0.55+ similarity - Strong relevance
- Tier 3 (RELATED): 0.40+ similarity - Connected topics
- Tier 4 (PERIPHERAL): 0.30+ similarity - Weak connections

**HNSW Indexes**: Sub-second approximate nearest neighbor search even with 10,000+ documents

## Configuration

All settings in `/iris-v3/app/config.py`:

```python
# Directories to index
KNOWLEDGE_SCAN_DIRECTORIES = [
    "/iris-v3",                    # Project code
    "/home/captain/docs",          # External docs
]

# File patterns
KNOWLEDGE_FILE_PATTERNS = {
    "code": ["*.py", "*.js", "*.sql", ...],
    "docs": ["*.md", "*.txt", "*.rst"],
    "pdf": ["*.pdf"],
}

# Chunking
KNOWLEDGE_MAX_CHUNK_TOKENS = 512     # Max tokens per chunk
KNOWLEDGE_CHUNK_OVERLAP_TOKENS = 50  # Overlap for continuity
KNOWLEDGE_MIN_CHUNK_TOKENS = 50      # Filter tiny fragments

# Search
KNOWLEDGE_SIMILARITY_THRESHOLD = 0.30  # Minimum similarity
KNOWLEDGE_TIER_THRESHOLDS = {
    1: 0.70, 2: 0.55, 3: 0.40, 4: 0.30
}

# Incremental indexing
KNOWLEDGE_INCREMENTAL_INDEXING = True  # Only re-index changed files
KNOWLEDGE_HASH_CHECK = True            # SHA256 content verification
```

## MCP Tools

### document_search

Semantic search over indexed documents.

**Parameters**:
- `query` (required): Natural language search query
- `top_k` (optional, default 10): Number of results
- `filter_category` (optional): Filter by category (e.g., "project_code")
- `filter_file_type` (optional): Filter by extension (e.g., ".py")
- `filter_path` (optional): Filter by path pattern (e.g., "/iris-v3/app/")
- `similarity_threshold` (optional): Minimum similarity (default 0.30)

**Returns**:
```json
{
  "success": true,
  "query": "how to add MCP tool",
  "result_count": 5,
  "results": [
    {
      "chunk_id": 123,
      "chunk_text": "INSERT INTO mcp_tools (name, description...",
      "file_path": "/iris-v3/CLAUDE.md",
      "file_name": "CLAUDE.md",
      "section_title": "Adding New MCP Tools",
      "similarity": 0.856,
      "tier": 1,
      "line_range": [245, 267],
      "token_count": 142
    }
  ]
}
```

### knowledge_stats

Get statistics about the knowledge base.

**Returns**:
```json
{
  "success": true,
  "total_documents": 269,
  "total_chunks": 1543,
  "total_tokens": 156789,
  "by_category": {"project_code": 269},
  "by_file_type": {".py": 120, ".md": 45, ".sh": 18, ...},
  "last_index_run": {
    "started_at": "2026-01-06T03:00:00",
    "completed_at": "2026-01-06T03:12:34",
    "status": "completed",
    "docs_indexed": 15,
    "docs_failed": 0,
    "duration_seconds": 754
  }
}
```

## Module Reference

### file_scanner.py

**Functions**:
- `scan_directories()` - Recursive directory traversal with pattern matching
- `should_index_file()` - Incremental indexing logic (mtime + hash check)
- `calculate_file_hash()` - SHA256 hash for change detection

### extractors.py

**TextExtractor class**:
- `extract_code()` - Extract from Python, JavaScript, SQL, etc.
- `extract_markdown()` - Parse headings, links, code blocks
- `extract_pdf()` - Page-by-page text extraction using pypdf

### chunker.py

**DocumentChunker class**:
- `chunk_document()` - Main entry point for hybrid semantic chunking
- `_chunk_code()` - Code-specific chunking (functions, classes)
- `_chunk_markdown()` - Markdown-specific chunking (headings)
- `_chunk_text()` - Plain text chunking (paragraphs)
- `_split_large_text()` - Recursive splitting for oversized chunks

**Strategy**: Preserve natural boundaries (headings, functions) while enforcing token limits

### embedder.py

**Functions**:
- `generate_chunk_embeddings()` - Batch dual-facet embedding generation
- `generate_single_embedding()` - Single embedding for search queries

**Reuses**: Existing `core/embeddings.py` singleton (thread-safe all-mpnet-base-v2)

### db_writer.py

**Functions**:
- `index_document()` - Transactional UPSERT of document + chunks
- `create_index_status()` - Create indexing run record
- `update_index_status()` - Update run with completion stats

**Pattern**: Full transaction (BEGIN → UPSERT doc → DELETE old chunks → INSERT new chunks → UPDATE links → COMMIT)

### indexer.py

**Main orchestrator** called by cron script:

1. Scan directories → get file list
2. Filter for indexing (incremental check)
3. For each file: extract → chunk → embed → write
4. Track statistics in knowledge_index_status
5. Handle errors gracefully (log and continue)

**Usage**:
```bash
python backend/knowledge/indexer.py
```

## Cron Script

`/iris-v3/scripts/index_knowledge.sh`

**Features**:
- Pre-flight checks (lock file, DB password, paths)
- Comprehensive logging to `logs/knowledge_indexing/`
- Error handling and exit codes
- Cleanup of old logs (30-day retention)

**Manual run**:
```bash
./scripts/index_knowledge.sh
```

**Cron setup** (nightly at 3 AM):
```bash
crontab -e
# Add:
0 3 * * * /iris-v3/scripts/index_knowledge.sh
```

## Performance

### Indexing

- **Initial run** (1,000 files): 10-30 minutes
  - Bottleneck: Embedding generation (batch optimized)
  - ~100 files/minute average throughput

- **Incremental run** (daily): <1 minute
  - Only processes changed files (mtime + hash check)
  - Typical: 5-20 files changed per day

- **Storage**: ~162KB per document (metadata + content + embeddings)
  - 1,000 documents ≈ 162MB total

### Search

- **Latency**: <500ms per query (HNSW approximate nearest neighbor)
- **Scalability**: Tested up to 10,000 documents, 200,000 chunks
- **Index type**: HNSW (m=16, ef_construction=64)

## Troubleshooting

### Indexing Issues

**Problem**: Files not being indexed

**Check**:
```bash
# Verify configuration
grep KNOWLEDGE_SCAN_DIRECTORIES app/config.py

# Test file scanner
python -c "
from backend.knowledge.file_scanner import scan_directories
from app import config
files = scan_directories(
    config.KNOWLEDGE_SCAN_DIRECTORIES,
    config.KNOWLEDGE_FILE_PATTERNS,
    config.KNOWLEDGE_EXCLUDE_PATTERNS
)
print(f'Found {len(files)} files')
"
```

**Problem**: Extraction failures

**Check**:
```bash
# Test extractor on specific file
python -c "
from backend.knowledge.extractors import TextExtractor
ext = TextExtractor()
doc = ext.extract_text('/path/to/file.py', '.py')
print(f'Extracted: {len(doc.text) if doc else 0} chars')
"
```

**Problem**: Embedding generation fails

**Check**:
```bash
# Test embedding model
python -c "
from core.embeddings import generate_embedding
emb = generate_embedding('test')
print(f'Generated: {len(emb) if emb else 0} dimensions')
"
```

### Search Issues

**Problem**: No results found

**Solutions**:
1. Lower similarity threshold (try 0.20 instead of 0.30)
2. Check if documents are indexed: `SELECT COUNT(*) FROM knowledge_documents;`
3. Verify embeddings exist: `SELECT COUNT(*) FROM knowledge_chunks WHERE emb_content IS NOT NULL;`

**Problem**: Poor result quality

**Solutions**:
1. Increase `top_k` to see more candidates
2. Use filters (filter_file_type, filter_path) to narrow scope
3. Check tier distribution in results (should have mix of Tier 1-3)

### Database Issues

**Problem**: Vector similarity queries slow

**Check indexes**:
```sql
\d knowledge_chunks
-- Should see:
-- idx_chunk_emb_content (hnsw)
-- idx_chunk_emb_context (hnsw)

-- Rebuild if degraded:
REINDEX INDEX idx_chunk_emb_content;
REINDEX INDEX idx_chunk_emb_context;
```

## Testing

### Unit Tests

```bash
# Test individual modules
python backend/knowledge/file_scanner.py
python backend/knowledge/extractors.py
python backend/knowledge/chunker.py
python backend/knowledge/embedder.py
```

### Integration Test

```bash
# Create test documents
mkdir -p /tmp/test_knowledge
echo "# Test Document\nThis tests RAG." > /tmp/test_knowledge/test.md

# Update config temporarily
# Add /tmp/test_knowledge to KNOWLEDGE_SCAN_DIRECTORIES

# Run indexing
./scripts/index_knowledge.sh

# Verify
psql -U irisuser -d irisdb -c "
SELECT file_name, chunk_count
FROM knowledge_documents
WHERE file_path LIKE '%test_knowledge%';
"
```

### Search Test

Start Iris and test search:
```
User: "Search for test document"
→ Should return chunks from test.md with similarity scores
```

## Maintenance

### Weekly

- Review failed indexing logs: `tail logs/knowledge_indexing/index_*.log`
- Check disk space: `df -h` (ensure room for growth)
- Verify search performance: `\timing` in psql

### Monthly

- Rebuild HNSW indexes (if query latency increases):
  ```sql
  REINDEX INDEX idx_chunk_emb_content;
  REINDEX INDEX idx_chunk_emb_context;
  ```

- Archive old logs: `find logs/knowledge_indexing -name '*.log' -mtime +30 -delete`

### Quarterly

- Full re-index to catch any drift:
  ```bash
  # Temporarily disable incremental in config.py:
  # KNOWLEDGE_INCREMENTAL_INDEXING = False
  ./scripts/index_knowledge.sh
  # Re-enable incremental after
  ```

- Review and update file patterns/exclusions in config.py
- Evaluate search quality (precision/recall)

## Future Enhancements

### Planned

1. **Code-aware chunking**: Use AST parsing for better function/class boundaries
2. **Hybrid search**: Combine vector similarity + BM25 keyword search
3. **Query expansion**: LLM-based query refinement for better retrieval
4. **Real-time indexing**: File system watcher for instant updates
5. **Knowledge graph**: Extract and index code imports, citations, links

### Under Consideration

- Multi-modal embeddings (code + docstrings separately)
- Recursive retrieval (follow links/imports)
- Smart re-ranking based on access patterns
- Conversational context awareness (remember previous searches)

## References

- Implementation plan: `/home/captain/.claude/plans/virtual-orbiting-fountain.md`
- MCP server code: `/iris-v3/mcp_servers/knowledge/knowledge_server.py`
- Database schema: `/iris-v3/database/sql/create_knowledge_tables.sql`
- Main documentation: `/iris-v3/CLAUDE.md` (Knowledge Base section)
