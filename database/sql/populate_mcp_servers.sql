-- ============================================================================
-- Populate mcp_servers table from current server_configs.py
-- ============================================================================
-- Run: psql -h localhost -U irisuser -d irisdb -f database/sql/populate_mcp_servers.sql
-- Requires: create_mcp_servers_table.sql must be run first

-- Clear existing entries (idempotent)
TRUNCATE mcp_servers RESTART IDENTITY CASCADE;

-- Insert server configurations
-- script_path is relative to project root (e.g., mcp_servers/info/info_server.py)

INSERT INTO mcp_servers (name, description, command, script_path, enabled, priority) VALUES
(
    'info',
    'Information retrieval tools: weather, news, webcam, web content',
    'python',
    'mcp_servers/info/info_server.py',
    TRUE,
    10
),
(
    'knowledge',
    'Document and knowledge search, RAG system',
    'python',
    'mcp_servers/knowledge/knowledge_server.py',
    TRUE,
    20
),
(
    'traits',
    'Personality trait management',
    'python',
    'mcp_servers/traits/traits_server.py',
    TRUE,
    30
),
(
    'memory',
    'Short-term memory management',
    'python',
    'mcp_servers/memory/memory_server.py',
    TRUE,
    40
),
(
    'creative',
    'Image generation via ComfyUI',
    'python',
    'mcp_servers/creative/creative_server.py',
    TRUE,
    50
),
(
    'system',
    'System stats, health monitoring, shell access',
    'python',
    'mcp_servers/system/system_server.py',
    TRUE,
    60
),
(
    'protocols',
    'Protocol activation and management',
    'python',
    'mcp_servers/protocols/protocol_server.py',
    TRUE,
    70
),
(
    'directions',
    'Ship navigation and wayfinding',
    'python',
    'mcp_servers/directions/directions_server.py',
    TRUE,
    80
),
(
    'seeds',
    'Iris motivation and goal management',
    'python',
    'mcp_servers/seeds/seeds_server.py',
    TRUE,
    90
),
(
    'calendar',
    'Event scheduling and reminders',
    'python',
    'mcp_servers/calendar/calendar_server.py',
    TRUE,
    100
),
(
    'meeting',
    'Meeting recording and transcription',
    'python',
    'mcp_servers/meeting/meeting_server.py',
    TRUE,
    110
),
(
    'moltbook',
    'AI social network integration',
    'python',
    'mcp_servers/moltbook/moltbook_server.py',
    TRUE,
    120
);

-- Verification
SELECT
    id,
    name,
    description,
    command,
    script_path,
    enabled,
    priority
FROM mcp_servers
ORDER BY priority;
