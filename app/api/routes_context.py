"""
Context inspection API routes
Provides visibility into what's being sent to Ollama
"""

from fastapi import APIRouter
from typing import Dict, Any
import sys
import os; PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..' if '__file__' in dir() else '.')); sys.path.insert(0, PROJECT_ROOT)
from app import config
from core.system_prompt import build_system_message
from core.token_counter import TokenCounter
from core import attachments

router = APIRouter(prefix="/api/conversation", tags=["context"])

# This will be set by main.py
active_conversation = None

def set_active_conversation(conv):
    """Set the active conversation instance"""
    global active_conversation
    active_conversation = conv

@router.get("/context")
async def get_conversation_context() -> Dict[str, Any]:
    """
    Get the actual context that would be sent to Ollama
    Includes images loaded from attachments
    """
    try:
        # Build exactly what would be sent to Ollama
        system_msg = build_system_message()
        conversation_msgs = active_conversation.get_messages()
        
        # Load images for messages with attachments
        messages_with_images = []
        for msg in conversation_msgs:
            msg_copy = msg.copy()
            
            # Load images if attachments present
            if "attachments" in msg:
                try:
                    attachment_list = attachments.parse_attachments_json(msg["attachments"])
                    if attachment_list:
                        encoded_images = []
                        for att in attachment_list:
                            if att.get("type") == "image":
                                base64_img = attachments.load_and_encode(att["path"])
                                if base64_img:
                                    # Add data URI prefix for frontend display
                                    mime_type = att.get("mime_type", "image/png")
                                    encoded_images.append(f"data:{mime_type};base64,{base64_img}")
                        
                        if encoded_images:
                            msg_copy["images"] = encoded_images
                except Exception as e:
                    print(f"[routes_context.py] Error loading images for message: {e}")
            
            messages_with_images.append(msg_copy)
        
        all_messages = [system_msg] + messages_with_images
        
        # Count tokens
        system_tokens = TokenCounter.count_tokens(system_msg["content"])
        conversation_tokens = TokenCounter.count_message_tokens(conversation_msgs)
        total_tokens = system_tokens + conversation_tokens
        
        return {
            "session_id": active_conversation.get_session_id(),
            "message_count": len(conversation_msgs),
            "total_messages": len(all_messages),
            "system_prompt_tokens": system_tokens,
            "conversation_tokens": conversation_tokens,
            "total_tokens": total_tokens,
            "context_window": config.OLLAMA_CONTEXT_WINDOW,
            "tokens_remaining": config.OLLAMA_CONTEXT_WINDOW - total_tokens,
            "messages": all_messages  # Full context with images for display
        }
    except Exception as e:
        return {
            "error": str(e),
            "message_count": 0,
            "total_tokens": 0
        }

@router.get("/context/summary")
async def get_context_summary() -> Dict[str, Any]:
    """
    Get context statistics without full message content
    Lighter weight for dashboards
    """
    try:
        system_msg = build_system_message()
        conversation_msgs = active_conversation.get_messages()
        
        # Count by role
        role_counts = {}
        role_tokens = {}
        for msg in conversation_msgs:
            role = msg.get("role", "unknown")
            role_counts[role] = role_counts.get(role, 0) + 1
            role_tokens[role] = role_tokens.get(role, 0) + TokenCounter.count_tokens(msg.get("content", ""))
        
        system_tokens = TokenCounter.count_tokens(system_msg["content"])
        conversation_tokens = TokenCounter.count_message_tokens(conversation_msgs)
        
        return {
            "session_id": active_conversation.get_session_id(),
            "total_messages": len(conversation_msgs),
            "message_counts_by_role": role_counts,
            "token_counts_by_role": role_tokens,
            "system_prompt_tokens": system_tokens,
            "conversation_tokens": conversation_tokens,
            "total_tokens": system_tokens + conversation_tokens,
            "context_window": config.OLLAMA_CONTEXT_WINDOW,
            "utilization_percent": round(((system_tokens + conversation_tokens) / config.OLLAMA_CONTEXT_WINDOW) * 100, 1)
        }
    except Exception as e:
        return {"error": str(e)}

@router.get("/info")
async def conversation_info() -> Dict[str, Any]:
    """Get current conversation info"""
    return {
        "session_id": active_conversation.get_session_id(),
        "message_count": active_conversation.get_message_count(),
        "model": config.OLLAMA_MODEL,
        "context_window": config.OLLAMA_CONTEXT_WINDOW
    }