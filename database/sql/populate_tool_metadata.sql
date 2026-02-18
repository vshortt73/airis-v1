-- ============================================================================
-- Populate mcp_tools metadata from hardcoded values
-- Maps tools to servers, groups, triggers, and core status
-- ============================================================================
-- Run: psql -h localhost -U irisuser -d irisdb -f database/sql/populate_tool_metadata.sql
-- Requires: alter_mcp_tools_smart_selection.sql must be run first

-- ============================================================================
-- CORE TOOLS (always included in context)
-- ============================================================================
UPDATE mcp_tools SET is_core = TRUE WHERE tool_name IN (
    'weather',
    'memory',
    'knowledge',
    'knowledge_save',
    'face'
);

-- ============================================================================
-- SERVER MAPPINGS (which server provides each tool)
-- ============================================================================

-- Info server tools
UPDATE mcp_tools SET server_name = 'info' WHERE tool_name IN (
    'weather',
    'research',
    'face',
    'news_headlines',
    'web_search',
    'url_fetch',
    'webcam_recognize'
);

-- Knowledge server tools
UPDATE mcp_tools SET server_name = 'knowledge' WHERE tool_name IN (
    'knowledge',
    'knowledge_save'
);

-- Traits server tools
UPDATE mcp_tools SET server_name = 'traits' WHERE tool_name IN (
    'trait'
);

-- Memory server tools
UPDATE mcp_tools SET server_name = 'memory' WHERE tool_name IN (
    'memory'
);

-- Creative server tools
UPDATE mcp_tools SET server_name = 'creative' WHERE tool_name IN (
    'image'
);

-- System server tools
UPDATE mcp_tools SET server_name = 'system' WHERE tool_name IN (
    'generate_alerts',
    'get_system_health_statistics',
    'system_status_summary',
    'linux_shell',
    'database_query',
    'distributed_system_health'
);

-- Protocols server tools
UPDATE mcp_tools SET server_name = 'protocols' WHERE tool_name IN (
    'protocol'
);

-- Directions server tools
UPDATE mcp_tools SET server_name = 'directions' WHERE tool_name IN (
    'ship_directions',
    'ship_locations'
);

-- Seeds server tools
UPDATE mcp_tools SET server_name = 'seeds' WHERE tool_name IN (
    'seed'
);

-- Calendar server tools
UPDATE mcp_tools SET server_name = 'calendar' WHERE tool_name IN (
    'calendar',
    'calendar_add'
);

-- Meeting server tools
UPDATE mcp_tools SET server_name = 'meeting' WHERE tool_name IN (
    'meeting',
    'meeting_start'
);

-- Moltbook server tools
UPDATE mcp_tools SET server_name = 'moltbook' WHERE tool_name IN (
    'moltbook',
    'moltbook_post'
);

-- ============================================================================
-- TOOL GROUPS AND TRIGGERS
-- Triggers are substrings matched against lowercased user messages
-- ============================================================================

-- Navigation group
UPDATE mcp_tools SET
    tool_group = 'navigation',
    trigger_keywords = ARRAY['directions', 'where is', 'how to get', 'navigate', 'deck', 'location', 'find the']
WHERE tool_name IN ('ship_directions', 'ship_locations');

-- Social group
UPDATE mcp_tools SET
    tool_group = 'social',
    trigger_keywords = ARRAY['moltbook', 'post', 'submolt', 'social', 'community', 'molt']
WHERE tool_name IN ('moltbook', 'moltbook_post');

-- Creative group
UPDATE mcp_tools SET
    tool_group = 'creative',
    trigger_keywords = ARRAY['image', 'picture', 'draw', 'paint', 'generate', 'selfie', 'photo']
WHERE tool_name IN ('image');

-- Calendar group
UPDATE mcp_tools SET
    tool_group = 'calendar',
    trigger_keywords = ARRAY['calendar', 'event', 'schedule', 'remind', 'appointment']
WHERE tool_name IN ('calendar', 'calendar_add');

-- Meeting group
UPDATE mcp_tools SET
    tool_group = 'meeting',
    trigger_keywords = ARRAY['meeting', 'record', 'transcri', 'minutes']
WHERE tool_name IN ('meeting', 'meeting_start');

-- Research group
UPDATE mcp_tools SET
    tool_group = 'research',
    trigger_keywords = ARRAY['search', 'look up', 'find out', 'news', 'article', 'arxiv', 'pubmed', 'website', 'url']
WHERE tool_name IN ('web_search', 'url_fetch', 'research', 'news_headlines');

-- System group
UPDATE mcp_tools SET
    tool_group = 'system',
    trigger_keywords = ARRAY['system', 'server', 'shell', 'command', 'database', 'query', 'sql', 'webcam', 'look at', 'health', 'gpu', 'service', 'memory', 'diagnose', 'status']
WHERE tool_name IN ('linux_shell', 'database_query', 'webcam_recognize', 'distributed_system_health');

-- Personality group
UPDATE mcp_tools SET
    tool_group = 'personality',
    trigger_keywords = ARRAY['trait', 'personality', 'protocol', 'mode', 'seed', 'motivation', 'goal']
WHERE tool_name IN ('trait', 'protocol', 'seed');

-- ============================================================================
-- AUTONOMOUS FLAGS
-- Defines which tools can execute without user confirmation
-- ============================================================================

-- Most tools are autonomous (can run without confirmation)
UPDATE mcp_tools SET is_autonomous = TRUE WHERE tool_name IN (
    'weather',
    'research',
    'face',
    'news_headlines',
    'web_search',
    'url_fetch',
    'webcam_recognize',
    'linux_shell',
    'knowledge',
    'knowledge_save',
    'trait',
    'memory',
    'protocol',
    'ship_directions',
    'ship_locations',
    'seed',
    'image',
    'calendar',
    'calendar_add',
    'meeting',
    'meeting_start',
    'moltbook',
    'moltbook_post',
    'database_query',
    'distributed_system_health'
);

-- ============================================================================
-- VERIFICATION
-- ============================================================================
SELECT
    tool_name,
    server_name,
    tool_group,
    trigger_keywords,
    is_core,
    is_autonomous
FROM mcp_tools
WHERE enabled = true
ORDER BY
    COALESCE(tool_group, 'zzz'),  -- Group NULL groups at end
    tool_name;
