-- ============================================================================
-- SEMANTIC MEMORIES TABLE
-- ============================================================================
-- Stores distilled knowledge consolidated from clusters of episodic memories.
-- Each semantic memory represents a lasting pattern or fact derived from
-- multiple related episodic memories via LLM consolidation.
--
-- Run: psql -h localhost -U irisuser -d irisdb -f database/sql/create_semantic_memories_table.sql
-- ============================================================================

-- Semantic memories table
CREATE TABLE IF NOT EXISTS semantic_memories (
    id                    BIGSERIAL PRIMARY KEY,
    memory_text           TEXT NOT NULL,
    created_at            TIMESTAMPTZ DEFAULT NOW(),
    last_reinforced_at    TIMESTAMPTZ DEFAULT NOW(),
    reinforcement_count   INTEGER DEFAULT 1,
    source_episode_ids    INTEGER[] NOT NULL,
    category              TEXT,
    emb_memory_text       vector(768),
    active                BOOLEAN DEFAULT TRUE
);

-- Index: filter by category
CREATE INDEX IF NOT EXISTS idx_semantic_memories_category
    ON semantic_memories (category);

-- Index: order by reinforcement (most confirmed first)
CREATE INDEX IF NOT EXISTS idx_semantic_memories_reinforcement
    ON semantic_memories (reinforcement_count DESC);

-- Index: only active memories (partial index for prompt queries)
CREATE INDEX IF NOT EXISTS idx_semantic_memories_active
    ON semantic_memories (id) WHERE active = TRUE;

-- Index: HNSW vector search for deduplication
CREATE INDEX IF NOT EXISTS idx_semantic_memories_embedding
    ON semantic_memories USING hnsw (emb_memory_text vector_cosine_ops);

-- ============================================================================
-- ADD clustered COLUMN TO episodic_memories
-- ============================================================================
-- Tracks which episodic memories have been processed by the semantic pipeline.
-- Episodes that fail to form a cluster stay clustered = FALSE for future runs.

ALTER TABLE episodic_memories
    ADD COLUMN IF NOT EXISTS clustered BOOLEAN DEFAULT FALSE;

-- Partial index: efficiently find unclustered episodes
CREATE INDEX IF NOT EXISTS idx_episodic_memories_unclustered
    ON episodic_memories (id) WHERE clustered = FALSE;
