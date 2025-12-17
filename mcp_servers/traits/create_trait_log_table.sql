-- Migration: Add trait_modification_log table
-- This table tracks all modifications Iris makes to her personality traits

CREATE TABLE IF NOT EXISTS trait_modification_log (
    id SERIAL PRIMARY KEY,
    trait_id INTEGER REFERENCES character_traits(id),
    trait_name VARCHAR(255) NOT NULL,
    old_value VARCHAR(50),
    new_value VARCHAR(50),
    reason TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for faster queries
CREATE INDEX IF NOT EXISTS idx_trait_log_trait_id ON trait_modification_log(trait_id);
CREATE INDEX IF NOT EXISTS idx_trait_log_timestamp ON trait_modification_log(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_trait_log_trait_name ON trait_modification_log(LOWER(trait_name));

-- Grant permissions
-- GRANT SELECT, INSERT ON trait_modification_log TO iris_user;
-- GRANT USAGE, SELECT ON SEQUENCE trait_modification_log_id_seq TO iris_user;
