-- Calendar tool definition for mcp_tools table

INSERT INTO mcp_tools (tool_name, description, input_schema, icon, enabled, priority) VALUES
('calendar',
 'Manage calendar events - add, list, update, delete, and search appointments and reminders. Use this when the user mentions scheduling, appointments, meetings, deadlines, or asks about upcoming events.',
 '{
   "type": "object",
   "properties": {
     "action": {
       "type": "string",
       "enum": ["add", "list", "update", "delete", "search"],
       "description": "Action to perform: add (create event), list (show upcoming), update (modify event), delete (cancel event), search (find by keyword)"
     },
     "title": {
       "type": "string",
       "description": "Event title (required for add)"
     },
     "description": {
       "type": "string",
       "description": "Event description or notes"
     },
     "start_time": {
       "type": "string",
       "description": "Event start time in ISO 8601 format (e.g. 2026-02-01T14:00:00). Required for add."
     },
     "end_time": {
       "type": "string",
       "description": "Event end time in ISO 8601 format. Defaults to start_time + 1 hour if not provided."
     },
     "all_day": {
       "type": "boolean",
       "description": "Whether this is an all-day event (default: false)"
     },
     "location": {
       "type": "string",
       "description": "Event location"
     },
     "category": {
       "type": "string",
       "enum": ["appointment", "meeting", "personal", "reminder", "deadline"],
       "description": "Event category (default: personal)"
     },
     "reminder": {
       "type": "boolean",
       "description": "Enable reminder for this event (default: true)"
     },
     "reminder_hours_before": {
       "type": "number",
       "description": "Hours before event to trigger reminder (default: 4)"
     },
     "event_id": {
       "type": "integer",
       "description": "Event ID for update/delete actions"
     },
     "days_ahead": {
       "type": "integer",
       "description": "For list action: show events in next N days (default: 7)"
     },
     "query": {
       "type": "string",
       "description": "For search action: search term to match against title and description"
     },
     "limit": {
       "type": "integer",
       "description": "Maximum number of results to return (default: 20)"
     }
   },
   "required": ["action"]
 }'::jsonb,
 '📅',
 true,
 50)
ON CONFLICT (tool_name) DO UPDATE SET
  description = EXCLUDED.description,
  input_schema = EXCLUDED.input_schema,
  icon = EXCLUDED.icon,
  enabled = EXCLUDED.enabled,
  priority = EXCLUDED.priority;
