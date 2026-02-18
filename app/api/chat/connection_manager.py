"""
WebSocket connection state and management.

Extracted from routes_chat.py lines 203-343.
"""

from fastapi import WebSocket
from dataclasses import dataclass, field
from typing import Optional, Dict, List
import asyncio

from core.sentence_processor import SentenceProcessor, OutputMode, TextBatch


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


class InterruptManager:
    """Manages interrupt requests for stopping generation"""
    def __init__(self):
        self.interrupt_requested = False

    def request_interrupt(self):
        """Request an interrupt of current generation"""
        self.interrupt_requested = True
        print("[InterruptManager] ⚠ Interrupt requested")

    def clear(self):
        """Clear interrupt flag for new generation"""
        self.interrupt_requested = False

    def is_interrupted(self):
        """Check if interrupt was requested"""
        return self.interrupt_requested
