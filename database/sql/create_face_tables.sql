-- ============================================================================
-- Face Recognition System - Database Schema
-- ============================================================================
-- Creates 6 tables for face recognition, person management, camera registry,
-- and presence tracking with pgvector embeddings and HNSW indexes
-- ============================================================================

-- Enable pgvector extension (if not already enabled)
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================================
-- Table 1: face_persons - Known people/identities
-- ============================================================================
CREATE TABLE IF NOT EXISTS face_persons (
    person_id SERIAL PRIMARY KEY,

    -- Identity
    name TEXT NOT NULL UNIQUE,
    display_name TEXT,

    -- Metadata
    notes TEXT,
    relationship TEXT,  -- e.g., "owner", "family", "friend", "colleague"
    tags TEXT[],        -- Flexible tagging: ["family", "authorized", "vip"]

    -- Statistics
    training_image_count INTEGER DEFAULT 0,
    last_seen TIMESTAMP WITH TIME ZONE,
    first_seen TIMESTAMP WITH TIME ZONE,
    recognition_count INTEGER DEFAULT 0,

    -- Management
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    enabled BOOLEAN DEFAULT true,

    metadata JSONB DEFAULT '{}'
);

CREATE INDEX idx_person_name ON face_persons(name);
CREATE INDEX idx_person_enabled ON face_persons(enabled) WHERE enabled = true;
CREATE INDEX idx_person_last_seen ON face_persons(last_seen DESC NULLS LAST);
CREATE INDEX idx_person_tags ON face_persons USING GIN(tags);

-- ============================================================================
-- Table 2: face_embeddings - 512-dim face vectors
-- ============================================================================
CREATE TABLE IF NOT EXISTS face_embeddings (
    embedding_id SERIAL PRIMARY KEY,
    person_id INTEGER NOT NULL REFERENCES face_persons(person_id) ON DELETE CASCADE,

    -- Embedding vector (InsightFace ArcFace 512-dim)
    embedding vector(512) NOT NULL,

    -- Source image metadata
    image_path TEXT,
    image_hash TEXT,  -- SHA256 for deduplication
    captured_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Quality metrics (from InsightFace detection)
    face_confidence FLOAT,      -- Detection confidence (0-1)
    face_bbox JSONB,            -- Bounding box: {"x1": float, "y1": float, "x2": float, "y2": float}
    face_quality FLOAT,         -- Face quality score

    -- Management
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    is_primary BOOLEAN DEFAULT false,  -- Mark best embedding for this person

    CONSTRAINT unique_image_hash UNIQUE(person_id, image_hash),
    CONSTRAINT valid_face_confidence CHECK (face_confidence IS NULL OR (face_confidence >= 0.0 AND face_confidence <= 1.0)),
    CONSTRAINT valid_face_quality CHECK (face_quality IS NULL OR (face_quality >= 0.0 AND face_quality <= 1.0))
);

CREATE INDEX idx_embedding_person ON face_embeddings(person_id);
CREATE INDEX idx_embedding_primary ON face_embeddings(person_id, is_primary) WHERE is_primary = true;
CREATE INDEX idx_embedding_image_hash ON face_embeddings(image_hash);

-- HNSW index for fast similarity search (cosine distance)
-- Same parameters as knowledge_chunks: m=16, ef_construction=64
CREATE INDEX idx_embedding_vector ON face_embeddings
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- ============================================================================
-- Table 3: face_cameras - Camera registry
-- ============================================================================
CREATE TABLE IF NOT EXISTS face_cameras (
    camera_id SERIAL PRIMARY KEY,

    -- Identification
    name TEXT NOT NULL UNIQUE,
    camera_type TEXT NOT NULL,  -- 'usb', 'rtsp', 'ip', 'file'

    -- Connection details
    connection_string TEXT NOT NULL,  -- Device ID (0, 1, ...) or RTSP URL or file path
    username TEXT,                    -- For authenticated RTSP
    password TEXT,                    -- For authenticated RTSP (consider encryption)

    -- Location & Purpose
    location TEXT,
    description TEXT,

    -- Monitoring settings
    enabled BOOLEAN DEFAULT true,
    check_interval_seconds INTEGER,  -- NULL = use global default from config

    -- Statistics
    last_checked TIMESTAMP WITH TIME ZONE,
    last_face_detected TIMESTAMP WITH TIME ZONE,
    check_count INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,
    last_error TEXT,

    -- Management
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    metadata JSONB DEFAULT '{}',

    CONSTRAINT valid_camera_type CHECK (camera_type IN ('usb', 'rtsp', 'ip', 'file'))
);

