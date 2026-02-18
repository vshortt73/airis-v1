-- Calendar configuration entries in system_config

INSERT INTO system_config (category, key, value, value_type, default_value, description, requires_restart) VALUES
('calendar', 'CALENDAR_ENABLED', 'true', 'bool', 'false', 'Enable calendar tool and reminder injection', true),
('calendar', 'CALENDAR_REMINDER_WINDOW_HOURS', '6', 'int', '6', 'Hours ahead to look for upcoming reminders in system prompt', true),
('calendar', 'CALENDAR_REMINDER_DEFAULT_HOURS_BEFORE', '4', 'float', '4', 'Default hours before event to start showing reminder', true),
('calendar', 'CALENDAR_TIMEZONE', 'America/New_York', 'string', 'America/New_York', 'Default timezone for display and naive datetime parsing', true),
('calendar', 'CALENDAR_GOOGLE_SYNC_ENABLED', 'false', 'bool', 'false', 'Enable Google Calendar sync (Phase 2)', true),
('calendar', 'CALENDAR_GOOGLE_CREDENTIALS_PATH', '', 'string', '', 'Path to Google Calendar OAuth credentials JSON', true),
('calendar', 'CALENDAR_GOOGLE_SYNC_INTERVAL_MINUTES', '15', 'int', '15', 'How often to sync with Google Calendar', true)
ON CONFLICT (key) DO UPDATE SET
    value = EXCLUDED.value,
    description = EXCLUDED.description,
    last_modified = NOW();
