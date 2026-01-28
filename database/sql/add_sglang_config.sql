-- SGLang inference backend configuration
-- Run: psql -h localhost -U irisuser -d irisdb -f database/sql/add_sglang_config.sql

INSERT INTO system_config (category, key, value, value_type, default_value, description, requires_restart)
VALUES
    ('llm', 'INFERENCE_BACKEND', 'llamacpp', 'string', 'llamacpp', 'Active inference backend: llamacpp or sglang', true),
    ('llm', 'SGLANG_BASE_URL', 'http://localhost:11434', 'string', 'http://localhost:11434', 'SGLang server endpoint', true),
    ('llm', 'SGLANG_MODEL_PATH', '/localmodels/qwen/Qwen3-32B-Q4_K_M.gguf', 'string', '/localmodels/qwen/Qwen3-32B-Q4_K_M.gguf', 'Model file for SGLang server', true),
    ('llm', 'SGLANG_CONTEXT_LENGTH', '40960', 'int', '40960', 'SGLang context window size', true),
    ('llm', 'SGLANG_PORT', '11434', 'int', '11434', 'SGLang server port', true),
    ('llm', 'SGLANG_MEM_FRACTION', '0.95', 'float', '0.95', 'GPU memory fraction for SGLang', true)
ON CONFLICT (key) DO UPDATE SET
    value = EXCLUDED.value,
    description = EXCLUDED.description;
