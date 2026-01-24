-- ============================================================================
-- UPDATE SEED TOOL: Add batch dismiss capability
--
-- The seed tool's input_schema in the database must include suggestion_ids
-- for the model to know it can batch dismiss suggestions.
-- ============================================================================

-- First, let's see the current schema
-- SELECT input_schema FROM mcp_tools WHERE tool_name = 'seed';

-- Update the seed tool schema to add suggestion_ids parameter
UPDATE mcp_tools
SET input_schema = jsonb_set(
    input_schema::jsonb,
    '{properties,suggestion_ids}',
    '{
        "type": "string",
        "description": "For batch dismiss: comma-separated suggestion IDs (e.g., \"1,2,3,4,5\"). Use this to dismiss multiple suggestions in ONE call instead of calling dismiss repeatedly."
    }'::jsonb
),
description = 'Iris''s Motivation Engine - manage your autonomous wants and desires.

Actions:
- plant: Create a new seed (log a want)
- tend: Update progress, add notes, change status
- reflect: Add completion reflection when a seed blooms
- list: View your seeds (filter by status, category)
- garden: Visual overview of your seed garden
- suggestions: View pending seed suggestions
- accept: Accept a suggestion (creates the seed)
- dismiss: Dismiss suggestions - use suggestion_ids="1,2,3" for BATCH dismiss
- clear_suggestions: Delete all pending suggestions

BATCH DISMISS: To dismiss multiple suggestions at once, use:
  action="dismiss", suggestion_ids="1,2,3,4,5"
Do NOT call dismiss multiple times - use the batch parameter!'
WHERE tool_name = 'seed';

-- Verify the update
SELECT tool_name, description, input_schema->'properties'->'suggestion_ids' as suggestion_ids_param
FROM mcp_tools
WHERE tool_name = 'seed';
