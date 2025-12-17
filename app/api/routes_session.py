"""
Session management API routes
"""

from fastapi import APIRouter
from typing import Dict, Any
import sys
import os; PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..' if '__file__' in dir() else '.')); sys.path.insert(0, PROJECT_ROOT)
from database import persistence
from core.conversation import ConversationHistory

router = APIRouter(prefix="/api/sessions", tags=["sessions"])

# This will be set by main.py
active_conversation = None

def set_active_conversation(conv):
    """Set the active conversation instance"""
    global active_conversation
    active_conversation = conv

def get_active_conversation():
    """Get the active conversation instance"""
    return active_conversation

@router.get("/recent")
async def get_recent_sessions(limit: int = 10) -> Dict[str, Any]:
    """Get list of recent sessions"""
    sessions = persistence.get_recent_sessions(limit)
    return {"sessions": sessions}

@router.post("/load/{session_id}")
async def load_session(session_id: str) -> Dict[str, Any]:
    """Load an existing session"""
    global active_conversation
    try:
        active_conversation = ConversationHistory(session_id=session_id, enable_persistence=True)
        return {
            "status": "loaded",
            "session_id": session_id,
            "message_count": active_conversation.get_message_count()
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }

@router.post("/new")
async def new_session() -> Dict[str, Any]:
    """Create a new session"""
    global active_conversation
    active_conversation = ConversationHistory(session_id=None, enable_persistence=True)
    return {
        "status": "created",
        "session_id": active_conversation.get_session_id(),
        "message_count": 0
    }

@router.post("/clear")
async def clear_conversation() -> Dict[str, Any]:
    """Clear the conversation history (in-memory only)"""
    active_conversation.clear()
    return {"status": "cleared"}
