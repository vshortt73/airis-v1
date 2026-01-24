-- ============================================================================
-- Insert Face Recognition Tools into mcp_tools table
-- ============================================================================

INSERT INTO mcp_tools (tool_name, description, input_schema, icon, enabled, priority) VALUES

-- Face Database Status Tool
('face_database_status',
 'Get status and statistics about the face recognition database. Shows how many people Iris knows, training images, and recent recognition activity.',
 '{
   "type": "object",
   "properties": {},
   "required": []
 }'::jsonb,
 '👤',
 true,
 5),

-- List Detected Faces Tool
('list_detected_faces',
 'List people currently detected/present in camera views. Shows who Iris can currently see and where they are.',
 '{
   "type": "object",
   "properties": {},
   "required": []
 }'::jsonb,
 '👥',
 true,
 5),

-- Get Person Info Tool
('get_person_info',
 'Get detailed information about a specific person in the face database.',
 '{
   "type": "object",
   "properties": {
     "name": {
       "type": "string",
       "description": "Person''s name (e.g., \"Victor\", \"Luna\")"
     }
   },
   "required": ["name"]
 }'::jsonb,
 '🔍',
 true,
 5)

ON CONFLICT (tool_name) DO UPDATE SET
  description = EXCLUDED.description,
  input_schema = EXCLUDED.input_schema,
  icon = EXCLUDED.icon,
  enabled = EXCLUDED.enabled,
  priority = EXCLUDED.priority;
