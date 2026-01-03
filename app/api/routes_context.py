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
        # NEW: Return image URLs instead of base64 data for faster loading
        messages_with_images = []
        for msg in conversation_msgs:
            msg_copy = msg.copy()

            # Load images if attachments present
            if "attachments" in msg:
                try:
                    attachment_list = attachments.parse_attachments_json(msg["attachments"])
                    if attachment_list:
                        image_urls = []
                        for att in attachment_list:
                            if att.get("type") == "image":
                                # Instead of loading and encoding, just return the URL
                                # The path is relative to attachments/, e.g., "user/session_id/file.png"
                                path = att.get("path", "")
                                if path:
                                    # Convert filesystem path to URL path
                                    # Remove leading slash if present
                                    url_path = path.lstrip("/")
                                    image_url = f"/attachments/{url_path}"
                                    image_urls.append(image_url)

                        if image_urls:
                            msg_copy["images"] = image_urls
                except Exception as e:
                    print(f"[routes_context.py] Error processing images for message: {e}")

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
    Shows what's ACTUALLY sent to Ollama (not in-memory bloat)
    """
    try:
        # CRITICAL FIX: Use assemble_full_context() to get what's ACTUALLY sent to Ollama
        # This reloads from DB with truncation, not the bloated in-memory conversation
        from core.system_prompt import assemble_full_context
        from mcp_servers.tool_manager import get_tool_manager

        # Get tool definitions to match what chat endpoint does
        tool_manager = get_tool_manager()
        tool_definitions = tool_manager.get_tool_definitions_for_ollama()

        # Assemble context exactly as the chat endpoint does
        all_messages, budget = assemble_full_context(active_conversation, tool_definitions)

        # Separate system message from conversation
        system_msg = all_messages[0] if all_messages else {"content": ""}
        conversation_msgs = all_messages[1:] if len(all_messages) > 1 else []

        # Count by role
        role_counts = {}
        role_tokens = {}
        for msg in conversation_msgs:
            role = msg.get("role", "unknown")
            role_counts[role] = role_counts.get(role, 0) + 1
            role_tokens[role] = role_tokens.get(role, 0) + TokenCounter.count_tokens(msg.get("content", ""))

        system_tokens = TokenCounter.count_tokens(system_msg.get("content", ""))
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
            "utilization_percent": round(((system_tokens + conversation_tokens) / config.OLLAMA_CONTEXT_WINDOW) * 100, 1),
            "note": "This shows what's ACTUALLY sent to Ollama after truncation, not the in-memory bloat"
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