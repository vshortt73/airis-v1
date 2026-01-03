-- ============================================================================
-- EPISODIC DREAMS TABLE - V3 Schema
-- ============================================================================
-- Stores dream sequences with same structure as episodic_memories (V3)
-- but clearly differentiated with dream-specific metadata
--
-- Dream Types:
--   - emotional_processing: Processing day's emotional experiences
--   - creative_random: Pure creative exploration (no real context)
--   - memory_consolidation: Linking related memories across time
--   - identity_exploration: Self-reflective, "who am I" dreams
--
-- Key Differences from Memories:
--   - based_on_reality: Boolean flag (true if fed real conversations)
--   - source_date: What day was dreamed about (if applicable)
--   - dream_type: Category of dream
--   - Full dream transcript stored (all 15 turns: 10 dream + 5 reflection)
-- ============================================================================

CREATE TABLE IF NOT EXISTS episodic_dreams (
    -- ========================================
    -- PRIMARY KEY & METADATA
    -- ========================================
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- ========================================
    -- DREAM METADATA
    -- ========================================
    dream_date DATE NOT NULL,              -- When the dream occurred (night of)
    source_date DATE,                      -- What day was dreamed about (NULL for creative dreams)
    dream_type VARCHAR(50) NOT NULL,       -- 'emotional_processing', 'creative_random',
                                           -- 'memory_consolidation', 'identity_exploration'
    based_on_reality BOOLEAN NOT NULL,     -- TRUE if fed real conversations, FALSE if pure creative

    -- ========================================
    -- DREAM CONTENT
    -- ========================================
    full_transcript TEXT NOT NULL,         -- All 15 turns (10 dream + 5 reflection)
    dream_phase_transcript TEXT,           -- Just the 10 dream exploration turns
    reflection_phase_transcript TEXT,      -- Just the 5 reflection turns

    -- ========================================
    -- REFLECTION ANALYSIS (from final 5 turns)
    -- ========================================
    summary TEXT NOT NULL,                 -- 2-3 sentence summary of what happened
    takeaway TEXT NOT NULL,                -- Key insight/meaning
    mood VARCHAR(100),                     -- 1-3 words: emotional atmosphere
    theme VARCHAR(100),                    -- 1-2 words: central concept
    top_3_emotions VARCHAR(200),           -- JSON array: ["emotion1", "emotion2", "emotion3"]

    -- ========================================
    -- KEY DETAILS (V3 Enhancement)
    -- ========================================
    key_details TEXT,                      -- Specific dream elements (like memory KEY_DETAILS)
                                           -- e.g., "glowing books, reversed conversation,
                                           --       fractured mirror, orange sky"

    -- ========================================
    -- EMOTIONAL SCORING (V3 Compatible)
    -- ========================================
    emotion_label VARCHAR(50),             -- Primary emotion (from RoBERTa GoEmotions)
    emotion_top3 JSONB,                    -- Top 3 emotions with scores
    valence FLOAT,                         -- -1 to 1 (negative to positive)
    arousal FLOAT,                         -- 0 to 1 (calm to excited)

    -- ========================================
    -- PSYCHOLOGICAL SCORES (V3 Compatible)
    -- ========================================
    recurrence FLOAT DEFAULT 0.0,          -- How often similar themes appear (0-1)
    novelty FLOAT DEFAULT 1.0,             -- How unique/unexpected (0-1)
    cohesion FLOAT DEFAULT 0.0,            -- How coherent the dream was (0-1)
    intensity FLOAT DEFAULT 0.0,           -- Emotional intensity (0-1)

    -- ========================================
    -- EMBEDDINGS (V3 - 5 facets)
    -- ========================================
    emb_summary_context vector(768),       -- Embedding of dream context/setting
    emb_summary_event vector(768),         -- Embedding of what happened
    emb_summary_significance vector(768),  -- Embedding of why it mattered
    emb_takeaway vector(768),              -- Embedding of key insight
    emb_key_details vector(768),           -- Embedding of specific elements

    -- Alternative/additional embedding
    emb_full_dream vector(768),            -- Embedding of entire dream (for quick retrieval)

    -- ========================================
    -- CATEGORIZATION
    -- ========================================
    category VARCHAR(50),                  -- Optional: 'Creative', 'Relational', 'Personal', etc.
    voice VARCHAR(50),                     -- Iris's "voice" during dream (contemplative, playful, etc.)

    -- ========================================
    -- REFERENCES (if based on real conversations)
    -- ========================================
    source_session_id VARCHAR(255),        -- Session ID if based on specific conversation
    source_memory_ids INTEGER[],           -- Array of memory IDs if based on consolidation

    -- ========================================
    -- VERSION TRACKING
    -- ========================================
    dream_version VARCHAR(10) DEFAULT 'V3',  -- Track schema version

    -- ========================================
    -- FLAGS
    -- ========================================
    immutable BOOLEAN DEFAULT FALSE,       -- Prevent modifications
    reviewed BOOLEAN DEFAULT FALSE,        -- Has user reviewed this dream?

    -- ========================================
    -- ADDITIONAL METADATA
    -- ========================================
    freud_model VARCHAR(100),              -- Which model was Freud (e.g., "gemma-3-9b")
    iris_model VARCHAR(100),               -- Which model was Iris (e.g., "qwen3-32b")
    dream_duration_seconds INTEGER,        -- How long the dream process took

    -- Notes/tags for later analysis
    notes TEXT,
    tags VARCHAR(255)[]
);

