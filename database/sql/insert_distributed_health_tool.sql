-- Add distributed_system_health tool to mcp_tools
-- This tool gives Iris visibility into both localhost and Node2 GPU/service health

INSERT INTO mcp_tools (
    tool_name,
    description,
    input_schema,
    enabled,
    icon
) VALUES (
    'distributed_system_health',
    'Get comprehensive health status across both localhost and Node2. Returns GPU memory usage per service (with service names like iris-vision.service), service health status, GPU Manager state, and any services in crash loops. Use this to diagnose OOM errors, service failures, or GPU resource conflicts.',
    '{
        "type": "object",
        "properties": {},
        "required": []
    }'::jsonb,
    true,
    'activity'
)
ON CONFLICT (tool_name) DO UPDATE SET
    description = EXCLUDED.description,
    input_schema = EXCLUDED.input_schema,
    enabled = EXCLUDED.enabled,
    icon = EXCLUDED.icon;
