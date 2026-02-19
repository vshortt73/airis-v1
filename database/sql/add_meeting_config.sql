-- Meeting transcription configuration entries in system_config

INSERT INTO system_config (category, key, value, value_type, default_value, description, requires_restart) VALUES
('features', 'TRANSCRIBE_ENABLED', 'false', 'bool', 'false', 'Enable meeting transcription (requires Node2 WhisperX service)', true),
('remote_services', 'TRANSCRIBE_SERVER_URL', 'http://node2:8500', 'string', 'http://node2:8500', 'WhisperX transcription service URL on Node2', true),
('meeting', 'MEETING_WHISPERX_MODEL', 'large-v3', 'string', 'large-v3', 'WhisperX model size for transcription', true),
('meeting', 'MEETING_CHUNK_DURATION_SECONDS', '300', 'int', '300', 'Audio chunk duration in seconds (5 minutes)', false),
('meeting', 'MEETING_AUDIO_PATH', 'attachments/meetings', 'string', 'attachments/meetings', 'Base path for meeting audio storage', true)
ON CONFLICT (key) DO UPDATE SET
    value = EXCLUDED.value,
    description = EXCLUDED.description,
    last_modified = NOW();
