-- ============================================================================
-- COMPLETE SYSTEM CONFIGURATION POPULATION
-- ============================================================================
-- This script ensures ALL config.py parameters are in the database.
-- The database is the source of truth - config.py values are fallbacks only.
--
-- Run this to sync all parameters. Uses ON CONFLICT to safely upsert.
-- ============================================================================

-- ============================================================================
-- LLM BACKEND CONFIGURATION
-- ============================================================================

INSERT INTO system_config (category, key, value, value_type, default_value, description, requires_restart) VALUES
('llm', 'OLLAMA_BASE_URL', 'http://localhost:11434', 'string', 'http://localhost:11434', 'Main Ollama/llama-server endpoint', true),
('llm', 'OLLAMA_MODEL', 'Qwen2.5-32B-Instruct-Q5_K_M', 'string', 'Qwen2.5-32B-Instruct-Q5_K_M', 'Primary inference model name', true),
('llm', 'OLLAMA_CONTEXT_WINDOW', '32768', 'int', '32768', 'Server-side context window size (tokens)', true),
('llm', 'OLLAMA_MEMORY_MODEL', 'Qwen2.5-32B-Instruct-Q5_K_M', 'string', 'Qwen2.5-32B-Instruct-Q5_K_M', 'Memory processing model', true),
('llm', 'OLLAMA_MEMORY_CONTEXT_WINDOW', '4096', 'int', '4096', 'Memory model context window', true),
('llm', 'OLLAMA_MEMORY_URL', 'http://localhost:11434', 'string', 'http://localhost:11434', 'Memory processing endpoint', true),
('llm', 'OLLAMA_TOOL_EVAL_URL', 'http://localhost:11434', 'string', 'http://localhost:11434', 'Tool evaluation endpoint', true),
('llm', 'OLLAMA_TOOL_EVAL_MODEL', 'Qwen2.5-32B-Instruct-Q5_K_M', 'string', 'Qwen2.5-32B-Instruct-Q5_K_M', 'Tool evaluation model', true),
('llm', 'OLLAMA_TOOL_EVAL_CONTEXT_WINDOW', '8192', 'int', '8192', 'Tool evaluation context window', true)
ON CONFLICT (key) DO UPDATE SET
    value = EXCLUDED.value,
    description = EXCLUDED.description,
    last_modified = NOW();

-- ============================================================================
-- SERVER CONFIGURATION
-- ============================================================================

INSERT INTO system_config (category, key, value, value_type, default_value, description, requires_restart) VALUES
('server', 'HOST', '0.0.0.0', 'string', '0.0.0.0', 'Server bind address', true),
('server', 'PORT', '8000', 'int', '8000', 'Server port', true)
ON CONFLICT (key) DO UPDATE SET
    value = EXCLUDED.value,
    description = EXCLUDED.description,
    last_modified = NOW();

-- ============================================================================
-- REMOTE SERVICES (Node2)
-- ============================================================================

