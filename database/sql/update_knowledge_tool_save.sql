-- ============================================================================
-- UPDATE KNOWLEDGE TOOL WITH SAVE ACTION
-- ============================================================================
-- Adds save action parameters to the knowledge tool for document ingestion.
--
-- Run with: psql -h localhost -U irisuser -d irisdb -f database/sql/update_knowledge_tool_save.sql
-- ============================================================================

UPDATE mcp_tools
SET input_schema = '{
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["search", "stats", "save"],
            "description": "Action to perform: search (semantic search), stats (knowledge base statistics), or save (save document for future retrieval)"
        },
        "query": {
            "type": "string",
            "description": "Search query (required for search action)"
        },
        "top_k": {
            "type": "integer",
            "default": 10,
            "description": "Number of results to return (for search)"
        },
        "filter_file_type": {
            "type": "string",
            "description": "Filter by file type e.g. .py, .md (for search)"
        },
        "filter_path": {
            "type": "string",
            "description": "Filter by path pattern (for search)"
        },
        "title": {
            "type": "string",
            "description": "Document title (required for save action)"
        },
        "content": {
            "type": "string",
            "description": "Full document text to save (required for save action)"
        },
        "category": {
            "type": "string",
            "default": "uploaded_documents",
            "description": "Category for organizing saved documents (for save)"
        }
    },
    "required": ["action"]
}'::jsonb,
    description = 'Search the knowledge base for code and documentation, view stats, or save documents for future retrieval. Use save action to permanently remember important documents.'
WHERE tool_name = 'knowledge';

-- Verification
SELECT tool_name, description, input_schema
FROM mcp_tools
WHERE tool_name = 'knowledge';
