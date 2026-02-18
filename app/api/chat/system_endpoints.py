"""
System endpoints: /api/system/trigger, /api/contact/message, /api/test, /api/ui/notify.

Extracted from routes_chat.py lines 870-1349.
"""

import json
import asyncio
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel

from inference.client import chat_completion_stream, chat_completion_with_tools
from database.persistence import get_db_connection, load_recent_conversation
from core.system_prompt import assemble_full_context, assemble_unified_context, get_active_protocol, assemble_prompt
from core.sentence_processor import SentenceProcessor, OutputMode
from core.node2_check import is_node2_service_enabled
from app import config

from .tts_handler import tts_video_processor


router = APIRouter(tags=["system"])


# ---------------------------------------------------------------------------
# These module-level references are set by routes_chat.py at import time
# via init_system_endpoints() to avoid circular imports.
# ---------------------------------------------------------------------------
_connection_manager = None
_active_conversation = None
_tool_manager = None
_ensure_tool_manager_connected = None
_USE_UNIFIED_CONTEXT = False


def init_system_endpoints(connection_manager, active_conversation_getter, tool_manager,
                          ensure_connected_fn, use_unified_context):
    """Initialize module-level references. Called once from routes_chat.py."""
    global _connection_manager, _active_conversation, _tool_manager
    global _ensure_tool_manager_connected, _USE_UNIFIED_CONTEXT
    _connection_manager = connection_manager
    _active_conversation = active_conversation_getter  # callable that returns current conversation
    _tool_manager = tool_manager
    _ensure_tool_manager_connected = ensure_connected_fn
    _USE_UNIFIED_CONTEXT = use_unified_context


def _get_active_conversation():
    """Get the current active conversation (may be updated by routes_chat)."""
    if callable(_active_conversation):
        return _active_conversation()
    return _active_conversation


# ---------------------------------------------------------------------------
# /api/test
# ---------------------------------------------------------------------------

@router.post("/api/test")
async def test_endpoint():
    """Simple test endpoint"""
    print("[system_endpoints][test_endpoint] Test endpoint called!")
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# /api/ui/notify
# ---------------------------------------------------------------------------

class UINotificationRequest(BaseModel):
    """Request model for UI notification endpoint"""
    message: str
    style: str = "info"  # info, success, warning, error


@router.post("/api/ui/notify")
async def ui_notify(request: UINotificationRequest):
    """
    Broadcast a UI notification to all connected clients.
    Called by core.ui_notify.ui_msg() from anywhere in the codebase.
    """
    valid_styles = {"info", "success", "warning", "error"}
    style = request.style if request.style in valid_styles else "info"

    await _connection_manager.broadcast({
        "type": "ui_notification",
        "message": request.message,
        "style": style
    })

    return {"status": "ok", "clients": len(_connection_manager.active_connections)}


# ---------------------------------------------------------------------------
# /api/system/trigger
# ---------------------------------------------------------------------------

class SystemTriggerRequest(BaseModel):
    """Request model for system trigger endpoint"""
    content: str
    allow_tools: bool = False
    context_mode: str = "FULL"


