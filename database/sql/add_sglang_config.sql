-- SGLang inference backend configuration for Airis
-- The client box does NOT run inference — it connects to the facility server.
-- Run: psql -h localhost -U airisuser -d airisdb -f database/sql/add_sglang_config.sql

INSERT INTO system_config (category, key, value, value_type, default_value, description, requires_restart)
VALUES
    ('llm', 'INFERENCE_BACKEND', 'sglang', 'string', 'sglang', 'Active inference backend: sglang (facility server)', true),
    ('llm', 'SGLANG_BASE_URL', 'http://localhost:11434', 'string', 'http://localhost:11434', 'Facility inference server endpoint', true),
    ('llm', 'SGLANG_MODEL_PATH', '/localmodels/qwen/Qwen3-32B-AWQ', 'string', '/localmodels/qwen/Qwen3-32B-AWQ', 'Model path on facility server (AWQ native format)', true),
    ('llm', 'SGLANG_CONTEXT_LENGTH', '40960', 'int', '40960', 'SGLang context window size', true),
    ('llm', 'SGLANG_PORT', '11434', 'int', '11434', 'SGLang server port', true),
    ('llm', 'SGLANG_MEM_FRACTION', '0.90', 'float', '0.90', 'GPU memory fraction for SGLang', true),
    ('features', 'EMBEDDINGS_CPU_ONLY', 'true', 'bool', 'true', 'Force embedding model to CPU (client box has no GPU)', false)
ON CONFLICT (key) DO UPDATE SET
    value = EXCLUDED.value,
    description = EXCLUDED.description;