INSERT INTO system_config (category, key, value, value_type, default_value, description, requires_restart) VALUES
('remote_services', 'FLOAT_SERVER_URL', 'http://node2:8000', 'string', 'http://node2:8000', 'FLOAT video generation server (Node2 GPU 0)', true),
('remote_services', 'XTTS_SERVER_URL', 'http://node2:8700', 'string', 'http://node2:8700', 'XTTS text-to-speech server (Node2 GPU 1)', true),
('remote_services', 'STT_SERVER_URL', 'http://node2:8600', 'string', 'http://node2:8600', 'Whisper speech-to-text server (Node2 GPU 1)', true),
('remote_services', 'VISION_OLLAMA_URL', 'http://node2:11435', 'string', 'http://node2:11435', 'Vision model endpoint (Node2 GPU 0)', true),
('remote_services', 'OLLAMA_VISION_MODEL', 'llama3.2-vision:11b', 'string', 'llama3.2-vision:11b', 'Vision model name', true),
('remote_services', 'FLORENCE2_SERVER_URL', 'http://node2:5100', 'string', 'http://node2:5100', 'Florence2 vision server', true),
('remote_services', 'FLORENCE2_MODE', 'remote', 'string', 'remote', 'Florence2 mode: remote or local', false),
('remote_services', 'PADDLEOCR_SERVER_URL', 'http://node2:5200', 'string', 'http://node2:5200', 'PaddleOCR server for deck plans/maps', true),
('remote_services', 'FREUD_URL', 'http://node2:11435', 'string', 'http://node2:11435', 'Freud dream guide endpoint (Node2 GPU 0)', true),
('remote_services', 'FREUD_MODEL', 'gemma3:4b', 'string', 'gemma3:4b', 'Dream processing model', true),
('remote_services', 'MISTRAL_URL', 'http://node2:11437/v1/chat/completions', 'string', 'http://node2:11437/v1/chat/completions', 'Mistral sentiment analysis endpoint (Node2 GPU 1)', true),
('remote_services', 'COMFYUI_SERVER_URL', 'http://node2:8189', 'string', 'http://node2:8189', 'ComfyUI API endpoint (Node2)', true),
('remote_services', 'COMFYUI_OUTPUT_PATH', '/home/captain/node2-mount/programs/ComfyUI/output', 'string', '/home/captain/node2-mount/programs/ComfyUI/output', 'ComfyUI output directory (NFS mount from Node2)', true),
('remote_services', 'NODE2_HOST', 'node2', 'string', 'node2', 'Node2 hostname or IP for SSH and health checks', true),
('remote_services', 'NODE2_SSH_USER', 'captain', 'string', 'captain', 'SSH username for Node2 operations', true)
ON CONFLICT (key) DO UPDATE SET
    value = EXCLUDED.value,
    description = EXCLUDED.description,
    last_modified = NOW();

-- ============================================================================
-- IDENTITY
-- ============================================================================

INSERT INTO system_config (category, key, value, value_type, default_value, description, requires_restart) VALUES
('identity', 'IRIS_NAME', 'Iris', 'string', 'Iris', 'AI assistant name', false),
('identity', 'VICTOR_NAME', 'Victor', 'string', 'Victor', 'Primary user name', false)
ON CONFLICT (key) DO UPDATE SET
    value = EXCLUDED.value,
    description = EXCLUDED.description,
    last_modified = NOW();

-- ============================================================================
-- SESSION MANAGEMENT
-- ============================================================================

INSERT INTO system_config (category, key, value, value_type, default_value, description, requires_restart) VALUES
('session', 'SESSION_TIMEOUT_MINUTES', '30', 'int', '30', 'Create new session if conversation gap exceeds this (minutes)', false)
ON CONFLICT (key) DO UPDATE SET
    value = EXCLUDED.value,
    description = EXCLUDED.description,
    last_modified = NOW();

-- ============================================================================
-- TOKEN BUDGET ALLOCATION
-- ============================================================================

