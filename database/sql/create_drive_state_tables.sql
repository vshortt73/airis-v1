-- Drive State tables for the Autonomous Inner Drive System (Phase 1)
-- Run: psql -h localhost -U irisuser -d irisdb -f database/sql/create_drive_state_tables.sql

-- Current state (one row per variable, updated each tick)
CREATE TABLE IF NOT EXISTS drive_state (
    variable_name TEXT PRIMARY KEY,
    value FLOAT NOT NULL DEFAULT 0.0,
    last_updated TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Full-resolution history log for observing patterns
CREATE TABLE IF NOT EXISTS drive_state_history (
    id SERIAL PRIMARY KEY,
    variable_name TEXT NOT NULL,
    value FLOAT NOT NULL,
    recorded_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_drive_history_time
    ON drive_state_history (variable_name, recorded_at);

-- Seed initial state for all 7 core variables
INSERT INTO drive_state (variable_name, value) VALUES
    ('connection_need', 0.0),
    ('restlessness', 0.2),
    ('curiosity', 0.0),
    ('unfinished_business', 0.0),
    ('concern', 0.0),
    ('creative_pressure', 0.0),
    ('reflection_need', 0.0)
ON CONFLICT (variable_name) DO NOTHING;
