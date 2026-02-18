-- ============================================================================
-- ADD FILE PATH CONFIGURATION KEYS
-- ============================================================================
-- Centralizes all hardcoded file paths into system_config.
-- Python files use config.X, shell scripts use scripts/paths.env.
-- ============================================================================

-- Localhost paths (consumed by Python code)
INSERT INTO system_config (category, key, value, value_type, default_value, description, requires_restart) VALUES
('paths', 'PROJECT_ROOT', '/iris-v3', 'string', '/iris-v3', 'Project installation directory', true),
('paths', 'VENV_PATH', '/venv/iris-v3', 'string', '/venv/iris-v3', 'Python virtual environment path', true),
('paths', 'LLAMA_SERVER_PATH', '/programs/llama.cpp/build/bin/llama-server', 'string', '/programs/llama.cpp/build/bin/llama-server', 'llama.cpp server binary (localhost)', true),
('paths', 'EMBEDDING_MODEL_PATH', '/models/llm_models/huggingface/models/all-mpnet-base-v2/', 'string', '/models/llm_models/huggingface/models/all-mpnet-base-v2/', 'Sentence transformer embedding model', true),
('paths', 'HF_CACHE_DIR', '/home/captain/.cache/huggingface/hub', 'string', '/home/captain/.cache/huggingface/hub', 'HuggingFace model cache directory', true),
('paths', 'EMOTION_MODEL_PATH', '/models/Memory-models/emotion_model_balanced', 'string', '/models/Memory-models/emotion_model_balanced', 'Emotion classification model directory', true),
('paths', 'VALENCE_MODEL_PATH', '/models/Memory-models/valence_model', 'string', '/models/Memory-models/valence_model', 'Valence regression model directory', true),
('paths', 'AROUSAL_MODEL_PATH', '/models/Memory-models/arousal_model', 'string', '/models/Memory-models/arousal_model', 'Arousal regression model directory', true),
('paths', 'RHUBARB_PATH', '/home/captain/bin/rhubarb', 'string', '/home/captain/bin/rhubarb', 'Rhubarb lip-sync binary', true),
('paths', 'SSL_CERT_PATH', '/iris-v3/ssl/cert.pem', 'string', '/iris-v3/ssl/cert.pem', 'SSL certificate for HTTPS', true),
('paths', 'FLORENCE2_MODEL_PATH', '/models/vision/florence2', 'string', '/models/vision/florence2', 'Florence2 vision model directory', true),
('paths', 'MAIN_MODEL_GGUF', '/localmodels/qwen/Qwen3-32B-Q4_K_M.gguf', 'string', '/localmodels/qwen/Qwen3-32B-Q4_K_M.gguf', 'Primary LLM model file (localhost GPU 0)', true),
('paths', 'ALT_MODEL_GGUF', '/models/llm_models/qwen/Qwen3-30B-A3B-abliterated-erotic.Q5_K_M.gguf', 'string', '/models/llm_models/qwen/Qwen3-30B-A3B-abliterated-erotic.Q5_K_M.gguf', 'Alternative LLM model file (localhost GPU 0)', true)
ON CONFLICT (key) DO UPDATE SET
    value = EXCLUDED.value,
    description = EXCLUDED.description,
    last_modified = NOW();

-- Node2 paths (reference only — for admin UI visibility, not consumed by Node2 services)
INSERT INTO system_config (category, key, value, value_type, default_value, description, requires_restart) VALUES
('node2_paths', 'FREUD_MODEL_GGUF', '/models/llm_models/gemma/gemma-3-4b-it-Q5_K_M.gguf', 'string', '/models/llm_models/gemma/gemma-3-4b-it-Q5_K_M.gguf', 'Freud dream model (Node2 GPU 0)', false),
('node2_paths', 'VISION_MODEL_GGUF', '/models/vision/pixtral/pixtral-12b-Q4_K_M.gguf', 'string', '/models/vision/pixtral/pixtral-12b-Q4_K_M.gguf', 'Vision model (Node2 GPU 0)', false),
('node2_paths', 'SENTIMENT_MODEL_GGUF', '/models/llm_models/mistral/mistral-7b-instruct-v0.3-q4_k_m.gguf', 'string', '/models/llm_models/mistral/mistral-7b-instruct-v0.3-q4_k_m.gguf', 'Sentiment model (Node2 GPU 1)', false)
ON CONFLICT (key) DO UPDATE SET
    value = EXCLUDED.value,
    description = EXCLUDED.description,
    last_modified = NOW();

-- Verify
SELECT category, key, value FROM system_config WHERE category IN ('paths', 'node2_paths') ORDER BY category, key;