CREATE INDEX idx_camera_name ON face_cameras(name);
CREATE INDEX idx_camera_enabled ON face_cameras(enabled) WHERE enabled = true;
CREATE INDEX idx_camera_type ON face_cameras(camera_type);
CREATE INDEX idx_camera_last_checked ON face_cameras(last_checked DESC NULLS LAST);

-- ============================================================================
-- Table 4: face_recognition_log - Historical recognition events
-- ============================================================================
CREATE TABLE IF NOT EXISTS face_recognition_log (
    log_id BIGSERIAL PRIMARY KEY,

    -- Recognition details
    person_id INTEGER REFERENCES face_persons(person_id) ON DELETE SET NULL,
    camera_id INTEGER REFERENCES face_cameras(camera_id) ON DELETE SET NULL,

    -- Results
    confidence FLOAT NOT NULL,  -- Similarity score (0-1)
    recognized_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Captured face data
    face_embedding vector(512),  -- Detected embedding for later analysis
    face_bbox JSONB,             -- Bounding box where face was found
    captured_image_path TEXT,    -- Optional: path to saved frame

    -- Context
    trigger_type TEXT,  -- 'background_monitor', 'manual', 'mcp_tool'
    session_id UUID,    -- Chat session if triggered during conversation

    -- Classification
    is_false_positive BOOLEAN DEFAULT false,  -- Mark for retraining
    is_unknown BOOLEAN DEFAULT false,         -- Unknown person detected
    notes TEXT,

    CONSTRAINT valid_confidence CHECK (confidence >= 0.0 AND confidence <= 1.0)
);

CREATE INDEX idx_recognition_person ON face_recognition_log(person_id);
CREATE INDEX idx_recognition_camera ON face_recognition_log(camera_id);
CREATE INDEX idx_recognition_time ON face_recognition_log(recognized_at DESC);
CREATE INDEX idx_recognition_trigger ON face_recognition_log(trigger_type);
CREATE INDEX idx_recognition_session ON face_recognition_log(session_id) WHERE session_id IS NOT NULL;
CREATE INDEX idx_recognition_unknown ON face_recognition_log(is_unknown) WHERE is_unknown = true;
CREATE INDEX idx_recognition_false_positive ON face_recognition_log(is_false_positive) WHERE is_false_positive = true;

-- ============================================================================
-- Table 5: face_presence_state - Current presence tracking
-- ============================================================================
CREATE TABLE IF NOT EXISTS face_presence_state (
    state_id SERIAL PRIMARY KEY,
    person_id INTEGER NOT NULL REFERENCES face_persons(person_id) ON DELETE CASCADE,
    camera_id INTEGER NOT NULL REFERENCES face_cameras(camera_id) ON DELETE CASCADE,

    -- State
    is_present BOOLEAN DEFAULT true,
    entered_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_seen_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    exited_at TIMESTAMP WITH TIME ZONE,

    -- Notification tracking
    notification_sent BOOLEAN DEFAULT false,
    notification_sent_at TIMESTAMP WITH TIME ZONE,

    CONSTRAINT unique_person_camera_present UNIQUE(person_id, camera_id, is_present)
);

CREATE INDEX idx_presence_current ON face_presence_state(is_present) WHERE is_present = true;
CREATE INDEX idx_presence_person ON face_presence_state(person_id);
CREATE INDEX idx_presence_camera ON face_presence_state(camera_id);
CREATE INDEX idx_presence_last_seen ON face_presence_state(last_seen_at DESC);

-- ============================================================================
-- Table 6: face_recognition_config - System settings
-- ============================================================================
CREATE TABLE IF NOT EXISTS face_recognition_config (
    config_id SERIAL PRIMARY KEY,

    -- Recognition settings
    similarity_threshold FLOAT DEFAULT 0.5,        -- Minimum similarity for match (0-1)
    confidence_threshold FLOAT DEFAULT 0.8,        -- Minimum detection confidence (0-1)

    -- Background monitoring
    monitoring_enabled BOOLEAN DEFAULT true,
    monitoring_interval_seconds INTEGER DEFAULT 60,

    -- Image storage
    store_captured_frames BOOLEAN DEFAULT false,
    captured_frames_path TEXT DEFAULT 'attachments/face_captures',
    max_stored_frames INTEGER DEFAULT 1000,

    -- Notifications
    notify_on_entry BOOLEAN DEFAULT true,
    notify_on_exit BOOLEAN DEFAULT false,
    notify_unknown_faces BOOLEAN DEFAULT true,

    -- Performance
    max_faces_per_frame INTEGER DEFAULT 10,
    embedding_batch_size INTEGER DEFAULT 32,

    -- Management
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    CONSTRAINT valid_similarity_threshold CHECK (similarity_threshold >= 0.0 AND similarity_threshold <= 1.0),
    CONSTRAINT valid_confidence_threshold CHECK (confidence_threshold >= 0.0 AND confidence_threshold <= 1.0)
);

