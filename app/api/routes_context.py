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
        system_msg = build_system_message(user_message=None)  # No user message for static context view
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


@router.get("/messages")
async def get_conversation_messages() -> Dict[str, Any]:
    """
    Get the conversation messages that are loaded into context.
    Shows which messages are full (verbose) vs summarized.
    """
    try:
        messages = active_conversation.get_messages()

        # Analyze messages
        verbose_count = 0
        summary_count = 0
        verbose_tokens = 0
        summary_tokens = 0

        message_list = []
        for i, msg in enumerate(messages):
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            is_summary = msg.get("is_summary", False)
            timeframe = msg.get("timeframe", "")

            tokens = TokenCounter.count_tokens(content)

            if is_summary:
                summary_count += 1
                summary_tokens += tokens
            else:
                verbose_count += 1
                verbose_tokens += tokens

            # Truncate content for display
            preview = content[:200] + "..." if len(content) > 200 else content

            message_list.append({
                "index": i,
                "role": role,
                "is_summary": is_summary,
                "timeframe": timeframe,
                "tokens": tokens,
                "chars": len(content),
                "preview": preview
            })

        return {
            "total_messages": len(messages),
            "verbose_count": verbose_count,
            "verbose_tokens": verbose_tokens,
            "summary_count": summary_count,
            "summary_tokens": summary_tokens,
            "messages": message_list
        }
    except Exception as e:
        return {"error": str(e)}


@router.get("/raw")
async def get_raw_context():
    """
    Get the EXACT context sent to the model.
    This is exactly what Iris sees, with summaries clearly marked.
    """
    from fastapi.responses import PlainTextResponse
    from database.persistence import load_recent_conversation

    try:
        # Load conversation with tiered budgets - same as assemble_full_context does
        verbose_budget = getattr(config, 'VERBOSE_TOKEN_BUDGET', 3000)
        summary_budget = getattr(config, 'SUMMARY_TOKEN_BUDGET', 17000)

        history = load_recent_conversation(
            verbose_budget=verbose_budget,
            summary_budget=summary_budget,
            max_messages=getattr(config, 'MAX_TOTAL_MESSAGES', 50)
        )

        # Build readable output
        output = []
        output.append("=" * 80)
        output.append("CONVERSATION CONTEXT (what Iris sees)")
        output.append(f"Budgets: {verbose_budget:,} verbose + {summary_budget:,} summary tokens")
        output.append("=" * 80)
        output.append("")

        total_tokens = 0
        verbose_count = 0
        summary_count = 0

        for i, msg in enumerate(history):
            role = msg.get("role", "unknown").upper()
            content = msg.get("content", "")
            is_summary = msg.get("is_summary", False)
            timeframe = msg.get("timeframe", "")
            tokens = TokenCounter.count_tokens(content)
            total_tokens += tokens

            if is_summary:
                summary_count += 1
                marker = "📝 SUMMARY"
            else:
                verbose_count += 1
                marker = "📄 VERBOSE"

            output.append(f"{'─' * 80}")
            header = f"[{i}] {role} | {marker} | {tokens:,} tokens"
            if timeframe:
                header += f" | {timeframe}"
            output.append(header)
            output.append(f"{'─' * 80}")
            output.append(content)
            output.append("")

        output.append("=" * 80)
        output.append(f"TOTAL: {len(history)} messages ({verbose_count} verbose, {summary_count} summaries)")
        output.append(f"Tokens: {total_tokens:,} / {config.OLLAMA_CONTEXT_WINDOW:,} ({(total_tokens / config.OLLAMA_CONTEXT_WINDOW * 100):.1f}%)")
        output.append("=" * 80)

        return PlainTextResponse("\n".join(output))

    except Exception as e:
        import traceback
        return PlainTextResponse(f"Error: {e}\n\n{traceback.format_exc()}")