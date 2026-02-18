-- ============================================================================
-- Insert News Headlines Tool into mcp_tools table
-- ============================================================================
-- Run: psql -h localhost -U irisuser -d irisdb -f database/sql/insert_news_tools.sql

INSERT INTO mcp_tools (tool_name, description, input_schema, icon, enabled, priority) VALUES
('news_headlines',
 'Get latest news headlines from RSS feeds. Categories: general, technology, science, world.',
 '{
   "type": "object",
   "properties": {
     "category": {
       "type": "string",
       "description": "News category: general, technology, science, or world",
       "enum": ["general", "technology", "science", "world"],
       "default": "general"
     },
     "max_results": {
       "type": "integer",
       "description": "Maximum number of headlines to return (default 10, max 25)",
       "default": 10
     }
   },
   "required": []
 }'::jsonb,
 '📰',
 true,
 5)
ON CONFLICT (tool_name) DO UPDATE SET
  description = EXCLUDED.description,
  input_schema = EXCLUDED.input_schema,
  icon = EXCLUDED.icon,
  enabled = EXCLUDED.enabled,
  priority = EXCLUDED.priority;
