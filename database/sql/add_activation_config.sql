-- Progressive activation thresholds in system_config
INSERT INTO system_config (category, key, value, value_type, default_value)
VALUES
    ('activation', 'FACT_THRESHOLD', '1', 'int', '1'),
    ('activation', 'MEMORY_THRESHOLD', '5', 'int', '5'),
    ('activation', 'TRAIT_THRESHOLD', '1', 'int', '1'),
    ('activation', 'SEMANTIC_THRESHOLD', '1', 'int', '1'),
    ('activation', 'DREAM_THRESHOLD', '1', 'int', '1'),
    ('activation', 'PROGRESSIVE_ACTIVATION_ENABLED', 'true', 'bool', 'true')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