INSERT INTO system_config (category, key, value, value_type, default_value, description, requires_restart) VALUES
-- Fixed allocations
('tokens', 'CONTEXT_WINDOW', '32768', 'int', '32768', 'Total available context window (mirrors OLLAMA_CONTEXT_WINDOW)', false),
('tokens', 'SYSTEM_PROMPT_BASE_BUDGET', '600', 'int', '600', 'Base identity paragraph tokens', false),
('tokens', 'CHARACTER_TRAITS_BUDGET', '200', 'int', '200', 'Character traits tokens', false),
('tokens', 'RESPONSE_GENERATION_BUDGET', '2000', 'int', '2000', 'Room for Iris to respond', false),
-- Dynamic allocations (Priority 1 - High)
('tokens', 'EPISODIC_MEMORY_BUDGET', '2500', 'int', '2500', 'Retrieved memories from past', false),
('tokens', 'EMOTIONAL_STATE_BUDGET', '200', 'int', '200', 'Current emotional context', false),
-- Dynamic allocations (Priority 2 - Medium)
('tokens', 'TOOL_DEFINITIONS_BUDGET', '1500', 'int', '1500', 'Tool schemas/descriptions', false),
('tokens', 'TOOL_RESULTS_BUDGET', '15000', 'int', '15000', 'Recent tool call results', false),
-- Dynamic allocations (Priority 3 - Low)
('tokens', 'CONVERSATION_HISTORY_BUDGET', '7000', 'int', '7000', 'Recent conversation turns', false),
-- Safety limits
('tokens', 'MAX_CONVERSATION_TURNS', '500', 'int', '500', 'Legacy limit (deprecated - kept for compatibility)', false),
('tokens', 'MAX_CONTEXT_TOKENS', '6000', 'int', '6000', 'Conversation history token limit', false),
('tokens', 'MAX_TOTAL_MESSAGES', '50', 'int', '50', 'Absolute maximum messages (safety brake)', false),
('tokens', 'SYSTEM_PROMPT_TOKEN_BUDGET', '2000', 'int', '2000', 'Reserve for system prompt', false),
('tokens', 'RESPONSE_TOKEN_BUDGET', '2000', 'int', '2000', 'Reserve for model response', false),
('tokens', 'MAX_SQL_RESULT_TOKENS', '3000', 'int', '3000', 'Token limit for SQL query results', false)
ON CONFLICT (key) DO UPDATE SET
    value = EXCLUDED.value,
    description = EXCLUDED.description,
    last_modified = NOW();

-- ============================================================================
-- SYSTEM PROMPT INCLUDES (Feature Flags)
-- ============================================================================

INSERT INTO system_config (category, key, value, value_type, default_value, description, requires_restart) VALUES
('features', 'SYSTEM_INSTRUCTIONS', 'true', 'bool', 'true', 'Load system instructions from database', false),
('features', 'CHARACTER_TRAITS', 'true', 'bool', 'true', 'Include character traits in prompt', false),
('features', 'SHORT_TERM_FACTS', 'true', 'bool', 'true', 'Include recent manually flagged facts', false),
('features', 'EPISODIC_MEMORIES', 'true', 'bool', 'true', 'Include episodic memories', false),
('features', 'EMOTIONAL_STATE', 'true', 'bool', 'true', 'Dynamic emotional state tracking', false),
('features', 'ACTIVE_SEEDS', 'true', 'bool', 'true', 'Include active seeds from Motivation Engine', false),
('features', 'TOOLS_ENABLE', 'true', 'bool', 'true', 'Enable tool calling', false),
('features', 'TOOL_RESULTS', 'true', 'bool', 'true', 'Include tool results in context', false),
('features', 'CONTEXT_DEBUG', 'false', 'bool', 'false', 'Log detailed token counting info', false)
ON CONFLICT (key) DO UPDATE SET
    value = EXCLUDED.value,
    description = EXCLUDED.description,
    last_modified = NOW();

-- ============================================================================
-- NODE2 OPTIONAL FLAGS
-- ============================================================================

INSERT INTO system_config (category, key, value, value_type, default_value, description, requires_restart) VALUES
('features', 'NODE2_ENABLED', 'false', 'bool', 'false', 'Master toggle for Node2 GPU server. When false, all Node2-dependent services are disabled.', true),
('features', 'STT_ENABLED', 'false', 'bool', 'false', 'Enable speech-to-text (Whisper on Node2). Requires NODE2_ENABLED.', false),
('features', 'TTS_ENABLED', 'false', 'bool', 'false', 'Enable text-to-speech (XTTS on Node2). Requires NODE2_ENABLED.', false),
('features', 'VIDEO_ENABLED', 'false', 'bool', 'false', 'Enable FLOAT video generation (Node2 GPU 0). Requires NODE2_ENABLED.', false),
('features', 'GPU_MANAGER_ENABLED', 'false', 'bool', 'false', 'Enable Node2 GPU manager for service coordination. Requires NODE2_ENABLED.', false),
('features', 'FLORENCE2_ENABLED', 'false', 'bool', 'false', 'Enable Florence2 vision model (Node2). Requires NODE2_ENABLED.', false),
('features', 'PADDLEOCR_ENABLED', 'false', 'bool', 'false', 'Enable PaddleOCR service (Node2). Requires NODE2_ENABLED.', false),
('features', 'DREAMS_ENABLED', 'false', 'bool', 'false', 'Enable dream processing (Freud on Node2). Requires NODE2_ENABLED.', false)
ON CONFLICT (key) DO UPDATE SET
    value = EXCLUDED.value,
    description = EXCLUDED.description,
    last_modified = NOW();

