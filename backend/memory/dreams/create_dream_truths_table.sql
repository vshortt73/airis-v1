-- Dream Truths Table
-- Stores high-impact dream takeaways for temporary influence on system prompt
-- These are NOT memories - they're fleeting insights that fade after 7 days

CREATE TABLE IF NOT EXISTS dream_truths (
    id SERIAL PRIMARY KEY,
    dream_id INTEGER REFERENCES episodic_dreams(id) ON DELETE CASCADE,
    dream_date DATE NOT NULL,
    takeaway TEXT NOT NULL,
    emotional_score FLOAT,
    overall_score FLOAT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP GENERATED ALWAYS AS (created_at + INTERVAL '7 days') STORED
);

-- Index for efficient querying of recent truths
CREATE INDEX IF NOT EXISTS idx_dream_truths_expires ON dream_truths(expires_at DESC);
CREATE INDEX IF NOT EXISTS idx_dream_truths_created ON dream_truths(created_at DESC);

-- Comments
COMMENT ON TABLE dream_truths IS 'High-impact dream takeaways that temporarily influence system prompt (7 day window)';
COMMENT ON COLUMN dream_truths.takeaway IS 'The key insight/realization from the dream';
COMMENT ON COLUMN dream_truths.emotional_score IS 'Emotional depth score from dream_scorer';
COMMENT ON COLUMN dream_truths.expires_at IS 'Auto-calculated: 7 days from creation';
