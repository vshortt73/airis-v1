"""
Configuration for Iris v3
All settings explicitly defined
"""

# ============================================
# OLLAMA CONFIGURATION
# ============================================
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL = "qwen3:32b"
OLLAMA_CONTEXT_WINDOW = 32768  # CRITICAL: Never use default 4096

# ============================================
# SERVER CONFIGURATION
# ============================================
HOST = "0.0.0.0"
PORT = 8000

# ============================================
# IDENTITY
# ============================================
IRIS_NAME = "Iris"
VICTOR_NAME = "Victor"

# ============================================
# SESSION MANAGEMENT
# ============================================
SESSION_TIMEOUT_MINUTES = 30  # Create new session if gap exceeds this

# ============================================
# TOKEN BUDGET ALLOCATION
# ============================================
# Total available context window
CONTEXT_WINDOW = OLLAMA_CONTEXT_WINDOW  # 16384 tokens

# Fixed allocations (cannot be truncated)
SYSTEM_PROMPT_BASE_BUDGET = 600         # Base identity paragraph
CHARACTER_TRAITS_BUDGET = 200           # All 144 traits (estimated)
RESPONSE_GENERATION_BUDGET = 2500       # Room for Iris to respond

# Dynamic allocations (can be truncated with priority)
# Priority 1 (High) - Truncate last
EPISODIC_MEMORY_BUDGET = 2500           # Retrieved memories from past
EMOTIONAL_STATE_BUDGET = 200            # Current emotional context

# Priority 2 (Medium) - Truncate second
TOOL_DEFINITIONS_BUDGET = 1500          # Tool schemas/descriptions
TOOL_RESULTS_BUDGET = 800               # Recent tool call results

# Priority 3 (Low) - Truncate first
CONVERSATION_HISTORY_BUDGET = 7000      # Recent conversation turns

# Calculate totals
FIXED_BUDGET = (SYSTEM_PROMPT_BASE_BUDGET + CHARACTER_TRAITS_BUDGET + 
                RESPONSE_GENERATION_BUDGET)
DYNAMIC_BUDGET = (EPISODIC_MEMORY_BUDGET + EMOTIONAL_STATE_BUDGET + 
                  TOOL_DEFINITIONS_BUDGET + TOOL_RESULTS_BUDGET + 
                  CONVERSATION_HISTORY_BUDGET)
TOTAL_ALLOCATED = FIXED_BUDGET + DYNAMIC_BUDGET

# Safety margin
SAFETY_MARGIN = CONTEXT_WINDOW - TOTAL_ALLOCATED



# ============================================
# CONTEXT MANAGEMENT
# ============================================

# Primary limit: conversation turns (user+assistant pairs)
MAX_CONVERSATION_TURNS = 15

# Safety limits: prevent context overflow
MAX_CONTEXT_TOKENS = 12000        # Hard token limit for conversation history
MAX_TOTAL_MESSAGES = 100          # Absolute message count limit (safety net)

# Context budget allocation (total: 16384 tokens)
SYSTEM_PROMPT_TOKEN_BUDGET = 2000  # Reserve for system prompt
RESPONSE_TOKEN_BUDGET = 2000       # Reserve for model response
# Remaining ~12,384 tokens available for conversation

# Role filtering
CONTEXT_ROLES = ["user", "assistant", "tool"]  # Which roles to load

# Debug mode
CONTEXT_DEBUG = False              # Log detailed token counting info

# ============================================
# SYSTEM PROMPT INCLUDES
# ============================================
SYSTEM_INSTRUCTIONS = True
CHARACTER_TRAITS = True
EPISODIC_MEMORIES = True
TOOLS_ENABLE = True
TOOL_RESULTS = True


# ============================================
# DATABASE CONFIGURATION
# ============================================
DB_HOST = "localhost"
DB_PORT = 5432
DB_NAME = "irisdb"
DB_USER = "irisuser"
# IMPORTANT: Use IRIS_DB_PASSWORD environment variable instead of hardcoding
# DB_PASSWORD is a fallback only - DO NOT commit real credentials
DB_PASSWORD = None  # Always use IRIS_DB_PASSWORD environment variable
