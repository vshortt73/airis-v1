-- Meeting transcription tool definition for mcp_tools table

INSERT INTO mcp_tools (tool_name, description, input_schema, icon, enabled, priority, custom_instructions) VALUES
('meeting',
 'Record, transcribe, and manage meeting notes. Start requires a title. Use when the user mentions recording a meeting, transcribing audio, meeting notes, or asks about past meeting discussions.',
 '{
   "type": "object",
   "properties": {
     "action": {
       "type": "string",
       "enum": ["start", "stop", "status", "list", "get", "summarize", "speakers", "export"],
       "description": "Action to perform: start (begin recording — MUST include title param), stop (end and process), status (check progress), list (recent meetings), get (full transcript), summarize (generate summary), speakers (map speaker labels to names), export (download document)"
     },
     "meeting_title": {
       "type": "string",
       "description": "Meeting title — REQUIRED for start action. Extract from user message."
     },
     "meeting_type": {
       "type": "string",
       "enum": ["conference", "teams", "phone"],
       "description": "Type of meeting: conference (room mic), teams (cable/speaker), phone (default: conference)"
     },
     "meeting_id": {
       "type": "integer",
       "description": "Meeting ID for stop, status, get, summarize, speakers, export actions"
     },
     "calendar_event_id": {
       "type": "integer",
       "description": "Optional. If omitted, auto-links to a nearby calendar event (±15 min) or creates one. Pass 0 to force a standalone recording."
     },
     "speaker_map": {
       "type": "string",
       "description": "JSON string mapping speaker labels to names, e.g. {\"Speaker 0\": \"Victor\", \"Speaker 1\": \"Sarah\"} (for speakers action)"
     },
     "query": {
       "type": "string",
       "description": "Search term for list action"
     },
     "format": {
       "type": "string",
       "enum": ["summary", "notes", "transcript"],
       "description": "Export format: summary (concise), notes (summary + key quotes), transcript (full diarized). Default: summary"
     },
     "limit": {
       "type": "integer",
       "description": "Maximum number of results for list action (default: 10)"
     }
   },
   "required": ["action"]
 }'::jsonb,
 '🎙️',
 true,
 50,
 'IMPORTANT: The start action REQUIRES the meeting_title parameter. Always include meeting_title when action=start. Example: meeting(action="start", meeting_title="Weekly Standup"). You do NOT need to provide calendar_event_id — the system auto-detects nearby calendar events or creates one. If the tool returns needs_decision=true, present the question to the user and relay their choice.')
ON CONFLICT (tool_name) DO UPDATE SET
  description = EXCLUDED.description,
  input_schema = EXCLUDED.input_schema,
  icon = EXCLUDED.icon,
  enabled = EXCLUDED.enabled,
  priority = EXCLUDED.priority,
  custom_instructions = EXCLUDED.custom_instructions;
