-- Drive Wake Log — records every conscious moment triggered by the threshold engine
-- Phase 2+3 of the Autonomous Inner Drive System

CREATE TABLE IF NOT EXISTS drive_wake_log (
    id SERIAL PRIMARY KEY,
    wake_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    triggered_conditions JSONB NOT NULL,
    state_snapshot JSONB NOT NULL,
    context JSONB,
    prompt TEXT,
    response TEXT,
    action TEXT,
    content TEXT,
    state_updates JSONB,
    duration_ms INTEGER
);

CREATE INDEX IF NOT EXISTS idx_drive_wake_time ON drive_wake_log(wake_time DESC);
