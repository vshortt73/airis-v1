-- ============================================================================
-- Iris v3 — Base Table Schemas
-- ============================================================================
-- These tables were created before git history began. This file was
-- reconstructed from the live database on 2026-01-28 to enable
-- from-scratch deployment.
--
-- EXECUTION ORDER: Run this FIRST, before any other SQL file.
-- PREREQUISITE: Extensions must be installed (see DEPLOYMENT.md Step 2).
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 0. Required Extensions
-- ----------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS vector;       -- pgvector 0.8.0+
CREATE EXTENSION IF NOT EXISTS pgcrypto;     -- password hashing
CREATE EXTENSION IF NOT EXISTS plpython3u;   -- Python stored procedures
-- pg_dirtyread is optional (recovery tool), skip if not available

-- ----------------------------------------------------------------------------
-- 1. Trigger Functions (must exist before tables that reference them)
-- ----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION update_system_instructions_timestamp()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION update_mcp_tools_timestamp()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

-- ----------------------------------------------------------------------------
-- 2. chat_sessions (must exist before chat_history references session_id)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id    UUID PRIMARY KEY,
    start_time    TIMESTAMP NOT NULL,
    end_time      TIMESTAMP NOT NULL,
    message_count INTEGER NOT NULL,
    summary       TEXT,
    subject_count INTEGER DEFAULT 0,
    clustered     BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_start_time
    ON chat_sessions (start_time);

