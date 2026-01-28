-- Batch Trim KV Cache Optimization
-- Reuses conversation snapshot for N turns to maximize Ollama KV cache hits
-- Instead of reloading from DB every turn (invalidating cache), keeps a frozen prefix

INSERT INTO system_config (category, key, value, value_type, default_value, description, requires_restart) VALUES
('context', 'BATCH_TRIM_ENABLED', 'true', 'bool', 'true', 'Enable batch trim KV cache optimization', false),
('context', 'BATCH_TRIM_SIZE', '5', 'int', '5', 'User turns between DB reloads (higher = more cache hits)', false),
('context', 'BATCH_TRIM_HEADROOM_TOKENS', '4000', 'int', '4000', 'Token budget reserved in snapshot for message growth', false)
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, description = EXCLUDED.description;