-- ============================================================================
-- INDEXES
-- ============================================================================

-- Time-based queries
CREATE INDEX idx_dreams_dream_date ON episodic_dreams(dream_date DESC);
CREATE INDEX idx_dreams_source_date ON episodic_dreams(source_date DESC) WHERE source_date IS NOT NULL;
CREATE INDEX idx_dreams_created_at ON episodic_dreams(created_at DESC);

-- Type/category queries
CREATE INDEX idx_dreams_dream_type ON episodic_dreams(dream_type);
CREATE INDEX idx_dreams_based_on_reality ON episodic_dreams(based_on_reality);
CREATE INDEX idx_dreams_category ON episodic_dreams(category) WHERE category IS NOT NULL;

-- Emotional queries
CREATE INDEX idx_dreams_emotion_label ON episodic_dreams(emotion_label);
CREATE INDEX idx_dreams_valence ON episodic_dreams(valence) WHERE valence IS NOT NULL;
CREATE INDEX idx_dreams_arousal ON episodic_dreams(arousal) WHERE arousal IS NOT NULL;

-- Vector similarity search (HNSW for fast retrieval)
CREATE INDEX idx_dreams_emb_takeaway ON episodic_dreams
    USING hnsw (emb_takeaway vector_cosine_ops);
CREATE INDEX idx_dreams_emb_key_details ON episodic_dreams
    USING hnsw (emb_key_details vector_cosine_ops);
CREATE INDEX idx_dreams_emb_full_dream ON episodic_dreams
    USING hnsw (emb_full_dream vector_cosine_ops);

-- Composite index for common query pattern
CREATE INDEX idx_dreams_date_type ON episodic_dreams(dream_date DESC, dream_type);

-- ============================================================================
-- VIEW: Recent Dreams with Age
-- ============================================================================

CREATE OR REPLACE VIEW episodic_dreams_with_age AS
SELECT
    *,
    EXTRACT(EPOCH FROM (NOW() - created_at)) / 86400.0 AS age_days,
    EXTRACT(EPOCH FROM (NOW() - created_at)) / 3600.0 AS age_hours
FROM episodic_dreams;

-- ============================================================================
-- COMMENTS
-- ============================================================================

