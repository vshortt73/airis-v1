-- ============================================================================
-- SEMANTIC MEMORY CONFIGURATION
-- ============================================================================
-- Config keys for the semantic memory consolidation pipeline.
-- Category: 'semantic'
--
-- Run: psql -h localhost -U irisuser -d irisdb -f database/sql/add_semantic_memory_config.sql
-- ============================================================================

INSERT INTO system_config (category, key, value, value_type, default_value, description, requires_restart) VALUES
('semantic', 'SEMANTIC_MEMORIES', 'true', 'bool', 'true', 'Feature flag: enable semantic memories in system prompt', false),
('semantic', 'SEMANTIC_MEMORY_LIMIT', '10', 'int', '10', 'Maximum semantic memories to include in prompt', false),
('semantic', 'SEMANTIC_CLUSTER_SIMILARITY_THRESHOLD', '0.60', 'float', '0.60', 'Cosine similarity threshold for clustering takeaways', false),
('semantic', 'SEMANTIC_CLUSTER_MIN_SIZE', '5', 'int', '5', 'Minimum cluster size to qualify for consolidation', false),
('semantic', 'SEMANTIC_DEDUP_SIMILARITY_THRESHOLD', '0.85', 'float', '0.85', 'Similarity threshold for deduplicating against existing semantic memories', false),
('semantic', 'SEMANTIC_HIGH_WATER_MARK', '0', 'int', '0', 'Highest episodic_memories.id processed as a seed (pipeline cursor)', false),
('semantic', 'SEMANTIC_LLM_TEMPERATURE', '0.1', 'float', '0.1', 'LLM temperature for consolidation prompts', false),
('semantic', 'SEMANTIC_LLM_MAX_TOKENS', '300', 'int', '300', 'Max tokens for LLM consolidation output', false)
ON CONFLICT (key) DO UPDATE SET
    value = EXCLUDED.value,
    description = EXCLUDED.description,
    last_modified = NOW();
