"""
Chat WebSocket subpackage — extracted from routes_chat.py

Modules:
    connection_manager  — ConnectionState, ConnectionManager, InterruptManager
    tool_executor       — Tool execution, truncation, spoiler/hallucination detection
    tts_handler         — XTTS calls, TTS/video background processor
    video_handler       — HLS streaming, video chunk queue, session management
    input_processor     — Vision, document, memory retrieval, emotional state
    turn_pipeline       — Core turn: streaming + tool loop + hallucination intervention
    system_endpoints    — /api/system/trigger, /api/contact_message, utilities
    observability       — Turn metrics, response embedding, memory influence scoring
"""

from .connection_manager import ConnectionState, ConnectionManager, InterruptManager
from .tool_executor import (
    truncate_tool_content, detect_tool_hallucination, get_tool_icon,
    execute_tool_calls, process_tool_results, check_spoilers,
)
from .tts_handler import call_xtts, tts_video_processor, initialize_tts, finalize_tts
from .video_handler import stream_batch_to_hls, queue_video_chunk, start_video_session_for_connection
from .input_processor import preprocess_user_turn, PreprocessResult
from .turn_pipeline import execute_turn, TurnResult
from .observability import finalize_response, capture_turn_metrics, send_kv_metrics, send_completion
