-- Add webcam_recognize tool to mcp_tools table
-- This tool captures from webcam and recognizes faces

INSERT INTO mcp_tools (tool_name, description, input_schema, icon, server_name, enabled)
VALUES (
    'webcam_recognize',
    'Capture image from webcam and recognize faces. Returns list of recognized people with confidence scores and any unknown faces detected.',
    '{
        "type": "object",
        "properties": {
            "camera_id": {
                "type": "integer",
                "description": "Camera device ID (default: 0 for built-in webcam)",
                "default": 0
            },
            "similarity_threshold": {
                "type": "number",
                "description": "Minimum similarity threshold for recognition (0.0-1.0, default: 0.5)",
                "minimum": 0.0,
                "maximum": 1.0
            }
        },
        "required": []
    }'::jsonb,
    '📷',
    'info',
    true
)
ON CONFLICT (tool_name) DO UPDATE
SET
    description = EXCLUDED.description,
    input_schema = EXCLUDED.input_schema,
    icon = EXCLUDED.icon,
    server_name = EXCLUDED.server_name,
    enabled = EXCLUDED.enabled;
