-- Add repetition penalty config to system_config
-- These control OpenAI-compatible frequency_penalty and presence_penalty
-- sent to llama-server to prevent Iris from repeating the same motifs.

INSERT INTO system_config (category, key, value, value_type, default_value)
VALUES
    ('llm', 'FREQUENCY_PENALTY', '0.4', 'float', '0.0'),
    ('llm', 'PRESENCE_PENALTY', '0.3', 'float', '0.0')
ON CONFLICT (key) DO UPDATE
SET value = EXCLUDED.value,
    category = EXCLUDED.category,
    value_type = EXCLUDED.value_type,
    default_value = EXCLUDED.default_value;
