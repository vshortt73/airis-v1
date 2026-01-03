-- Insert short-term memory tools into mcp_tools table
-- These tools enable the middle-tier memory system

-- Tool 1: short_term_memory_insert
INSERT INTO mcp_tools (
    tool_name,
    description,
    input_schema,
    enabled,
    priority,
    icon,
    custom_instructions
) VALUES (
    'short_term_memory_insert',
    'Store a short-term fact for future reference. Use when Victor says "Remember this:", "Make a note:", "Don''t forget:", or "For future reference:"',
    '{
        "type": "object",
        "properties": {
            "fact": {
                "type": "string",
                "description": "Single sentence factual statement to remember"
            },
            "category": {
                "type": "string",
                "description": "Optional category: ongoing_project, user_preference, discovery, user_status, or other"
            },
            "conversation_id": {
                "type": "string",
                "description": "Optional conversation/session ID for traceability"
            }
        },
        "required": ["fact"]
    }'::jsonb,
    true,
    100,
    '🧠',
    'Extract the fact from user''s statement (everything after the trigger phrase). This tool should be called autonomously when Victor uses memory trigger phrases.'
) ON CONFLICT (tool_name) DO UPDATE SET
    description = EXCLUDED.description,
    input_schema = EXCLUDED.input_schema,
    enabled = EXCLUDED.enabled,
    priority = EXCLUDED.priority,
    icon = EXCLUDED.icon,
    custom_instructions = EXCLUDED.custom_instructions;

-- Tool 2: short_term_memory_retrieve
INSERT INTO mcp_tools (
    tool_name,
    description,
    input_schema,
    enabled,
    priority,
    icon,
    custom_instructions
) VALUES (
    'short_term_memory_retrieve',
    'Retrieve active short-term facts for context. Returns recent facts that are still relevant.',
    '{
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Maximum number of facts to retrieve (default: 20)"
            }
        },
        "required": []
    }'::jsonb,
    true,
    101,
    '💭',
    'This tool is typically called at conversation start or when context requires recent facts. Retrieved facts are automatically marked as referenced.'
) ON CONFLICT (tool_name) DO UPDATE SET
    description = EXCLUDED.description,
    input_schema = EXCLUDED.input_schema,
    enabled = EXCLUDED.enabled,
    priority = EXCLUDED.priority,
    icon = EXCLUDED.icon,
    custom_instructions = EXCLUDED.custom_instructions;

-- Tool 3: short_term_memory_archive_old
INSERT INTO mcp_tools (
    tool_name,
    description,
    input_schema,
    enabled,
    priority,
    icon,
    custom_instructions
) VALUES (
    'short_term_memory_archive_old',
    'Archive old, unreferenced facts. Facts created >90 days ago and not referenced in 30 days are archived but NOT deleted.',
    '{
        "type": "object",
        "properties": {},
        "required": []
    }'::jsonb,
    true,
    102,
    '📦',
    'This tool is typically run as part of maintenance/cleanup. Archived facts remain in database for training data analysis.'
) ON CONFLICT (tool_name) DO UPDATE SET
    description = EXCLUDED.description,
    input_schema = EXCLUDED.input_schema,
    enabled = EXCLUDED.enabled,
    priority = EXCLUDED.priority,
    icon = EXCLUDED.icon,
    custom_instructions = EXCLUDED.custom_instructions;

-- Verify insertion
SELECT tool_name, enabled, priority, icon
FROM mcp_tools
WHERE tool_name LIKE 'short_term_memory%'
ORDER BY priority;
