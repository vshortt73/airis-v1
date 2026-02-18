-- ============================================================================
-- Create mcp_servers table for database-driven server configuration
-- Replaces hardcoded server configs in server_configs.py
-- ============================================================================
-- Run: psql -h localhost -U irisuser -d irisdb -f database/sql/create_mcp_servers_table.sql

-- Create the mcp_servers table
CREATE TABLE IF NOT EXISTS mcp_servers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    command VARCHAR(255) NOT NULL DEFAULT 'python',
    script_path TEXT NOT NULL,
    enabled BOOLEAN DEFAULT TRUE,
    priority INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_mcp_servers_enabled ON mcp_servers(enabled);
CREATE INDEX IF NOT EXISTS idx_mcp_servers_name ON mcp_servers(name);

-- Add trigger to update updated_at on changes
CREATE OR REPLACE FUNCTION update_mcp_servers_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS mcp_servers_update_timestamp ON mcp_servers;
CREATE TRIGGER mcp_servers_update_timestamp
    BEFORE UPDATE ON mcp_servers
    FOR EACH ROW
    EXECUTE FUNCTION update_mcp_servers_timestamp();

-- Add comments
COMMENT ON TABLE mcp_servers IS 'MCP server configurations - defines which servers to connect to and how';
COMMENT ON COLUMN mcp_servers.name IS 'Unique server identifier (e.g., info, system, knowledge)';
COMMENT ON COLUMN mcp_servers.description IS 'Human-readable description of server purpose';
COMMENT ON COLUMN mcp_servers.command IS 'Command to run the server (e.g., python, node)';
COMMENT ON COLUMN mcp_servers.script_path IS 'Path to server script relative to project root';
COMMENT ON COLUMN mcp_servers.enabled IS 'If false, server will not be started';
COMMENT ON COLUMN mcp_servers.priority IS 'Server startup priority (lower = starts first)';

-- Verification
SELECT
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_name = 'mcp_servers'
ORDER BY ordinal_position;
