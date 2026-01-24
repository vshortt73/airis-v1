-- ============================================================================
-- ADD SUMMARY COLUMN TO CHAT_HISTORY
-- ============================================================================
-- Stores AI-generated summaries of each message for tiered context loading.
-- Recent messages use full content, older messages use summaries to fit
-- more conversation history into the context window.
--
-- Run with: psql -h localhost -U irisuser -d irisdb -f database/sql/add_summary_column.sql
-- ============================================================================

-- Add summary column if it doesn't exist
ALTER TABLE chat_history
ADD COLUMN IF NOT EXISTS summary TEXT DEFAULT NULL;

-- Add summary_generated_at timestamp to track when summary was created
ALTER TABLE chat_history
ADD COLUMN IF NOT EXISTS summary_generated_at TIMESTAMP DEFAULT NULL;

-- Add index for efficient queries on messages needing summaries
CREATE INDEX IF NOT EXISTS idx_chat_history_needs_summary
ON chat_history (role, summary)
WHERE summary IS NULL AND role IN ('user', 'assistant');

-- Comment on columns
COMMENT ON COLUMN chat_history.summary IS 'AI-generated 50-token summary of message content for tiered context loading';
COMMENT ON COLUMN chat_history.summary_generated_at IS 'Timestamp when summary was generated';

-- ============================================================================
-- ADD TOKEN BUDGET CONFIG FOR TIERED CONTEXT
-- ============================================================================

INSERT INTO system_config (category, key, value, value_type, default_value, description, requires_restart) VALUES
('tokens', 'VERBOSE_TOKEN_BUDGET', '3000', 'int', '3000', 'Token budget for recent full messages (verbose)', false),
('tokens', 'SUMMARY_TOKEN_BUDGET', '17000', 'int', '17000', 'Token budget for older summarized messages', false),
('tokens', 'SUMMARY_MIN_LENGTH', '50', 'int', '50', 'Minimum message length (chars) to generate summary', false)
ON CONFLICT (key) DO UPDATE SET
    value = EXCLUDED.value,
    description = EXCLUDED.description,
    last_modified = NOW();

-- ============================================================================
-- VERIFICATION
-- ============================================================================

-- Check column was added
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'chat_history'
AND column_name IN ('summary', 'summary_generated_at');

-- Check config was added
SELECT key, value, description
FROM system_config
WHERE key IN ('VERBOSE_TOKEN_BUDGET', 'SUMMARY_TOKEN_BUDGET', 'SUMMARY_MIN_LENGTH');

-- Count messages that need summaries (for backfill planning)
SELECT
    role,
    COUNT(*) as total,
    COUNT(*) FILTER (WHERE summary IS NULL AND LENGTH(message) >= 50) as needs_summary
FROM chat_history
WHERE role IN ('user', 'assistant')
GROUP BY role;
