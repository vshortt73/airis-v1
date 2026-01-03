-- ============================================================================
-- Create Readable Views (No Embeddings)
--
-- Purpose: Provide clean views of tables that exclude embedding vectors
-- This allows SELECT * queries without overwhelming results with 768-dim vectors
-- ============================================================================

-- Drop existing views if they exist
DROP VIEW IF EXISTS episodic_memories_readable CASCADE;
DROP VIEW IF EXISTS chat_history_readable CASCADE;

-- ============================================================================
-- EPISODIC_MEMORIES_READABLE
-- Excludes 7 embedding columns: emb_minilm, emb_summary_context,
-- emb_summary_event, emb_summary_significance, emb_takeaway,
-- emb_key_details, emb_topic
-- ============================================================================

CREATE VIEW episodic_memories_readable AS
SELECT
    id,
    session_id,
    segment_id,
    topic_id,
    created_at,
    updated_at,
    event_time,
    transcript,
    summary_context,
    summary_event,
    summary_significance,
    summary_tone,
    immutable,
    emotion_label,
    valence,
    arousal,
    recurrence,
    novelty,
    cohesion,
    recommendation,
    takeaway,
    emotion_top3,
    voice,
    category,
    key_details,
    memory_version,
    topic_label
FROM episodic_memories;

COMMENT ON VIEW episodic_memories_readable IS
'Clean view of episodic_memories without embedding vectors. Use this for queries to avoid overwhelming results with 768-dimensional vectors.';

-- ============================================================================
-- CHAT_HISTORY_READABLE
-- Excludes 1 embedding column: emb_message
-- ============================================================================

CREATE VIEW chat_history_readable AS
SELECT
    id,
    role,
    message,
    c_timestamp,
    node_id,
    conv_title,
    attachments,
    session_id,
    subject_id,
    clustered,
    sessioned,
    segmented_at,
    meaningfulness,
    system_version,
    tool_calls,
    tool_call_id,
    tool_name,
    topic_id,
    memory_processed_at,
    sender
FROM chat_history;

COMMENT ON VIEW chat_history_readable IS
'Clean view of chat_history without embedding vector. Use this for queries to avoid overwhelming results with 768-dimensional vectors.';

-- ============================================================================
-- Grant permissions (adjust user as needed)
-- ============================================================================

GRANT SELECT ON episodic_memories_readable TO irisuser;
GRANT SELECT ON chat_history_readable TO irisuser;

-- ============================================================================
-- Verification queries
-- ============================================================================

-- Test that views work
SELECT 'episodic_memories_readable' as view_name, COUNT(*) as row_count FROM episodic_memories_readable
UNION ALL
SELECT 'chat_history_readable', COUNT(*) FROM chat_history_readable;

-- Show column counts (should be less than base tables)
SELECT
    'episodic_memories' as table_name,
    COUNT(*) as column_count
FROM information_schema.columns
WHERE table_name = 'episodic_memories' AND table_schema = 'public'
UNION ALL
SELECT
    'episodic_memories_readable',
    COUNT(*)
FROM information_schema.columns
WHERE table_name = 'episodic_memories_readable' AND table_schema = 'public'
UNION ALL
SELECT
    'chat_history',
    COUNT(*)
FROM information_schema.columns
WHERE table_name = 'chat_history' AND table_schema = 'public'
UNION ALL
SELECT
    'chat_history_readable',
    COUNT(*)
FROM information_schema.columns
WHERE table_name = 'chat_history_readable' AND table_schema = 'public';
