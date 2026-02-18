-- Add drive daemon configuration to system_config
-- These control the autonomous inner drive system's wake behavior and thresholds.
-- All are hot-reloadable (requires_restart = false) — daemon picks up changes every ~5 minutes.

INSERT INTO system_config (category, key, value, value_type, default_value, description, requires_restart)
VALUES
    ('drive', 'DRIVE_WAKE_ENABLED', 'true', 'bool', 'true',
     'Master kill switch for wake system. Thresholds still checked, just no wake fired.', false),

    ('drive', 'DRIVE_WAKE_COOLDOWN_SECONDS', '1800', 'int', '1800',
     'Minimum seconds between wake events (default 30 minutes).', false),

    ('drive', 'DRIVE_QUIET_HOURS_START', '1', 'int', '1',
     'Quiet hours start (0-23, local time). Non-urgent wakes suppressed.', false),

    ('drive', 'DRIVE_QUIET_HOURS_END', '6', 'int', '6',
     'Quiet hours end (0-23, local time). Non-urgent wakes suppressed.', false),

    ('drive', 'DRIVE_THRESHOLD_CONNECTION', '0.7', 'float', '0.7',
     'connection_need threshold for wake trigger.', false),

    ('drive', 'DRIVE_THRESHOLD_CURIOSITY', '0.6', 'float', '0.6',
     'curiosity threshold for wake trigger.', false),

    ('drive', 'DRIVE_THRESHOLD_UNFINISHED', '0.65', 'float', '0.65',
     'unfinished_business threshold for wake trigger.', false),

    ('drive', 'DRIVE_THRESHOLD_RESTLESSNESS', '0.8', 'float', '0.8',
     'restlessness threshold for wake trigger.', false),

    ('drive', 'DRIVE_THRESHOLD_CONCERN', '0.5', 'float', '0.5',
     'concern threshold for wake trigger.', false),

    ('drive', 'DRIVE_THRESHOLD_CREATIVE', '0.7', 'float', '0.7',
     'creative_pressure threshold for wake trigger.', false),

    ('drive', 'DRIVE_THRESHOLD_REFLECTION', '0.6', 'float', '0.6',
     'reflection_need threshold for wake trigger.', false)

ON CONFLICT (key) DO UPDATE SET
    value = EXCLUDED.value,
    default_value = EXCLUDED.default_value,
    description = EXCLUDED.description,
    requires_restart = EXCLUDED.requires_restart,
    last_modified = NOW();
