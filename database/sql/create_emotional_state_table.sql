-- Emotional State Table for Iris v3
-- Tracks dynamic emotional state that evolves with each conversation turn
-- Part of the Dynamic Emotional State Tracker system

-- Main emotional state table (single row, updated per-turn)
CREATE TABLE IF NOT EXISTS emotional_state (
    id INTEGER PRIMARY KEY DEFAULT 1,
    state_data JSONB NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Ensure only one row exists
    CONSTRAINT single_row CHECK (id = 1)
);

-- Emotional state history for analysis and debugging
CREATE TABLE IF NOT EXISTS emotional_state_history (
    id SERIAL PRIMARY KEY,
    state_data JSONB NOT NULL,
    trigger_message TEXT,  -- The user message that triggered this state
    analysis_data JSONB,   -- Mistral's analysis output
    recorded_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Index for time-based queries on history
CREATE INDEX IF NOT EXISTS idx_emotional_history_time
ON emotional_state_history(recorded_at DESC);

-- Comments
COMMENT ON TABLE emotional_state IS 'Current emotional state for Iris - single row updated each turn';
COMMENT ON TABLE emotional_state_history IS 'Historical record of emotional state changes for analysis';
COMMENT ON COLUMN emotional_state.state_data IS 'JSONB containing all emotional state values (Calm, Joy, Desire, etc.)';
COMMENT ON COLUMN emotional_state_history.trigger_message IS 'The user message that caused this emotional state change';
COMMENT ON COLUMN emotional_state_history.analysis_data IS 'Mistral sentiment analysis output (tone, intent, descriptors, intensity)';
