-- Calendar Events Table
-- Stores calendar events with optional Google Calendar sync support

CREATE TABLE IF NOT EXISTS calendar_events (
    id SERIAL PRIMARY KEY,
    title VARCHAR(500) NOT NULL,
    description TEXT,
    location VARCHAR(500),

    -- Timing
    start_time TIMESTAMP WITH TIME ZONE NOT NULL,
    end_time TIMESTAMP WITH TIME ZONE,
    all_day BOOLEAN DEFAULT false,

    -- Reminders
    reminder_enabled BOOLEAN DEFAULT true,
    reminder_hours_before FLOAT DEFAULT 4.0,
    reminder_dismissed BOOLEAN DEFAULT false,

    -- Google Calendar sync (Phase 2)
    google_event_id VARCHAR(255),
    google_calendar_id VARCHAR(255),
    google_sync_status VARCHAR(50) DEFAULT 'local_only',  -- local_only, synced, pending_push, pending_pull
    google_last_synced TIMESTAMP WITH TIME ZONE,
    google_etag VARCHAR(255),

    -- Classification
    category VARCHAR(50) DEFAULT 'personal',  -- appointment, meeting, personal, reminder, deadline
    status VARCHAR(50) DEFAULT 'active',       -- active, cancelled, completed
    source VARCHAR(50) DEFAULT 'conversation', -- conversation, google_sync, manual

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Index for querying upcoming events by start time
CREATE INDEX IF NOT EXISTS idx_calendar_events_start_time
    ON calendar_events (start_time);

-- Index for reminder lookup: enabled + active + not dismissed
CREATE INDEX IF NOT EXISTS idx_calendar_events_reminders
    ON calendar_events (start_time)
    WHERE reminder_enabled = true AND status = 'active' AND reminder_dismissed = false;

-- Index for Google Calendar sync lookups
CREATE INDEX IF NOT EXISTS idx_calendar_events_google_id
    ON calendar_events (google_event_id)
    WHERE google_event_id IS NOT NULL;

-- Auto-update updated_at on modification
CREATE OR REPLACE FUNCTION update_calendar_events_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_calendar_events_updated_at ON calendar_events;
CREATE TRIGGER trg_calendar_events_updated_at
    BEFORE UPDATE ON calendar_events
    FOR EACH ROW
    EXECUTE FUNCTION update_calendar_events_updated_at();
