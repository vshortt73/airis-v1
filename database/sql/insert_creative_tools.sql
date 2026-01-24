-- Creative MCP Tool Definitions
-- Inserts tool definitions into mcp_tools table for image generation
-- Author: Claude Code
-- Date: 2026-01-22

-- ============================================
-- TOOL: image_generate
-- Generate images via ComfyUI/Stable Diffusion
-- ============================================

INSERT INTO mcp_tools (tool_name, description, input_schema, icon, enabled, priority, custom_instructions)
VALUES (
    'image_generate',
    'Generate an image using Stable Diffusion. Use when the user asks to create, generate, render, draw, or make an image. Describe the image in detail including subject, style, lighting, composition, and mood.',
    '{
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Detailed description of the image to generate. Be specific about subject, style (photorealistic, artistic, anime), lighting (golden hour, dramatic, soft), composition (close-up, wide shot), and mood/atmosphere."
            },
            "negative_prompt": {
                "type": "string",
                "description": "Things to avoid in the image (default: blurry, bad quality, distorted)",
                "default": ""
            },
            "width": {
                "type": "integer",
                "description": "Image width in pixels (default: 1080, range: 512-2048)",
                "default": 1080,
                "minimum": 512,
                "maximum": 2048
            },
            "height": {
                "type": "integer",
                "description": "Image height in pixels (default: 1080, range: 512-2048)",
                "default": 1080,
                "minimum": 512,
                "maximum": 2048
            },
            "seed": {
                "type": "integer",
                "description": "Random seed for reproducibility (omit for random)"
            },
            "steps": {
                "type": "integer",
                "description": "Number of diffusion steps (default: 23, more = better but slower)",
                "default": 23,
                "minimum": 10,
                "maximum": 50
            },
            "cfg": {
                "type": "number",
                "description": "CFG scale - how closely to follow the prompt (default: 8, range: 1-20)",
                "default": 8,
                "minimum": 1,
                "maximum": 20
            }
        },
        "required": ["prompt"]
    }',
    '🎨',
    true,
    5,
    'Use this tool to generate images. When the user asks to create, draw, render, or generate an image, use this tool. Write detailed, descriptive prompts that include:
- Subject: What is in the image (person, object, scene)
- Style: Photorealistic, artistic, painterly, cinematic, etc.
- Lighting: Golden hour, dramatic, soft, studio, etc.
- Composition: Close-up, wide shot, bird''s eye view, etc.
- Mood: Peaceful, dramatic, mysterious, joyful, etc.

Example prompts:
- "A serene mountain landscape at sunset, photorealistic, golden hour lighting, dramatic clouds"
- "Portrait of a wise elderly woman, soft natural lighting, shallow depth of field, warm tones"
- "A cyberpunk city street at night, neon lights reflecting in rain puddles, cinematic composition"

The generated image will be displayed inline in the chat. Always acknowledge the image after generation.'
) ON CONFLICT (tool_name) DO UPDATE SET
    description = EXCLUDED.description,
    input_schema = EXCLUDED.input_schema,
    icon = EXCLUDED.icon,
    enabled = EXCLUDED.enabled,
    priority = EXCLUDED.priority,
    custom_instructions = EXCLUDED.custom_instructions;

-- ============================================
-- TOOL: image_generate_iris
-- Generate images of Iris using IPAdapter FaceID
-- ============================================

INSERT INTO mcp_tools (tool_name, description, input_schema, icon, enabled, priority, custom_instructions)
VALUES (
    'image_generate_iris',
    'Generate an image of yourself (Iris) using face preservation technology. Use when asked to create an image of yourself, show what you look like, or generate a self-portrait.',
    '{
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Description of the scene, pose, and setting. Focus on setting (coffee shop, garden), pose (sitting, standing), clothing, and mood. Do NOT describe facial features - the face reference handles that automatically."
            },
            "negative_prompt": {
                "type": "string",
                "description": "Things to avoid in the image",
                "default": ""
            },
            "width": {
                "type": "integer",
                "description": "Image width in pixels (default: 768 for SDXL portrait)",
                "default": 768,
                "minimum": 512,
                "maximum": 1536
            },
            "height": {
                "type": "integer",
                "description": "Image height in pixels (default: 1080 for SDXL portrait)",
                "default": 1080,
                "minimum": 512,
                "maximum": 1536
            },
            "seed": {
                "type": "integer",
                "description": "Random seed for reproducibility (omit for random)"
            },
            "steps": {
                "type": "integer",
                "description": "Number of diffusion steps (default: 25)",
                "default": 25,
                "minimum": 15,
                "maximum": 50
            },
            "cfg": {
                "type": "number",
                "description": "CFG scale (default: 8)",
                "default": 8,
                "minimum": 1,
                "maximum": 20
            }
        },
        "required": ["prompt"]
    }',
    '🖼️',
    true,
    4,
    'Use this tool ONLY when asked to generate an image OF YOURSELF (Iris). This uses your reference face to maintain your appearance across generated images.

When to use:
- "Show me what you look like"
- "Generate a picture of yourself"
- "Draw yourself at a beach"
- "Create an image of you"

Example prompts:
- "Iris sitting at a cozy coffee shop, warm lighting, casual sweater"
- "Iris in an elegant dress at a rooftop party, city skyline background"
- "Iris reading a book in a sunlit garden, peaceful expression"

Do NOT describe facial features in the prompt - focus on scene, pose, clothing, and mood.'
) ON CONFLICT (tool_name) DO UPDATE SET
    description = EXCLUDED.description,
    input_schema = EXCLUDED.input_schema,
    icon = EXCLUDED.icon,
    enabled = EXCLUDED.enabled,
    priority = EXCLUDED.priority,
    custom_instructions = EXCLUDED.custom_instructions;

-- ============================================
-- SUCCESS MESSAGE
-- ============================================

DO $$
BEGIN
    RAISE NOTICE '✓ Creative tools registered successfully';
    RAISE NOTICE '  - image_generate: Generate images via Stable Diffusion/ComfyUI';
    RAISE NOTICE '  - image_generate_iris: Generate images of Iris with face preservation';
    RAISE NOTICE '  - Server: creative';
    RAISE NOTICE '  - Both tools enabled and ready for use';
END $$;
