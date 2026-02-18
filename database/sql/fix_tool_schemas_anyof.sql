-- Fix tool schemas - remove anyOf patterns that confuse Qwen3
-- The model was interpreting {"type": "string"} from anyOf and echoing it
-- as {"type": "string", "value": "..."} instead of just providing values
--
-- Issue: chat_history IDs 44297, 44299 on 2026-02-04
-- Affected tools: trait, protocol, image

-- Fix trait tool
UPDATE mcp_tools
SET input_schema = '{
  "type": "object",
  "required": ["action"],
  "properties": {
    "action": {
      "type": "string",
      "description": "The action to perform: get, list, or modify"
    },
    "name": {
      "type": "string",
      "description": "Trait name (required for get/modify)"
    },
    "value": {
      "type": "number",
      "description": "New value 0-10 (required for modify)"
    },
    "reason": {
      "type": "string",
      "description": "Reason for modification (required for modify)"
    }
  }
}'::jsonb
WHERE tool_name = 'trait';

-- Fix protocol tool
UPDATE mcp_tools
SET input_schema = '{
  "type": "object",
  "required": ["action"],
  "properties": {
    "action": {
      "type": "string",
      "description": "The action to perform: list, activate, deactivate, suggest, request"
    },
    "name": {
      "type": "string",
      "description": "Protocol name (required for activate/deactivate)"
    },
    "request": {
      "type": "string",
      "description": "Description of desired behavior (for suggest action)"
    },
    "duration": {
      "type": "string",
      "description": "How long to activate protocol (e.g., 1 hour, until told otherwise)"
    }
  }
}'::jsonb
WHERE tool_name = 'protocol';

-- Fix image tool
UPDATE mcp_tools
SET input_schema = '{
  "type": "object",
  "required": ["action", "prompt"],
  "properties": {
    "action": {
      "type": "string",
      "description": "Image type: generate (general image) or self (self-portrait with face preservation)"
    },
    "prompt": {
      "type": "string",
      "description": "Detailed description of the image to generate"
    },
    "negative_prompt": {
      "type": "string",
      "description": "Things to avoid in the image"
    },
    "width": {
      "type": "integer",
      "description": "Image width in pixels (default 1024)"
    },
    "height": {
      "type": "integer",
      "description": "Image height in pixels (default 1024)"
    },
    "steps": {
      "type": "integer",
      "description": "Sampling steps (default 25, higher = more detail)"
    },
    "cfg": {
      "type": "number",
      "description": "Classifier-free guidance scale (default 7.0)"
    },
    "seed": {
      "type": "integer",
      "description": "Random seed for reproducibility"
    }
  }
}'::jsonb
WHERE tool_name = 'image';

-- Verify the updates
SELECT tool_name,
       CASE WHEN input_schema::text LIKE '%anyOf%' THEN 'STILL HAS anyOf' ELSE 'OK' END as status
FROM mcp_tools
WHERE tool_name IN ('trait', 'protocol', 'image');
