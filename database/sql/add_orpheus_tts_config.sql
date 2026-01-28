-- Add Orpheus TTS configuration to system_config
-- Run with: psql -h localhost -U irisuser -d irisdb -f database/sql/add_orpheus_tts_config.sql

-- Orpheus TTS Server URL
INSERT INTO system_config (category, key, value, value_type, default_value, description)
VALUES ('remote_services', 'ORPHEUS_SERVER_URL', 'http://node2:8701', 'string', 'http://node2:8701', 'Orpheus TTS server URL')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, description = EXCLUDED.description;

-- Default voice for Orpheus
INSERT INTO system_config (category, key, value, value_type, default_value, description)
VALUES ('tts', 'ORPHEUS_VOICE', 'mia', 'string', 'mia', 'Default Orpheus voice (mia, tara, leah, jess, leo, dan, zac, zoe)')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, description = EXCLUDED.description;

-- TTS Backend selection: 'orpheus' or 'xtts'
INSERT INTO system_config (category, key, value, value_type, default_value, description)
VALUES ('tts', 'TTS_BACKEND', 'orpheus', 'string', 'orpheus', 'TTS backend: orpheus (emotion support) or xtts (fallback)')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, description = EXCLUDED.description;

-- Verify
SELECT category, key, value, description
FROM system_config
WHERE key IN ('ORPHEUS_SERVER_URL', 'ORPHEUS_VOICE', 'TTS_BACKEND')
ORDER BY category, key;