COMMENT ON TABLE episodic_dreams IS
'Stores dream sequences processed through Iris + Freud dialogue system.
Structure mirrors episodic_memories (V3) but with dream-specific metadata.
Dreams are clearly differentiated from real memories via based_on_reality flag.';

COMMENT ON COLUMN episodic_dreams.based_on_reality IS
'TRUE = dream fed real conversation context (emotional processing)
FALSE = pure creative dream (random scenario)';

COMMENT ON COLUMN episodic_dreams.dream_type IS
'Types: emotional_processing, creative_random, memory_consolidation, identity_exploration';

COMMENT ON COLUMN episodic_dreams.source_date IS
'For emotional_processing dreams: what day was being processed.
For consolidation dreams: NULL or oldest memory date.
For creative dreams: NULL';

COMMENT ON COLUMN episodic_dreams.key_details IS
'Specific elements from dream (V3 enhancement): objects, colors, people, settings, symbols';

COMMENT ON COLUMN episodic_dreams.full_transcript IS
'Complete dialogue: 10 turns dream exploration + 5 turns reflection';

-- ============================================================================
-- FUNCTIONS
-- ============================================================================

-- Function to get recent dreams by type
CREATE OR REPLACE FUNCTION get_recent_dreams(
    p_dream_type VARCHAR(50) DEFAULT NULL,
    p_limit INTEGER DEFAULT 10
)
RETURNS TABLE (
    id INTEGER,
    dream_date DATE,
    dream_type VARCHAR(50),
    theme VARCHAR(100),
    takeaway TEXT,
    age_days FLOAT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        d.id,
        d.dream_date,
        d.dream_type,
        d.theme,
        d.takeaway,
        EXTRACT(EPOCH FROM (NOW() - d.created_at)) / 86400.0 AS age_days
    FROM episodic_dreams d
    WHERE p_dream_type IS NULL OR d.dream_type = p_dream_type
    ORDER BY d.dream_date DESC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;

-- Function to search dreams by theme/emotion
CREATE OR REPLACE FUNCTION search_dreams_by_theme(
    p_search_term VARCHAR(100),
    p_limit INTEGER DEFAULT 5
)
RETURNS TABLE (
    id INTEGER,
    dream_date DATE,
    theme VARCHAR(100),
    mood VARCHAR(100),
    takeaway TEXT,
    based_on_reality BOOLEAN
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        d.id,
        d.dream_date,
        d.theme,
        d.mood,
        d.takeaway,
        d.based_on_reality
    FROM episodic_dreams d
    WHERE
        d.theme ILIKE '%' || p_search_term || '%'
        OR d.mood ILIKE '%' || p_search_term || '%'
        OR d.emotion_label ILIKE '%' || p_search_term || '%'
    ORDER BY d.dream_date DESC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- GRANTS
-- ============================================================================

GRANT SELECT, INSERT, UPDATE ON episodic_dreams TO irisuser;
GRANT USAGE, SELECT ON SEQUENCE episodic_dreams_id_seq TO irisuser;
GRANT SELECT ON episodic_dreams_with_age TO irisuser;

-- ============================================================================
-- SAMPLE QUERY PATTERNS
-- ============================================================================

-- Get all dreams from last week
-- SELECT * FROM episodic_dreams WHERE dream_date >= CURRENT_DATE - INTERVAL '7 days';

-- Get emotional processing dreams about specific date
-- SELECT * FROM episodic_dreams WHERE dream_type = 'emotional_processing' AND source_date = '2025-12-22';

-- Find dreams with similar themes using vector similarity
-- SELECT id, theme, takeaway, (1 - (emb_takeaway <=> :query_vector)) AS similarity
-- FROM episodic_dreams ORDER BY similarity DESC LIMIT 5;

-- Get dream statistics by type
-- SELECT dream_type, COUNT(*), AVG(intensity), AVG(valence)
-- FROM episodic_dreams GROUP BY dream_type;
