-- Meeting Transcription Tables
-- Stores meeting recordings and diarized transcripts from WhisperX

-- ============================================================================
-- MEETING TRANSCRIPTS (master record per meeting)
-- ============================================================================

CREATE TABLE IF NOT EXISTS meeting_transcripts (
    id SERIAL PRIMARY KEY,
    title VARCHAR(500) NOT NULL,
    meeting_type VARCHAR(50) DEFAULT 'conference',  -- conference, teams, phone
    status VARCHAR(50) DEFAULT 'recording',          -- recording, processing, completed, failed

    -- Timing
    started_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    ended_at TIMESTAMP WITH TIME ZONE,
    duration_seconds INTEGER,

    -- Audio
    audio_path TEXT,                    -- Path to stitched audio file
    audio_format VARCHAR(20) DEFAULT 'webm',
    audio_chunks INTEGER DEFAULT 0,    -- Number of uploaded chunks

    -- Processing
    processing_started_at TIMESTAMP WITH TIME ZONE,
    processing_ended_at TIMESTAMP WITH TIME ZONE,
    whisperx_model VARCHAR(100) DEFAULT 'large-v3',

    -- Results
    speaker_count INTEGER,
    calendar_event_id INTEGER REFERENCES calendar_events(id) ON DELETE SET NULL,
    summary TEXT,
    action_items JSONB DEFAULT '[]'::jsonb,
    participant_names JSONB DEFAULT '{}'::jsonb,  -- {"Speaker 0": "Victor", "Speaker 1": "Sarah"}

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Index for listing meetings by date
CREATE INDEX IF NOT EXISTS idx_meeting_transcripts_started_at
    ON meeting_transcripts (started_at DESC);

-- Index for status filtering
CREATE INDEX IF NOT EXISTS idx_meeting_transcripts_status
    ON meeting_transcripts (status);

-- Auto-update updated_at on modification
CREATE OR REPLACE FUNCTION update_meeting_transcripts_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_meeting_transcripts_updated_at ON meeting_transcripts;
CREATE TRIGGER trg_meeting_transcripts_updated_at
    BEFORE UPDATE ON meeting_transcripts
    FOR EACH ROW
    EXECUTE FUNCTION update_meeting_transcripts_updated_at();

-- ============================================================================
-- MEETING SEGMENTS (individual speaker turns)
-- ============================================================================

CREATE TABLE IF NOT EXISTS meeting_segments (
    id SERIAL PRIMARY KEY,
    transcript_id INTEGER NOT NULL REFERENCES meeting_transcripts(id) ON DELETE CASCADE,
    speaker_label VARCHAR(100) NOT NULL,  -- "Speaker 0", "Speaker 1", etc.
    start_time FLOAT NOT NULL,            -- Seconds from start of audio
    end_time FLOAT NOT NULL,              -- Seconds from start of audio
    text TEXT NOT NULL,
    confidence FLOAT,
    words JSONB,                          -- Word-level timestamps from WhisperX
    segment_order INTEGER NOT NULL        -- Order within transcript
);

-- Index for fetching all segments of a transcript in order
CREATE INDEX IF NOT EXISTS idx_meeting_segments_transcript_order
    ON meeting_segments (transcript_id, segment_order);

-- Index for speaker-based queries
CREATE INDEX IF NOT EXISTS idx_meeting_segments_speaker
    ON meeting_segments (transcript_id, speaker_label);
