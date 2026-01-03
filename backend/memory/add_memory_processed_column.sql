-- ============================================================================
-- ADD MEMORY PROCESSING TRACKING TO CHAT_HISTORY
-- ============================================================================
-- Marks chat_history entries that have been evaluated for memory creation
-- Prevents re-processing of topics deemed not worthy
-- ============================================================================

-- Add column to track when a topic was processed for memory creation
-- NULL = not yet processed
-- timestamp = processed at this time (whether worthy or not)
ALTER TABLE chat_history
ADD COLUMN IF NOT EXISTS memory_processed_at TIMESTAMPTZ DEFAULT NULL;

-- Create index for efficient queries
CREATE INDEX IF NOT EXISTS idx_chat_history_memory_processed
    ON chat_history(memory_processed_at) WHERE memory_processed_at IS NULL;

-- Create index on topic_id for queries
CREATE INDEX IF NOT EXISTS idx_chat_history_topic_id
    ON chat_history(topic_id) WHERE topic_id IS NOT NULL AND topic_id != 0;

-- ============================================================================
-- COMMENTS
-- ============================================================================

COMMENT ON COLUMN chat_history.memory_processed_at IS
'Timestamp when this topic was evaluated for episodic memory creation.
NULL = not yet processed
Non-NULL = processed at this time (may or may not have created a memory)
This prevents re-processing topics that were deemed not worthy.';

-- ============================================================================
-- SAMPLE QUERIES
-- ============================================================================

-- Find all unprocessed topics
-- SELECT DISTINCT session_id, topic_id
-- FROM chat_history
-- WHERE topic_id IS NOT NULL
--   AND topic_id != 0
--   AND memory_processed_at IS NULL;

-- Find topics processed in last 24 hours
-- SELECT DISTINCT session_id, topic_id, memory_processed_at
-- FROM chat_history
-- WHERE memory_processed_at >= NOW() - INTERVAL '24 hours';

-- Mark a topic as processed
-- UPDATE chat_history
-- SET memory_processed_at = NOW()
-- WHERE session_id = 'abc-123' AND topic_id = 5;