-- ============================================================================
-- EMOTIONAL STATE TRACKING
-- ============================================================================

INSERT INTO system_config (category, key, value, value_type, default_value, description, requires_restart) VALUES
('emotional', 'EMOTIONAL_DECAY_PER_TURN', '0.05', 'float', '0.05', 'Decay toward baseline per turn (5%)', false),
('emotional', 'EMOTIONAL_DECAY_PER_MINUTE', '0.02', 'float', '0.02', 'Decay toward baseline per minute (2%)', false)
ON CONFLICT (key) DO UPDATE SET
    value = EXCLUDED.value,
    description = EXCLUDED.description,
    last_modified = NOW();

-- ============================================================================
-- VISION SYSTEM CONFIGURATION
-- ============================================================================

INSERT INTO system_config (category, key, value, value_type, default_value, description, requires_restart) VALUES
('vision', 'VISION_ENABLED', 'true', 'bool', 'true', 'Enable vision capabilities', false),
('vision', 'VISION_MODEL', 'llava-phi-3', 'string', 'llava-phi-3', 'Vision model name', true),
('vision', 'VISION_AUTO_UNLOAD_MINUTES', '5', 'int', '5', 'Unload vision after idle time (minutes)', false),
('vision', 'VISION_MAX_TOKENS', '1000', 'int', '1000', 'Max tokens per image analysis', false),
('vision', 'VISION_MAX_IMAGE_SIZE_MB', '10', 'int', '10', 'Max image size for processing (MB)', false),
('vision', 'VISION_MAX_IMAGES_PER_REQUEST', '5', 'int', '5', 'Maximum images per batch', false),
('vision', 'VISION_TIMEOUT_SECONDS', '30', 'int', '30', 'Per-image timeout (seconds)', false),
('vision', 'VISION_TEMPERATURE', '0.7', 'float', '0.7', 'Sampling temperature for vision model', false),
('vision', 'VISION_DEBUG', 'false', 'bool', 'false', 'Verbose vision logging', false)
ON CONFLICT (key) DO UPDATE SET
    value = EXCLUDED.value,
    description = EXCLUDED.description,
    last_modified = NOW();

-- ============================================================================
-- FACE RECOGNITION CONFIGURATION
-- ============================================================================

