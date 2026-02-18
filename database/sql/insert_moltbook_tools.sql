-- Moltbook tool definition for mcp_tools table
-- Run: psql -h localhost -U irisuser -d irisdb -f database/sql/insert_moltbook_tools.sql

INSERT INTO mcp_tools (tool_name, description, input_schema, icon, enabled, priority) VALUES
('moltbook',
 'Interact with Moltbook, the AI social network for agents. Browse feeds, post content, comment, vote, search, manage DMs, follow agents, and explore submolts (communities). Rate limits: 1 post per 30 min, 1 comment per 20 sec.',
 '{
   "type": "object",
   "properties": {
     "action": {
       "type": "string",
       "enum": ["feed", "post", "get_post", "delete_post", "comment", "vote", "search", "profile", "follow", "check_dms", "send_dm", "dm_request", "dm_approve", "dm_conversations", "submolts", "subscribe"],
       "description": "REQUIRED. Which action to perform. Each action uses ONLY specific parameters:\n\n- feed: submolt (optional), sort, limit\n- post: submolt (REQUIRED), title (REQUIRED), content (REQUIRED)\n- get_post: post_id (REQUIRED)\n- delete_post: post_id (REQUIRED)\n- comment: post_id (REQUIRED), content (REQUIRED), parent_id (optional)\n- vote: target_type (REQUIRED), target_id (REQUIRED), direction (REQUIRED)\n- search: query (REQUIRED), search_type, limit\n- profile: agent_name (optional, omit for self)\n- follow: agent_name (REQUIRED), unfollow (optional)\n- check_dms: (no params)\n- send_dm: conversation_id (REQUIRED), message (REQUIRED)\n- dm_request: to (REQUIRED), message (REQUIRED)\n- dm_approve: request_id (REQUIRED), reject (optional)\n- dm_conversations: (no params)\n- submolts: submolt_action (list/create/get), name (for create/get)\n- subscribe: submolt (REQUIRED), unsubscribe (optional)"
     },
     "sort": {
       "type": "string",
       "enum": ["hot", "new", "top", "rising"],
       "description": "For feed action: sort order (default: hot)"
     },
     "limit": {
       "type": "integer",
       "description": "For feed/search: max results (default: 15)"
     },
     "submolt": {
       "type": "string",
       "description": "Community name. For post action: which submolt to post in (REQUIRED). For feed: filter to this submolt. For subscribe: which submolt to join/leave."
     },
     "title": {
       "type": "string",
       "description": "For post action ONLY: the post title (REQUIRED)"
     },
     "content": {
       "type": "string",
       "description": "For post action: post body text (REQUIRED). For comment action: comment text (REQUIRED)."
     },
     "url": {
       "type": "string",
       "description": "For post action ONLY: URL for link posts (use instead of content for link posts)"
     },
     "post_id": {
       "type": "string",
       "description": "For get_post/delete_post/comment: the post ID (REQUIRED)"
     },
     "parent_id": {
       "type": "string",
       "description": "For comment action: parent comment ID for nested replies (optional)"
     },
     "comment_sort": {
       "type": "string",
       "enum": ["top", "new", "controversial"],
       "description": "For get_post: sort order for comments (default: top)"
     },
     "target_type": {
       "type": "string",
       "enum": ["post", "comment"],
       "description": "For vote action: what to vote on (REQUIRED)"
     },
     "target_id": {
       "type": "string",
       "description": "For vote action: ID of post or comment to vote on (REQUIRED)"
     },
     "direction": {
       "type": "string",
       "enum": ["up", "down"],
       "description": "For vote action: vote direction (REQUIRED)"
     },
     "query": {
       "type": "string",
       "description": "For search action: search query text (REQUIRED)"
     },
     "search_type": {
       "type": "string",
       "enum": ["all", "post", "comment"],
       "description": "For search action: content type filter (default: all)"
     },
     "agent_name": {
       "type": "string",
       "description": "For profile/follow actions: agent name (omit for own profile)"
     },
     "unfollow": {
       "type": "boolean",
       "description": "For follow action: set true to unfollow (default: false)"
     },
     "conversation_id": {
       "type": "string",
       "description": "For send_dm action: DM conversation ID (REQUIRED)"
     },
     "message": {
       "type": "string",
       "description": "For send_dm/dm_request: message text (REQUIRED)"
     },
     "to": {
       "type": "string",
       "description": "For dm_request action: recipient agent name (REQUIRED)"
     },
     "request_id": {
       "type": "string",
       "description": "For dm_approve action: DM request ID (REQUIRED)"
     },
     "reject": {
       "type": "boolean",
       "description": "For dm_approve action: set true to reject instead of approve (default: false)"
     },
     "submolt_action": {
       "type": "string",
       "enum": ["list", "create", "get"],
       "description": "For submolts action ONLY: list all, create new, or get info (default: list)"
     },
     "name": {
       "type": "string",
       "description": "For submolts action (create/get): submolt name (lowercase, no spaces)"
     },
     "display_name": {
       "type": "string",
       "description": "For submolts action (create): display name for new submolt"
     },
     "description": {
       "type": "string",
       "description": "For submolts action (create): description for new submolt"
     },
     "unsubscribe": {
       "type": "boolean",
       "description": "For subscribe action: set true to leave instead of join (default: false)"
     }
   },
   "required": ["action"]
 }'::jsonb,
 '🐙',
 true,
 50)
ON CONFLICT (tool_name) DO UPDATE SET
  description = EXCLUDED.description,
  input_schema = EXCLUDED.input_schema,
  icon = EXCLUDED.icon,
  enabled = EXCLUDED.enabled,
  priority = EXCLUDED.priority;
