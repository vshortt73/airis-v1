-- Knowledge Base MCP Tool Definitions
-- Inserts tool definitions into mcp_tools table for MCP server registration
-- Author: Claude Code
-- Date: 2026-01-06

-- ============================================
-- TOOL: document_search
-- Semantic search over indexed code and documentation
-- ============================================

INSERT INTO mcp_tools (tool_name, description, input_schema, icon, enabled, priority, custom_instructions)
VALUES (
    'document_search',
    'Search indexed code and documentation using semantic similarity. Use for finding information in the codebase or external docs. Searches across all indexed files (Python, JavaScript, Markdown, PDFs, etc.) and returns relevant chunks with context.',
    '{
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural language search query (e.g., \"how to add MCP tool\", \"PostgreSQL setup\", \"embeddings implementation\")"
            },
            "top_k": {
                "type": "integer",
                "description": "Number of results to return (default: 10, max: 50)",
                "default": 10,
                "minimum": 1,
                "maximum": 50
            },
            "filter_category": {
                "type": "string",
                "description": "Filter by document category (e.g., \"project_code\", \"external_docs\", \"reference\")"
            },
            "filter_file_type": {
                "type": "string",
                "description": "Filter by file extension (e.g., \".py\", \".md\", \".pdf\")"
            },
            "filter_path": {
                "type": "string",
                "description": "Filter by file path pattern (substring match, e.g., \"/iris-v3/app/\" or \"backend/\")"
            },
            "similarity_threshold": {
                "type": "number",
                "description": "Minimum similarity score 0-1 (default: 0.30). Higher = more strict matching",
                "default": 0.30,
                "minimum": 0.0,
                "maximum": 1.0
            }
        },
        "required": ["query"]
    }',
    '📚',
    true,
    10,
    'Use this tool to search the knowledge base. Handles knowledge server via MCP.'
) ON CONFLICT (tool_name) DO UPDATE SET
    description = EXCLUDED.description,
    input_schema = EXCLUDED.input_schema,
    icon = EXCLUDED.icon,
    enabled = EXCLUDED.enabled,
    priority = EXCLUDED.priority,
    custom_instructions = EXCLUDED.custom_instructions;

-- ============================================
-- TOOL: knowledge_stats
-- Get statistics about the knowledge base
-- ============================================

INSERT INTO mcp_tools (tool_name, description, input_schema, icon, enabled, priority, custom_instructions)
VALUES (
    'knowledge_stats',
    'Get statistics about the indexed knowledge base. Shows document counts, chunk counts, indexing status, coverage by file type and category. Use to check if knowledge base is up-to-date or to understand what content is indexed.',
    '{
        "type": "object",
        "properties": {},
        "required": []
    }',
    '📊',
    true,
    20,
    'Use this tool to get knowledge base statistics. Handles knowledge server via MCP.'
) ON CONFLICT (tool_name) DO UPDATE SET
    description = EXCLUDED.description,
    input_schema = EXCLUDED.input_schema,
    icon = EXCLUDED.icon,
    enabled = EXCLUDED.enabled,
    priority = EXCLUDED.priority,
    custom_instructions = EXCLUDED.custom_instructions;

-- ============================================
-- SUCCESS MESSAGE
-- ============================================

DO $$
BEGIN
    RAISE NOTICE '✓ Knowledge base tools registered successfully';
    RAISE NOTICE '  - document_search: Semantic search over indexed documents';
    RAISE NOTICE '  - knowledge_stats: Statistics about knowledge base';
    RAISE NOTICE '  - Server: knowledge';
    RAISE NOTICE '  - Both tools enabled and ready for use';
END $$;
