-- ============================================================================
-- ADD DOCUMENT EXTRACTION CONFIG
-- ============================================================================
-- Adds configuration for Word (.docx) and ODT document extraction
-- for the knowledge/RAG system.
--
-- Run with: psql -h localhost -U irisuser -d irisdb -f database/sql/add_document_extraction_config.sql
-- ============================================================================

-- Add enable flags for new document types
INSERT INTO system_config (category, key, value, value_type, default_value, description, requires_restart) VALUES
('knowledge', 'KNOWLEDGE_DOCX_ENABLED', 'true', 'bool', 'true', 'Enable Word (.docx) document extraction', false),
('knowledge', 'KNOWLEDGE_ODT_ENABLED', 'true', 'bool', 'true', 'Enable LibreOffice (.odt) document extraction', false)
ON CONFLICT (key) DO UPDATE SET
    value = EXCLUDED.value,
    description = EXCLUDED.description,
    last_modified = NOW();

-- Update file patterns to include new document types
UPDATE system_config
SET value = '{"code": ["*.py", "*.js", "*.ts", "*.jsx", "*.sh", "*.yaml", "*.yml"], "docs": ["*.md", "*.rst", "*.org"], "pdf": ["*.pdf"], "office": ["*.docx", "*.odt"]}',
    last_modified = NOW()
WHERE key = 'KNOWLEDGE_FILE_PATTERNS';

-- Verification
SELECT key, value, description
FROM system_config
WHERE key IN ('KNOWLEDGE_DOCX_ENABLED', 'KNOWLEDGE_ODT_ENABLED', 'KNOWLEDGE_PDF_ENABLED', 'KNOWLEDGE_FILE_PATTERNS');
