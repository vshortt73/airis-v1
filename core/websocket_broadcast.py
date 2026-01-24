"""
WebSocket Broadcast Helper Module

Provides global access to the WebSocket broadcast function from routes_chat.py
so that other modules (routes_video, protocol_loader) can push messages to clients.

Usage:
    # In routes_chat.py (at startup):
    from core.websocket_broadcast import set_broadcast_function
    set_broadcast_function(connection_manager.broadcast)

    # In other modules (async context):
    from core.websocket_broadcast import broadcast
    await broadcast({"type": "video_chunk_ready", "session_id": "...", ...})

    # In sync contexts (like protocol_loader):
    from core.websocket_broadcast import broadcast_sync
    broadcast_sync({"type": "protocol_status", "active_protocol": "...", ...})
"""

import asyncio
from typing import Callable, Awaitable, Optional

# Global reference to the broadcast function (set by routes_chat on startup)
_broadcast_fn: Optional[Callable[[dict], Awaitable[None]]] = None


def set_broadcast_function(fn: Callable[[dict], Awaitable[None]]) -> None:
    """
    Register the broadcast function from ConnectionManager.
    Called once at startup from routes_chat.py.

    Args:
        fn: The async broadcast function (connection_manager.broadcast)
    """
    global _broadcast_fn
    _broadcast_fn = fn
    print("[websocket_broadcast] Broadcast function registered")


async def broadcast(message: dict) -> bool:
    """
    Broadcast a message to all connected WebSocket clients (async version).

    Args:
        message: Dict with at least a 'type' key

    Returns:
        True if broadcast was sent, False if no broadcast function available
    """
    if _broadcast_fn is None:
        print("[websocket_broadcast] Warning: Broadcast attempted but no function registered")
        return False

    try:
        await _broadcast_fn(message)
        return True
    except Exception as e:
        print(f"[websocket_broadcast] Error broadcasting: {e}")
        return False


def broadcast_sync(message: dict) -> bool:
    """
    Broadcast a message from a synchronous context.
    Creates a new event loop or uses existing one to run the async broadcast.

    Args:
        message: Dict with at least a 'type' key

    Returns:
        True if broadcast was queued, False if no broadcast function available
    """
    if _broadcast_fn is None:
        print("[websocket_broadcast] Warning: Broadcast attempted but no function registered")
        return False

    try:
        # Try to get running loop
        try:
            loop = asyncio.get_running_loop()
            # We're in an async context, schedule the broadcast
            loop.create_task(_broadcast_fn(message))
            return True
        except RuntimeError:
            # No running loop - create one
            asyncio.run(_broadcast_fn(message))
            return True
    except Exception as e:
        print(f"[websocket_broadcast] Error in sync broadcast: {e}")
        return False


def is_registered() -> bool:
    """Check if broadcast function is registered."""
    return _broadcast_fn is not None
