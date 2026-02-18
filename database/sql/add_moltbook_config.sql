-- Moltbook configuration for system_config table
-- Run: psql -h localhost -U irisuser -d irisdb -f database/sql/add_moltbook_config.sql

INSERT INTO system_config (category, key, value, value_type, default_value, description, requires_restart)
VALUES
    ('moltbook', 'MOLTBOOK_API_KEY', '', 'string', '', 'Moltbook API key (Bearer token). Get from registration or moltbook.com dashboard.', true),
    ('moltbook', 'MOLTBOOK_BASE_URL', 'https://www.moltbook.com/api/v1', 'string', 'https://www.moltbook.com/api/v1', 'Moltbook API base URL. Always use www subdomain.', false)
ON CONFLICT (key) DO UPDATE SET
    category = EXCLUDED.category,
    description = EXCLUDED.description,
    default_value = EXCLUDED.default_value,
    value_type = EXCLUDED.value_type;