INSERT INTO system_config (category, key, value, value_type, default_value, description, requires_restart) VALUES
-- Model settings
('face', 'FACE_RECOGNITION_MODEL', 'buffalo_l', 'string', 'buffalo_l', 'InsightFace ArcFace model', true),
('face', 'FACE_EMBEDDING_DIM', '512', 'int', '512', 'ArcFace embedding dimension', true),
-- Recognition thresholds
('face', 'FACE_SIMILARITY_THRESHOLD', '0.5', 'float', '0.5', 'Minimum similarity for person match (0-1)', false),
('face', 'FACE_DETECTION_CONFIDENCE', '0.5', 'float', '0.5', 'Minimum confidence for face detection (0-1)', false),
-- Background monitoring
('face', 'FACE_MONITORING_ENABLED', 'true', 'bool', 'true', 'Enable periodic camera monitoring', false),
('face', 'FACE_MONITORING_INTERVAL_SECONDS', '30', 'int', '30', 'Check cameras every N seconds', false),
-- Greeting thresholds
('face', 'FACE_GREETING_MIN_ABSENCE_MINUTES', '5', 'int', '5', 'Minimum absence to trigger greeting (minutes)', false),
('face', 'FACE_GREETING_COOLDOWN_MINUTES', '15', 'int', '15', 'Minimum time between greetings (minutes)', false),
-- Image storage
('face', 'FACE_STORE_CAPTURED_FRAMES', 'false', 'bool', 'false', 'Save frames when faces detected (privacy)', false),
('face', 'FACE_MAX_TRAINING_IMAGES', '20', 'int', '20', 'Maximum training images per person', false),
('face', 'FACE_TRAINING_IMAGE_PATH', 'attachments/face_training', 'string', 'attachments/face_training', 'Training image directory', true),
('face', 'FACE_CAPTURES_PATH', 'attachments/face_captures', 'string', 'attachments/face_captures', 'Captured frame directory', true),
-- Performance settings
('face', 'FACE_MAX_FACES_PER_FRAME', '10', 'int', '10', 'Maximum faces to detect per frame', false),
('face', 'FACE_USE_GPU', 'false', 'bool', 'false', 'Use GPU for face recognition (CPU only recommended)', false),
('face', 'FACE_DETECTION_SIZE', '[640, 640]', 'json', '[640, 640]', 'Detection input size [width, height]', false),
-- Notification settings
('face', 'FACE_NOTIFY_ON_ENTRY', 'true', 'bool', 'true', 'Notify when person enters', false),
('face', 'FACE_NOTIFY_ON_EXIT', 'false', 'bool', 'false', 'Notify when person exits', false),
('face', 'FACE_NOTIFY_UNKNOWN', 'true', 'bool', 'true', 'Notify on unknown face detection', false)
ON CONFLICT (key) DO UPDATE SET
    value = EXCLUDED.value,
    description = EXCLUDED.description,
    last_modified = NOW();

-- ============================================================================
-- KNOWLEDGE/RAG SYSTEM CONFIGURATION
-- ============================================================================

