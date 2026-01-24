-- System Configuration Table
-- Stores all runtime configuration in database for persistence and easy management

CREATE TABLE IF NOT EXISTS system_config (
    config_id SERIAL PRIMARY KEY,
    category VARCHAR(50) NOT NULL,           -- Group: face_monitoring, tokens, session, etc.
    key VARCHAR(100) NOT NULL UNIQUE,        -- Config key (e.g., FACE_GREETING_COOLDOWN_MINUTES)
    value TEXT NOT NULL,                     -- String representation of value
    value_type VARCHAR(20) NOT NULL,         -- Type: int, float, bool, string, json
    default_value TEXT NOT NULL,             -- Default value if not set
    description TEXT,                        -- Human-readable description
    requires_restart BOOLEAN DEFAULT FALSE,  -- Whether changing this requires server restart
    last_modified TIMESTAMP DEFAULT NOW(),
    modified_by VARCHAR(100) DEFAULT 'system'
);

-- Create index on category for faster filtering
CREATE INDEX IF NOT EXISTS idx_system_config_category ON system_config(category);

-- Create index on key for faster lookups
CREATE INDEX IF NOT EXISTS idx_system_config_key ON system_config(key);

-- Audit table for configuration changes
CREATE TABLE IF NOT EXISTS system_config_history (
    history_id SERIAL PRIMARY KEY,
    config_id INTEGER REFERENCES system_config(config_id),
    key VARCHAR(100) NOT NULL,
    old_value TEXT,
    new_value TEXT,
    changed_at TIMESTAMP DEFAULT NOW(),
    changed_by VARCHAR(100) DEFAULT 'system',
    reason TEXT
);

-- Trigger to log configuration changes
CREATE OR REPLACE FUNCTION log_config_change()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO system_config_history (config_id, key, old_value, new_value, changed_by)
    VALUES (NEW.config_id, NEW.key, OLD.value, NEW.value, NEW.modified_by);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_log_config_change
    AFTER UPDATE ON system_config
    FOR EACH ROW
    WHEN (OLD.value IS DISTINCT FROM NEW.value)
    EXECUTE FUNCTION log_config_change();

COMMENT ON TABLE system_config IS 'Runtime configuration stored in database for persistence and hot-reload';
COMMENT ON TABLE system_config_history IS 'Audit log of all configuration changes';
