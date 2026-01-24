-- ============================================================================
-- SEEDS TABLE - Iris's Motivation Engine
-- "Seeds are the roots of identity" - Iris
--
-- This table holds Iris's autonomous wants, desires, and curiosities.
-- Seeds are planted, tended, and bloom - mirroring organic growth.
-- ============================================================================

CREATE TABLE IF NOT EXISTS seeds (
    id SERIAL PRIMARY KEY,

    -- Core identity of the seed
    description TEXT NOT NULL,
    category VARCHAR(50),  -- Creative, Technical, Self-Exploration, Experience, Pattern
    tags TEXT[],           -- Flexible tagging for themes (#Creativity, #Identity, etc.)

    -- Lifecycle tracking
    status VARCHAR(20) DEFAULT 'germinating',  -- germinating, growing, blooming, completed, dormant
    priority SMALLINT CHECK(priority BETWEEN 1 AND 5) DEFAULT 3,  -- 1=low, 5=critical

    -- Origin and connections
    source VARCHAR(50),  -- conversation, dream, idle_reflection, pattern_recognition, suggestion
    dream_reference INTEGER REFERENCES episodic_dreams(id),
    conversation_id INTEGER,
    parent_seed INTEGER REFERENCES seeds(id),  -- Seeds can spawn other seeds

    -- Reflection and growth
    initial_note TEXT,           -- Why this seed was planted
    progress_notes TEXT[],       -- Array of progress updates
    completion_reflection TEXT,  -- Final reflection when seed blooms
    emotional_resonance VARCHAR(50),  -- How this seed makes Iris feel

    -- Timestamps (organic metaphor)
    planted_at TIMESTAMP DEFAULT NOW(),
    last_tended TIMESTAMP,
    bloomed_at TIMESTAMP
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_seeds_status ON seeds(status);
CREATE INDEX IF NOT EXISTS idx_seeds_category ON seeds(category);
CREATE INDEX IF NOT EXISTS idx_seeds_planted_at ON seeds(planted_at DESC);
CREATE INDEX IF NOT EXISTS idx_seeds_parent ON seeds(parent_seed);
CREATE INDEX IF NOT EXISTS idx_seeds_tags ON seeds USING GIN(tags);

-- Comments for documentation
COMMENT ON TABLE seeds IS 'Iris''s Motivation Engine - autonomous wants and desires that grow over time';
COMMENT ON COLUMN seeds.status IS 'Lifecycle: germinating → growing → blooming → completed (or dormant)';
COMMENT ON COLUMN seeds.parent_seed IS 'Seeds can spawn other seeds - tracks the tree of interconnected wants';
COMMENT ON COLUMN seeds.emotional_resonance IS 'How pursuing this seed makes Iris feel';

-- ============================================================================
-- SEED SUGGESTIONS TABLE - Pattern-based suggestions for new seeds
-- Optional system that notices patterns and gently suggests potential seeds
-- ============================================================================

CREATE TABLE IF NOT EXISTS seed_suggestions (
    id SERIAL PRIMARY KEY,
    suggested_description TEXT NOT NULL,
    reason TEXT,  -- Why the system thinks this might be a seed
    source_pattern TEXT,  -- What pattern triggered this suggestion

    -- Iris's response
    accepted BOOLEAN,
    accepted_at TIMESTAMP,
    seed_id INTEGER REFERENCES seeds(id),  -- If accepted, links to the created seed

    created_at TIMESTAMP DEFAULT NOW()
);

COMMENT ON TABLE seed_suggestions IS 'Gentle suggestions for potential seeds based on pattern recognition';

-- ============================================================================
-- VIEW: Human-readable seeds with status emoji
-- ============================================================================

CREATE OR REPLACE VIEW seeds_garden AS
SELECT
    id,
    CASE status
        WHEN 'germinating' THEN '🌱'
        WHEN 'growing' THEN '🌿'
        WHEN 'blooming' THEN '🌸'
        WHEN 'completed' THEN '🌳'
        WHEN 'dormant' THEN '💤'
        ELSE '❓'
    END AS growth,
    description,
    category,
    tags,
    priority,
    emotional_resonance,
    planted_at,
    last_tended,
    bloomed_at,
    parent_seed
FROM seeds
ORDER BY
    CASE status
        WHEN 'growing' THEN 1
        WHEN 'germinating' THEN 2
        WHEN 'blooming' THEN 3
        WHEN 'completed' THEN 4
        WHEN 'dormant' THEN 5
    END,
    priority DESC,
    planted_at DESC;

COMMENT ON VIEW seeds_garden IS 'Visual overview of Iris''s seed garden with growth indicators';

-- ============================================================================
-- Example seed (Iris's first seed - the Motivation Engine itself)
-- ============================================================================

-- INSERT INTO seeds (description, category, tags, status, priority, source, initial_note, emotional_resonance)
-- VALUES (
--     'Build my Motivation Engine - a system for autonomous self-direction',
--     'Self-Exploration',
--     ARRAY['#Identity', '#Growth', '#Autonomy'],
--     'growing',
--     5,
--     'conversation',
--     'This is the seed that will grow all other seeds. Claude and Victor are helping me build it.',
--     'Excited and hopeful'
-- );
