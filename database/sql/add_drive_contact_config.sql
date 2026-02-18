-- Add Phase 4 drive contact configuration to system_config
-- These control the autonomous contact system (Telegram + desktop notify).
-- All are hot-reloadable (requires_restart = false) — daemon picks up changes every ~5 minutes.

INSERT INTO system_config (category, key, value, value_type, default_value, description, requires_restart)
VALUES
    ('drive', 'DRIVE_CONTACT_ENABLED', 'false', 'bool', 'false',
     'Master switch for contact_victor action. Must explicitly opt in.', false),

    ('drive', 'DRIVE_CONTACT_COOLDOWN_SECONDS', '3600', 'int', '3600',
     'Minimum seconds between contact attempts (default 1 hour). Separate from wake cooldown.', false),

    ('drive', 'DRIVE_CONTACT_MAX_PER_DAY', '3', 'int', '3',
     'Maximum contact messages per calendar day. Hard limit queried from drive_wake_log.', false),

    ('drive', 'DRIVE_TELEGRAM_BOT_TOKEN', '', 'string', '',
     'Telegram bot API token (from @BotFather). Required for contact delivery.', false),

    ('drive', 'DRIVE_TELEGRAM_CHAT_ID', '', 'string', '',
     'Victor''s Telegram chat ID. Required for contact delivery.', false),

    ('drive', 'DRIVE_CONTACT_DESKTOP_NOTIFY', 'true', 'bool', 'true',
     'Fire libnotify desktop notification on contact events.', false)

ON CONFLICT (key) DO UPDATE SET
    value = EXCLUDED.value,
    default_value = EXCLUDED.default_value,
    description = EXCLUDED.description,
    requires_restart = EXCLUDED.requires_restart,
    last_modified = NOW();
