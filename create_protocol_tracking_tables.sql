-- ============================================================================
-- Protocol Tracking Tables
-- ============================================================================
-- Creates tables to track active protocols and protocol activation history

-- ============================================================================
-- ACTIVE PROTOCOL TABLE
-- ============================================================================
-- Stores the currently active protocol (only one row should exist at a time)

CREATE TABLE IF NOT EXISTS active_protocol (
    id SERIAL PRIMARY KEY,
    protocol_id INTEGER NOT NULL REFERENCES protocols(id) ON DELETE CASCADE,
    protocol_name VARCHAR(100) NOT NULL,  -- Denormalized for quick access
    activated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMP,  -- NULL = permanent
    passphrase_hash TEXT,  -- bcrypt hash if passphrase protection enabled
    activated_by VARCHAR(100) DEFAULT 'Victor',  -- Who activated it
    created_at TIMESTAMP DEFAULT NOW()
);

-- Only one active protocol at a time
CREATE UNIQUE INDEX IF NOT EXISTS idx_active_protocol_singleton
ON active_protocol ((1));

-- Index for expiration checks
CREATE INDEX IF NOT EXISTS idx_active_protocol_expires
ON active_protocol (expires_at)
WHERE expires_at IS NOT NULL;

COMMENT ON TABLE active_protocol IS 'Tracks the currently active protocol (singleton - only one row)';
COMMENT ON COLUMN active_protocol.protocol_id IS 'Reference to protocols table';
COMMENT ON COLUMN active_protocol.expires_at IS 'When protocol auto-deactivates (NULL = permanent)';
COMMENT ON COLUMN active_protocol.passphrase_hash IS 'bcrypt hash of passphrase (NULL = no passphrase required)';

-- ============================================================================
-- PROTOCOL HISTORY TABLE
-- ============================================================================
-- Audit log of all protocol activations and deactivations

CREATE TABLE IF NOT EXISTS protocol_history (
    id SERIAL PRIMARY KEY,
    protocol_id INTEGER REFERENCES protocols(id) ON DELETE SET NULL,
    protocol_name VARCHAR(100) NOT NULL,
    action VARCHAR(50) NOT NULL,  -- 'activate' or 'deactivate'
    activated_at TIMESTAMP,
    deactivated_at TIMESTAMP,
    duration_minutes INTEGER,  -- Planned duration (0 = permanent)
    actual_duration_minutes INTEGER,  -- Actual time active
    passphrase_protected BOOLEAN DEFAULT FALSE,
    deactivation_reason VARCHAR(100),  -- 'manual', 'expired', 'passphrase', 'system'
    activated_by VARCHAR(100),
    deactivated_by VARCHAR(100),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for history queries
CREATE INDEX IF NOT EXISTS idx_protocol_history_protocol
ON protocol_history (protocol_id);

CREATE INDEX IF NOT EXISTS idx_protocol_history_action
ON protocol_history (action);

CREATE INDEX IF NOT EXISTS idx_protocol_history_activated
ON protocol_history (activated_at DESC);

COMMENT ON TABLE protocol_history IS 'Audit log of protocol activations and deactivations';
COMMENT ON COLUMN protocol_history.action IS 'Either "activate" or "deactivate"';
COMMENT ON COLUMN protocol_history.deactivation_reason IS 'Why protocol was deactivated: manual, expired, passphrase, system';

-- ============================================================================
-- HELPER FUNCTIONS
-- ============================================================================

-- Function to get current active protocol
CREATE OR REPLACE FUNCTION get_active_protocol()
RETURNS TABLE (
    protocol_id INTEGER,
    protocol_name VARCHAR(100),
    activated_at TIMESTAMP,
    expires_at TIMESTAMP,
    is_expired BOOLEAN,
    time_remaining INTERVAL
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        ap.protocol_id,
        ap.protocol_name,
        ap.activated_at,
        ap.expires_at,
        (ap.expires_at IS NOT NULL AND ap.expires_at <= NOW()) AS is_expired,
        CASE
            WHEN ap.expires_at IS NULL THEN NULL
            WHEN ap.expires_at <= NOW() THEN INTERVAL '0'
            ELSE ap.expires_at - NOW()
        END AS time_remaining
    FROM active_protocol ap
    LIMIT 1;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_active_protocol() IS 'Returns the currently active protocol with expiration info';

-- ============================================================================
-- DEFAULT DATA
-- ============================================================================

-- Ensure "Default" protocol exists in protocols table
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM protocols WHERE name = 'Default') THEN
        RAISE NOTICE 'Default protocol not found in protocols table!';
        RAISE NOTICE 'Run create_default_protocol.py first to create it.';
    END IF;
END $$;

-- Set "Default" protocol as initially active (if active_protocol is empty)
INSERT INTO active_protocol (protocol_id, protocol_name, activated_at, activated_by)
SELECT id, name, NOW(), 'system'
FROM protocols
WHERE name = 'Default'
AND NOT EXISTS (SELECT 1 FROM active_protocol)
LIMIT 1;

-- Log the initial activation in history
INSERT INTO protocol_history (
    protocol_id, protocol_name, action, activated_at,
    duration_minutes, passphrase_protected, activated_by
)
SELECT
    ap.protocol_id,
    ap.protocol_name,
    'activate',
    ap.activated_at,
    0,  -- permanent
    FALSE,
    ap.activated_by
FROM active_protocol ap
WHERE NOT EXISTS (
    SELECT 1 FROM protocol_history
    WHERE protocol_name = 'Default'
    AND action = 'activate'
)
LIMIT 1;

-- ============================================================================
-- VERIFICATION
-- ============================================================================

-- Show current active protocol
SELECT
    'Active Protocol:' as info,
    protocol_name,
    activated_at,
    CASE
        WHEN expires_at IS NULL THEN 'Permanent'
        ELSE 'Expires: ' || expires_at::TEXT
    END as expiration,
    CASE
        WHEN passphrase_hash IS NOT NULL THEN 'Protected'
        ELSE 'No passphrase'
    END as security
FROM active_protocol;

-- Show tables created
SELECT
    'Tables Created:' as info,
    COUNT(*) FILTER (WHERE table_name = 'active_protocol') as active_protocol,
    COUNT(*) FILTER (WHERE table_name = 'protocol_history') as protocol_history
FROM information_schema.tables
WHERE table_schema = 'public'
AND table_name IN ('active_protocol', 'protocol_history');
