-- Add Node2 optional feature flags
-- Allows running Iris without Node2 by setting NODE2_ENABLED=false
-- Run: psql -h localhost -U irisuser -d irisdb -f database/sql/add_node2_optional_flags.sql

-- Master toggle
INSERT INTO system_config (category, key, value, value_type, default_value, description, requires_restart)
VALUES
('features', 'NODE2_ENABLED', 'true', 'bool', 'true',
 'Master toggle for Node2 GPU server. When false, all Node2-dependent services are disabled.', true)
ON CONFLICT (key) DO UPDATE SET description = EXCLUDED.description, last_modified = NOW();

-- Per-service flags for previously ungated Node2 services
INSERT INTO system_config (category, key, value, value_type, default_value, description, requires_restart)
VALUES
('features', 'STT_ENABLED', 'true', 'bool', 'true',
 'Enable speech-to-text (Whisper on Node2). Requires NODE2_ENABLED.', false),
('features', 'TTS_ENABLED', 'true', 'bool', 'true',
 'Enable text-to-speech (XTTS on Node2). Requires NODE2_ENABLED.', false),
('features', 'VIDEO_ENABLED', 'true', 'bool', 'true',
 'Enable FLOAT video generation (Node2 GPU 0). Requires NODE2_ENABLED.', false),
('features', 'GPU_MANAGER_ENABLED', 'true', 'bool', 'true',
 'Enable Node2 GPU manager for service coordination. Requires NODE2_ENABLED.', false),
('features', 'FLORENCE2_ENABLED', 'true', 'bool', 'true',
 'Enable Florence2 vision model (Node2). Requires NODE2_ENABLED.', false),
('features', 'PADDLEOCR_ENABLED', 'true', 'bool', 'true',
 'Enable PaddleOCR service (Node2). Requires NODE2_ENABLED.', false),
('features', 'DREAMS_ENABLED', 'true', 'bool', 'true',
 'Enable dream processing (Freud on Node2). Requires NODE2_ENABLED.', false)
ON CONFLICT (key) DO UPDATE SET description = EXCLUDED.description, last_modified = NOW();

-- Verify
SELECT key, value, description FROM system_config WHERE key IN (
    'NODE2_ENABLED', 'STT_ENABLED', 'TTS_ENABLED', 'VIDEO_ENABLED',
    'GPU_MANAGER_ENABLED', 'FLORENCE2_ENABLED', 'PADDLEOCR_ENABLED', 'DREAMS_ENABLED'
) ORDER BY key;
