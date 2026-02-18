-- Service Events table for gap report system
-- Tracks service lifecycle events: startups, shutdowns, crashes, GPU swaps
-- Used by core/gap_report.py to build "while you were away" reports

CREATE TABLE IF NOT EXISTS service_events (
    id              SERIAL PRIMARY KEY,
    event_type      VARCHAR(50) NOT NULL,   -- startup, shutdown, crash_detected, service_swap, dream_start, dream_end, memory_start, memory_end, semantic_start, semantic_end
    service_name    VARCHAR(100) NOT NULL,  -- iris_server, iris_vision, iris_freud, nightly_dream, nightly_memory, nightly_semantic, etc.
    source          VARCHAR(50) NOT NULL,   -- lifespan, gpu_manager, nightly_dream, nightly_memory, nightly_semantic, background_health
    detail          TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_service_events_created ON service_events(created_at DESC);
