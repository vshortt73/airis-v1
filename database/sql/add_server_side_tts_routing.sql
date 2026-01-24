-- Add SERVER_SIDE_TTS_ROUTING configuration to system_config
-- This enables server-side sentence extraction and TTS/video routing

INSERT INTO system_config (category, key, value, value_type, default_value, description, requires_restart) VALUES
('features', 'SERVER_SIDE_TTS_ROUTING', 'false', 'bool', 'false', 'When enabled, server handles sentence extraction and routes directly to XTTS/FLOAT instead of round-tripping through the browser. Reduces latency and simplifies browser code.', false)
ON CONFLICT (key) DO UPDATE SET
    value = EXCLUDED.value,
    description = EXCLUDED.description,
    last_modified = NOW();

-- Verify
SELECT category, key, value, description FROM system_config WHERE key = 'SERVER_SIDE_TTS_ROUTING';
