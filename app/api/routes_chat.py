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
import base64
import httpx
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, PROJECT_ROOT)
from core.system_prompt import assemble_full_context, assemble_unified_context
from inference.client import chat_completion_stream, chat_completion_with_tools, chat_completion_stream_with_tools
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

async def refresh_memories_if_needed(message_count: int):
    """
    Refresh episodic memories every 10 messages

    Args:
        message_count: Total number of messages in conversation
    """
    # Trigger memory refresh every 10 messages
    if message_count % 10 == 0 and message_count > 0:
        print(f"[routes_chat.py][refresh_memories] 🧠 Refreshing memories (message count: {message_count})")
        try:
            # Run iris_memory_retrieval.py asynchronously
            memory_script = os.path.join(PROJECT_ROOT, "backend", "memory", "iris_memory_retrieval.py")

            # Run in background, don't wait for completion
            process = await asyncio.create_subprocess_exec(
                "python",
                memory_script,
                "--top_k", "10",
                "--insert", "true",
                "--mode", "replace",
                env={**os.environ, "IRIS_DB_PASSWORD": os.environ.get("IRIS_DB_PASSWORD", "yourpassword")},
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            # Don't await - let it run in background
            asyncio.create_task(_wait_for_memory_refresh(process))

            print(f"[routes_chat.py][refresh_memories] ✓ Memory refresh triggered in background")
        except Exception as e:
            print(f"[routes_chat.py][refresh_memories] ✗ Error triggering memory refresh: {e}")

async def _wait_for_memory_refresh(process):
    """Helper to wait for memory refresh completion and log result"""
    try:
        stdout, stderr = await process.communicate()
        if process.returncode == 0:
            print(f"[routes_chat.py][memory_refresh] ✓ Memory refresh completed successfully")
        else:
            print(f"[routes_chat.py][memory_refresh] ✗ Memory refresh failed with code {process.returncode}")
            if stderr:
                print(f"[routes_chat.py][memory_refresh] Error: {stderr.decode()[:200]}")
    except Exception as e:
        print(f"[routes_chat.py][memory_refresh] ✗ Error waiting for memory refresh: {e}")


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
            content = msg.get('message', '')

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

        # Send 'start' message if clients are connected
        if has_clients:
            await connection_manager.broadcast({
                "type": "start",
                "context_level": "FULL"
            })

        async for content_chunk in chat_completion_stream(
            messages=context
        ):
            # chat_completion_stream yields strings directly, not dicts
            if content_chunk:
                assistant_response += content_chunk

                # Broadcast chunk to WebSocket clients (if any)
                if has_clients:
                    await connection_manager.broadcast({
                        "type": "chunk",
                        "content": content_chunk
                    })

        # 5. Save assistant response to database
        active_conversation.add_assistant_message(assistant_response)
        print(f"[routes_chat.py][system_trigger] ✓ Response generated: {assistant_response[:80]}...")

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

                if mode == OutputMode.VIDEO and config.SERVER_SIDE_TTS_ROUTING:
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

            # Check if we should refresh memories (every 10 messages)
            message_count = len(active_conversation.get_messages())
            await refresh_memories_if_needed(message_count)

            # ============================================
            # EMOTIONAL STATE PROCESSING
            # ============================================
            # Analyze user message and update Iris's emotional state
            # This happens BEFORE context assembly so state is included in prompt
            # ============================================
            if config.EMOTIONAL_STATE and user_message:
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
            if user_images and config.VISION_ENABLED:
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

            # Get tool definitions first (needed for dynamic budgeting)
            tool_definitions = tool_manager.get_tool_definitions_for_ollama()
            print(f"[routes_chat.py][websocket_chat] ├─ TOOLS AVAILABLE: {len(tool_definitions)} ─┤")

            # Assemble context with prompt snapshot (KV cache batch trim optimization)
            # When batch trim is enabled, reuses a frozen snapshot for N turns
            # instead of rebuilding every turn — keeps prefix byte-identical for KV cache
            from core.system_prompt import assemble_context_with_snapshot
            all_messages, budget = assemble_context_with_snapshot(
                active_conversation, tool_definitions,
                context_level=context_level,
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
            use_server_tts = (config.SERVER_SIDE_TTS_ROUTING and
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
                    await websocket.send_json({
                        "type": "tool_result",
                        "tool_name": tool_name,
                        "success": result["success"],
                        "error": result.get("error"),
                        "in_bubble": True
                    })

                    if result["success"]:
                        print(f"[routes_chat.py][websocket_chat] │  ✓ Tool succeeded")
                    else:
                        print(f"[routes_chat.py][websocket_chat] │  ✗ Tool failed: {result.get('error')}")
                        # Spoil the snapshot so failed tool patterns don't get cached
                        active_conversation.invalidate_snapshot(reason=f"Tool '{tool_name}' failed: {result.get('error', 'unknown')[:80]}")

                # Send tool marker end
                await websocket.send_json({
                    "type": "tool_marker_end"
                })

                # Save assistant message with tool calls (include any streamed content)
                active_conversation.add_assistant_message(content=full_response, tool_calls=tool_response.tool_calls)

                # Append assistant message (with tool calls) to snapshot
                snapshot_assistant_msg = {"role": "assistant", "content": full_response}
                if tool_response.tool_calls:
                    snapshot_assistant_msg["tool_calls"] = tool_response.tool_calls
                active_conversation.append_to_snapshot(snapshot_assistant_msg)

                # Add tool results to conversation
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

                    # ── Enforce tool result token budget ──
                    from core.token_counter import TokenCounter
                    tool_result_budget = getattr(config, 'TOOL_RESULTS_BUDGET', 15000)
                    tool_content_tokens = TokenCounter.count_tokens(tool_content)
                    if tool_content_tokens > tool_result_budget:
                        encoder = TokenCounter.get_encoder()
                        encoded = encoder.encode(tool_content)
                        truncated_encoded = encoded[:tool_result_budget - 50]
                        tool_content = encoder.decode(truncated_encoded)
                        tool_content += (
                            "\n\n[TRUNCATED — Result exceeded token budget "
                            f"({tool_content_tokens:,} > {tool_result_budget:,} tokens). "
                            "Data above is incomplete. Do not fabricate the missing portion.]"
                        )
                        print(f"[routes_chat.py] ⚠ Tool result truncated: {tool_content_tokens:,} → {tool_result_budget:,} tokens")

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
                            elif tool_name == "memory" and action == "insert":
                                active_conversation.invalidate_snapshot("memory_insert")
                        except Exception:
                            pass

                # Reassemble context with tool results for follow-up call
                from core.system_prompt import assemble_context_with_snapshot
                all_messages, budget = assemble_context_with_snapshot(
                    active_conversation, tool_definitions,
                    context_level=context_level,
                    use_unified=USE_UNIFIED_CONTEXT
                )

                print(f"[routes_chat.py][websocket_chat] ├─ CONTEXT UPDATED (with tool results) ─┤")

                # Iterative tool loop: follow-up calls can trigger more tools
                MAX_TOOL_ITERATIONS = 5
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

                            await websocket.send_json({
                                "type": "tool_result",
                                "tool_name": tn,
                                "success": result["success"],
                                "error": result.get("error"),
                                "in_bubble": True
                            })

                            if result["success"]:
                                print(f"[routes_chat.py][websocket_chat] │  ✓ Tool succeeded")
                            else:
                                print(f"[routes_chat.py][websocket_chat] │  ✗ Tool failed: {result.get('error')}")
                                active_conversation.invalidate_snapshot(reason=f"Tool '{tn}' failed: {result.get('error', 'unknown')[:80]}")

                        await websocket.send_json({"type": "tool_marker_end"})

                        # Save assistant + tool results to conversation
                        active_conversation.add_assistant_message(content=full_response, tool_calls=followup_tool_response.tool_calls)
                        active_conversation.append_to_snapshot({"role": "assistant", "content": full_response, "tool_calls": followup_tool_response.tool_calls})

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
                                    elif tn == "memory" and action == "insert":
                                        active_conversation.invalidate_snapshot("memory_insert")
                                except Exception:
                                    pass

                        # Reassemble context for next iteration
                        all_messages, budget = assemble_context_with_snapshot(
                            active_conversation, tool_definitions,
                            context_level=context_level,
                            use_unified=USE_UNIFIED_CONTEXT
                        )
                        print(f"[routes_chat.py][websocket_chat] ├─ CONTEXT UPDATED (iteration {tool_iteration + 2}) ─┤")
                        continue  # Loop back for another follow-up
                    else:
                        # No more tool calls - we're done
                        break

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
            from core.token_counter import TokenCounter
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
