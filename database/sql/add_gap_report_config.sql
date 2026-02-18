-- Gap Report configuration keys
-- Controls the "while you were away" feature

INSERT INTO system_config (category, key, value, value_type, default_value, description)
VALUES
    ('gap_report', 'GAP_REPORT_ENABLED', 'true', 'bool', 'true', 'Enable the while-you-were-away gap report on first turn after absence'),
    ('gap_report', 'GAP_REPORT_MIN_GAP_MINUTES', '30', 'int', '30', 'Minimum gap in minutes before generating a gap report')
ON CONFLICT (key) DO UPDATE SET
    value = EXCLUDED.value,
    value_type = EXCLUDED.value_type,
    description = EXCLUDED.description;
