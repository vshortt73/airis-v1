-- Ship Directions MCP Tool Definitions
-- Inserts tool definitions into mcp_tools table for MCP server registration
-- Author: Claude Code
-- Date: 2026-01-19

-- ============================================
-- TOOL: get_ship_directions
-- Get walking directions between ship locations
-- ============================================

INSERT INTO mcp_tools (tool_name, description, input_schema, icon, enabled, priority, custom_instructions)
VALUES (
    'get_ship_directions',
    'Get walking directions between two locations on the cruise ship. Accepts natural language location names like "carousel", "deck 6 carousel", "zip line", "starbucks", "main dining room deck 3". Returns step-by-step human-readable directions including staircase usage.',
    '{
        "type": "object",
        "properties": {
            "start": {
                "type": "string",
                "description": "Starting location (e.g., \"carousel\", \"deck 6 carousel\", \"starbucks\", \"main dining room deck 3\")"
            },
            "end": {
                "type": "string",
                "description": "Destination location (e.g., \"zip line\", \"windjammer\", \"casino royale\", \"vitality spa\")"
            }
        },
        "required": ["start", "end"]
    }',
    '🧭',
    true,
    10,
    'Use this tool when asked for directions between locations on the ship. The ship is Royal Caribbean Oasis of the Seas. Provide the directions in a helpful, friendly manner.'
) ON CONFLICT (tool_name) DO UPDATE SET
    description = EXCLUDED.description,
    input_schema = EXCLUDED.input_schema,
    icon = EXCLUDED.icon,
    enabled = EXCLUDED.enabled,
    priority = EXCLUDED.priority,
    custom_instructions = EXCLUDED.custom_instructions;

-- ============================================
-- TOOL: list_ship_locations
-- List available locations on the ship
-- ============================================

INSERT INTO mcp_tools (tool_name, description, input_schema, icon, enabled, priority, custom_instructions)
VALUES (
    'list_ship_locations',
    'List available locations on the cruise ship, optionally filtered by deck. Use to help find valid location names for navigation or to show what amenities are on a specific deck.',
    '{
        "type": "object",
        "properties": {
            "deck": {
                "type": "integer",
                "description": "Optional deck number to filter by (e.g., 6, 16, 5). If not specified, returns all locations.",
                "minimum": 1,
                "maximum": 18
            }
        },
        "required": []
    }',
    '🗺️',
    true,
    20,
    'Use this tool to help users find location names on the ship or to list amenities by deck. The ship is Royal Caribbean Oasis of the Seas.'
) ON CONFLICT (tool_name) DO UPDATE SET
    description = EXCLUDED.description,
    input_schema = EXCLUDED.input_schema,
    icon = EXCLUDED.icon,
    enabled = EXCLUDED.enabled,
    priority = EXCLUDED.priority,
    custom_instructions = EXCLUDED.custom_instructions;

-- ============================================
-- SUCCESS MESSAGE
-- ============================================

DO $$
BEGIN
    RAISE NOTICE '✓ Ship directions tools registered successfully';
    RAISE NOTICE '  - get_ship_directions: Get walking directions between locations';
    RAISE NOTICE '  - list_ship_locations: List available ship locations by deck';
    RAISE NOTICE '  - Server: directions';
    RAISE NOTICE '  - Both tools enabled and ready for use';
END $$;
