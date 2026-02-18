"""
Configuration for Iris v3

!! CLAUDE: DATABASE IS SOURCE OF TRUTH !!

This file contains ONLY bootstrap configuration needed to connect to PostgreSQL.
ALL runtime configuration loads from the system_config database table.

If you need to add/modify configuration:
1. Add to database: database/sql/populate_system_config_complete.sql
2. Run the SQL
3. Restart Iris

The config_loader injects all database values into this module on startup.
"""

import os

# ============================================
# DATABASE CONNECTION (Bootstrap - Required)
# ============================================
# These are the ONLY hardcoded values needed - to connect to the database
DB_HOST = "localhost"
DB_PORT = 5432
DB_NAME = "irisdb"
DB_USER = "irisuser"
# IMPORTANT: Use IRIS_DB_PASSWORD environment variable (required)
DB_PASSWORD = os.environ.get('IRIS_DB_PASSWORD', '')

# ============================================
# SERVER (Bootstrap - Required before DB load)
# ============================================
HOST = "0.0.0.0"
PORT = 8000

# ============================================
# PLACEHOLDER DEFAULTS
# ============================================
# These are set here ONLY so code doesn't crash before database injection.
# They will be OVERWRITTEN by database values on startup.
# If you see these values in use, database loading has failed!

# # LLM Backend (will be overwritten)
# OLLAMA_BASE_URL = "http://localhost:11434"
# OLLAMA_MODEL = "PLACEHOLDER_CHECK_DB"
# OLLAMA_CONTEXT_WINDOW = 32768

# # Remote Services (will be overwritten)
# FLOAT_SERVER_URL = "http://node2:8000"
# XTTS_SERVER_URL = "http://node2:8700"
# STT_SERVER_URL = "http://node2:8600"
# VISION_OLLAMA_URL = "http://node2:11435"
# MISTRAL_URL = "http://node2:11437/v1/chat/completions"

# # Feature Flags - MUST come from database
# SERVER_SIDE_TTS_ROUTING = None  # None = not loaded, will crash if DB fails (intentional)
# EMOTIONAL_STATE = None
# TOOLS_ENABLE = None

# # Identity (will be overwritten)
# IRIS_NAME = "Iris"
# VICTOR_NAME = "Victor"

# # Token Budgets (will be overwritten)
# CONTEXT_WINDOW = 32768
# SYSTEM_PROMPT_BASE_BUDGET = 600
# CHARACTER_TRAITS_BUDGET = 200
# RESPONSE_GENERATION_BUDGET = 2000
# EPISODIC_MEMORY_BUDGET = 2500
# EMOTIONAL_STATE_BUDGET = 200
# TOOL_DEFINITIONS_BUDGET = 1500
# TOOL_RESULTS_BUDGET = 15000
# CONVERSATION_HISTORY_BUDGET = 7000
# DOCUMENT_CONTEXT_BUDGET = 8000  # Max tokens for uploaded documents

# Fallback default for document processing
DOCUMENT_CONTEXT_BUDGET = 8000

# Node2 SSH access (will be overwritten by database)
NODE2_HOST = "node2"
NODE2_SSH_USER = "captain"

# Inference backend (llamacpp or sglang) - overwritten by database
INFERENCE_BACKEND = "llamacpp"

# Batch trim KV cache optimization - overwritten by database
BATCH_TRIM_ENABLED = True
BATCH_TRIM_SIZE = 5
BATCH_TRIM_HEADROOM_TOKENS = 4000

# Smart tool selection - only send relevant tools per snapshot window
SMART_TOOL_SELECTION = False

# # Session
# SESSION_TIMEOUT_MINUTES = 30

# # Context Management
# MAX_CONTEXT_TOKENS = 6000
# MAX_TOTAL_MESSAGES = 50
# SYSTEM_PROMPT_TOKEN_BUDGET = 2000
# RESPONSE_TOKEN_BUDGET = 2000
# CONTEXT_ROLES = ["user", "assistant", "tool"]
# CONTEXT_DEBUG = False

# # System Prompt Includes
# SYSTEM_INSTRUCTIONS = True
# CHARACTER_TRAITS = True
# SHORT_TERM_FACTS = True
# EPISODIC_MEMORIES = True
# ACTIVE_SEEDS = True
# TOOL_RESULTS = True

# Meeting transcription (fallback defaults - overwritten by database)
TRANSCRIBE_ENABLED = False
TRANSCRIBE_SERVER_URL = "http://node2:8500"

# Calendar (fallback defaults - overwritten by database)
CALENDAR_ENABLED = False
CALENDAR_REMINDER_WINDOW_HOURS = 6
CALENDAR_REMINDER_DEFAULT_HOURS_BEFORE = 4
CALENDAR_TIMEZONE = "America/New_York"
CALENDAR_GOOGLE_SYNC_ENABLED = False

# # Emotional State
# EMOTIONAL_DECAY_PER_TURN = 0.05
# EMOTIONAL_DECAY_PER_MINUTE = 0.02

# # Vision
# VISION_ENABLED = True
# VISION_MODEL = "llava-phi-3"
# OLLAMA_VISION_MODEL = "llama3.2-vision:11b"
# VISION_AUTO_UNLOAD_MINUTES = 5
# VISION_MAX_TOKENS = 1000
# VISION_MAX_IMAGE_SIZE_MB = 10
# VISION_MAX_IMAGES_PER_REQUEST = 5
# VISION_TIMEOUT_SECONDS = 30
# VISION_TEMPERATURE = 0.7
# VISION_DEBUG = False