-- Insert default configuration (single row table)
INSERT INTO face_recognition_config (config_id)
VALUES (1)
ON CONFLICT (config_id) DO NOTHING;

-- ============================================================================
-- Triggers for automatic timestamp updates
-- ============================================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply triggers to relevant tables
DROP TRIGGER IF EXISTS update_face_persons_updated_at ON face_persons;
CREATE TRIGGER update_face_persons_updated_at
    BEFORE UPDATE ON face_persons
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_face_cameras_updated_at ON face_cameras;
CREATE TRIGGER update_face_cameras_updated_at
    BEFORE UPDATE ON face_cameras
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_face_recognition_config_updated_at ON face_recognition_config;
CREATE TRIGGER update_face_recognition_config_updated_at
    BEFORE UPDATE ON face_recognition_config
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- Helpful views for common queries
-- ============================================================================

-- View: Active persons with their latest recognition
CREATE OR REPLACE VIEW face_persons_active AS
SELECT
    p.*,
    COUNT(e.embedding_id) as embedding_count,
    MAX(l.recognized_at) as last_recognized_at
FROM face_persons p
LEFT JOIN face_embeddings e ON p.person_id = e.person_id
LEFT JOIN face_recognition_log l ON p.person_id = l.person_id
WHERE p.enabled = true
GROUP BY p.person_id;

-- View: Camera status with latest activity
CREATE OR REPLACE VIEW face_cameras_status AS
SELECT
    c.*,
    COUNT(l.log_id) as total_recognitions,
    COUNT(DISTINCT l.person_id) as unique_persons_detected,
    MAX(l.recognized_at) as last_recognition_at,
    CASE
        WHEN c.last_checked IS NULL THEN 'never_checked'
        WHEN c.last_checked < NOW() - INTERVAL '5 minutes' THEN 'stale'
        WHEN c.error_count > 5 THEN 'error'
        WHEN c.enabled = false THEN 'disabled'
        ELSE 'active'
    END as status
FROM face_cameras c
LEFT JOIN face_recognition_log l ON c.camera_id = l.camera_id
    AND l.recognized_at > NOW() - INTERVAL '24 hours'
GROUP BY c.camera_id;

-- View: Current presence summary
CREATE OR REPLACE VIEW face_presence_current AS
SELECT
    p.person_id,
    p.name,
    p.display_name,
    c.camera_id,
    c.name as camera_name,
    c.location,
    s.entered_at,
    s.last_seen_at,
    EXTRACT(EPOCH FROM (NOW() - s.entered_at))::INTEGER as seconds_present
FROM face_presence_state s
JOIN face_persons p ON s.person_id = p.person_id
JOIN face_cameras c ON s.camera_id = c.camera_id
WHERE s.is_present = true
ORDER BY s.entered_at DESC;

-- ============================================================================
-- Verification queries
-- ============================================================================

-- Run these to verify successful creation:
-- \dt face_*
-- \di *face*embedding*
-- SELECT * FROM face_recognition_config;

-- ============================================================================
-- Cleanup (optional - for development/testing)
-- ============================================================================

-- Uncomment to drop all tables (WARNING: destroys all data)
-- DROP TABLE IF EXISTS face_recognition_log CASCADE;
-- DROP TABLE IF EXISTS face_presence_state CASCADE;
-- DROP TABLE IF EXISTS face_embeddings CASCADE;
-- DROP TABLE IF EXISTS face_persons CASCADE;
-- DROP TABLE IF EXISTS face_cameras CASCADE;
-- DROP TABLE IF EXISTS face_recognition_config CASCADE;
-- DROP VIEW IF EXISTS face_persons_active CASCADE;
-- DROP VIEW IF EXISTS face_cameras_status CASCADE;
-- DROP VIEW IF EXISTS face_presence_current CASCADE;
