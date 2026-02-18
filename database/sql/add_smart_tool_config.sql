-- Smart Tool Selection feature flag
-- When enabled, only sends relevant tool groups to the LLM based on recent conversation context.
-- Reduces tool definition tokens by ~60-80% on typical turns.
-- Tool selection is aligned to the batch trim snapshot lifecycle for KV cache compatibility.

INSERT INTO system_config (category, key, value, value_type, default_value, description, requires_restart)
VALUES ('tools', 'SMART_TOOL_SELECTION', 'true', 'bool', 'false',
        'Enable smart tool selection — only include relevant tool groups per snapshot window', true)
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, description = EXCLUDED.description;
