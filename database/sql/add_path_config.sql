-- ============================================================================
-- ADD FILE PATH CONFIGURATION KEYS (Airis Client Box)
-- ============================================================================
-- Client box paths only. No inference, no Node2, no GPU model paths.
-- ============================================================================

INSERT INTO system_config (category, key, value, value_type, default_value, description, requires_restart) VALUES
('paths', 'PROJECT_ROOT', '/airis-v1', 'string', '/airis-v1', 'Project installation directory', true),
('paths', 'VENV_PATH', '/venv/iris-v3', 'string', '/venv/iris-v3', 'Python virtual environment path', true),
('paths', 'EMBEDDING_MODEL_PATH', '/models/llm_models/huggingface/models/all-mpnet-base-v2/', 'string', '/models/llm_models/huggingface/models/all-mpnet-base-v2/', 'Sentence transformer embedding model', true),
('paths', 'SSL_CERT_PATH', '/airis-v1/ssl/cert.pem', 'string', '/airis-v1/ssl/cert.pem', 'SSL certificate for HTTPS (if used)', true)
ON CONFLICT (key) DO UPDATE SET
    value = EXCLUDED.value,
    description = EXCLUDED.description,
    last_modified = NOW();

-- Verify
SELECT category, key, value FROM system_config WHERE category = 'paths' ORDER BY key;
