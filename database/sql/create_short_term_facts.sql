-- Short-Term Facts Memory System
-- Stores manually flagged facts for middle-tier memory (between working memory and long-term)
-- Created: 2024-12-27
-- Spec: short_term_memory_spec.md

CREATE TABLE IF NOT EXISTS short_term_facts (
    fact_id SERIAL PRIMARY KEY,
    fact_text TEXT NOT NULL,
    category VARCHAR(50),
    created_date TIMESTAMP DEFAULT NOW(),
    last_referenced_date TIMESTAMP DEFAULT NOW(),
    conversation_id VARCHAR(100),
    status VARCHAR(20) DEFAULT 'active',  -- 'active' or 'archived'
    reference_count INTEGER DEFAULT 0
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_short_term_status ON short_term_facts(status);
CREATE INDEX IF NOT EXISTS idx_short_term_created ON short_term_facts(created_date);
CREATE INDEX IF NOT EXISTS idx_short_term_referenced ON short_term_facts(last_referenced_date);

-- Add comment to table
COMMENT ON TABLE short_term_facts IS 'Middle-tier memory: manually flagged facts that persist longer than conversation context but shorter than episodic memories';

-- Add comments to columns
COMMENT ON COLUMN short_term_facts.fact_id IS 'Primary key';
COMMENT ON COLUMN short_term_facts.fact_text IS 'Single sentence factual statement';
COMMENT ON COLUMN short_term_facts.category IS 'Optional categorization: ongoing_project, user_preference, discovery, user_status, other';
COMMENT ON COLUMN short_term_facts.created_date IS 'When fact was created';
COMMENT ON COLUMN short_term_facts.last_referenced_date IS 'Last time fact was retrieved/used in conversation';
COMMENT ON COLUMN short_term_facts.conversation_id IS 'Links to originating conversation session';
COMMENT ON COLUMN short_term_facts.status IS 'active (loads into context) or archived (training data only)';
COMMENT ON COLUMN short_term_facts.reference_count IS 'Tracks retrieval frequency for training analysis';
