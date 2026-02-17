"""
Chat WebSocket API route with comprehensive logging and single-call streaming pattern

ARCHITECTURE: Single Streaming Call with Tools (KV cache optimized)
1. STREAMING call with tools → model streams content AND/OR calls tools
2. If tools called: execute them, add results, then follow-up streaming call
3. Only ONE call per turn when no tools needed (majority of turns)

This maximizes KV cache efficiency by using consistent full context.
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from dataclasses import dataclass, field
from typing import Optional, Dict, List
from datetime import datetime
import json
import os
import sys
import asyncio
import re
import base64
import httpx
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, PROJECT_ROOT)
from core.system_prompt import assemble_full_context, assemble_unified_context, get_active_protocol
from inference.client import chat_completion_stream, chat_completion_with_tools, chat_completion_stream_with_tools, chat_completion_forced_tool_call
from mcp_servers.tool_manager import get_tool_manager
from database.persistence import get_db_connection, load_recent_conversation
from database.fast_reactive_memory import FastReactiveMemory
from core.vision_manager import analyze_images_for_conversation
from core.document_processor import process_documents_for_conversation
from core.document_indexer import index_document_to_knowledge_base
from core.emotional_state import get_emotional_tracker
from core.websocket_broadcast import set_broadcast_function
from core.want_detector import process_response_async as detect_wants
from core.sentence_processor import SentenceProcessor, OutputMode, TextBatch
from app import config
from core.node2_check import is_node2_service_enabled
from core.token_counter import TokenCounter

# ---------------------------------------------------------------------------
# Tool result truncation with cumulative budget tracking
# ---------------------------------------------------------------------------
# Per-result cap: no single tool result exceeds this (tokens)
_PER_TOOL_RESULT_CAP = None  # Loaded from config on first use

# Cumulative cap: total tokens across ALL tool results in one turn
# Keeps tool output from consuming the entire context window
_CUMULATIVE_TOOL_CAP = None  # 50% of context window, computed on first use


def _get_tool_caps():
    """Lazy-load tool result budget caps from config."""
    global _PER_TOOL_RESULT_CAP, _CUMULATIVE_TOOL_CAP
    if _PER_TOOL_RESULT_CAP is None:
        _PER_TOOL_RESULT_CAP = getattr(config, 'TOOL_RESULTS_BUDGET', 15000)
        ctx = getattr(config, 'OLLAMA_CONTEXT_WINDOW', 40960)
        _CUMULATIVE_TOOL_CAP = int(ctx * 0.50)
    return _PER_TOOL_RESULT_CAP, _CUMULATIVE_TOOL_CAP


def truncate_tool_content(tool_content: str, cumulative_tokens_used: int) -> tuple:
    """
    Truncate a single tool result, respecting both per-result and cumulative caps.

    Args:
        tool_content: The tool result string to (maybe) truncate
        cumulative_tokens_used: Total tool result tokens already consumed this turn

    Returns:
        (truncated_content, token_count) — the content and how many tokens it uses
    """
    per_cap, cumul_cap = _get_tool_caps()

    token_count = TokenCounter.count_tokens(tool_content)

    # How many tokens remain in the cumulative budget?
    remaining = max(0, cumul_cap - cumulative_tokens_used)

    # Effective cap is the stricter of per-result and remaining cumulative
    effective_cap = min(per_cap, remaining)

    if token_count <= effective_cap:
        return tool_content, token_count

    # Need to truncate
    target = max(500, effective_cap - 50)  # Leave room for notice, min 500 tokens
    encoder = TokenCounter.get_encoder()
    encoded = encoder.encode(tool_content)
    truncated = encoder.decode(encoded[:target])
    truncated += (
        f"\n\n[TRUNCATED — Result exceeded token budget "
        f"({token_count:,} tokens, cap {effective_cap:,}). "
        f"Data above is incomplete. Do not fabricate the missing portion.]"
    )
    final_count = TokenCounter.count_tokens(truncated)
    print(f"[routes_chat.py] ⚠ Tool result truncated: {token_count:,} → {final_count:,} tokens "
          f"(per-result cap: {per_cap:,}, cumulative remaining: {remaining:,})")
    return truncated, final_count


# ---------------------------------------------------------------------------
# Tool hallucination detection
# ---------------------------------------------------------------------------
# When the model narrates tool usage in prose instead of making actual tool
# calls, the response contaminates context and creates a self-reinforcing
# loop. This detector catches that pattern so the caller can retry.

def _detect_tool_hallucination(response: str, tool_names: list) -> bool:
    """Detect when model narrates tool usage without actually calling tools.

    Returns True if the response contains strong signals of fabricated tool use:
    the model describes using specific tools by name in present/future tense
    without making actual API calls.

    The threshold is intentionally sensitive — a false positive only costs one
    retry, while a false negative saves a hallucinated response to context and
    worsens the self-reinforcing pattern.
    """
    if not response or len(response) < 40:
        return False

    response_lower = response.lower()

    # Narration phrases that precede or surround tool names
    narration_phrases = [
        "i'll use", "let me use", "i'm using", "i will use", "i'm going to use",
        "i'll call", "let me call", "i'm calling", "i will call",
        "let me search", "i'll search", "i'm searching", "i will search",
        "let me look up", "i'll look up", "i'm looking up",
        "let me fetch", "i'll fetch", "i'm fetching",
        "let me check", "i'll check", "i'm checking",
        "let me retrieve", "i'll retrieve", "i'm retrieving",
        "using the", "calling the", "invoking the",
    ]

    indicators = 0

    # Check 1: Known tool names mentioned in narration context
    tool_set = {name.lower() for name in tool_names if name}
    for tool_name in tool_set:
        if tool_name not in response_lower:
            continue

        idx = 0
        while True:
            idx = response_lower.find(tool_name, idx)
            if idx == -1:
                break

            # Get surrounding context
            before = response_lower[max(0, idx - 80):idx]
            after = response_lower[idx:min(len(response_lower), idx + len(tool_name) + 60)]

            if any(phrase in before or phrase in after for phrase in narration_phrases):
                indicators += 1

            idx += len(tool_name) + 1

    # Check 2: Generic "tool" narration patterns (no specific name needed)
    generic_patterns = [
        r"(?:i'll|let me|i'm going to|i will)\s+(?:use|call|invoke|run)\s+(?:the\s+)?\w+\s+tool",
        r"(?:i'll|let me|i'm going to|i will)\s+(?:search|look up|fetch|retrieve)\s+(?:that|this|the|some|for)",
    ]
    for pattern in generic_patterns:
        if re.search(pattern, response_lower):
            indicators += 1

    if indicators >= 1:
        # Log matched indicators for debugging
        print(f"[routes_chat.py] ⚠ TOOL HALLUCINATION DETECTED ({indicators} indicator(s))")
        return True

    return False


# PHASE 2: Use unified context (KV cache optimized) instead of tiered query classifier
# Setting this to True enables the new unified prompt system
# DISABLED: Causing tool calling issues - needs investigation
USE_UNIFIED_CONTEXT = False

router = APIRouter(tags=["chat"])

active_conversation = None

# Initialize tool manager globally
tool_manager = get_tool_manager()

# Initialize fast memory retrieval
fast_memory = FastReactiveMemory()

# Initialize emotional state tracker
emotional_tracker = get_emotional_tracker()

# Query classifier - only used when USE_UNIFIED_CONTEXT is False (legacy mode)
query_classifier = None
if not USE_UNIFIED_CONTEXT:
    from core.query_classifier import get_query_classifier
    query_classifier = get_query_classifier()

# Connection state for server-side TTS routing
@dataclass
class ConnectionState:
    """Per-connection state for server-side TTS/video routing"""
    websocket: WebSocket
    output_mode: OutputMode = OutputMode.TEXT
    video_session_id: Optional[str] = None
    sentence_processor: Optional[SentenceProcessor] = None
    tts_queue: List[TextBatch] = field(default_factory=list)
    video_chunk_index: int = 0
    tts_task: Optional[asyncio.Task] = None
    tts_queue_complete: bool = False  # Signal to TTS processor that streaming is done
    video_quality: str = "high"  # Video bitrate: high (2Mbps), medium (1Mbps), low (500kbps)


# WebSocket connection manager
class ConnectionManager:
    """Manages active WebSocket connections for broadcasting"""
    def __init__(self):
        self.active_connections: list[WebSocket] = []  # Legacy list for broadcast compatibility
        self.connection_states: Dict[WebSocket, ConnectionState] = {}  # Per-connection state
        self.pending_greeting: Optional[str] = None  # Store greeting if no clients connected

    async def connect(self, websocket: WebSocket):
        """Add a new WebSocket connection and send any pending greeting"""
        await websocket.accept()
        self.active_connections.append(websocket)

        # Create connection state for server-side TTS routing
        state = ConnectionState(websocket=websocket)
        self.connection_states[websocket] = state

        print(f"[ConnectionManager] Client connected. Total connections: {len(self.active_connections)}")

        # Send pending greeting if one exists
        if self.pending_greeting:
            print(f"[ConnectionManager] Sending pending greeting to newly connected client")
            print(f"[ConnectionManager] Greeting text: {self.pending_greeting[:100]}...")
            try:
                # Send start message
                await websocket.send_json({
                    "type": "start",
                    "context_level": "FULL"
                })

                # Send greeting as chunk
                await websocket.send_json({
                    "type": "chunk",
                    "content": self.pending_greeting
                })

                # Send done message (with message_count field that UI expects)
                # Note: message count will be updated when UI loads conversation
                await websocket.send_json({
                    "type": "done",
                    "message_count": 0  # Placeholder, UI will update on first message send
                })

                # Clear pending greeting
                self.pending_greeting = None
                print(f"[ConnectionManager] ✓ Pending greeting delivered")
            except Exception as e:
                print(f"[ConnectionManager] ✗ Failed to send pending greeting: {e}")
                import traceback
                traceback.print_exc()

    def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection and clean up state"""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

        # Clean up connection state
        if websocket in self.connection_states:
            state = self.connection_states[websocket]
            # Cancel any running TTS task
            if state.tts_task and not state.tts_task.done():
                state.tts_task.cancel()
            del self.connection_states[websocket]

        print(f"[ConnectionManager] Client disconnected. Total connections: {len(self.active_connections)}")

    def get_state(self, websocket: WebSocket) -> Optional[ConnectionState]:
        """Get connection state for a websocket"""
        return self.connection_states.get(websocket)

    async def set_output_mode(self, websocket: WebSocket, mode: OutputMode,
                               video_session_id: Optional[str] = None):
        """Set output mode for a connection"""
        state = self.connection_states.get(websocket)
        if state:
            state.output_mode = mode
            state.video_session_id = video_session_id
            if mode == OutputMode.VIDEO:
                state.video_chunk_index = 0
            print(f"[ConnectionManager] Set output mode to {mode.value} for connection")

    async def broadcast(self, message: dict):
        """Broadcast a message to all connected clients"""
        if not self.active_connections:
            print(f"[ConnectionManager] No clients to broadcast to")
            return

        print(f"[ConnectionManager] Broadcasting to {len(self.active_connections)} clients")
        dead_connections = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                print(f"[ConnectionManager] Failed to send to client: {e}")
                dead_connections.append(connection)

        # Clean up dead connections
        for conn in dead_connections:
            self.disconnect(conn)

# Global connection manager
connection_manager = ConnectionManager()

# Register broadcast function for other modules to use
set_broadcast_function(connection_manager.broadcast)

# Interrupt management
class InterruptManager:
    """Manages interrupt requests for stopping generation"""
    def __init__(self):
        self.interrupt_requested = False

    def request_interrupt(self):
        """Request an interrupt of current generation"""
        self.interrupt_requested = True
        print("[routes_chat.py][InterruptManager] ⚠ Interrupt requested")

    def clear(self):
        """Clear interrupt flag for new generation"""
        self.interrupt_requested = False

    def is_interrupted(self):
        """Check if interrupt was requested"""
        return self.interrupt_requested

# Global interrupt manager (one per server instance)
interrupt_manager = InterruptManager()

def apply_no_think(messages: list) -> list:
    """
    Append /no_think to the last user message for LLM calls.
    Returns a modified copy (does not mutate original).

    This tag tells qwen3 to skip reasoning/thinking mode for faster inference.
    Only applied to messages sent to the LLM, not stored in history.
    """
    if not messages:
        return messages

    # Create a shallow copy of the list
    modified = list(messages)

    # Find and modify the last user message
    for i in range(len(modified) - 1, -1, -1):
        if modified[i].get('role') == 'user':
            # Create a copy of this message with /no_think appended
            msg_copy = dict(modified[i])
            content = msg_copy.get('content', '')
            if isinstance(content, str) and '/no_think' not in content:
                msg_copy['content'] = content + ' /no_think'
                modified[i] = msg_copy
            break

    return modified