@router.post("/api/system/trigger")
async def system_trigger(trigger_request: SystemTriggerRequest):
    """
    Trigger Iris response from system event (face detection, scheduled task, etc.)

    Inserts system message into chat_history and generates Iris's response
    using the normal conversation flow with full tool support.
    """
    active_conversation = _get_active_conversation()

    print(f"[system_endpoints][system_trigger] ┌── SYSTEM TRIGGER ──┐")
    print(f"[system_endpoints][system_trigger] Received request: {trigger_request}")

    try:
        content = trigger_request.content
        if not content:
            print(f"[system_endpoints][system_trigger] ✗ Missing content field")
            return {"success": False, "error": "Missing 'content' field"}

        print(f"[system_endpoints][system_trigger] System message: {content[:100]}...")

        await _ensure_tool_manager_connected()

        # 1. Save system message to chat_history directly
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT session_id FROM chat_sessions
            ORDER BY session_id DESC
            LIMIT 1
        """)
        result = cursor.fetchone()
        session_id = result[0] if result else 'default'

        cursor.execute("""
            INSERT INTO chat_history (session_id, role, message, c_timestamp)
            VALUES (%s, 'system', %s, %s)
        """, (session_id, content, datetime.now()))

        conn.commit()
        cursor.close()
        conn.close()

        print(f"[system_endpoints][system_trigger] ✓ System message saved to chat_history")

        # 2. Load conversation context
        recent_messages = load_recent_conversation(max_messages=30)

        active_conversation.messages = []
        for msg in recent_messages:
            role = msg.get('role')
            content_val = msg.get('content', '')

            message_dict = {
                'role': role,
                'content': content_val
            }

            if role == 'tool':
                message_dict['tool_name'] = msg.get('tool_name', '')
                if msg.get('tool_call_id'):
                    message_dict['tool_call_id'] = msg.get('tool_call_id')

            active_conversation.messages.append(message_dict)

        # Smart tool selection for system triggers
        if getattr(config, 'SMART_TOOL_SELECTION', False):
            recent_texts = [m["content"] for m in active_conversation.messages
                            if m.get("role") == "user"][-getattr(config, 'BATCH_TRIM_SIZE', 5):]
            protocol = get_active_protocol()
            blocked_tools = protocol.get('blocked_tools', [])
            tool_definitions = _tool_manager.get_tools_for_context(
                recent_texts,
                active_conversation.snapshot_force_groups,
                blocked_tools=blocked_tools
            )
            active_conversation.snapshot_force_groups = set()
        else:
            tool_definitions = _tool_manager.get_tool_definitions_for_ollama()

        context_mode = trigger_request.context_mode
        print(f"[system_endpoints][system_trigger] Using context mode: {context_mode}")

        if _USE_UNIFIED_CONTEXT:
            context, budget = assemble_unified_context(active_conversation, tool_definitions)
        else:
            context, budget = assemble_full_context(active_conversation, tool_definitions, skip_fast_memory=(context_mode == "GREETING"), context_level=context_mode)
        print(f"[system_endpoints][system_trigger] ✓ Context loaded ({len(tool_definitions)} tools available)")

        # 3. Check if tools are allowed
        if trigger_request.allow_tools:
            print(f"[system_endpoints][system_trigger] → First call (checking for tool requests)...")
            first_response = await chat_completion_with_tools(
                messages=context,
                tools=tool_definitions
            )
            tool_calls = first_response.get('message', {}).get('tool_calls', [])
        else:
            print(f"[system_endpoints][system_trigger] ⚡ Skipping tool evaluation (allow_tools=False)")
            tool_calls = []

        if tool_calls:
            print(f"[system_endpoints][system_trigger] 🔧 Tools requested: {len(tool_calls)}")

            active_conversation.add_assistant_message(
                content=first_response.get('message', {}).get('content', ''),
                tool_calls=tool_calls
            )

            for tool_call in tool_calls:
                function_name = tool_call.get('function', {}).get('name')
                arguments = tool_call.get('function', {}).get('arguments', {})
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except json.JSONDecodeError:
                        arguments = {}

                print(f"[system_endpoints][system_trigger]   🔧 Executing: {function_name}")

                try:
                    result = await _tool_manager.execute_tool(function_name, arguments)
                    active_conversation.add_tool_message(
                        content=json.dumps(result),
                        tool_name=function_name
                    )
                    print(f"[system_endpoints][system_trigger]   ✓ {function_name} completed")
                except Exception as tool_error:
                    error_result = {"success": False, "error": str(tool_error)}
                    active_conversation.add_tool_message(
                        content=json.dumps(error_result),
                        tool_name=function_name
                    )
                    print(f"[system_endpoints][system_trigger]   ✗ {function_name} failed: {tool_error}")

            if _USE_UNIFIED_CONTEXT:
                context, budget = assemble_unified_context(active_conversation, tool_definitions)
            else:
                context, budget = assemble_full_context(active_conversation, tool_definitions, skip_fast_memory=False, context_level='FULL')

        # 4. Generate final response
        print(f"[system_endpoints][system_trigger] → Generating response...")
        print(f"[system_endpoints][system_trigger] Connected WebSocket clients: {len(_connection_manager.active_connections)}")
        assistant_response = ""
        has_clients = len(_connection_manager.active_connections) > 0

        context.append({
            "role": "user",
            "content": f"[SYSTEM TRIGGER] {trigger_request.content}"
        })
        print(f"[system_endpoints][system_trigger] Appended trigger as final user message ({len(trigger_request.content)} chars)")

        # Strip tool-related messages when not using tools
        if not trigger_request.allow_tools or not tool_calls:
            clean_context = []
            stripped = 0
            for msg in context:
                if msg.get("role") == "tool":
                    stripped += 1
                    continue
                if "tool_calls" in msg:
                    msg = {k: v for k, v in msg.items() if k != "tool_calls"}
                    if not msg.get("content"):
                        msg["content"] = "(tool interaction omitted)"
                clean_context.append(msg)
            if stripped > 0:
                print(f"[system_endpoints][system_trigger] Stripped {stripped} tool messages from context (no tools in payload)")
            context = clean_context

        # Server-side TTS routing setup for greetings
        use_server_tts = False
        tts_state = None
        tts_websocket = None
        is_video_mode = False

        if has_clients and config.SERVER_SIDE_TTS_ROUTING and is_node2_service_enabled('TTS_ENABLED'):
            for ws in _connection_manager.active_connections:
                state = _connection_manager.get_state(ws)
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
            print(f"[system_endpoints][system_trigger] ├─ SERVER-SIDE TTS ROUTING ({tts_state.output_mode.value}) ─┤")
        else:
            print(f"[system_endpoints][system_trigger] TTS routing: {'no clients' if not has_clients else 'browser-side or text mode'}")

        if has_clients:
            await _connection_manager.broadcast({
                "type": "start",
                "context_level": "FULL"
            })

        async for content_chunk in chat_completion_stream(messages=context):
            if not content_chunk:
                continue

            if isinstance(content_chunk, dict):
                continue
            if isinstance(content_chunk, tuple):
                text, is_thinking = content_chunk
                if is_thinking or not text:
                    continue
                content_chunk = text

            assistant_response += content_chunk

            if has_clients:
                await _connection_manager.broadcast({
                    "type": "chunk",
                    "content": content_chunk
                })

            if use_server_tts and tts_state and tts_state.sentence_processor:
                batches = tts_state.sentence_processor.add_chunk(content_chunk, is_video_mode)
                for batch in batches:
                    tts_state.tts_queue.append(batch)

        # Finalize TTS
        if use_server_tts and tts_state and tts_state.sentence_processor:
            final_batches = tts_state.sentence_processor.finalize(is_video_mode)
            for batch in final_batches:
                tts_state.tts_queue.append(batch)
            tts_state.tts_queue_complete = True

            if tts_state.tts_task:
                try:
                    await asyncio.wait_for(tts_state.tts_task, timeout=300.0)
                except asyncio.TimeoutError:
                    print(f"[system_endpoints][system_trigger] ⚠ TTS processor timed out")
                    tts_state.tts_task.cancel()
                except Exception as e:
                    print(f"[system_endpoints][system_trigger] ⚠ TTS processor error: {e}")

            print(f"[system_endpoints][system_trigger] ├─ TTS ROUTING COMPLETE ─┤")

        # 5. Save assistant response
        active_conversation.add_assistant_message(assistant_response)
        print(f"[system_endpoints][system_trigger] ✓ Response generated: {assistant_response[:80]}...")

        # Repetition scoring
        try:
            from core.repetition_gate import score_repetition
            rep_score, rep_phrases = score_repetition(assistant_response, active_conversation.get_messages())
            if rep_score > 0:
                print(f"[system_endpoints][system_trigger] Repetition score: {rep_score} ({len(rep_phrases)} shared phrases)")
            if rep_score >= 0.3:
                print(f"[system_endpoints][system_trigger] ⚠ HIGH REPETITION: {rep_phrases[:5]}")
        except Exception as e:
            print(f"[system_endpoints][system_trigger] Repetition scoring error: {e}")

        # 6. Handle completion
        if has_clients:
            await _connection_manager.broadcast({"type": "done"})
        else:
            print(f"[system_endpoints][system_trigger] ⏳ No clients connected - storing as pending greeting")
            _connection_manager.pending_greeting = assistant_response

        print(f"[system_endpoints][system_trigger] └── COMPLETE ──┘")

        return {
            "success": True,
            "response": assistant_response
        }

    except Exception as e:
        print(f"[system_endpoints][system_trigger] ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "error": str(e)
        }


# ---------------------------------------------------------------------------
# /api/contact/message
# ---------------------------------------------------------------------------

class ContactMessageRequest(BaseModel):
    """Request model for contact message endpoint (autonomous drive contact_victor)"""
    content: str
    source: str = "autonomous_drive"
    reason: str = ""


@router.post("/api/contact/message")
async def save_contact_message(request: ContactMessageRequest):
    """
    Save Iris's autonomous contact message as an assistant message.

    Used by the autonomous drive system when Iris initiates contact (contact_victor).
    """
    active_conversation = _get_active_conversation()

    print(f"[system_endpoints][contact_message] ┌── CONTACT MESSAGE ──┐")
    print(f"[system_endpoints][contact_message] Source: {request.source}")
    print(f"[system_endpoints][contact_message] Content: {request.content[:100]}...")

    try:
        content = request.content
        if not content:
            return {"success": False, "error": "Missing 'content' field"}

        conn = get_db_connection()
        cursor = conn.cursor()

        session_id = active_conversation.get_session_id()
        if not session_id:
            cursor.execute("""
                SELECT session_id FROM chat_sessions
                ORDER BY start_time DESC
                LIMIT 1
            """)
            result = cursor.fetchone()
            session_id = result[0] if result else None

        sender_with_reason = request.source
        if request.reason:
            sender_with_reason = f"{request.source}:{request.reason}"
            print(f"[system_endpoints][contact_message] Reason: {request.reason}")

        cursor.execute("""
            INSERT INTO chat_history (session_id, role, message, c_timestamp, sender)
            VALUES (%s, 'assistant', %s, %s, %s)
            RETURNING id
        """, (session_id, content, datetime.now(), sender_with_reason))

        message_id = cursor.fetchone()[0]

        conn.commit()
        cursor.close()
        conn.close()

        print(f"[system_endpoints][contact_message] ✓ Saved as assistant message (id={message_id})")

        active_conversation.messages.append({
            "role": "assistant",
            "content": content,
            "sender": sender_with_reason
        })

        if _connection_manager.active_connections:
            await _connection_manager.broadcast({
                "type": "contact_message",
                "role": "assistant",
                "content": content,
                "sender": request.source
            })

        print(f"[system_endpoints][contact_message] └── COMPLETE ──┘")

        return {
            "success": True,
            "message_id": message_id
        }

    except Exception as e:
        print(f"[system_endpoints][contact_message] ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "error": str(e)
        }
