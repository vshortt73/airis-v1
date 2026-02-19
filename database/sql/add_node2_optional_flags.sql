-- Add Node2 optional feature flags
-- Airis: All Node2 features disabled by default (no local GPU assumed)
-- Facility operators can enable as needed

-- Master toggle
INSERT INTO system_config (category, key, value, value_type, default_value, description, requires_restart)
VALUES
('features', 'NODE2_ENABLED', 'false', 'bool', 'false',
 'Master toggle for Node2 GPU server. When false, all Node2-dependent services are disabled.', true)
ON CONFLICT (key) DO UPDATE SET description = EXCLUDED.description, last_modified = NOW();

-- Per-service flags for Node2 services
INSERT INTO system_config (category, key, value, value_type, default_value, description, requires_restart)
VALUES
('features', 'STT_ENABLED', 'false', 'bool', 'false',
 'Enable speech-to-text (Whisper on Node2). Requires NODE2_ENABLED.', false),
('features', 'TTS_ENABLED', 'false', 'bool', 'false',
 'Enable text-to-speech (XTTS on Node2). Requires NODE2_ENABLED.', false),
('features', 'VIDEO_ENABLED', 'false', 'bool', 'false',
 'Enable FLOAT video generation (Node2 GPU 0). Requires NODE2_ENABLED.', false),
('features', 'GPU_MANAGER_ENABLED', 'false', 'bool', 'false',
 'Enable Node2 GPU manager for service coordination. Requires NODE2_ENABLED.', false),
('features', 'FLORENCE2_ENABLED', 'false', 'bool', 'false',
 'Enable Florence2 vision model (Node2). Requires NODE2_ENABLED.', false),
('features', 'PADDLEOCR_ENABLED', 'false', 'bool', 'false',
 'Enable PaddleOCR service (Node2). Requires NODE2_ENABLED.', false),
('features', 'DREAMS_ENABLED', 'false', 'bool', 'false',
 'Enable dream processing (Freud on Node2). Requires NODE2_ENABLED.', false)
ON CONFLICT (key) DO UPDATE SET description = EXCLUDED.description, last_modified = NOW();

-- Verify
SELECT key, value, description FROM system_config WHERE key IN (
    'NODE2_ENABLED', 'STT_ENABLED', 'TTS_ENABLED', 'VIDEO_ENABLED',
    'GPU_MANAGER_ENABLED', 'FLORENCE2_ENABLED', 'PADDLEOCR_ENABLED', 'DREAMS_ENABLED'
) ORDER BY key;
