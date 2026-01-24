-- Populate system_config with default values from config.py
-- Run this ONCE to migrate from file-based config to database config

-- ============================================================================
-- FACE MONITORING CONFIGURATION
-- ============================================================================

INSERT INTO system_config (category, key, value, value_type, default_value, description, requires_restart) VALUES
('face_monitoring', 'FACE_MONITORING_ENABLED', 'true', 'bool', 'true', 'Enable background face recognition monitoring', true),
('face_monitoring', 'FACE_MONITORING_INTERVAL_SECONDS', '30', 'int', '30', 'How often to scan webcam for faces (seconds)', false),
('face_monitoring', 'FACE_GREETING_MIN_ABSENCE_MINUTES', '5', 'int', '5', 'Minimum absence duration to trigger greeting (minutes)', false),
('face_monitoring', 'FACE_GREETING_COOLDOWN_MINUTES', '15', 'int', '15', 'Minimum time between greetings to prevent spam (minutes)', false),
('face_monitoring', 'FACE_SIMILARITY_THRESHOLD', '0.5', 'float', '0.5', 'Face recognition similarity threshold (0.0-1.0)', false)
ON CONFLICT (key) DO NOTHING;

-- ============================================================================
-- TOKEN BUDGET CONFIGURATION
-- ============================================================================

INSERT INTO system_config (category, key, value, value_type, default_value, description, requires_restart) VALUES
('tokens', 'MAX_CONVERSATION_TURNS', '30', 'int', '30', 'Maximum conversation turns to load (primary limit)', false),
('tokens', 'MAX_CONTEXT_TOKENS', '12000', 'int', '12000', 'Hard limit on total context tokens', false),
('tokens', 'MAX_TOTAL_MESSAGES', '100', 'int', '100', 'Absolute maximum messages (safety brake)', false),
('tokens', 'RESPONSE_BUDGET_TOKENS', '2500', 'int', '2500', 'Tokens reserved for model response', false),
('tokens', 'SYSTEM_PROMPT_BUDGET_TOKENS', '600', 'int', '600', 'Base system prompt budget', false),
('tokens', 'TRAITS_BUDGET_TOKENS', '200', 'int', '200', 'Character traits budget', false),
('tokens', 'TOOL_BUDGET_TOKENS', '2300', 'int', '2300', 'Tool definitions and results budget', false),
('tokens', 'CONVERSATION_BUDGET_TOKENS', '7000', 'int', '7000', 'Conversation history budget', false),
('tokens', 'MEMORY_BUDGET_TOKENS', '2500', 'int', '2500', 'Episodic memory budget', false)
ON CONFLICT (key) DO NOTHING;

-- ============================================================================
-- SESSION CONFIGURATION
-- ============================================================================

INSERT INTO system_config (category, key, value, value_type, default_value, description, requires_restart) VALUES
('session', 'SESSION_TIMEOUT_MINUTES', '30', 'int', '30', 'Create new session if gap exceeds this (minutes)', false),
('session', 'OLLAMA_CONTEXT_WINDOW', '32768', 'int', '32768', 'Ollama context window size (tokens)', true),
('session', 'VISION_ENABLED', 'true', 'bool', 'true', 'Enable vision capabilities', false)
ON CONFLICT (key) DO NOTHING;

-- ============================================================================
-- SYSTEM FEATURES
-- ============================================================================

INSERT INTO system_config (category, key, value, value_type, default_value, description, requires_restart) VALUES
('features', 'SYSTEM_INSTRUCTIONS', 'true', 'bool', 'true', 'Load system instructions from database', false),
('features', 'CHARACTER_TRAITS', 'true', 'bool', 'true', 'Include character traits in system prompt', false),
('features', 'EPISODIC_MEMORIES', 'true', 'bool', 'true', 'Load episodic memories', false),
('features', 'SHORT_TERM_FACTS', 'true', 'bool', 'true', 'Include short-term facts', false),
('features', 'DREAM_SYSTEM', 'true', 'bool', 'true', 'Enable dream consolidation system', false)
ON CONFLICT (key) DO NOTHING;

-- ============================================================================
-- KNOWLEDGE BASE CONFIGURATION
-- ============================================================================

INSERT INTO system_config (category, key, value, value_type, default_value, description, requires_restart) VALUES
('knowledge', 'KNOWLEDGE_MAX_CHUNK_TOKENS', '512', 'int', '512', 'Maximum tokens per knowledge chunk', false),
('knowledge', 'KNOWLEDGE_CHUNK_OVERLAP_TOKENS', '50', 'int', '50', 'Overlap between knowledge chunks (tokens)', false),
('knowledge', 'KNOWLEDGE_SIMILARITY_THRESHOLD', '0.30', 'float', '0.30', 'Minimum similarity for knowledge search results', false)
ON CONFLICT (key) DO NOTHING;

-- ============================================================================
-- OLLAMA CONFIGURATION (read-only, for display purposes)
-- ============================================================================

INSERT INTO system_config (category, key, value, value_type, default_value, description, requires_restart) VALUES
('ollama', 'OLLAMA_BASE_URL', 'http://localhost:11434', 'string', 'http://localhost:11434', 'Main Ollama API URL', true),
('ollama', 'OLLAMA_MODEL', 'qwen3:32b', 'string', 'qwen3:32b', 'Main Ollama model name', true),
('ollama', 'VISION_OLLAMA_URL', 'http://localhost:11435', 'string', 'http://localhost:11435', 'Vision Ollama API URL', true),
('ollama', 'OLLAMA_VISION_MODEL', 'llama3.2-vision:11b', 'string', 'llama3.2-vision:11b', 'Vision model name', true),
('ollama', 'OLLAMA_MEMORY_URL', 'http://localhost:11436', 'string', 'http://localhost:11436', 'Memory/embeddings Ollama URL', true),
('ollama', 'OLLAMA_MEMORY_MODEL', 'qwen2.5:14b', 'string', 'qwen2.5:14b', 'Memory/embeddings model name', true)
ON CONFLICT (key) DO NOTHING;

-- Verify insertion
SELECT category, COUNT(*) as config_count
FROM system_config
GROUP BY category
ORDER BY category;
