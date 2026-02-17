-- Turn Metrics: Per-turn observability data captured inline during chat flow
-- Stores memory retrieval provenance, emotional deltas, LLM performance,
-- context budget, and tool usage for every conversation turn.

CREATE TABLE IF NOT EXISTS turn_metrics (
    id BIGSERIAL PRIMARY KEY,
    session_id UUID,
    timestamp TIMESTAMPTZ DEFAULT NOW(),

    -- Memory retrieval provenance
    memories_in_context INT,
    memory_ids INT[],
    memory_tiers INT[],
    memory_scores FLOAT4[],
    avg_topic_similarity FLOAT4,
    avg_emotional_congruence FLOAT4,
    avg_recency FLOAT4,

    -- Memory influence (post-response)
    response_embedding VECTOR(768),
    memory_influence_scores FLOAT4[],
    max_memory_influence FLOAT4,
    unexplained_ratio FLOAT4,

    -- Emotional state
    emotional_state_before JSONB,
    emotional_state_after JSONB,
    emotional_delta FLOAT4,
    dominant_emotion TEXT,

    -- LLM performance
    kv_cache_tokens INT,
    kv_prompt_tokens INT,
    kv_cache_efficiency FLOAT4,
    gen_tokens_per_sec FLOAT4,
    response_tokens INT,
    response_time_ms INT,

    -- Context budget
    total_context_tokens INT,
    system_prompt_tokens INT,
    conversation_tokens INT,

    -- Tool usage
    tool_calls_count INT DEFAULT 0,
    tools_used TEXT[],
    tool_iterations INT DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_turn_metrics_session ON turn_metrics(session_id);
CREATE INDEX IF NOT EXISTS idx_turn_metrics_timestamp ON turn_metrics(timestamp);
