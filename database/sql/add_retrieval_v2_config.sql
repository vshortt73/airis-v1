-- ============================================================================
-- MEMORY RETRIEVAL V2 CONFIGURATION
-- ============================================================================
-- Config keys for the v2 memory retrieval pipeline.
-- Category: 'retrieval'
--
-- Run: psql -h localhost -U irisuser -d irisdb -f database/sql/add_retrieval_v2_config.sql
-- ============================================================================

INSERT INTO system_config (category, key, value, value_type, default_value, description, requires_restart) VALUES
('retrieval', 'RETRIEVAL_MESSAGES_COUNT',   '5',    'int',   '5',    'Number of recent user messages to use as retrieval query',       false),
('retrieval', 'RETRIEVAL_TRIGGER_INTERVAL', '5',    'int',   '5',    'Run retrieval every N messages',                                 false),
('retrieval', 'RETRIEVAL_W_TOPIC',          '0.60', 'float', '0.60', 'Weight for topic similarity in final score',                     false),
('retrieval', 'RETRIEVAL_W_EMOTION',        '0.25', 'float', '0.25', 'Weight for emotional congruence in final score',                 false),
('retrieval', 'RETRIEVAL_W_RECENCY',        '0.15', 'float', '0.15', 'Weight for recency decay in final score',                        false),
('retrieval', 'RETRIEVAL_TIER1_THRESHOLD',  '0.55', 'float', '0.55', 'Minimum score for tier 1 (primary) match',                       false),
('retrieval', 'RETRIEVAL_TIER2_THRESHOLD',  '0.40', 'float', '0.40', 'Minimum score for tier 2 (supporting) match',                    false),
('retrieval', 'RETRIEVAL_TIER3_THRESHOLD',  '0.30', 'float', '0.30', 'Minimum score for tier 3 (associative) match',                   false),
('retrieval', 'RETRIEVAL_MIN_SIMILARITY',   '0.25', 'float', '0.25', 'Floor similarity — memories below this are discarded',           false),
('retrieval', 'RETRIEVAL_TOP_K',            '10',   'int',   '10',   'Maximum number of memories to retrieve and insert into live_memories', false)
ON CONFLICT (key) DO UPDATE SET
    value = EXCLUDED.value,
    description = EXCLUDED.description,
    last_modified = NOW();
