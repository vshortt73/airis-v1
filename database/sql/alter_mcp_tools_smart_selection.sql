-- ============================================================================
-- ALTER mcp_tools for Smart Tool Selection
-- Adds columns for database-driven tool routing and smart selection
-- ============================================================================
-- Run: psql -h localhost -U irisuser -d irisdb -f database/sql/alter_mcp_tools_smart_selection.sql

-- Add server_name: which MCP server provides this tool
ALTER TABLE mcp_tools ADD COLUMN IF NOT EXISTS server_name VARCHAR(100);

-- Add tool_group: logical grouping for smart selection (navigation, creative, system, etc.)
ALTER TABLE mcp_tools ADD COLUMN IF NOT EXISTS tool_group VARCHAR(100);

-- Add trigger_keywords: array of strings that trigger this tool's group inclusion
ALTER TABLE mcp_tools ADD COLUMN IF NOT EXISTS trigger_keywords TEXT[];

-- Add is_core: if true, tool is always included regardless of context
ALTER TABLE mcp_tools ADD COLUMN IF NOT EXISTS is_core BOOLEAN DEFAULT FALSE;

-- Add is_autonomous: if true, tool can be called without user confirmation
ALTER TABLE mcp_tools ADD COLUMN IF NOT EXISTS is_autonomous BOOLEAN DEFAULT TRUE;

-- Create index for efficient server lookups
CREATE INDEX IF NOT EXISTS idx_mcp_tools_server_name ON mcp_tools(server_name);

-- Create index for efficient group lookups
CREATE INDEX IF NOT EXISTS idx_mcp_tools_tool_group ON mcp_tools(tool_group);

-- Create index for core tools
CREATE INDEX IF NOT EXISTS idx_mcp_tools_is_core ON mcp_tools(is_core) WHERE is_core = TRUE;

-- Add comment explaining the columns
COMMENT ON COLUMN mcp_tools.server_name IS 'Name of MCP server that provides this tool (e.g., info, system, knowledge)';
COMMENT ON COLUMN mcp_tools.tool_group IS 'Logical grouping for smart selection (e.g., navigation, creative, system)';
COMMENT ON COLUMN mcp_tools.trigger_keywords IS 'Keywords that trigger this tool group inclusion when found in user messages';
COMMENT ON COLUMN mcp_tools.is_core IS 'If true, tool is always included in context regardless of triggers';
COMMENT ON COLUMN mcp_tools.is_autonomous IS 'If true, tool can execute without user confirmation';

-- Verification query
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_name = 'mcp_tools'
AND column_name IN ('server_name', 'tool_group', 'trigger_keywords', 'is_core', 'is_autonomous')
ORDER BY column_name;
