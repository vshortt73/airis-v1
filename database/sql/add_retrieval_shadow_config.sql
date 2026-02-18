-- Retrieval Strategy B (per-message) + shadow comparison mode
-- Shadow mode runs both strategies per turn, logs to retrieval_comparison, but only
-- writes the active strategy's results to live_memories.

-- Config keys
INSERT INTO system_config (category, key, value, value_type, default_value)
VALUES
    ('retrieval', 'RETRIEVAL_STRATEGY', 'concat', 'str', 'concat'),
    ('retrieval', 'RETRIEVAL_SHADOW_ENABLED', 'true', 'bool', 'true')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;

-- Comparison logging table
CREATE TABLE IF NOT EXISTS retrieval_comparison (
    id          SERIAL PRIMARY KEY,
    run_id      UUID NOT NULL,
    strategy    VARCHAR(20) NOT NULL,     -- 'concat' or 'per_message'
    memory_id   INTEGER NOT NULL,
    final_score NUMERIC NOT NULL,
    tier        INTEGER NOT NULL,
    topic_sim   NUMERIC,
    emo_score   NUMERIC,
    recency     NUMERIC,
    takeaway    TEXT,
    category    VARCHAR(50),
    query_preview TEXT,                    -- first 200 chars of query input
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_retrieval_comparison_run ON retrieval_comparison(run_id);
CREATE INDEX IF NOT EXISTS idx_retrieval_comparison_created ON retrieval_comparison(created_at DESC);