# # Face Recognition
# FACE_RECOGNITION_MODEL = "buffalo_l"
# FACE_EMBEDDING_DIM = 512
# FACE_SIMILARITY_THRESHOLD = 0.5
# FACE_DETECTION_CONFIDENCE = 0.5
# FACE_MONITORING_ENABLED = True
# FACE_MONITORING_INTERVAL_SECONDS = 30
# FACE_GREETING_MIN_ABSENCE_MINUTES = 5
# FACE_GREETING_COOLDOWN_MINUTES = 15
# FACE_STORE_CAPTURED_FRAMES = False
# FACE_MAX_TRAINING_IMAGES = 20
# FACE_TRAINING_IMAGE_PATH = "attachments/face_training"
# FACE_CAPTURES_PATH = "attachments/face_captures"
# FACE_MAX_FACES_PER_FRAME = 10
# FACE_USE_GPU = False
# FACE_DETECTION_SIZE = (640, 640)
# FACE_NOTIFY_ON_ENTRY = True
# FACE_NOTIFY_ON_EXIT = False
# FACE_NOTIFY_UNKNOWN = True

# # Tool Limits
# MAX_SQL_RESULT_TOKENS = 3000

# # Memory Processing
# OLLAMA_MEMORY_MODEL = "Qwen2.5-32B-Instruct-Q5_K_M"
# OLLAMA_MEMORY_CONTEXT_WINDOW = 4096
# OLLAMA_MEMORY_URL = "http://localhost:11434"
# OLLAMA_TOOL_EVAL_URL = "http://localhost:11434"
# OLLAMA_TOOL_EVAL_MODEL = "Qwen2.5-32B-Instruct-Q5_K_M"
# OLLAMA_TOOL_EVAL_CONTEXT_WINDOW = 8192

# # Florence2 / PaddleOCR
# FLORENCE2_SERVER_URL = "http://node2:5100"
# FLORENCE2_MODE = "remote"
# PADDLEOCR_SERVER_URL = "http://node2:5200"

# # Freud
# FREUD_URL = "http://node2:11435"
# FREUD_MODEL = "gemma3:4b"

# # Knowledge/RAG (complex config - kept as placeholders)
# KNOWLEDGE_SCAN_DIRECTORIES = ["/iris-v3"]
# KNOWLEDGE_FILE_PATTERNS = {"code": ["*.py"], "docs": ["*.md"]}
# KNOWLEDGE_EXCLUDE_PATTERNS = ["__pycache__", ".git", "node_modules"]
# KNOWLEDGE_EXCLUDE_FILENAMES = ["__init__.py"]
# KNOWLEDGE_MAX_CHUNK_TOKENS = 512
# KNOWLEDGE_CHUNK_OVERLAP_TOKENS = 50
# KNOWLEDGE_MIN_CHUNK_TOKENS = 50
# KNOWLEDGE_EMBEDDING_BATCH_SIZE = 32
# KNOWLEDGE_EMBEDDING_FACETS = ["content", "context"]
# KNOWLEDGE_DEFAULT_SEARCH_LIMIT = 10
# KNOWLEDGE_MAX_SEARCH_LIMIT = 50
# KNOWLEDGE_SIMILARITY_THRESHOLD = 0.30
# KNOWLEDGE_TIER_THRESHOLDS = {1: 0.70, 2: 0.55, 3: 0.40, 4: 0.30}
# KNOWLEDGE_FACET_WEIGHTS = {"content": 0.6, "context": 0.4}
# KNOWLEDGE_INCREMENTAL_INDEXING = True
# KNOWLEDGE_HASH_CHECK = True
# KNOWLEDGE_MAX_FILE_SIZE_MB = 10
# KNOWLEDGE_PDF_ENABLED = True
# KNOWLEDGE_PDF_MAX_PAGES = 500

# # Legacy compatibility
# MAX_CONVERSATION_TURNS = 500
# FIXED_BUDGET = SYSTEM_PROMPT_BASE_BUDGET + CHARACTER_TRAITS_BUDGET + RESPONSE_GENERATION_BUDGET
# DYNAMIC_BUDGET = (EPISODIC_MEMORY_BUDGET + EMOTIONAL_STATE_BUDGET +
#                   TOOL_DEFINITIONS_BUDGET + TOOL_RESULTS_BUDGET +
#                   CONVERSATION_HISTORY_BUDGET)
# TOTAL_ALLOCATED = FIXED_BUDGET + DYNAMIC_BUDGET
# SAFETY_MARGIN = CONTEXT_WINDOW - TOTAL_ALLOCATED


# ============================================
# DATABASE CONFIG INJECTION
# ============================================

def load_database_config():
    """
    Load configuration from database and inject into this module.
    Called automatically on startup.

    This OVERWRITES all placeholder values above with real database values.
    """
    try:
        import sys
        PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        sys.path.insert(0, PROJECT_ROOT)

        from database.config_loader import inject_into_module
        import app.config as config_module

        # Inject database values into this module
        inject_into_module(config_module)

        # Verify critical values were loaded
        if getattr(config_module, 'SERVER_SIDE_TTS_ROUTING', None) is None:
            print("[config.py] !! CRITICAL: SERVER_SIDE_TTS_ROUTING not loaded from database!")
            print("[config.py] !! Check that system_config table has this key")
            config_module.SERVER_SIDE_TTS_ROUTING = False  # Safe default

        return True
    except Exception as e:
        print(f"[config.py] !! CRITICAL: Failed to load database config: {e}")
        print(f"[config.py] !! Server may not function correctly!")
        import traceback
        traceback.print_exc()
        return False


# Auto-load on import
_DB_CONFIG_LOADED = load_database_config()

if not _DB_CONFIG_LOADED:
    print("[config.py] !! WARNING: Running with placeholder config - check database connection!")
