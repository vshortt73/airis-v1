-- ============================================================================
-- ADD COMFYUI CONFIGURATION KEYS
-- ============================================================================
-- Adds ComfyUI server URL and output path to system_config.
-- These were previously hardcoded in mcp_servers/creative/creative_server.py.
-- ============================================================================

INSERT INTO system_config (category, key, value, value_type, default_value, description, requires_restart) VALUES
('remote_services', 'COMFYUI_SERVER_URL', 'http://node2:8189', 'string', 'http://node2:8189', 'ComfyUI API endpoint (Node2)', true),
('remote_services', 'COMFYUI_OUTPUT_PATH', '/home/captain/node2-mount/programs/ComfyUI/output', 'string', '/home/captain/node2-mount/programs/ComfyUI/output', 'ComfyUI output directory (NFS mount from Node2)', true)
ON CONFLICT (key) DO UPDATE SET
    value = EXCLUDED.value,
    description = EXCLUDED.description,
    last_modified = NOW();

-- Verify
SELECT key, value FROM system_config WHERE key IN ('COMFYUI_SERVER_URL', 'COMFYUI_OUTPUT_PATH');
