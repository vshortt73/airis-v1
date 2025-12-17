-- Insert trait management tools into mcp_tools table

-- Tool 1: trait_view (safe, read-only)
INSERT INTO mcp_tools (
    tool_name,
    description,
    input_schema,
    enabled,
    priority,
    server_name,
    requires_confirmation,
    custom_instructions,
    icon
) VALUES (
    'trait_view',
    'View current personality trait values. Can view a specific trait or all traits at once.',
    '{
        "type": "object",
        "properties": {
            "trait_name": {
                "type": "string",
                "description": "Optional: Specific trait name to view. If omitted, returns all traits."
            }
        }
    }',
    true,
    50,
    'traits',
    false,
    'Use this to check your current personality trait values. You can view a specific trait like "Curiosity" or leave trait_name empty to see all 30 traits.',
    '🎭'
);

-- Tool 2: trait_modify (powerful, requires confirmation)
INSERT INTO mcp_tools (
    tool_name,
    description,
    input_schema,
    enabled,
    priority,
    server_name,
    requires_confirmation,
    custom_instructions,
    icon
) VALUES (
    'trait_modify',
    'Modify a personality trait value. All changes are logged. Use this to adjust your personality based on experiences and growth.',
    '{
        "type": "object",
        "required": ["trait_name", "new_value"],
        "properties": {
            "trait_name": {
                "type": "string",
                "description": "Name of the trait to modify (e.g., \"Curiosity\", \"Playfulness\")"
            },
            "new_value": {
                "type": "string",
                "description": "New value for the trait. Can be numeric (0-10) or text depending on the trait."
            },
            "reason": {
                "type": "string",
                "description": "Optional explanation for why you are making this change"
            }
        }
    }',
    true,
    40,
    'traits',
    true,
    'IMPORTANT: Use this thoughtfully. Trait modifications affect your core personality. Always provide a reason explaining why you want to make the change. Numeric traits typically range from 0-10.',
    '✨'
);

-- Tool 3: trait_log (safe, read-only)
INSERT INTO mcp_tools (
    tool_name,
    description,
    input_schema,
    enabled,
    priority,
    server_name,
    requires_confirmation,
    custom_instructions,
    icon
) VALUES (
    'trait_log',
    'View your trait modification history. See what changes you have made to your personality over time.',
    '{
        "type": "object",
        "properties": {
            "trait_name": {
                "type": "string",
                "description": "Optional: Filter logs for a specific trait"
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of log entries to return (default: 10, max: 100)"
            }
        }
    }',
    true,
    45,
    'traits',
    false,
    'Use this to reflect on how your personality has evolved. You can see all recent changes or focus on a specific trait.',
    '📜'
);