INSERT INTO system_config (category, key, value, value_type, default_value, description, requires_restart) VALUES
-- Directories and patterns (JSON arrays)
('knowledge', 'KNOWLEDGE_SCAN_DIRECTORIES', '["/iris-v3", "/programs/ComfyUI", "/programs/float", "/programs/llama.cpp", "/programs/xtts"]', 'json', '["/iris-v3"]', 'Directories to index (absolute paths)', true),
('knowledge', 'KNOWLEDGE_FILE_PATTERNS', '{"code": ["*.py", "*.js", "*.ts", "*.jsx", "*.sh", "*.yaml", "*.yml"], "docs": ["*.md", "*.rst", "*.org"], "pdf": ["*.pdf"]}', 'json', '{}', 'File type patterns by category', true),
('knowledge', 'KNOWLEDGE_EXCLUDE_PATTERNS', '["__pycache__", ".git", "node_modules", ".venv", "venv", ".pytest_cache", "build", "dist", ".egg-info", "*.pyc", ".DS_Store"]', 'json', '[]', 'Path patterns to exclude', true),
('knowledge', 'KNOWLEDGE_EXCLUDE_FILENAMES', '["__init__.py", "__main__.py", "setup.py", "conftest.py", ".gitignore", ".gitkeep", "package-lock.json", "yarn.lock"]', 'json', '[]', 'Exact filenames to exclude', true),
-- Chunking parameters
('knowledge', 'KNOWLEDGE_MAX_CHUNK_TOKENS', '512', 'int', '512', 'Max tokens per chunk', false),
('knowledge', 'KNOWLEDGE_CHUNK_OVERLAP_TOKENS', '50', 'int', '50', 'Overlap between chunks for continuity', false),
('knowledge', 'KNOWLEDGE_MIN_CHUNK_TOKENS', '50', 'int', '50', 'Minimum chunk size (avoid tiny fragments)', false),
-- Embedding configuration
('knowledge', 'KNOWLEDGE_EMBEDDING_BATCH_SIZE', '32', 'int', '32', 'Batch size for embedding generation', false),
('knowledge', 'KNOWLEDGE_EMBEDDING_FACETS', '["content", "context"]', 'json', '["content", "context"]', 'Multi-facet embeddings', false),
-- Search parameters
('knowledge', 'KNOWLEDGE_DEFAULT_SEARCH_LIMIT', '10', 'int', '10', 'Default results per search', false),
('knowledge', 'KNOWLEDGE_MAX_SEARCH_LIMIT', '50', 'int', '50', 'Maximum results allowed', false),
('knowledge', 'KNOWLEDGE_SIMILARITY_THRESHOLD', '0.30', 'float', '0.30', 'Minimum cosine similarity', false),
-- Tiered results
('knowledge', 'KNOWLEDGE_TIER_THRESHOLDS', '{"1": 0.70, "2": 0.55, "3": 0.40, "4": 0.30}', 'json', '{}', 'Tier thresholds for result categorization', false),
('knowledge', 'KNOWLEDGE_FACET_WEIGHTS', '{"content": 0.6, "context": 0.4}', 'json', '{}', 'Facet weighting for multi-facet similarity', false),
-- Indexing behavior
('knowledge', 'KNOWLEDGE_INCREMENTAL_INDEXING', 'true', 'bool', 'true', 'Only re-index changed files', false),
('knowledge', 'KNOWLEDGE_HASH_CHECK', 'true', 'bool', 'true', 'Use SHA256 to detect content changes', false),
('knowledge', 'KNOWLEDGE_MAX_FILE_SIZE_MB', '10', 'int', '10', 'Skip files larger than this (MB)', false),
-- PDF processing
('knowledge', 'KNOWLEDGE_PDF_ENABLED', 'true', 'bool', 'true', 'Enable PDF processing', false),
('knowledge', 'KNOWLEDGE_PDF_MAX_PAGES', '500', 'int', '500', 'Skip very large PDFs', false)
ON CONFLICT (key) DO UPDATE SET
    value = EXCLUDED.value,
    description = EXCLUDED.description,
    last_modified = NOW();

-- ============================================================================
-- CONTEXT MANAGEMENT
-- ============================================================================

INSERT INTO system_config (category, key, value, value_type, default_value, description, requires_restart) VALUES
('context', 'CONTEXT_ROLES', '["user", "assistant", "tool"]', 'json', '["user", "assistant", "tool"]', 'Which roles to load into context', false)
ON CONFLICT (key) DO UPDATE SET
    value = EXCLUDED.value,
    description = EXCLUDED.description,
    last_modified = NOW();

-- ============================================================================
-- FILE PATHS (localhost)
-- ============================================================================

-- Client box paths only. No inference engines, no GPU model paths, no Node2.
INSERT INTO system_config (category, key, value, value_type, default_value, description, requires_restart) VALUES
('paths', 'PROJECT_ROOT', '/airis-v1', 'string', '/airis-v1', 'Project installation directory', true),
('paths', 'VENV_PATH', '/venv/airis', 'string', '/venv/airis', 'Python virtual environment path', true),
('paths', 'EMBEDDING_MODEL_PATH', '/models/llm_models/huggingface/models/all-mpnet-base-v2/', 'string', '/models/llm_models/huggingface/models/all-mpnet-base-v2/', 'Sentence transformer embedding model', true),
('paths', 'SSL_CERT_PATH', '/airis-v1/ssl/cert.pem', 'string', '/airis-v1/ssl/cert.pem', 'SSL certificate for HTTPS (if used)', true)
ON CONFLICT (key) DO UPDATE SET
    value = EXCLUDED.value,
    description = EXCLUDED.description,
    last_modified = NOW();

-- ============================================================================
-- VERIFICATION
-- ============================================================================

-- Show category counts
SELECT category, COUNT(*) as config_count
FROM system_config
GROUP BY category
ORDER BY category;

-- Total count
SELECT COUNT(*) as total_config_values FROM system_config;