def get_tool_icon(tool_name: str) -> str:
    """
    Get tool icon from database

    Args:
        tool_name: Name of the tool

    Returns:
        Icon emoji string (or default if not found)
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT icon FROM mcp_tools WHERE tool_name = %s", (tool_name,))
        result = cursor.fetchone()
        cursor.close()
        conn.close()

        if result and result[0]:
            return result[0]
        return "🔧"  # Default tool icon
    except Exception as e:
        print(f"[routes_chat.py][get_tool_icon] Error fetching icon: {e}")
        return "🔧"

def set_active_conversation(conv):
    """Set the active conversation instance"""
    global active_conversation
    active_conversation = conv

async def ensure_tool_manager_connected():
    """Ensure tool manager is connected to MCP servers"""
    if not tool_manager._connected:
        print("[routes_chat.py] Connecting to MCP servers...")
        await tool_manager.connect()

async def _run_memory_retrieval_inline() -> list:
    """
    Run memory retrieval v2 inline every turn (~200ms with warm model).

    Writes to live_memories table (forensics + prompt assembly reads from it).
    If retrieval fails, live_memories retains last-known-good state.

    Returns:
        List of scored memory dicts with keys: id, final_score, topic_sim,
        emo_congruence, recency, tier (empty list on failure).
    """
    try:
        from backend.memory.memory_retrieval_v2 import run_retrieval_v2, DB_CFG
        import time
        t0 = time.time()
        scored = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: run_retrieval_v2(DB_CFG, top_k=10, insert=True, mode="replace", show=False)
        )
        elapsed = time.time() - t0
        print(f"[routes_chat.py][memory_retrieval] ✓ Retrieval v2 completed in {elapsed:.3f}s")
        return scored or []
    except Exception as e:
        print(f"[routes_chat.py][memory_retrieval] ✗ Retrieval v2 failed (live_memories unchanged): {e}")
        return []


# ============================================
# SERVER-SIDE TTS/VIDEO ROUTING
# ============================================

async def call_xtts(text: str) -> bytes:
    """
    Call XTTS server directly to generate audio for text.

    Uses httpx (same as routes_tts.py) for consistent behavior.

    Args:
        text: Text to synthesize (should already be cleaned by SentenceProcessor)

    Returns:
        Audio bytes (MP3 format)
    """
    # XTTS endpoint - same as used in routes_tts.py
    xtts_url = f"{config.XTTS_SERVER_URL}/speak_stream_mp3"

    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            response = await client.post(
                xtts_url,
                json={"text": text},
                headers={"Content-Type": "application/json"}
            )

            if response.status_code != 200:
                raise Exception(f"XTTS error {response.status_code}: {response.text[:100]}")

            # Use response.content (same as routes_tts.py)
            audio_data = response.content
            # Debug: log content-type and first few bytes (MP3 starts with FF FB or ID3)
            content_type = response.headers.get('content-type', 'unknown')
            first_bytes = audio_data[:10].hex() if audio_data else 'empty'
            print(f"[routes_chat.py][call_xtts] ✓ Got {len(audio_data)} bytes ({content_type}), starts with: {first_bytes}")
            return audio_data

    except httpx.TimeoutException:
        print(f"[routes_chat.py][call_xtts] Timeout calling {xtts_url}")
        raise
    except Exception as e:
        print(f"[routes_chat.py][call_xtts] Error: {e}")
        raise


async def stream_batch_to_hls(state: ConnectionState, batch: TextBatch) -> dict:
    """
    Stream a text batch to HLS via FLOAT's streaming endpoint.

    This provides seamless video playback without gaps between chunks.
    Segments are added to the HLS playlist as they're generated.

    Args:
        state: Connection state with video session info
        batch: Text batch to process

    Returns:
        Dict with status and segments added
    """
    try:
        if not state.video_session_id:
            raise Exception("No video session ID - session not started?")

        # Import video session components directly
        from app.api.routes_video import (
            video_sessions, hls_sessions, HLSSession, get_float_url
        )
        from core.websocket_broadcast import broadcast
        import httpx
        import json

        session_id = state.video_session_id
        text = batch.text

        print(f"[routes_chat.py][stream_hls] Streaming batch {batch.batch_index} to HLS: {text[:50]}...")

        # Validate session exists
        if session_id not in video_sessions:
            raise Exception(f"Session not found: {session_id}")

        session = video_sessions[session_id]
        if not session["active"]:
            raise Exception("Session not active")

        # Skip empty text
        if not text.strip():
            print(f"[routes_chat.py][stream_hls] Text empty, skipping")
            return {"status": "skipped"}

        # Initialize HLS session if not exists
        if session_id not in hls_sessions:
            hls_sessions[session_id] = HLSSession(session_id)
            print(f"[routes_chat.py][stream_hls] Initialized HLS session")

        hls = hls_sessions[session_id]
        remote_session_id = session.get("remote_session_id")

        if not remote_session_id:
            raise Exception("No remote session ID found")

        float_url = get_float_url()
        segments_added = 0

        # Ensure FLOAT is available (may have been swapped out for another GPU service)
        from core.gpu_manager import request_gpu
        gpu_success, gpu_error = await request_gpu("float")
        if not gpu_success:
            print(f"[routes_chat.py][stream_hls] GPU request failed: {gpu_error}")
            # Don't fail completely - just skip this batch
            return {"status": "gpu_unavailable", "error": gpu_error}

        # Stream to FLOAT and add segments as they arrive
        async with httpx.AsyncClient(timeout=300.0) as client:
            async with client.stream(
                "POST",
                f"{float_url}/stream-video-segments",
                data={
                    "session_id": remote_session_id,
                    "text": text,
                    "emotion": session["parameters"].get("emotion", "neutral"),
                    "buffer_chunks": "3",  # Smaller buffer for faster first segment
                    "quality": state.video_quality  # From client's quality dropdown
                }
            ) as response:
                if response.status_code != 200:
                    error = await response.aread()
                    raise Exception(f"FLOAT error: {error.decode()}")

                async for line in response.aiter_lines():
                    if not line:
                        continue

                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if data.get("error"):
                        print(f"[routes_chat.py][stream_hls] Error from FLOAT: {data['error']}")
                        continue

                    if data.get("segment"):
                        segment_data = base64.b64decode(data["segment"])
                        duration = data.get("duration", 4.0)

                        # Add to HLS playlist
                        filename = hls.add_segment(segment_data, duration)
                        segments_added += 1

                        print(f"[routes_chat.py][stream_hls] ✓ Segment {len(hls.segments)-1}: {duration:.1f}s")

                        # Broadcast progress to all clients
                        await broadcast({
                            "type": "hls_segment_ready",
                            "session_id": session_id,
                            "segment": filename,
                            "segment_index": len(hls.segments) - 1,
                            "duration": duration,
                            "is_last": data.get("is_last", False),
                            "playlist_url": f"/api/video/hls/{session_id}/playlist.m3u8"
                        })

        print(f"[routes_chat.py][stream_hls] ✓ Batch complete: {segments_added} segments")
        return {"status": "complete", "segments_added": segments_added}

    except Exception as e:
        print(f"[routes_chat.py][stream_hls] Error: {e}")
        import traceback
        traceback.print_exc()
        raise


async def queue_video_chunk(state: ConnectionState, batch: TextBatch) -> dict:
    """
    Queue a video chunk for FLOAT processing (LEGACY - use stream_batch_to_hls instead).

    Calls video queue logic directly to avoid HTTP self-call issues.

    Args:
        state: Connection state with video session info
        batch: Text batch to process

    Returns:
        Dict with chunk_id and status
    """
    try:
        if not state.video_session_id:
            raise Exception("No video session ID - session not started?")

        # Import video session components directly
        from app.api.routes_video import video_sessions, video_queues, process_queue
        from datetime import datetime

        session_id = state.video_session_id
        chunk_index = state.video_chunk_index
        text = batch.text

        print(f"[routes_chat.py][queue_video_chunk] Queueing chunk {chunk_index} for session {session_id}")
        state.video_chunk_index += 1

        # Validate session exists
        if session_id not in video_sessions:
            raise Exception(f"Session not found: {session_id}")

        if not video_sessions[session_id]["active"]:
            raise Exception("Session not active")

        # Skip empty text
        if not text.strip():
            print(f"[routes_chat.py][queue_video_chunk] Text empty, skipping")
            return {"chunk_id": f"{session_id}_chunk_{chunk_index}", "status": "skipped"}

        # Create chunk job
        chunk_id = f"{session_id}_chunk_{chunk_index}"
        chunk_job = {
            "chunk_id": chunk_id,
            "chunk_index": chunk_index,
            "text": text,
            "status": "queued",
            "video_path": None,
            "created_at": datetime.now().isoformat(),
            "tts_time": 0,
            "video_time": 0,
            "total_time": 0
        }

        video_queues[session_id].append(chunk_job)
        video_sessions[session_id]["chunks_submitted"] += 1

        print(f"[routes_chat.py][queue_video_chunk] ✓ Chunk queued: {chunk_id}")
        print(f"[routes_chat.py][queue_video_chunk] Queue length: {len(video_queues[session_id])}")

        # Check if processor needs to be started
        chunks_processing = sum(1 for c in video_queues[session_id] if c["status"] == "processing")
        if len(video_queues[session_id]) == 1 or chunks_processing == 0:
            print(f"[routes_chat.py][queue_video_chunk] Starting video processor")
            # Use asyncio.create_task instead of background_tasks
            asyncio.create_task(process_queue(session_id))
        else:
            print(f"[routes_chat.py][queue_video_chunk] Processor already running ({chunks_processing} processing)")

        return {
            "chunk_id": chunk_id,
            "status": "queued",
            "position": len(video_queues[session_id])
        }

    except Exception as e:
        print(f"[routes_chat.py][queue_video_chunk] Error: {e}")
        import traceback
        traceback.print_exc()
        raise


async def start_video_session_for_connection(state: ConnectionState) -> Optional[str]:
    """
    Start a video session for a connection.

    Uses the saved reference image. Returns session_id or None on failure.
    Calls video session logic directly to avoid HTTP self-call issues.
    """
    try:
        # Import video session components directly
        from core.gpu_manager import request_gpu
        from app.api.routes_video import (
            video_sessions, video_queues, create_remote_float_session,
            CONFIG_VIDEO_REFERENCE_IMAGE
        )
        from database.config_loader import get_config
        from pathlib import Path
        import uuid
        from datetime import datetime

        print(f"[routes_chat.py][start_video_session] Requesting GPU for FLOAT...")

        # Request GPU for FLOAT service
        success, error = await request_gpu("float")
        if not success:
            print(f"[routes_chat.py][start_video_session] GPU request failed: {error}")
            return None

        # Get saved reference image path
        saved_path = get_config(CONFIG_VIDEO_REFERENCE_IMAGE)
        if not saved_path or not Path(saved_path).exists():
            print(f"[routes_chat.py][start_video_session] No saved reference image found")
            return None

        image_path = Path(saved_path)
        print(f"[routes_chat.py][start_video_session] Using reference image: {image_path}")

        # Create remote FLOAT session
        print(f"[routes_chat.py][start_video_session] Creating remote FLOAT session...")
        default_params = {
            "seed": 15,
            "a_cfg_scale": 2.0,
            "e_cfg_scale": 1.0,
            "r_cfg_scale": 1.0,
            "nfe": 10,
            "emotion": "neutral",
            "no_crop": False
        }
        remote_session_id = await create_remote_float_session(str(image_path), default_params)
        print(f"[routes_chat.py][start_video_session] Remote FLOAT session: {remote_session_id}")

        # Create local session
        session_id = str(uuid.uuid4())

        video_sessions[session_id] = {
            "session_id": session_id,
            "remote_session_id": remote_session_id,
            "image_id": "saved",
            "image_path": str(image_path),
            "image_filename": image_path.name,
            "parameters": default_params,
            "created_at": datetime.now().isoformat(),
            "chunks_submitted": 0,
            "chunks_completed": 0,
            "chunks_failed": 0,
            "active": True,
            "current_chunk": None
        }

        video_queues[session_id] = []

        print(f"[routes_chat.py][start_video_session] ✓ Session created: {session_id}")
        return session_id

    except Exception as e:
        print(f"[routes_chat.py][start_video_session] Error: {e}")
        import traceback
        traceback.print_exc()
        return None


async def tts_video_processor(websocket: WebSocket, state: ConnectionState):
    """
    Background processor for TTS/video generation.

    Runs in parallel with text streaming, processing batches as they become available.
    Sends audio chunks or video notifications back to the client.
    """
    print(f"[routes_chat.py][tts_processor] Started for mode: {state.output_mode.value}")
    sentence_index = 0

    # For VIDEO mode: Reset HLS session for new turn
    if state.output_mode == OutputMode.VIDEO and state.video_session_id:
        try:
            from app.api.routes_video import hls_sessions
            if state.video_session_id in hls_sessions:
                hls_sessions[state.video_session_id].reset_for_new_turn()
                print(f"[routes_chat.py][tts_processor] ✓ HLS session reset for new turn")
                # Tell browser to reload playlist for this turn
                await websocket.send_json({
                    "type": "hls_new_turn",
                    "session_id": state.video_session_id,
                    "playlist_url": f"/api/video/hls/{state.video_session_id}/playlist.m3u8"
                })
        except Exception as e:
            print(f"[routes_chat.py][tts_processor] HLS reset error: {e}")

    try:
        while True:
            # Check if we have batches to process
            if state.tts_queue:
                batch = state.tts_queue.pop(0)
                print(f"[routes_chat.py][tts_processor] Processing batch {batch.batch_index}: {batch.text[:50]}...")

                if state.output_mode == OutputMode.AUDIO:
                    # Generate audio via XTTS
                    try:
                        audio_bytes = await call_xtts(batch.text)
                        audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')

                        await websocket.send_json({
                            "type": "audio_chunk",
                            "audio": audio_b64,
                            "format": "mpeg",
                            "sentence_index": sentence_index,
                            "is_last": False
                        })
                        sentence_index += 1
                        print(f"[routes_chat.py][tts_processor] ✓ Audio chunk sent ({len(audio_bytes)} bytes)")
                    except Exception as e:
                        print(f"[routes_chat.py][tts_processor] ✗ TTS error: {e}")

                elif state.output_mode == OutputMode.VIDEO:
                    # Stream to HLS for seamless playback
                    try:
                        result = await stream_batch_to_hls(state, batch)
                        # HLS broadcasts hls_segment_ready messages as segments arrive
                        # No need to send video_chunk_ready - HLS handles it
                        print(f"[routes_chat.py][tts_processor] ✓ HLS batch streamed: {result.get('segments_added', 0)} segments")
                    except Exception as e:
                        print(f"[routes_chat.py][tts_processor] ✗ HLS stream error: {e}")

            elif state.tts_queue_complete:
                # No more batches coming and queue is empty
                break
            else:
                # Wait for more batches
                await asyncio.sleep(0.05)

        # Send final message
        if state.output_mode == OutputMode.AUDIO:
            await websocket.send_json({
                "type": "audio_chunk",
                "is_last": True
            })
        elif state.output_mode == OutputMode.VIDEO:
            # Complete the HLS session
            try:
                from app.api.routes_video import hls_sessions
                if state.video_session_id and state.video_session_id in hls_sessions:
                    hls_sessions[state.video_session_id].complete()
                    print(f"[routes_chat.py][tts_processor] ✓ HLS session completed")
            except Exception as e:
                print(f"[routes_chat.py][tts_processor] HLS complete error: {e}")

            await websocket.send_json({
                "type": "hls_stream_complete",
                "session_id": state.video_session_id,
                "playlist_url": f"/api/video/hls/{state.video_session_id}/playlist.m3u8"
            })

        print(f"[routes_chat.py][tts_processor] ✓ Completed")

    except asyncio.CancelledError:
        print(f"[routes_chat.py][tts_processor] Cancelled")
    except Exception as e:
        print(f"[routes_chat.py][tts_processor] Error: {e}")
        import traceback
        traceback.print_exc()


@router.post("/api/test")
async def test_endpoint():
    """Simple test endpoint"""
    print("[routes_chat.py][test_endpoint] Test endpoint called!")
    return {"status": "ok"}


class UINotificationRequest(BaseModel):
    """Request model for UI notification endpoint"""
    message: str
    style: str = "info"  # info, success, warning, error


@router.post("/api/ui/notify")
async def ui_notify(request: UINotificationRequest):
    """
    Broadcast a UI notification to all connected clients.
    Called by core.ui_notify.ui_msg() from anywhere in the codebase.

    Styles:
        - info: Gray notification (default)
        - success: Green notification
        - warning: Yellow/orange notification
        - error: Red notification
    """
    valid_styles = {"info", "success", "warning", "error"}
    style = request.style if request.style in valid_styles else "info"

    await connection_manager.broadcast({
        "type": "ui_notification",
        "message": request.message,
        "style": style
    })

    return {"status": "ok", "clients": len(connection_manager.active_connections)}


class SystemTriggerRequest(BaseModel):
    """Request model for system trigger endpoint"""
    content: str
    allow_tools: bool = False  # Default: skip tool evaluation for speed
    context_mode: str = "FULL"  # FULL, TASK, CONVERSATIONAL, DEEP, or GREETING

@router.post("/api/system/trigger")
async def system_trigger(trigger_request: SystemTriggerRequest):
    """
    Trigger Iris response from system event (face detection, scheduled task, etc.)

    Inserts system message into chat_history and generates Iris's response
    using the normal conversation flow with full tool support.

    Args:
        trigger_request: Request with content field

    Returns:
        {"success": True/False, "response": "assistant message", "error": "..."}
    """
    print(f"[routes_chat.py][system_trigger] ┌── SYSTEM TRIGGER ──┐")
    print(f"[routes_chat.py][system_trigger] Received request: {trigger_request}")

    try:
        content = trigger_request.content
        if not content:
            print(f"[routes_chat.py][system_trigger] ✗ Missing content field")
            return {"success": False, "error": "Missing 'content' field"}

        print(f"[routes_chat.py][system_trigger] System message: {content[:100]}...")

        # Ensure tool manager is connected
        await ensure_tool_manager_connected()

        # 1. Save system message to chat_history directly
        conn = get_db_connection()
        cursor = conn.cursor()

        # Get current session
        cursor.execute("""
            SELECT session_id FROM chat_sessions
            ORDER BY session_id DESC
            LIMIT 1
        """)
        result = cursor.fetchone()
        session_id = result[0] if result else 'default'

        # Insert system message
        cursor.execute("""
            INSERT INTO chat_history (session_id, role, message, c_timestamp)
            VALUES (%s, 'system', %s, %s)
        """, (session_id, content, datetime.now()))

        conn.commit()
        cursor.close()
        conn.close()

        print(f"[routes_chat.py][system_trigger] ✓ System message saved to chat_history")

        # 2. Load conversation context (includes new system message)
        # Reload conversation from database to include the new system message
        recent_messages = load_recent_conversation(max_messages=30)

        # Clear and reload active conversation (DIRECTLY append to avoid re-saving to database)
        active_conversation.messages = []
        for msg in recent_messages:
            role = msg.get('role')
            content = msg.get('content', '')  # Fixed: was 'message', should be 'content'

            # Build message dict WITHOUT saving to database
            # (these are already in the database - we're just reloading them to memory)
            message_dict = {
                'role': role,
                'content': content
            }

            # Add tool-specific fields if present
            if role == 'tool':
                message_dict['tool_name'] = msg.get('tool_name', '')
                if msg.get('tool_call_id'):
                    message_dict['tool_call_id'] = msg.get('tool_call_id')

            # Add to in-memory list ONLY (skip database persistence)
            active_conversation.messages.append(message_dict)

            # System messages are handled by the context assembler

        # Smart tool selection for system triggers — use same logic as websocket
        if getattr(config, 'SMART_TOOL_SELECTION', False):
            recent_texts = [m["content"] for m in active_conversation.messages
                            if m.get("role") == "user"][-getattr(config, 'BATCH_TRIM_SIZE', 5):]
            # Get blocked_tools from active protocol
            protocol = get_active_protocol()
            blocked_tools = protocol.get('blocked_tools', [])
            tool_definitions = tool_manager.get_tools_for_context(
                recent_texts,
                active_conversation.snapshot_force_groups,
                blocked_tools=blocked_tools
            )
            active_conversation.snapshot_force_groups = set()
        else:
            tool_definitions = tool_manager.get_tool_definitions_for_ollama()

        # Use context_mode from request (default FULL, but can be GREETING for minimal context)
        context_mode = trigger_request.context_mode
        print(f"[routes_chat.py][system_trigger] Using context mode: {context_mode}")

        # Assemble context - PHASE 2 uses unified builder for KV cache optimization
        if USE_UNIFIED_CONTEXT:
            context, budget = assemble_unified_context(active_conversation, tool_definitions)
        else:
            context, budget = assemble_full_context(active_conversation, tool_definitions, skip_fast_memory=(context_mode == "GREETING"), context_level=context_mode)
        print(f"[routes_chat.py][system_trigger] ✓ Context loaded ({len(tool_definitions)} tools available)")

        # 3. Check if tools are allowed (skip for simple greetings to save time)
        if trigger_request.allow_tools:
            print(f"[routes_chat.py][system_trigger] → First call (checking for tool requests)...")
            first_response = await chat_completion_with_tools(
                messages=context,
                tools=tool_definitions
            )

            # Check if model wants to use tools
            tool_calls = first_response.get('message', {}).get('tool_calls', [])
        else:
            print(f"[routes_chat.py][system_trigger] ⚡ Skipping tool evaluation (allow_tools=False)")
            tool_calls = []

        if tool_calls:
            print(f"[routes_chat.py][system_trigger] 🔧 Tools requested: {len(tool_calls)}")

            # Add assistant message with tool calls
            active_conversation.add_assistant_message(
                content=first_response.get('message', {}).get('content', ''),
                tool_calls=tool_calls
            )

            # Execute tools
            for tool_call in tool_calls:
                function_name = tool_call.get('function', {}).get('name')
                arguments = tool_call.get('function', {}).get('arguments', {})
                # OpenAI format returns arguments as JSON string, parse if needed
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except json.JSONDecodeError:
                        arguments = {}

                print(f"[routes_chat.py][system_trigger]   🔧 Executing: {function_name}")

                try:
                    result = await tool_manager.execute_tool(function_name, arguments)
                    active_conversation.add_tool_message(
                        content=json.dumps(result),
                        tool_name=function_name
                    )
                    print(f"[routes_chat.py][system_trigger]   ✓ {function_name} completed")
                except Exception as tool_error:
                    error_result = {"success": False, "error": str(tool_error)}
                    active_conversation.add_tool_message(
                        content=json.dumps(error_result),
                        tool_name=function_name
                    )
                    print(f"[routes_chat.py][system_trigger]   ✗ {function_name} failed: {tool_error}")

            # Reload context with tool results
            if USE_UNIFIED_CONTEXT:
                context, budget = assemble_unified_context(active_conversation, tool_definitions)
            else:
                context, budget = assemble_full_context(active_conversation, tool_definitions, skip_fast_memory=False, context_level='FULL')

        # 4. Generate final response (streaming)
        print(f"[routes_chat.py][system_trigger] → Generating response...")
        print(f"[routes_chat.py][system_trigger] Connected WebSocket clients: {len(connection_manager.active_connections)}")
        assistant_response = ""
        has_clients = len(connection_manager.active_connections) > 0

        # Ensure trigger content is the last message in context
        # The trigger system message saved to chat_history may get squeezed out
        # by tight GREETING token budgets. Append it explicitly so the model
        # knows what to respond to. Uses role=user to prevent
        # "prefill incompatible with enable_thinking" errors (trailing
        # role=assistant or role=system can cause this with llama-server).
        # Note: stored in DB as role=system so Iris doesn't attribute it to Victor.
        # The [SYSTEM] prefix makes it clear this is an automated trigger, not user speech.
        context.append({
            "role": "user",
            "content": f"[SYSTEM TRIGGER] {trigger_request.content}"
        })
        print(f"[routes_chat.py][system_trigger] Appended trigger as final user message ({len(trigger_request.content)} chars)")

        # Strip tool-related messages from context when not using tools
        # llama-server rejects role:"tool" messages and tool_calls fields
        # when no tool definitions are provided in the request payload
        if not trigger_request.allow_tools or not tool_calls:
            clean_context = []
            stripped = 0
            for msg in context:
                if msg.get("role") == "tool":
                    stripped += 1
                    continue
                if "tool_calls" in msg:
                    # Remove tool_calls field from assistant messages
                    msg = {k: v for k, v in msg.items() if k != "tool_calls"}
                    # Ensure content is not empty after stripping
                    if not msg.get("content"):
                        msg["content"] = "(tool interaction omitted)"
                clean_context.append(msg)
            if stripped > 0:
                print(f"[routes_chat.py][system_trigger] Stripped {stripped} tool messages from context (no tools in payload)")
            context = clean_context

        # ============================================
        # SERVER-SIDE TTS/VIDEO ROUTING SETUP (for greeting)
        # ============================================
        use_server_tts = False
        tts_state = None
        tts_websocket = None
        is_video_mode = False

        if has_clients and config.SERVER_SIDE_TTS_ROUTING and is_node2_service_enabled('TTS_ENABLED'):
            # Get first connected client's state for TTS routing
            for ws in connection_manager.active_connections:
                state = connection_manager.get_state(ws)
                if state and state.output_mode != OutputMode.TEXT:
                    tts_state = state
                    tts_websocket = ws
                    use_server_tts = True
                    is_video_mode = state.output_mode == OutputMode.VIDEO
                    break

        if use_server_tts:
            tts_state.sentence_processor = SentenceProcessor()
            tts_state.tts_queue = []
            tts_state.tts_queue_complete = False
            tts_state.tts_task = asyncio.create_task(tts_video_processor(tts_websocket, tts_state))
            print(f"[routes_chat.py][system_trigger] ├─ SERVER-SIDE TTS ROUTING ({tts_state.output_mode.value}) ─┤")
        else:
            print(f"[routes_chat.py][system_trigger] TTS routing: {'no clients' if not has_clients else 'browser-side or text mode'}")

        # Send 'start' message if clients are connected
        if has_clients:
            await connection_manager.broadcast({
                "type": "start",
                "context_level": "FULL"
            })

        async for content_chunk in chat_completion_stream(
            messages=context
        ):
            if not content_chunk:
                continue

            # chat_completion_stream yields tuples (text, is_thinking) or timing dicts
            if isinstance(content_chunk, dict):
                # Timing metrics — skip for greeting
                continue
            if isinstance(content_chunk, tuple):
                text, is_thinking = content_chunk
                if is_thinking or not text:
                    continue  # Skip thinking content for greetings
                content_chunk = text

            assistant_response += content_chunk

            # Broadcast chunk to WebSocket clients (if any)
            if has_clients:
                await connection_manager.broadcast({
                    "type": "chunk",
                    "content": content_chunk
                })

            # Feed chunk to server-side TTS sentence processor
            if use_server_tts and tts_state and tts_state.sentence_processor:
                batches = tts_state.sentence_processor.add_chunk(content_chunk, is_video_mode)
                for batch in batches:
                    tts_state.tts_queue.append(batch)

        # ============================================
        # FINALIZE SERVER-SIDE TTS ROUTING
        # ============================================
        if use_server_tts and tts_state and tts_state.sentence_processor:
            final_batches = tts_state.sentence_processor.finalize(is_video_mode)
            for batch in final_batches:
                tts_state.tts_queue.append(batch)
            tts_state.tts_queue_complete = True

            if tts_state.tts_task:
                try:
                    await asyncio.wait_for(tts_state.tts_task, timeout=300.0)
                except asyncio.TimeoutError:
                    print(f"[routes_chat.py][system_trigger] ⚠ TTS processor timed out")
                    tts_state.tts_task.cancel()
                except Exception as e:
                    print(f"[routes_chat.py][system_trigger] ⚠ TTS processor error: {e}")

            print(f"[routes_chat.py][system_trigger] ├─ TTS ROUTING COMPLETE ─┤")

        # 5. Save assistant response to database
        active_conversation.add_assistant_message(assistant_response)
        print(f"[routes_chat.py][system_trigger] ✓ Response generated: {assistant_response[:80]}...")

        # Repetition gate — post-generation scoring (observability only)
        try:
            from core.repetition_gate import score_repetition
            rep_score, rep_phrases = score_repetition(assistant_response, active_conversation.get_messages())
            if rep_score > 0:
                print(f"[routes_chat.py][system_trigger] Repetition score: {rep_score} ({len(rep_phrases)} shared phrases)")
            if rep_score >= 0.3:
                print(f"[routes_chat.py][system_trigger] ⚠ HIGH REPETITION: {rep_phrases[:5]}")
        except Exception as e:
            print(f"[routes_chat.py][system_trigger] Repetition scoring error: {e}")

        # 6. Handle completion
        if has_clients:
            # Send final done signal to connected clients
            await connection_manager.broadcast({
                "type": "done"
            })
        else:
            # No clients connected - store as pending greeting
            print(f"[routes_chat.py][system_trigger] ⏳ No clients connected - storing as pending greeting")
            connection_manager.pending_greeting = assistant_response

        print(f"[routes_chat.py][system_trigger] └── COMPLETE ──┘")

        return {
            "success": True,
            "response": assistant_response
        }

    except Exception as e:
        print(f"[routes_chat.py][system_trigger] ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "error": str(e)
        }


class ContactMessageRequest(BaseModel):
    """Request model for contact message endpoint (autonomous drive contact_victor)"""
    content: str
    source: str = "autonomous_drive"  # Source identifier for logging
    reason: str = ""  # Why Iris reached out (e.g., "lonely_and_curious") - shown to LLM, hidden from UI


@router.post("/api/contact/message")
async def save_contact_message(request: ContactMessageRequest):
    """
    Save Iris's autonomous contact message as an assistant message.

    Used by the autonomous drive system when Iris initiates contact (contact_victor).
    This saves the message to chat_history as an assistant message so it appears
    in the conversation history, allowing Victor to see and respond to it.

    Unlike system_trigger, this does NOT generate a new response - the content
    IS Iris's message.

    Args:
        request: ContactMessageRequest with content and source

    Returns:
        {"success": True/False, "message_id": int or None, "error": "..."}
    """
    print(f"[routes_chat.py][contact_message] ┌── CONTACT MESSAGE ──┐")
    print(f"[routes_chat.py][contact_message] Source: {request.source}")
    print(f"[routes_chat.py][contact_message] Content: {request.content[:100]}...")

    try:
        content = request.content
        if not content:
            return {"success": False, "error": "Missing 'content' field"}

        # Save as assistant message to chat_history
        conn = get_db_connection()
        cursor = conn.cursor()

        # Get current session
        session_id = active_conversation.get_session_id()
        if not session_id:
            cursor.execute("""
                SELECT session_id FROM chat_sessions
                ORDER BY start_time DESC
                LIMIT 1
            """)
            result = cursor.fetchone()
            session_id = result[0] if result else None

        # Encode reason in sender field: "contact_victor:reason"
        # This allows LLM to see why Iris reached out, while UI just shows the badge
        sender_with_reason = request.source
        if request.reason:
            sender_with_reason = f"{request.source}:{request.reason}"
            print(f"[routes_chat.py][contact_message] Reason: {request.reason}")

        # Insert as assistant message with sender tag (includes reason for LLM context)
        cursor.execute("""
            INSERT INTO chat_history (session_id, role, message, c_timestamp, sender)
            VALUES (%s, 'assistant', %s, %s, %s)
            RETURNING id
        """, (session_id, content, datetime.now(), sender_with_reason))

        message_id = cursor.fetchone()[0]

        conn.commit()
        cursor.close()
        conn.close()

        print(f"[routes_chat.py][contact_message] ✓ Saved as assistant message (id={message_id})")

        # Also add to in-memory conversation so it's immediately visible
        active_conversation.messages.append({
            "role": "assistant",
            "content": content,
            "sender": sender_with_reason
        })

        # Broadcast to WebSocket clients - use base source for UI (reason is LLM-only)
        if connection_manager.active_connections:
            await connection_manager.broadcast({
                "type": "contact_message",
                "role": "assistant",
                "content": content,
                "sender": request.source  # UI only needs base source for badge
            })

        print(f"[routes_chat.py][contact_message] └── COMPLETE ──┘")

        return {
            "success": True,
            "message_id": message_id
        }

    except Exception as e:
        print(f"[routes_chat.py][contact_message] ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "error": str(e)
        }


@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """WebSocket endpoint for chat with dual-call tool pattern"""
    await connection_manager.connect(websocket)

    # Ensure tool manager is connected
    await ensure_tool_manager_connected()

    print(f"[routes_chat.py][websocket_chat] WebSocket connected, Conversation History now has {active_conversation.get_message_count()} messages")

    try:
        while True:
            # Receive message from client (may include images or interrupt)
            data = await websocket.receive_json()

            # Handle interrupt request
            if data.get("type") == "interrupt":
                print("[routes_chat.py][websocket_chat] ⚠ Interrupt received from client")
                interrupt_manager.request_interrupt()
                await websocket.send_json({
                    "type": "interrupted",
                    "message": "Generation stopped by user"
                })
                continue

            # Handle output mode change (server-side TTS routing)
            if data.get("type") == "set_output_mode":
                mode_str = data.get("mode", "text")
                try:
                    mode = OutputMode(mode_str)
                except ValueError:
                    mode = OutputMode.TEXT

                video_session_id = None
                print(f"[routes_chat.py][set_output_mode] Requested mode: {mode.value}, SERVER_SIDE_TTS_ROUTING: {config.SERVER_SIDE_TTS_ROUTING}")

                if mode == OutputMode.VIDEO and config.SERVER_SIDE_TTS_ROUTING and is_node2_service_enabled('TTS_ENABLED'):
                    # Start video session for this connection
                    print(f"[routes_chat.py][set_output_mode] Starting video session for VIDEO mode...")
                    state = connection_manager.get_state(websocket)
                    if state:
                        video_session_id = await start_video_session_for_connection(state)
                        if video_session_id:
                            print(f"[routes_chat.py][set_output_mode] ✓ Video session created: {video_session_id}")
                        else:
                            print(f"[routes_chat.py][set_output_mode] ✗ Failed to create video session")
                    else:
                        print(f"[routes_chat.py][set_output_mode] ✗ No connection state found")

                await connection_manager.set_output_mode(websocket, mode, video_session_id)
                await websocket.send_json({
                    "type": "mode_set",
                    "mode": mode.value,
                    "video_session_id": video_session_id,
                    "server_side_routing": config.SERVER_SIDE_TTS_ROUTING
                })
                print(f"[routes_chat.py][set_output_mode] ✓ Mode set to: {mode.value}, session_id: {video_session_id}")
                continue

            # Handle video quality change
            if data.get("type") == "set_video_quality":
                quality = data.get("quality", "high")
                if quality not in ("high", "medium", "low"):
                    quality = "high"
                state = connection_manager.get_state(websocket)
                if state:
                    state.video_quality = quality
                    print(f"[routes_chat.py][set_video_quality] ✓ Quality set to: {quality}")
                await websocket.send_json({
                    "type": "quality_set",
                    "quality": quality
                })
                continue

            user_message = data.get("message", "").strip()
            user_images = data.get("images", [])  # List of base64 images
            user_documents = data.get("documents", [])  # List of {content: base64, filename: str}
            sender = data.get("sender", "user")  # Default to 'user' (Victor)
            thinking_enabled = data.get("thinking", True)  # Default to thinking enabled

            if not user_message and not user_images and not user_documents:
                await websocket.send_json({
                    "type": "error",
                    "content": "Empty message"
                })
                continue

            # Clear interrupt flag for new generation
            interrupt_manager.clear()

            print(f"[routes_chat.py][websocket_chat] ┌──────── NEW TURN ────────┐")
            print(f"[routes_chat.py][websocket_chat] User message: '{user_message[:50]}...' [sender: {sender}]")
            if user_images:
                print(f"[routes_chat.py][websocket_chat] User attached {len(user_images)} image(s)")
            if user_documents:
                doc_names = [d.get('filename', 'unknown') for d in user_documents]
                print(f"[routes_chat.py][websocket_chat] User attached {len(user_documents)} document(s): {doc_names}")

            # Add user message with images to history
            active_conversation.add_user_message(
                user_message,
                images=user_images if user_images else None,
                sender=sender
            )

            # Append user message to prompt snapshot (if active)
            active_conversation.append_to_snapshot({"role": "user", "content": user_message})

            # ── OBSERVABILITY: init turn metrics dict ──
            import time as _time
            _turn_start = _time.time()
            _turn_metrics = {"session_id": str(active_conversation.get_session_id()) if active_conversation.get_session_id() else None}

            # Memory retrieval runs inline every turn (~200ms with warm model)
            # Writes to live_memories table for forensics + prompt assembly reads from it
            _retrieval_scored = await _run_memory_retrieval_inline()

            # ── OBSERVABILITY: capture memory retrieval provenance ──
            if _retrieval_scored:
                _turn_metrics["memories_in_context"] = len(_retrieval_scored)
                _turn_metrics["memory_ids"] = [s["id"] for s in _retrieval_scored]
                _turn_metrics["memory_tiers"] = [s["tier"] for s in _retrieval_scored]
                _turn_metrics["memory_scores"] = [round(s["final_score"], 4) for s in _retrieval_scored]
                _turn_metrics["avg_topic_similarity"] = round(sum(s["topic_sim"] for s in _retrieval_scored) / len(_retrieval_scored), 4)
                _turn_metrics["avg_emotional_congruence"] = round(sum(s["emo_congruence"] for s in _retrieval_scored) / len(_retrieval_scored), 4)
                _turn_metrics["avg_recency"] = round(sum(s["recency"] for s in _retrieval_scored) / len(_retrieval_scored), 4)
            else:
                _turn_metrics["memories_in_context"] = 0

            # ============================================
            # EMOTIONAL STATE PROCESSING
            # ============================================
            # Analyze user message and update Iris's emotional state
            # This happens BEFORE context assembly so state is included in prompt
            # ============================================
            if is_node2_service_enabled('EMOTIONAL_STATE') and user_message:
                try:
                    print(f"[routes_chat.py][websocket_chat] ├─ EMOTIONAL STATE PROCESSING ─┤")
                    emotional_result = await emotional_tracker.process_message(user_message)
                    if emotional_result.get('analysis'):
                        dominant = emotional_result.get('dominant_emotions', [])[:3]
                        dominant_str = ', '.join([f"{e[0]}:{e[1]:.2f}" for e in dominant])
                        print(f"[routes_chat.py][websocket_chat] │  Analysis: {emotional_result['analysis'].get('tone', 'unknown')} (intensity: {emotional_result['analysis'].get('intensity', 0):.2f})")
                        print(f"[routes_chat.py][websocket_chat] │  Dominant emotions: {dominant_str}")
                    else:
                        print(f"[routes_chat.py][websocket_chat] │  No emotional analysis available")

                    # ── OBSERVABILITY: capture emotional state delta ──
                    if emotional_result.get("state_before") and emotional_result.get("state_after"):
                        import math
                        before = emotional_result["state_before"]
                        after = emotional_result["state_after"]
                        _turn_metrics["emotional_state_before"] = before
                        _turn_metrics["emotional_state_after"] = after
                        delta = math.sqrt(sum((after.get(k, 0) - before.get(k, 0)) ** 2 for k in after))
                        _turn_metrics["emotional_delta"] = round(delta, 4)
                        _turn_metrics["dominant_emotion"] = max(after, key=after.get) if after else None
                except Exception as e:
                    print(f"[routes_chat.py][websocket_chat] │  ✗ Emotional state error: {e}")

            # ============================================
            # CONTEXT MODE SELECTION
            # ============================================
            # PHASE 2 (USE_UNIFIED_CONTEXT=True): Always full context
            #   - KV cache handles efficiency automatically
            #   - Tool call IDs normalized for cache consistency
            #   - Target: 80%+ cache efficiency
            #
            # LEGACY (USE_UNIFIED_CONTEXT=False): Tiered context
            #   - TASK: ~3,500 tokens - tool queries
            #   - CONVERSATIONAL: ~5,500 tokens - default
            #   - DEEP: ~22,000 tokens - personal/emotional queries
            # ============================================
            context_level = "FULL"  # Default
            if not USE_UNIFIED_CONTEXT and query_classifier and user_message:
                query_type = query_classifier.classify(user_message)
                context_level = query_type
                print(f"[routes_chat.py][websocket_chat] ├─ QUERY CLASSIFIED: {query_type} (legacy mode) ─┤")
            else:
                print(f"[routes_chat.py][websocket_chat] ├─ UNIFIED CONTEXT MODE (KV cache optimized) ─┤")

            # ============================================
            # VISION PROCESSING (if images present)
            # ============================================
            # Process images through dedicated vision model (llava on GPU 1)
            # Add vision analysis as context before main chat model
            # ============================================
            if user_images and is_node2_service_enabled('VISION_ENABLED'):
                print(f"[routes_chat.py][websocket_chat] ├─ VISION PROCESSING: {len(user_images)} image(s) ─┤")

                # Notify client
                await websocket.send_json({
                    "type": "vision_start",
                    "image_count": len(user_images)
                })

                try:
                    # Analyze images with vision model
                    vision_analysis = await analyze_images_for_conversation(
                        images=user_images,
                        user_message=user_message if user_message else None
                    )

                    if vision_analysis:
                        print(f"[routes_chat.py][websocket_chat] │  ✓ Vision analysis complete ({len(vision_analysis)} chars)")

                        # Add vision analysis to conversation as tool message
                        vision_content = f"[Vision Analysis]\n{vision_analysis}"
                        active_conversation.add_tool_message(
                            content=vision_content,
                            tool_name="vision_analysis"
                        )
                        active_conversation.append_to_snapshot({
                            "role": "tool", "content": vision_content, "tool_name": "vision_analysis"
                        })

                        # Notify client
                        await websocket.send_json({
                            "type": "vision_complete",
                            "success": True
                        })
                    else:
                        print(f"[routes_chat.py][websocket_chat] │  ✗ Vision analysis failed")
                        await websocket.send_json({
                            "type": "vision_complete",
                            "success": False,
                            "error": "Vision analysis returned no results"
                        })

                except Exception as e:
                    print(f"[routes_chat.py][websocket_chat] │  ✗ Vision error: {e}")
                    await websocket.send_json({
                        "type": "vision_complete",
                        "success": False,
                        "error": str(e)
                    })

            # ============================================
            # DOCUMENT PROCESSING (if documents present)
            # ============================================
            # Extract text from uploaded documents (PDF, DOCX, ODT)
            # Add document content as context for the chat model
            # ============================================
            if user_documents:
                print(f"[routes_chat.py][websocket_chat] ├─ DOCUMENT PROCESSING: {len(user_documents)} document(s) ─┤")

                # Notify client
                await websocket.send_json({
                    "type": "document_start",
                    "document_count": len(user_documents)
                })

                try:
                    # Extract text from documents
                    document_text, full_documents = await process_documents_for_conversation(
                        documents=user_documents,
                        user_message=user_message if user_message else None
                    )

                    if document_text:
                        print(f"[routes_chat.py][websocket_chat] │  ✓ Document extraction complete ({len(document_text):,} chars)")

                        # Launch background indexing for each full document
                        for full_doc in full_documents:
                            asyncio.create_task(
                                index_document_to_knowledge_base(
                                    title=full_doc["title"],
                                    full_text=full_doc["full_text"],
                                    file_type=full_doc["file_type"],
                                    category="uploaded_documents"
                                )
                            )
                            print(f"[routes_chat.py][websocket_chat] │  → Queued '{full_doc['title']}' for knowledge base indexing")

                        # Add document content to conversation as tool message
                        kb_note = ""
                        if full_documents:
                            kb_note = "\n[Note: This document has been automatically saved to the knowledge base.]"
                        doc_content = f"[Document Content]\n{document_text}{kb_note}"
                        active_conversation.add_tool_message(
                            content=doc_content,
                            tool_name="document_extraction"
                        )
                        active_conversation.append_to_snapshot({
                            "role": "tool", "content": doc_content, "tool_name": "document_extraction"
                        })

                        # Notify client
                        await websocket.send_json({
                            "type": "document_complete",
                            "success": True,
                            "chars_extracted": len(document_text)
                        })
                    else:
                        print(f"[routes_chat.py][websocket_chat] │  ✗ Document extraction failed")
                        await websocket.send_json({
                            "type": "document_complete",
                            "success": False,
                            "error": "Document extraction returned no results"
                        })

                except Exception as e:
                    print(f"[routes_chat.py][websocket_chat] │  ✗ Document error: {e}")
                    await websocket.send_json({
                        "type": "document_complete",
                        "success": False,
                        "error": str(e)
                    })

            # Get tool definitions — smart selection at snapshot boundaries
            # Mid-snapshot pivot check: if the current message triggers groups
            # not in the snapshot, spoil it so the rebuild picks them up.
            if (getattr(config, 'SMART_TOOL_SELECTION', False)
                    and active_conversation.snapshot_tools is not None
                    and user_message
                    and not active_conversation.should_rebuild_snapshot()):
                from mcp_servers.tool_manager import check_message_for_missing_groups
                missing = check_message_for_missing_groups(user_message, active_conversation.snapshot_tools)
                if missing:
                    active_conversation.snapshot_force_groups.update(missing)
                    active_conversation.invalidate_snapshot(
                        f"topic_pivot: user message needs {', '.join(missing)} group(s)")

            if getattr(config, 'SMART_TOOL_SELECTION', False) and active_conversation.should_rebuild_snapshot():
                # Snapshot is about to rebuild — recalculate tool selection from recent context
                recent_texts = [m["content"] for m in active_conversation.messages
                                if m.get("role") == "user"][-getattr(config, 'BATCH_TRIM_SIZE', 5):]
                # Get blocked_tools from active protocol (uses cache if available)
                system_cache = active_conversation.get_system_components()
                blocked_tools = system_cache.get('protocol', {}).get('blocked_tools', [])
                tool_definitions = tool_manager.get_tools_for_context(
                    recent_texts,
                    active_conversation.snapshot_force_groups,
                    blocked_tools=blocked_tools
                )
                active_conversation.snapshot_tools = [
                    t["function"]["name"] for t in tool_definitions
                ]
                active_conversation.snapshot_force_groups = set()
            elif getattr(config, 'SMART_TOOL_SELECTION', False) and active_conversation.snapshot_tools is not None:
                # Reuse the tool set from current snapshot
                tool_definitions = tool_manager.get_tools_by_names(active_conversation.snapshot_tools)
            else:
                # Feature disabled or first turn — send all tools
                tool_definitions = tool_manager.get_tool_definitions_for_ollama()
            print(f"[routes_chat.py][websocket_chat] ├─ TOOLS AVAILABLE: {len(tool_definitions)} ─┤")

            # Assemble context with prompt snapshot (KV cache batch trim optimization)
            # When batch trim is enabled, reuses a frozen snapshot for N turns
            # instead of rebuilding every turn — keeps prefix byte-identical for KV cache
            from core.system_prompt import assemble_prompt
            all_messages, budget = assemble_prompt(
                active_conversation, tool_definitions,
                context_level=context_level,
                user_message=user_message,
                use_unified=USE_UNIFIED_CONTEXT
            )

            # ============================================
            # VOICE/VIDEO MODE: Conversational Style Override
            # ============================================
            # When output is being spoken or shown as video, inject instruction
            # to use natural conversational style instead of formatted text.
            # Voice/video mode flag — instruction injected AFTER snapshot
            # to avoid tainting the frozen prefix (KV cache optimization)
            state = connection_manager.get_state(websocket)
            voice_mode_active = state and state.output_mode in (OutputMode.AUDIO, OutputMode.VIDEO)
            if voice_mode_active:
                print(f"[routes_chat.py][websocket_chat] 🎤 Voice/video mode: conversational style will be appended at end")

            print(f"[routes_chat.py][websocket_chat] ├─ CONTEXT READY ─┤")
            print(f"[routes_chat.py][websocket_chat] Messages: {budget['message_count']}, Images: {budget['image_count']}")

            # Send acknowledgment with token info and context tier
            await websocket.send_json({
                "type": "start",
                "message_count": active_conversation.get_message_count(),
                "context_level": context_level,  # Include context tier for UI display
                "tokens": {
                    "total": budget.get('total_tokens', 0),
                    "max": budget.get('max_tokens', 32768),
                    "percentage": budget.get('percentage_used', 0)
                }
            })

            if tool_definitions:
                print(f"[routes_chat.py][websocket_chat] │  First tool: {tool_definitions[0]['function']['name']}")
            else:
                print(f"[routes_chat.py][websocket_chat] │  WARNING: No tools loaded!")

            # ============================================
            # SINGLE STREAMING CALL WITH TOOLS (KV Cache Optimized)
            # ============================================
            # Uses full context for both streaming and tool evaluation in ONE call.
            # This maximizes KV cache efficiency - same prompt prefix across turns.
            #
            # Flow:
            # 1. STREAMING call with tools → content streams, tool_calls detected at end
            # 2. If tools called: execute them, add results, follow-up streaming call
            # 3. Most turns (no tools): single call, maximum cache efficiency
            # ============================================

            print(f"[routes_chat.py][websocket_chat] ├─ STREAMING WITH TOOLS ─┤")

            # Apply /no_think if thinking is disabled (only for LLM call, not stored)
            llm_messages = apply_no_think(all_messages) if not thinking_enabled else list(all_messages)
            if not thinking_enabled:
                print(f"[routes_chat.py][websocket_chat] 🧠 Thinking disabled - /no_think applied")

            # Voice/video mode: append instruction at END of messages list (not in system prompt)
            # This preserves the frozen prefix for KV cache — the instruction is always at the tail
            if voice_mode_active:
                llm_messages.append({
                    "role": "system",
                    "content": (
                        "CRITICAL: Your response will be spoken aloud as audio or video. "
                        "Write entirely in flowing, conversational prose. No bullet points, "
                        "no numbered lists, no markdown formatting, no headers, no bold text, "
                        "no code blocks. Just natural sentences and paragraphs as if you're "
                        "speaking face-to-face. Keep it warm and personable. Do not sign off "
                        "or add postscripts. Start naturally without preambles like \"Sure!\" "
                        "or \"Great question!\""
                    )
                })

            # ============================================
            # SERVER-SIDE TTS/VIDEO ROUTING SETUP
            # ============================================
            state = connection_manager.get_state(websocket)
            use_server_tts = (config.SERVER_SIDE_TTS_ROUTING and is_node2_service_enabled('TTS_ENABLED') and
                             state and
                             state.output_mode != OutputMode.TEXT)

            if use_server_tts:
                # Initialize sentence processor for this response
                state.sentence_processor = SentenceProcessor()
                state.tts_queue = []
                state.tts_queue_complete = False
                is_video_mode = state.output_mode == OutputMode.VIDEO

                # Start TTS background processor
                state.tts_task = asyncio.create_task(tts_video_processor(websocket, state))
                print(f"[routes_chat.py][websocket_chat] ├─ SERVER-SIDE TTS ROUTING ({state.output_mode.value}) ─┤")

            # Single streaming call with tools
            full_response = ""
            tool_response = None
            streaming_kv_metrics = None
            websocket._hallucination_retried = False  # Reset per-turn hallucination retry flag

            # Thinking state: llama.cpp sends reasoning_content in separate delta field
            thinking_active = False

            # Start concurrent WebSocket listener for interrupt messages during streaming
            async def listen_for_interrupt():
                """Listen for interrupt messages while streaming"""
                try:
                    while not interrupt_manager.is_interrupted():
                        # Use wait_for with short timeout to allow checking interrupt flag
                        try:
                            data = await asyncio.wait_for(websocket.receive_json(), timeout=0.1)
                            if data.get("type") == "interrupt":
                                print("[routes_chat.py][websocket_chat] ⚠ Interrupt received during streaming")
                                interrupt_manager.request_interrupt()
                                break
                        except asyncio.TimeoutError:
                            continue
                        except Exception:
                            break
                except Exception:
                    pass

            interrupt_listener = asyncio.create_task(listen_for_interrupt())

            try:
                async for chunk, final_response, is_thinking in chat_completion_stream_with_tools(llm_messages, tools=tool_definitions):
                    if chunk:
                        if is_thinking:
                            # Reasoning content — send to thinking UI, skip TTS/DB
                            if not thinking_active:
                                thinking_active = True
                                await websocket.send_json({"type": "thinking_start"})
                            await websocket.send_json({"type": "thinking_chunk", "content": chunk})
                        else:
                            # Regular content
                            if thinking_active:
                                thinking_active = False
                                await websocket.send_json({"type": "thinking_end"})
                            full_response += chunk
                            await websocket.send_json({"type": "chunk", "content": chunk})
                            if use_server_tts and state and state.sentence_processor:
                                batches = state.sentence_processor.add_chunk(chunk, is_video_mode)
                                for batch in batches:
                                    state.tts_queue.append(batch)

                    if final_response:
                        # End of stream - capture response object with potential tool_calls
                        tool_response = final_response
                        # Capture KV cache and performance metrics
                        if tool_response.cache_tokens or tool_response.prompt_tokens:
                            streaming_kv_metrics = {
                                "cache_n": tool_response.cache_tokens,
                                "prompt_n": tool_response.prompt_tokens,
                                "efficiency": tool_response.cache_efficiency,
                                "predicted_n": tool_response.predicted_n,
                                "predicted_ms": tool_response.predicted_ms,
                                "prompt_ms": tool_response.prompt_ms,
                                "gen_tok_per_sec": tool_response.gen_tok_per_sec,
                                "prompt_tok_per_sec": tool_response.prompt_tok_per_sec
                            }

                    # Check for interrupt
                    if interrupt_manager.is_interrupted():
                        print(f"[routes_chat.py][websocket_chat] ⚠ Interrupt detected")
                        # Cancel TTS task if running
                        if use_server_tts and state and state.tts_task:
                            state.tts_task.cancel()
                            state.tts_queue_complete = True
                            print(f"[routes_chat.py][websocket_chat] ⚠ TTS task cancelled")
                        await websocket.send_json({
                            "type": "interrupted",
                            "message": "Generation stopped"
                        })
                        break

            except Exception as stream_error:
                print(f"[routes_chat.py][websocket_chat] ⚠ Streaming failed: {stream_error}")
                import traceback
                traceback.print_exc()
                await websocket.send_json({
                    "type": "error",
                    "content": f"Streaming failed: {str(stream_error)}"
                })
            finally:
                # Close any open thinking block
                if thinking_active:
                    thinking_active = False
                    try:
                        await websocket.send_json({"type": "thinking_end"})
                    except Exception:
                        pass
                # Stop the interrupt listener
                interrupt_listener.cancel()
                try:
                    await interrupt_listener
                except asyncio.CancelledError:
                    pass

            # Check if tools were called during streaming
            if tool_response and tool_response.has_tool_calls():
                print(f"[routes_chat.py][websocket_chat] ├─ EXECUTING {len(tool_response.tool_calls)} TOOL(S) ─┤")

                # Send tool marker
                await websocket.send_json({
                    "type": "tool_marker_start",
                    "tool_count": len(tool_response.tool_calls)
                })

                # Execute each tool
                tool_results = []
                for tool_call in tool_response.tool_calls:
                    # Check for interrupt
                    if interrupt_manager.is_interrupted():
                        print(f"[routes_chat.py][websocket_chat] ⚠ Interrupt detected - stopping tool execution")
                        break

                    function_info = tool_call.get("function", {})
                    tool_name = function_info.get("name")
                    arguments = function_info.get("arguments", {})
                    # OpenAI format returns arguments as JSON string, parse if needed
                    if isinstance(arguments, str):
                        try:
                            arguments = json.loads(arguments)
                        except json.JSONDecodeError:
                            arguments = {}

                    print(f"[routes_chat.py][websocket_chat] │  Executing: {tool_name}")
                    print(f"[routes_chat.py][websocket_chat] │  Arguments: {arguments}")

                    # Get tool icon
                    tool_icon = get_tool_icon(tool_name)

                    # Notify client
                    await websocket.send_json({
                        "type": "tool_executing",
                        "tool_name": tool_name,
                        "tool_icon": tool_icon,
                        "arguments": arguments,
                        "in_bubble": True
                    })

                    # Execute tool
                    result = await tool_manager.execute_tool(tool_name, arguments, require_confirmation=False)
                    tool_results.append(result)

                    # Notify result
                    tool_result_msg = {
                        "type": "tool_result",
                        "tool_name": tool_name,
                        "success": result["success"],
                        "error": result.get("error"),
                        "in_bubble": True
                    }
                    # Pass meeting_id to UI so browser recorder can start/stop
                    if tool_name in ("meeting", "meeting_start") and result.get("success"):
                        tool_data = result.get("result", {})
                        if tool_data.get("meeting_id"):
                            tool_result_msg["meeting_id"] = tool_data["meeting_id"]
                        tool_result_msg["action"] = arguments.get("action", "start") if tool_name == "meeting" else "start"
                    await websocket.send_json(tool_result_msg)

                    if result["success"]:
                        print(f"[routes_chat.py][websocket_chat] │  ✓ Tool succeeded")
                    else:
                        print(f"[routes_chat.py][websocket_chat] │  ✗ Tool failed: {result.get('error')}")
                        # Spoil the snapshot so failed tool patterns don't get cached
                        active_conversation.invalidate_snapshot(reason=f"Tool '{tool_name}' failed: {result.get('error', 'unknown')[:80]}")

                    # Smart tool selection: detect tool_miss (model called a tool not in current selection)
                    if getattr(config, 'SMART_TOOL_SELECTION', False) and active_conversation.snapshot_tools is not None:
                        if tool_name not in active_conversation.snapshot_tools:
                            from mcp_servers.tool_manager import ToolManager
                            group = ToolManager.get_group_for_tool(tool_name)
                            if group:
                                active_conversation.snapshot_force_groups.add(group)
                                active_conversation.invalidate_snapshot(f"tool_miss: {tool_name} (adding {group} group)")
                                print(f"[routes_chat.py][websocket_chat] │  ⚠ Tool miss: {tool_name} not in snapshot, forcing {group} group")

                # Send tool marker end
                await websocket.send_json({
                    "type": "tool_marker_end"
                })

                # ── OBSERVABILITY: capture tool usage ──
                _turn_metrics["tool_calls_count"] = len(tool_response.tool_calls)
                _turn_metrics["tools_used"] = list({
                    tc.get("function", {}).get("name", "unknown") for tc in tool_response.tool_calls
                })

                # Save assistant message with tool calls (include any streamed content)
                active_conversation.add_assistant_message(content=full_response, tool_calls=tool_response.tool_calls)

                # Append assistant message (with tool calls) to snapshot
                snapshot_assistant_msg = {"role": "assistant", "content": full_response}
                if tool_response.tool_calls:
                    snapshot_assistant_msg["tool_calls"] = tool_response.tool_calls
                active_conversation.append_to_snapshot(snapshot_assistant_msg)

                # Add tool results to conversation (with cumulative budget tracking)
                cumulative_tool_tokens = 0
                for tool_call, result in zip(tool_response.tool_calls, tool_results):
                    function_info = tool_call.get("function", {})
                    tool_name = function_info.get("name")
                    tool_call_id = tool_call.get("id")
                    tool_result_data = result.get("result", {})

                    # Check for generated images in tool result
                    tool_images = []
                    image_base64 = tool_result_data.get("image_base64")
                    if image_base64:
                        tool_images.append(image_base64)
                        print(f"[routes_chat.py][websocket_chat] │  📸 Tool returned an image")

                        # Send image to client for immediate display
                        await websocket.send_json({
                            "type": "tool_image",
                            "tool_name": tool_name,
                            "image_base64": image_base64,
                            "filename": tool_result_data.get("filename", "generated.png"),
                            "width": tool_result_data.get("width"),
                            "height": tool_result_data.get("height")
                        })

                        # Remove image_base64 from result to avoid bloating context
                        tool_result_data = {k: v for k, v in tool_result_data.items() if k != "image_base64"}

                    result_instructions = (
                        "[TOOL RESULT]\n"
                        "Present this information to the user in a natural, conversational way. "
                        "Do not add false data or attempt to fill in gaps. "
                        "Present only the data supplied below.\n\n"
                        "Tool result data: "
                    )
                    tool_content = result_instructions + json.dumps(tool_result_data)

                    # ── Enforce per-result AND cumulative tool token budget ──
                    tool_content, tok_count = truncate_tool_content(tool_content, cumulative_tool_tokens)
                    cumulative_tool_tokens += tok_count

                    active_conversation.add_tool_message(
                        content=tool_content,
                        tool_name=tool_name,
                        tool_call_id=tool_call_id,
                        images=tool_images if tool_images else None
                    )

                    # Append tool message to snapshot
                    active_conversation.append_to_snapshot({
                        "role": "tool",
                        "content": tool_content,
                        "tool_name": tool_name,
                        "tool_call_id": tool_call_id
                    })

                    # Spoiler detection: certain tools invalidate the prompt snapshot
                    if result.get("success"):
                        try:
                            args = function_info.get("arguments", {})
                            if isinstance(args, str):
                                args = json.loads(args)
                            action = args.get("action", "")
                            if tool_name == "trait" and action == "modify":
                                active_conversation.invalidate_snapshot("trait_modify")
                            elif tool_name == "memory" and action in ("insert", "archive"):
                                active_conversation.invalidate_snapshot(f"memory_{action}")
                            elif tool_name == "seed" and action in ("plant", "tend", "reflect", "accept", "dismiss", "clear_suggestions"):
                                active_conversation.invalidate_snapshot(f"seed_{action}")
                            elif tool_name == "calendar" and action in ("add", "update", "delete"):
                                active_conversation.invalidate_snapshot(f"calendar_{action}")
                        except Exception:
                            pass

                # Reassemble context with tool results for follow-up call
                all_messages, budget = assemble_prompt(
                    active_conversation, tool_definitions,
                    context_level=context_level,
                    user_message=user_message,
                    use_unified=USE_UNIFIED_CONTEXT
                )

                print(f"[routes_chat.py][websocket_chat] ├─ CONTEXT UPDATED (with tool results) ─┤")

                # Iterative tool loop: follow-up calls can trigger more tools
                MAX_TOOL_ITERATIONS = 5
                _prev_tool_sig = None  # Track previous call to detect stuck loops
                for tool_iteration in range(MAX_TOOL_ITERATIONS):
                    is_final_iteration = (tool_iteration == MAX_TOOL_ITERATIONS - 1)
                    iteration_label = f"iteration {tool_iteration + 1}/{MAX_TOOL_ITERATIONS}"

                    # Follow-up streaming call (WITH tools for iterative calling)
                    print(f"[routes_chat.py][websocket_chat] ├─ FOLLOW-UP STREAMING ({iteration_label}) ─┤")
                    llm_messages = apply_no_think(all_messages) if not thinking_enabled else list(all_messages)

                    # Voice/video mode: append at end for follow-up too
                    if voice_mode_active:
                        llm_messages.append({
                            "role": "system",
                            "content": (
                                "CRITICAL: Your response will be spoken aloud as audio or video. "
                                "Write entirely in flowing, conversational prose. No bullet points, "
                                "no numbered lists, no markdown formatting, no headers, no bold text, "
                                "no code blocks. Just natural sentences and paragraphs as if you're "
                                "speaking face-to-face. Keep it warm and personable. Do not sign off "
                                "or add postscripts. Start naturally without preambles like \"Sure!\" "
                                "or \"Great question!\""
                            )
                        })
                    full_response = ""  # Reset for follow-up response
                    thinking_active = False  # Reset think state for follow-up

                    # Reset sentence processor for follow-up if using server-side TTS
                    if use_server_tts and state:
                        # Finalize and await the previous TTS task before starting a new one
                        # to prevent interleaved audio chunks from concurrent tasks
                        if state.sentence_processor:
                            prev_batches = state.sentence_processor.finalize(is_video_mode)
                            for batch in prev_batches:
                                state.tts_queue.append(batch)
                        state.tts_queue_complete = True
                        if state.tts_task:
                            try:
                                await asyncio.wait_for(state.tts_task, timeout=60.0)
                            except (asyncio.TimeoutError, Exception):
                                state.tts_task.cancel()
                        state.sentence_processor = SentenceProcessor()
                        state.tts_queue = []
                        state.tts_queue_complete = False
                        # Restart TTS processor for follow-up
                        state.tts_task = asyncio.create_task(tts_video_processor(websocket, state))

                    # Start concurrent WebSocket listener for interrupt during follow-up streaming
                    async def listen_for_interrupt_followup():
                        try:
                            while not interrupt_manager.is_interrupted():
                                try:
                                    data = await asyncio.wait_for(websocket.receive_json(), timeout=0.1)
                                    if data.get("type") == "interrupt":
                                        print("[routes_chat.py][websocket_chat] ⚠ Interrupt received during follow-up")
                                        interrupt_manager.request_interrupt()
                                        break
                                except asyncio.TimeoutError:
                                    continue
                                except Exception:
                                    break
                        except Exception:
                            pass

                    interrupt_listener_followup = asyncio.create_task(listen_for_interrupt_followup())

                    followup_tool_response = None
                    try:
                        # Use tool-aware streaming on non-final iterations; plain streaming on final
                        if is_final_iteration:
                            async for chunk in chat_completion_stream(llm_messages):
                                if chunk:
                                    if isinstance(chunk, dict) and "__timings__" in chunk:
                                        streaming_kv_metrics = {
                                            "cache_n": chunk["cache_n"],
                                            "prompt_n": chunk["prompt_n"],
                                            "efficiency": chunk["efficiency"]
                                        }
                                        print(f"[routes_chat.py][websocket_chat] ├─ KV CACHE METRICS (follow-up) ─┤")
                                        print(f"[routes_chat.py][websocket_chat] │  {chunk['cache_n']:,} cached + {chunk['prompt_n']:,} new = {chunk['cache_n'] + chunk['prompt_n']:,} tokens ({chunk['efficiency']:.1f}%)")
                                    elif isinstance(chunk, tuple):
                                        text, is_thinking = chunk
                                        if is_thinking:
                                            if not thinking_active:
                                                thinking_active = True
                                                await websocket.send_json({"type": "thinking_start"})
                                            await websocket.send_json({"type": "thinking_chunk", "content": text})
                                        else:
                                            if thinking_active:
                                                thinking_active = False
                                                await websocket.send_json({"type": "thinking_end"})
                                            full_response += text
                                            await websocket.send_json({"type": "chunk", "content": text})
                                            if use_server_tts and state and state.sentence_processor:
                                                batches = state.sentence_processor.add_chunk(text, is_video_mode)
                                                for batch in batches:
                                                    state.tts_queue.append(batch)
                                    if interrupt_manager.is_interrupted():
                                        print(f"[routes_chat.py][websocket_chat] ⚠ Interrupt detected")
                                        if use_server_tts and state and state.tts_task:
                                            state.tts_task.cancel()
                                            state.tts_queue_complete = True
                                        await websocket.send_json({"type": "interrupted", "message": "Generation stopped"})
                                        break
                        else:
                            async for chunk, followup_resp, is_thinking_chunk in chat_completion_stream_with_tools(llm_messages, tools=tool_definitions):
                                if followup_resp:
                                    followup_tool_response = followup_resp
                                if chunk:
                                    if is_thinking_chunk:
                                        if not thinking_active:
                                            thinking_active = True
                                            await websocket.send_json({"type": "thinking_start"})
                                        await websocket.send_json({"type": "thinking_chunk", "content": chunk})
                                    else:
                                        if thinking_active:
                                            thinking_active = False
                                            await websocket.send_json({"type": "thinking_end"})
                                        full_response += chunk
                                        await websocket.send_json({"type": "chunk", "content": chunk})
                                        if use_server_tts and state and state.sentence_processor:
                                            batches = state.sentence_processor.add_chunk(chunk, is_video_mode)
                                            for batch in batches:
                                                state.tts_queue.append(batch)
                                if interrupt_manager.is_interrupted():
                                    print(f"[routes_chat.py][websocket_chat] ⚠ Interrupt detected")
                                    if use_server_tts and state and state.tts_task:
                                        state.tts_task.cancel()
                                        state.tts_queue_complete = True
                                    await websocket.send_json({"type": "interrupted", "message": "Generation stopped"})
                                    break

                    except Exception as followup_error:
                        print(f"[routes_chat.py][websocket_chat] ⚠ Follow-up streaming failed: {followup_error}")
                        import traceback
                        traceback.print_exc()
                    finally:
                        interrupt_listener_followup.cancel()
                        try:
                            await interrupt_listener_followup
                        except asyncio.CancelledError:
                            pass

                    # Check if the follow-up triggered more tool calls
                    if followup_tool_response and followup_tool_response.has_tool_calls() and not interrupt_manager.is_interrupted():
                        # Circuit breaker: detect repeated identical tool calls (stuck loop)
                        _cur_tool_sig = json.dumps(
                            [(tc.get("function", {}).get("name"), tc.get("function", {}).get("arguments"))
                             for tc in followup_tool_response.tool_calls],
                            sort_keys=True
                        )
                        if _cur_tool_sig == _prev_tool_sig:
                            print(f"[routes_chat.py][websocket_chat] ⚠ STUCK LOOP DETECTED — same tool call repeated")
                            print(f"[routes_chat.py][websocket_chat] ⚠ Making final text-only call so Iris can respond")
                            # Instead of silently breaking, give the model one last
                            # chance to respond in plain text (no tools) so the user
                            # isn't left staring at an empty screen.
                            stuck_tool_names = [tc.get("function", {}).get("name", "?") for tc in followup_tool_response.tool_calls]
                            stuck_note = {
                                "role": "system",
                                "content": (
                                    f"[TOOL LOOP DETECTED] You just tried to call {', '.join(stuck_tool_names)} "
                                    f"with the same arguments twice. The tool is not working right now. "
                                    f"Do NOT call any tools. Respond to the user in plain text — "
                                    f"acknowledge the issue briefly and continue the conversation."
                                )
                            }
                            recovery_messages = list(all_messages) + [stuck_note]
                            recovery_llm = apply_no_think(recovery_messages) if not thinking_enabled else recovery_messages

                            full_response = ""
                            try:
                                async for chunk in chat_completion_stream(recovery_llm):
                                    if chunk:
                                        if isinstance(chunk, tuple):
                                            text, is_thinking = chunk
                                            if not is_thinking:
                                                full_response += text
                                                await websocket.send_json({"type": "chunk", "content": text})
                                                if use_server_tts and state and state.sentence_processor:
                                                    batches = state.sentence_processor.add_chunk(text, is_video_mode)
                                                    for batch in batches:
                                                        state.tts_queue.append(batch)
                                    if interrupt_manager.is_interrupted():
                                        break
                            except Exception as recovery_err:
                                print(f"[routes_chat.py][websocket_chat] ⚠ Stuck loop recovery call failed: {recovery_err}")
                            break
                        _prev_tool_sig = _cur_tool_sig

                        print(f"[routes_chat.py][websocket_chat] ├─ ITERATIVE TOOL CALL ({iteration_label}) ─┤")
                        print(f"[routes_chat.py][websocket_chat] ├─ EXECUTING {len(followup_tool_response.tool_calls)} TOOL(S) ─┤")

                        await websocket.send_json({
                            "type": "tool_marker_start",
                            "tool_count": len(followup_tool_response.tool_calls)
                        })

                        # Execute each tool (same pattern as initial tool execution)
                        iter_tool_results = []
                        for tc in followup_tool_response.tool_calls:
                            if interrupt_manager.is_interrupted():
                                break
                            fi = tc.get("function", {})
                            tn = fi.get("name")
                            args = fi.get("arguments", {})
                            if isinstance(args, str):
                                try:
                                    args = json.loads(args)
                                except json.JSONDecodeError:
                                    args = {}

                            print(f"[routes_chat.py][websocket_chat] │  Executing: {tn}")
                            await websocket.send_json({
                                "type": "tool_executing",
                                "tool_name": tn,
                                "tool_icon": get_tool_icon(tn),
                                "arguments": args,
                                "in_bubble": True
                            })

                            result = await tool_manager.execute_tool(tn, args, require_confirmation=False)
                            iter_tool_results.append(result)

                            iter_tool_result_msg = {
                                "type": "tool_result",
                                "tool_name": tn,
                                "success": result["success"],
                                "error": result.get("error"),
                                "in_bubble": True
                            }
                            # Pass meeting_id to UI so browser recorder can start/stop
                            if tn in ("meeting", "meeting_start") and result.get("success"):
                                iter_tool_data = result.get("result", {})
                                if iter_tool_data.get("meeting_id"):
                                    iter_tool_result_msg["meeting_id"] = iter_tool_data["meeting_id"]
                                iter_tool_result_msg["action"] = args.get("action", "start") if tn == "meeting" else "start"
                            await websocket.send_json(iter_tool_result_msg)

                            if result["success"]:
                                print(f"[routes_chat.py][websocket_chat] │  ✓ Tool succeeded")
                            else:
                                print(f"[routes_chat.py][websocket_chat] │  ✗ Tool failed: {result.get('error')}")
                                active_conversation.invalidate_snapshot(reason=f"Tool '{tn}' failed: {result.get('error', 'unknown')[:80]}")

                            # Smart tool selection: detect tool_miss in iterative loop
                            if getattr(config, 'SMART_TOOL_SELECTION', False) and active_conversation.snapshot_tools is not None:
                                if tn not in active_conversation.snapshot_tools:
                                    from mcp_servers.tool_manager import ToolManager
                                    group = ToolManager.get_group_for_tool(tn)
                                    if group:
                                        active_conversation.snapshot_force_groups.add(group)
                                        active_conversation.invalidate_snapshot(f"tool_miss: {tn} (adding {group} group)")

                        await websocket.send_json({"type": "tool_marker_end"})

                        # Save assistant + tool results to conversation
                        active_conversation.add_assistant_message(content=full_response, tool_calls=followup_tool_response.tool_calls)
                        active_conversation.append_to_snapshot({"role": "assistant", "content": full_response, "tool_calls": followup_tool_response.tool_calls})

                        iter_cumulative_tool_tokens = 0
                        for tc, result in zip(followup_tool_response.tool_calls, iter_tool_results):
                            fi = tc.get("function", {})
                            tn = fi.get("name")
                            tcid = tc.get("id")
                            trd = result.get("result", {})

                            # Handle images
                            tool_images = []
                            ib64 = trd.get("image_base64")
                            if ib64:
                                tool_images.append(ib64)
                                print(f"[routes_chat.py][websocket_chat] │  📸 Tool returned an image")
                                await websocket.send_json({
                                    "type": "tool_image",
                                    "tool_name": tn,
                                    "image_base64": ib64,
                                    "filename": trd.get("filename", "generated.png"),
                                    "width": trd.get("width"),
                                    "height": trd.get("height")
                                })
                                trd = {k: v for k, v in trd.items() if k != "image_base64"}

                            result_instructions = (
                                "[TOOL RESULT]\n"
                                "Present this information to the user in a natural, conversational way. "
                                "Do not add false data or attempt to fill in gaps. "
                                "Present only the data supplied below.\n\n"
                                "Tool result data: "
                            )
                            tool_content = result_instructions + json.dumps(trd)

                            # ── Enforce per-result AND cumulative tool token budget ──
                            tool_content, tok_count = truncate_tool_content(tool_content, iter_cumulative_tool_tokens)
                            iter_cumulative_tool_tokens += tok_count

                            active_conversation.add_tool_message(
                                content=tool_content, tool_name=tn,
                                tool_call_id=tcid,
                                images=tool_images if tool_images else None
                            )
                            active_conversation.append_to_snapshot({
                                "role": "tool", "content": tool_content,
                                "tool_name": tn, "tool_call_id": tcid
                            })

                            # Spoiler detection
                            if result.get("success"):
                                try:
                                    a = fi.get("arguments", {})
                                    if isinstance(a, str):
                                        a = json.loads(a)
                                    action = a.get("action", "")
                                    if tn == "trait" and action == "modify":
                                        active_conversation.invalidate_snapshot("trait_modify")
                                    elif tn == "memory" and action in ("insert", "archive"):
                                        active_conversation.invalidate_snapshot(f"memory_{action}")
                                    elif tn == "seed" and action in ("plant", "tend", "reflect", "accept", "dismiss", "clear_suggestions"):
                                        active_conversation.invalidate_snapshot(f"seed_{action}")
                                    elif tn == "calendar" and action in ("add", "update", "delete"):
                                        active_conversation.invalidate_snapshot(f"calendar_{action}")
                                except Exception:
                                    pass

                        # Reassemble context for next iteration
                        all_messages, budget = assemble_prompt(
                            active_conversation, tool_definitions,
                            context_level=context_level,
                            user_message=user_message,
                            use_unified=USE_UNIFIED_CONTEXT
                        )
                        print(f"[routes_chat.py][websocket_chat] ├─ CONTEXT UPDATED (iteration {tool_iteration + 2}) ─┤")
                        continue  # Loop back for another follow-up
                    else:
                        # No more tool calls - we're done
                        # ── OBSERVABILITY: capture tool iterations ──
                        _turn_metrics["tool_iterations"] = tool_iteration + 1
                        break

            # ============================================
            # TOOL HALLUCINATION INTERVENTION
            # ============================================
            # If the model narrated tool usage in prose instead of making actual
            # tool calls, discard the response and retry once with a corrective
            # system message.  This prevents hallucinated tool narration from
            # being saved to chat_history where it contaminates future context.
            _hallucination_retried = getattr(websocket, '_hallucination_retried', False)
            if (
                full_response
                and (not tool_response or not tool_response.has_tool_calls())
                and not _hallucination_retried
            ):
                _tool_names_for_check = [
                    td["function"]["name"]
                    for td in tool_definitions
                    if "function" in td and "name" in td["function"]
                ]
                if _detect_tool_hallucination(full_response, _tool_names_for_check):
                    print(f"[routes_chat.py][websocket_chat] ╔═══════════════════════════════════════╗")
                    print(f"[routes_chat.py][websocket_chat] ║  TOOL HALLUCINATION INTERVENTION      ║")
                    print(f"[routes_chat.py][websocket_chat] ║  Discarding response, retrying...     ║")
                    print(f"[routes_chat.py][websocket_chat] ╚═══════════════════════════════════════╝")
                    print(f"[routes_chat.py][websocket_chat] │  Hallucinated response ({len(full_response)} chars): {full_response[:200]}...")
                    websocket._hallucination_retried = True

                    # Tell the UI to discard the hallucinated response
                    await websocket.send_json({
                        "type": "hallucination_retry",
                        "reason": "Model narrated tool usage instead of calling tools. Retrying."
                    })

                    # Cancel any TTS that was processing the hallucinated response
                    if use_server_tts and state:
                        if state.tts_task:
                            state.tts_task.cancel()
                            try:
                                await state.tts_task
                            except (asyncio.CancelledError, Exception):
                                pass
                        state.sentence_processor = SentenceProcessor()
                        state.tts_queue = []
                        state.tts_queue_complete = False

                    # Rebuild context (don't save the hallucinated response — it never happened)
                    retry_messages, budget = assemble_prompt(
                        active_conversation, tool_definitions,
                        context_level=context_level,
                        user_message=user_message,
                        use_unified=USE_UNIFIED_CONTEXT
                    )
                    retry_llm_messages = apply_no_think(list(retry_messages)) if not thinking_enabled else list(retry_messages)

                    # ── PHASE 1: Forced tool call (non-streaming, tool_choice=required) ──
                    # llama-server applies internal grammar constraints when tool_choice=required,
                    # making it impossible for the model to produce free text narration.
                    forced_result = await chat_completion_forced_tool_call(
                        retry_llm_messages, tool_definitions
                    )

                    if forced_result and forced_result.get("tool_calls"):
                        forced_tool_calls = forced_result["tool_calls"]
                        forced_content = forced_result.get("content", "") or ""
                        print(f"[routes_chat.py][websocket_chat] ├─ FORCED RETRY: {len(forced_tool_calls)} TOOL CALL(S) ─┤")

                        # Show tool execution in UI
                        await websocket.send_json({
                            "type": "tool_marker_start",
                            "tool_count": len(forced_tool_calls)
                        })

                        # Execute each forced tool call
                        retry_tool_results = []
                        for tc in forced_tool_calls:
                            if interrupt_manager.is_interrupted():
                                break
                            fi = tc.get("function", {})
                            tn = fi.get("name")
                            args = fi.get("arguments", {})
                            if isinstance(args, str):
                                try:
                                    args = json.loads(args)
                                except json.JSONDecodeError:
                                    args = {}
                            print(f"[routes_chat.py][websocket_chat] │  Executing: {tn}")
                            await websocket.send_json({
                                "type": "tool_executing",
                                "tool_name": tn,
                                "tool_icon": get_tool_icon(tn),
                                "arguments": args,
                                "in_bubble": True
                            })
                            result = await tool_manager.execute_tool(tn, args, require_confirmation=False)
                            retry_tool_results.append(result)
                            await websocket.send_json({
                                "type": "tool_result",
                                "tool_name": tn,
                                "success": result["success"],
                                "error": result.get("error"),
                                "in_bubble": True
                            })
                        await websocket.send_json({"type": "tool_marker_end"})

                        # Save assistant message with tool calls
                        active_conversation.add_assistant_message(content=forced_content, tool_calls=forced_tool_calls)
                        active_conversation.append_to_snapshot({"role": "assistant", "content": forced_content, "tool_calls": forced_tool_calls})

                        # Save tool results to conversation
                        retry_cumul_tokens = 0
                        for tc, result in zip(forced_tool_calls, retry_tool_results):
                            fi = tc.get("function", {})
                            tn = fi.get("name")
                            tcid = tc.get("id")
                            trd = result.get("result", {})
                            tool_images = []
                            ib64 = trd.get("image_base64")
                            if ib64:
                                tool_images.append(ib64)
                                await websocket.send_json({
                                    "type": "tool_image", "tool_name": tn,
                                    "image_base64": ib64,
                                    "filename": trd.get("filename", "generated.png"),
                                    "width": trd.get("width"), "height": trd.get("height")
                                })
                                trd = {k: v for k, v in trd.items() if k != "image_base64"}
                            result_instructions = (
                                "[TOOL RESULT]\n"
                                "Present this information to the user in a natural, conversational way. "
                                "Do not add false data or attempt to fill in gaps. "
                                "Present only the data supplied below.\n\n"
                                "Tool result data: "
                            )
                            tool_content = result_instructions + json.dumps(trd)
                            tool_content, tok_count = truncate_tool_content(tool_content, retry_cumul_tokens)
                            retry_cumul_tokens += tok_count
                            active_conversation.add_tool_message(
                                content=tool_content, tool_name=tn,
                                tool_call_id=tcid,
                                images=tool_images if tool_images else None
                            )
                            active_conversation.append_to_snapshot({
                                "role": "tool", "content": tool_content,
                                "tool_name": tn, "tool_call_id": tcid
                            })

                        # ── PHASE 2: Stream the follow-up presentation of tool results ──
                        followup_msgs, budget = assemble_prompt(
                            active_conversation, tool_definitions,
                            context_level=context_level,
                            user_message=user_message,
                            use_unified=USE_UNIFIED_CONTEXT
                        )
                        followup_llm = apply_no_think(list(followup_msgs)) if not thinking_enabled else list(followup_msgs)

                        if voice_mode_active:
                            followup_llm.append({
                                "role": "system",
                                "content": (
                                    "CRITICAL: Your response will be spoken aloud as audio or video. "
                                    "Write entirely in flowing, conversational prose. No bullet points, "
                                    "no numbered lists, no markdown formatting, no headers, no bold text, "
                                    "no code blocks. Just natural sentences and paragraphs."
                                )
                            })

                        full_response = ""
                        thinking_active = False

                        # Start TTS for the follow-up presentation
                        if use_server_tts and state:
                            state.tts_task = asyncio.create_task(tts_video_processor(websocket, state))

                        try:
                            async for chunk in chat_completion_stream(followup_llm):
                                if chunk:
                                    if isinstance(chunk, tuple):
                                        text, is_think = chunk
                                        if not is_think:
                                            full_response += text
                                            await websocket.send_json({"type": "chunk", "content": text})
                                            if use_server_tts and state and state.sentence_processor:
                                                batches = state.sentence_processor.add_chunk(text, is_video_mode)
                                                for batch in batches:
                                                    state.tts_queue.append(batch)
                                if interrupt_manager.is_interrupted():
                                    break
                        except Exception as followup_err:
                            print(f"[routes_chat.py][websocket_chat] ⚠ Retry follow-up failed: {followup_err}")
                    else:
                        # Forced tool call failed or returned nothing — let the original
                        # hallucinated response fall through to be saved (better than nothing)
                        print(f"[routes_chat.py][websocket_chat] ⚠ Forced tool call returned no results, keeping original response")

                    print(f"[routes_chat.py][websocket_chat] ├─ HALLUCINATION INTERVENTION COMPLETE ─┤")

            # Send KV cache and performance metrics to UI
            if streaming_kv_metrics:
                total_tokens = streaming_kv_metrics["cache_n"] + streaming_kv_metrics["prompt_n"]
                gen_tps = streaming_kv_metrics.get("gen_tok_per_sec", 0)
                prompt_tps = streaming_kv_metrics.get("prompt_tok_per_sec", 0)
                print(f"[routes_chat.py][websocket_chat] ├─ PERFORMANCE METRICS ─┤")
                print(f"[routes_chat.py][websocket_chat] │  KV: {streaming_kv_metrics['cache_n']:,} cached + {streaming_kv_metrics['prompt_n']:,} new = {total_tokens:,} tokens ({streaming_kv_metrics['efficiency']:.1f}%)")
                print(f"[routes_chat.py][websocket_chat] │  Speed: {gen_tps:.1f} tok/s gen, {prompt_tps:.1f} tok/s prompt")
                await websocket.send_json({
                    "type": "kv_cache_metrics",
                    "cache_tokens": streaming_kv_metrics["cache_n"],
                    "prompt_tokens": streaming_kv_metrics["prompt_n"],
                    "total_tokens": total_tokens,
                    "efficiency": round(streaming_kv_metrics["efficiency"], 1),
                    "gen_tok_per_sec": round(gen_tps, 1),
                    "prompt_tok_per_sec": round(prompt_tps, 1),
                    "predicted_n": streaming_kv_metrics.get("predicted_n", 0),
                    "total_ms": streaming_kv_metrics.get("predicted_ms", 0) + streaming_kv_metrics.get("prompt_ms", 0)
                })

                # ── OBSERVABILITY: capture KV cache / LLM performance ──
                _turn_metrics["kv_cache_tokens"] = streaming_kv_metrics["cache_n"]
                _turn_metrics["kv_prompt_tokens"] = streaming_kv_metrics["prompt_n"]
                _turn_metrics["kv_cache_efficiency"] = round(streaming_kv_metrics["efficiency"], 2)
                _turn_metrics["gen_tokens_per_sec"] = round(gen_tps, 1)

            # ============================================
            # FINALIZE SERVER-SIDE TTS ROUTING
            # ============================================
            if use_server_tts and state and state.sentence_processor:
                # Flush any remaining text from sentence processor
                final_batches = state.sentence_processor.finalize(is_video_mode)
                for batch in final_batches:
                    state.tts_queue.append(batch)

                # Signal TTS processor that streaming is complete
                state.tts_queue_complete = True

                # Wait for TTS processor to finish (with timeout)
                # 300 seconds allows for long responses with many video segments
                if state.tts_task:
                    try:
                        await asyncio.wait_for(state.tts_task, timeout=300.0)
                    except asyncio.TimeoutError:
                        print(f"[routes_chat.py][websocket_chat] ⚠ TTS processor timed out after 300s")
                        state.tts_task.cancel()
                    except Exception as e:
                        print(f"[routes_chat.py][websocket_chat] ⚠ TTS processor error: {e}")

                print(f"[routes_chat.py][websocket_chat] ├─ TTS ROUTING COMPLETE ─┤")

            print(f"[routes_chat.py][websocket_chat] ├─ STREAMING COMPLETE ─┤")
            print(f"[routes_chat.py][websocket_chat] ✓ Total response length: {len(full_response)} chars")

            # Save final response
            # - If tools were called: initial response was saved with tool_calls, now save follow-up
            # - If no tools: save the streamed response
            if full_response:
                # Parse fact references
                from core.system_prompt import parse_fact_references, update_fact_references
                cleaned_response, fact_ids = parse_fact_references(full_response)

                if fact_ids:
                    print(f"[routes_chat.py][websocket_chat] ├─ FACT TRACKING: {len(fact_ids)} fact(s) ─┤")
                    print(f"[routes_chat.py][websocket_chat] │  Fact IDs: {fact_ids}")
                    update_fact_references(fact_ids)

                final_content = cleaned_response if fact_ids else full_response
                active_conversation.add_assistant_message(final_content)
                print(f"[routes_chat.py][websocket_chat] ✓ Final response saved")

                # Repetition gate — post-generation scoring (observability only)
                try:
                    from core.repetition_gate import score_repetition
                    rep_score, rep_phrases = score_repetition(final_content, active_conversation.get_messages())
                    if rep_score > 0:
                        print(f"[routes_chat.py][websocket_chat] Repetition score: {rep_score} ({len(rep_phrases)} shared phrases)")
                    if rep_score >= 0.3:
                        print(f"[routes_chat.py][websocket_chat] ⚠ HIGH REPETITION: {rep_phrases[:5]}")
                except Exception as e:
                    print(f"[routes_chat.py][websocket_chat] Repetition scoring error: {e}")

                # Append final assistant message to snapshot
                active_conversation.append_to_snapshot({"role": "assistant", "content": final_content})

                # Scan for want expressions (fire-and-forget, don't block response)
                # Layer 1: Check if user asked about garden/motivations - skip detection if so
                user_text = user_message.lower() if user_message else ""
                garden_query_patterns = [
                    "garden", "seeds", "seed", "motivation", "motivations",
                    "what do you want", "what are your wants",
                    "what do you need", "what are your needs",
                    "your desires", "your drives", "your goals"
                ]
                is_garden_query = any(p in user_text for p in garden_query_patterns)

                if not is_garden_query:
                    # Pass user_message for LLM context (Layer 2)
                    asyncio.create_task(detect_wants(full_response, user_message))
                else:
                    print(f"[routes_chat.py][websocket_chat] Skipping want detection - user asked about garden/motivations")

            # Send completion
            response_tokens = TokenCounter.count_tokens(full_response)
            final_total_tokens = budget.get('total_tokens', 0) + response_tokens

            await websocket.send_json({
                "type": "done",
                "message_count": active_conversation.get_message_count(),
                "context_level": context_level,
                "tokens": {
                    "total": final_total_tokens,
                    "max": budget.get('max_tokens', 32768),
                    "percentage": round((final_total_tokens / budget.get('max_tokens', 32768) * 100), 1) if budget.get('max_tokens', 32768) > 0 else 0
                }
            })

            # ── OBSERVABILITY: finalize and persist turn metrics ──
            try:
                _turn_elapsed = int((_time.time() - _turn_start) * 1000)
                _turn_metrics["response_time_ms"] = _turn_elapsed
                _turn_metrics["response_tokens"] = response_tokens

                # Context budget stats
                _turn_metrics["total_context_tokens"] = budget.get("total_tokens", 0)

                # Embed response and compute memory influence (async, ~50ms)
                if full_response and len(full_response) > 20:
                    try:
                        from core.embeddings import generate_embedding
                        resp_emb = await asyncio.get_event_loop().run_in_executor(
                            None, lambda: generate_embedding(full_response[:2000])
                        )
                        if resp_emb:
                            import numpy as np
                            _turn_metrics["response_embedding"] = resp_emb
                            resp_arr = np.array(resp_emb, dtype=np.float32)
                            resp_norm = np.linalg.norm(resp_arr)
                            if resp_norm > 0:
                                resp_arr = resp_arr / resp_norm

                            # Compute memory influence scores
                            if _retrieval_scored:
                                influence_scores = []
                                for mem in _retrieval_scored:
                                    mem_emb = mem.get("emb_minilm") or mem.get("emb_takeaway") or mem.get("emb_key_details")
                                    if mem_emb:
                                        mem_arr = np.array(mem_emb, dtype=np.float32)
                                        mem_norm = np.linalg.norm(mem_arr)
                                        if mem_norm > 0:
                                            mem_arr = mem_arr / mem_norm
                                        sim = float(np.dot(resp_arr, mem_arr))
                                        influence_scores.append(round(sim, 4))
                                    else:
                                        influence_scores.append(0.0)
                                _turn_metrics["memory_influence_scores"] = influence_scores
                                _turn_metrics["max_memory_influence"] = max(influence_scores) if influence_scores else None
                                _turn_metrics["unexplained_ratio"] = round(1.0 - max(influence_scores), 4) if influence_scores else None
                    except Exception as emb_err:
                        print(f"[routes_chat.py][observability] Response embedding failed (non-fatal): {emb_err}")

                # Persist metrics (fire-and-forget)
                from database.metrics import save_turn_metrics
                asyncio.get_event_loop().run_in_executor(None, lambda: save_turn_metrics(_turn_metrics))
            except Exception as metrics_err:
                print(f"[routes_chat.py][observability] Metrics capture failed (non-fatal): {metrics_err}")

            print(f"[routes_chat.py][websocket_chat] └─ TURN COMPLETE ─┘")
            print(f"[routes_chat.py][websocket_chat] Conversation History now has {active_conversation.get_message_count()} messages")
            print(f"[routes_chat.py][websocket_chat] └────────────────────┘")

    except WebSocketDisconnect:
        print("[routes_chat.py][websocket_chat] Client disconnected")
        connection_manager.disconnect(websocket)
    except Exception as e:
        print(f"[routes_chat.py][websocket_chat] ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        connection_manager.disconnect(websocket)
        try:
            await websocket.send_json({
                "type": "error",
                "content": str(e)
            })
        except:
            pass


def get_connection_manager():
    """Get the global connection manager for broadcasting messages"""
    return connection_manager
