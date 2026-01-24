-- ============================================================================
-- ADD DOCUMENT CONTEXT BUDGET CONFIG
-- ============================================================================
-- Adds configurable token budget for uploaded documents in chat context.
--
-- Run with: psql -h localhost -U irisuser -d irisdb -f database/sql/add_document_context_budget.sql
-- ============================================================================

INSERT INTO system_config (category, key, value, value_type, description)
VALUES (
    'tokens',
    'DOCUMENT_CONTEXT_BUDGET',
    '8000',
    'int',
    'Maximum tokens allocated for uploaded documents in conversation context. Large documents are smartly truncated with relevant sections preserved.'
)
ON CONFLICT (category, key) DO UPDATE SET
    value = EXCLUDED.value,
    description = EXCLUDED.description;

-- Verification
SELECT category, key, value, description
FROM system_config
WHERE key = 'DOCUMENT_CONTEXT_BUDGET';