-- ----------------------------------------------------------------------------
-- 3. chat_history — conversation message storage
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chat_history (
    id                   SERIAL PRIMARY KEY,
    role                 TEXT,
    message              TEXT,
    c_timestamp          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    node_id              TEXT,
    conv_title           TEXT,
    attachments          TEXT,
    session_id           UUID,
    subject_id           UUID,
    clustered            BOOLEAN DEFAULT FALSE,
    sessioned            BOOLEAN DEFAULT FALSE,
    segmented_at         TIMESTAMP,
    emb_message          vector(768),
    meaningfulness       REAL,
    system_version       TEXT DEFAULT '1.0',
    tool_calls           JSONB,
    tool_call_id         TEXT,
    tool_name            TEXT,
    topic_id             INTEGER,
    memory_processed_at  TIMESTAMPTZ,
    sender               VARCHAR(50) DEFAULT 'user',
    summary              TEXT,
    summary_generated_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS chat_history_copy_session_id_idx
    ON chat_history (session_id);
CREATE INDEX IF NOT EXISTS chat_history_copy_subject_id_idx
    ON chat_history (subject_id);
CREATE INDEX IF NOT EXISTS idx_chat_history_memory_processed
    ON chat_history (memory_processed_at)
    WHERE memory_processed_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_chat_history_needs_summary
    ON chat_history (role, summary)
    WHERE summary IS NULL AND role IN ('user', 'assistant');
CREATE INDEX IF NOT EXISTS idx_chat_history_topic_id
    ON chat_history (topic_id)
    WHERE topic_id IS NOT NULL AND topic_id <> 0;

-- ----------------------------------------------------------------------------
-- 4. chat_history_generic — alternative protocol chat table
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chat_history_generic (
    id           SERIAL PRIMARY KEY,
    session_id   UUID NOT NULL,
    role         VARCHAR(20) NOT NULL,
    content      TEXT NOT NULL,
    timestamp    TIMESTAMP DEFAULT NOW(),
    tool_calls   JSONB,
    tool_call_id VARCHAR(100),
    tool_name    VARCHAR(100),
    attachments  JSONB,
    embedding    vector(768)
);

-- ----------------------------------------------------------------------------
-- 5. episodic_memories — long-term memory with vector embeddings
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS episodic_memories (
    id                       BIGSERIAL PRIMARY KEY,
    session_id               UUID NOT NULL,
    segment_id               INTEGER NOT NULL,
    topic_id                 INTEGER NOT NULL,
    created_at               TIMESTAMPTZ DEFAULT NOW(),
    updated_at               TIMESTAMPTZ,
    event_time               TIMESTAMPTZ,
    transcript               TEXT,
    summary_context          TEXT,
    summary_event            TEXT,
    summary_significance     TEXT,
    summary_tone             TEXT,
    immutable                BOOLEAN DEFAULT FALSE,
    emb_minilm               vector(768),
    emotion_label            TEXT,
    valence                  DOUBLE PRECISION,
    arousal                  DOUBLE PRECISION,
    recurrence               DOUBLE PRECISION,
    novelty                  DOUBLE PRECISION,
    cohesion                 DOUBLE PRECISION,
    recommendation           TEXT,
    takeaway                 TEXT,
    emotion_top3             JSONB,
    voice                    TEXT,
    category                 TEXT,
    emb_summary_context      vector(768),
    emb_summary_event        vector(768),
    emb_summary_significance vector(768),
    emb_takeaway             vector(768),
    key_details              TEXT,
    emb_key_details          vector(768),
    memory_version           TEXT DEFAULT 'V2',
    emb_topic                vector(768),
    topic_label              TEXT,
    UNIQUE (session_id, segment_id, topic_id)
);

-- ----------------------------------------------------------------------------
-- 6. fulltraits — personality traits (name/value pairs)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fulltraits (
    id          INTEGER PRIMARY KEY,
    name        VARCHAR(64),
    description TEXT,
    value       VARCHAR(64)
);

-- ----------------------------------------------------------------------------
-- 7. system_instructions — system prompt components
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS system_instructions (
    id                SERIAL PRIMARY KEY,
    instruction_key   VARCHAR(100) NOT NULL UNIQUE,
    instruction_text  TEXT NOT NULL,
    instruction_order INTEGER DEFAULT 0,
    active            BOOLEAN DEFAULT TRUE,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_system_instructions_active
    ON system_instructions (active);
CREATE INDEX IF NOT EXISTS idx_system_instructions_order
    ON system_instructions (instruction_order);

CREATE TRIGGER system_instructions_update_timestamp
    BEFORE UPDATE ON system_instructions
    FOR EACH ROW EXECUTE FUNCTION update_system_instructions_timestamp();

-- ----------------------------------------------------------------------------
-- 8. protocols — personality mode configurations
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS protocols (
    id                INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    name              VARCHAR(100) NOT NULL,
    description       TEXT,
    instructions      TEXT,
    rules_include     JSON,
    rules_exclude     JSON,
    show_chat_history BOOLEAN,
    show_memories     BOOLEAN,
    traits_adjust     JSON,
    tool_usage        JSON
);

-- ----------------------------------------------------------------------------
-- 9. mcp_tools — tool definitions with input schemas
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mcp_tools (
    id                  SERIAL PRIMARY KEY,
    tool_name           VARCHAR(255) NOT NULL UNIQUE,
    description         TEXT,
    input_schema        JSONB,
    enabled             BOOLEAN DEFAULT TRUE,
    priority            INTEGER DEFAULT 0,
    custom_instructions TEXT,
    created_at          TIMESTAMP DEFAULT NOW(),
    updated_at          TIMESTAMP DEFAULT NOW(),
    icon                TEXT
);

CREATE INDEX IF NOT EXISTS idx_mcp_tools_enabled
    ON mcp_tools (enabled);
CREATE INDEX IF NOT EXISTS idx_mcp_tools_priority
    ON mcp_tools (priority DESC);

CREATE TRIGGER mcp_tools_update_timestamp
    BEFORE UPDATE ON mcp_tools
    FOR EACH ROW EXECUTE FUNCTION update_mcp_tools_timestamp();

-- ----------------------------------------------------------------------------
-- 10. Supporting tables (smaller, less critical)
-- ----------------------------------------------------------------------------

-- Active protocol singleton
-- NOTE: Full creation with FK is in create_protocol_tracking_tables.sql
-- This is a minimal version if you need the table before that script.

-- Core agreements / facts
CREATE TABLE IF NOT EXISTS core_agreements (
    fact_id              INTEGER PRIMARY KEY,
    fact_text            TEXT NOT NULL,
    category             TEXT NOT NULL,
    created_date         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_referenced_date TIMESTAMP,
    reference_count      INTEGER DEFAULT 0
);

-- Activity log
CREATE TABLE IF NOT EXISTS iris_activity (
    id        SERIAL,
    activity  TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Live memory injection cache
CREATE TABLE IF NOT EXISTS live_memories (
    id          BIGSERIAL PRIMARY KEY,
    memory_id   INTEGER NOT NULL,
    rank        NUMERIC NOT NULL,
    injected_at TIMESTAMPTZ DEFAULT NOW(),
    tier        INTEGER DEFAULT 3
);

-- General log table
CREATE TABLE IF NOT EXISTS log (
    id         SERIAL,
    chat_id    INTEGER,
    log        TEXT,
    attachment TEXT,
    type       INTEGER,
    timestamp  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    line       TEXT,
    file       TEXT
);

-- Prompt hashes (change detection)
CREATE TABLE IF NOT EXISTS prompt_hashes (
    section TEXT NOT NULL UNIQUE,
    hash    TEXT NOT NULL
);

-- Temporal tags for memory display
CREATE TABLE IF NOT EXISTS temporal_tags (
    id                   INTEGER PRIMARY KEY,
    temporal_description TEXT NOT NULL,
    time_delta_factor    TEXT NOT NULL,
    time_delta_number    INTEGER NOT NULL,
    display_priority     INTEGER DEFAULT 0,
    emotion_bias         TEXT,
    created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    allow_daypart        BOOLEAN DEFAULT FALSE,
    min_hour             INTEGER,
    max_hour             INTEGER,
    minute_min           INTEGER,
    minute_max           INTEGER
);

-- Variables key-value store
CREATE TABLE IF NOT EXISTS variables (
    name  TEXT,
    value TEXT
);

-- Trait modification audit log
CREATE TABLE IF NOT EXISTS trait_modification_log (
    trait_id   INTEGER,
    trait_name TEXT,
    old_value  TEXT,
    new_value  TEXT,
    reason     TEXT,
    id         INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY
);

-- ----------------------------------------------------------------------------
-- 11. Memory weight calculation function
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION calculate_memory_weight(
    recurrence NUMERIC, novelty NUMERIC, cohesion NUMERIC,
    emotion NUMERIC, speaker_weight NUMERIC,
    length_tokens NUMERIC, duration_seconds NUMERIC,
    age_days NUMERIC,
    half_life_days NUMERIC DEFAULT 90.0,
    w_emotion NUMERIC DEFAULT 0.25, w_cohesion NUMERIC DEFAULT 0.20,
    w_speaker NUMERIC DEFAULT 0.15, w_recur NUMERIC DEFAULT 0.15,
    w_novel NUMERIC DEFAULT 0.15, w_len NUMERIC DEFAULT 0.05,
    w_dur NUMERIC DEFAULT 0.05,
    recur_k NUMERIC DEFAULT 4.0,
    len_mu NUMERIC DEFAULT 600.0, len_sigma NUMERIC DEFAULT 600.0,
    dur_tau NUMERIC DEFAULT 300.0
) RETURNS NUMERIC LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    rec_u NUMERIC; nov_u NUMERIC; coh_u NUMERIC;
    emo_u NUMERIC; spk_u NUMERIC; len_u NUMERIC; dur_u NUMERIC;
    base NUMERIC; dec NUMERIC; final_result NUMERIC;
BEGIN
    rec_u := saturate_recurrence(recurrence, recur_K);
    nov_u := clamp01(novelty);
    coh_u := clamp01(cohesion);
    emo_u := clamp01(emotion);
    spk_u := clamp01(speaker_weight);
    len_u := len_utility(length_tokens, len_mu, len_sigma);
    dur_u := dur_utility(duration_seconds, dur_tau);

    base := (
        w_emotion * emo_u +
        w_cohesion * coh_u +
        w_speaker * spk_u +
        w_recur * rec_u +
        w_novel * nov_u +
        w_len * len_u +
        w_dur * dur_u
    );

    dec := time_decay(age_days, half_life_days);
    final_result := base * dec;

    RETURN final_result;
END;
$$;

-- NOTE: calculate_memory_weight depends on helper functions:
-- saturate_recurrence(), clamp01(), len_utility(), dur_utility(), time_decay()
-- These are defined in the memory system setup scripts.

-- ============================================================================
-- DONE. Next steps:
-- 1. Run create_system_config_table.sql
-- 2. Run create_emotional_state_table.sql
-- 3. Run create_short_term_facts.sql
-- 4. Run create_protocol_tracking_tables.sql (creates active_protocol + protocol_history)
-- 5. Run create_knowledge_tables.sql
-- 6. Run create_face_tables.sql
-- 7. Run create_episodic_dreams_table.sql + create_dream_truths_table.sql
-- 8. Run create_seeds_table.sql
-- 9. Run create_readable_views.sql
-- 10. Populate: populate_system_config_complete.sql
-- 11. Populate: insert_optimized_instructions.sql
-- 12. Populate: insert_*_tools.sql (all tool registration files)
-- See DEPLOYMENT.md for the complete ordered procedure.
-- ============================================================================
