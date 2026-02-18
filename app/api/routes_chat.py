"""
Chat WebSocket API route — thin orchestrator.

Dispatches to extracted modules in app/api/chat/ for:
- Connection management (chat/connection_manager.py)
- Tool execution (chat/tool_executor.py)
- TTS/audio (chat/tts_handler.py)
- Video/HLS (chat/video_handler.py)
- Input preprocessing (chat/input_processor.py)
- Core turn pipeline (chat/turn_pipeline.py)
- System endpoints (chat/system_endpoints.py)
- Observability (chat/observability.py)

ARCHITECTURE: Single Streaming Call with Tools (KV cache optimized)
1. STREAMING call with tools → model streams content AND/OR calls tools
2. If tools called: execute them, add results, then follow-up streaming call
3. Only ONE call per turn when no tools needed (majority of turns)
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, PROJECT_ROOT)

from core.system_prompt import assemble_prompt
from mcp_servers.tool_manager import get_tool_manager
from database.fast_reactive_memory import FastReactiveMemory
from core.emotional_state import get_emotional_tracker
from core.websocket_broadcast import set_broadcast_function
from core.sentence_processor import OutputMode
from app import config
from core.node2_check import is_node2_service_enabled

# Extracted chat modules
from app.api.chat.connection_manager import ConnectionManager, InterruptManager
from app.api.chat.input_processor import preprocess_user_turn
from app.api.chat.turn_pipeline import execute_turn, apply_no_think
from app.api.chat.tts_handler import initialize_tts, finalize_tts
from app.api.chat.video_handler import start_video_session_for_connection
from app.api.chat.observability import finalize_response, capture_turn_metrics, send_kv_metrics, send_completion
from app.api.chat.system_endpoints import router as system_router, init_system_endpoints


# PHASE 2: Use unified context (KV cache optimized) instead of tiered query classifier
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

# Global connection manager
connection_manager = ConnectionManager()

# Register broadcast function for other modules to use
set_broadcast_function(connection_manager.broadcast)

# Global interrupt manager (one per server instance)
interrupt_manager = InterruptManager()


def set_active_conversation(conv):
    """Set the active conversation instance"""
    global active_conversation
    active_conversation = conv


def get_connection_manager():
    """Get the global connection manager for broadcasting messages"""
    return connection_manager


async def ensure_tool_manager_connected():
    """Ensure tool manager is connected to MCP servers"""
    if not tool_manager._connected:
        print("[routes_chat.py] Connecting to MCP servers...")
        await tool_manager.connect()


# ---------------------------------------------------------------------------
# Include system endpoints sub-router
# ---------------------------------------------------------------------------
init_system_endpoints(
    connection_manager=connection_manager,
    active_conversation_getter=lambda: active_conversation,
    tool_manager=tool_manager,
    ensure_connected_fn=ensure_tool_manager_connected,
    use_unified_context=USE_UNIFIED_CONTEXT,
)
router.include_router(system_router)


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

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

            # Validate input
            user_message = data.get("message", "").strip()
            user_images = data.get("images", [])
            user_documents = data.get("documents", [])
            thinking_enabled = data.get("thinking", True)
            sender = data.get("sender", "user")

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

            # === 1. INPUT PREPROCESSING ===
            prep = await preprocess_user_turn(
                data, active_conversation, emotional_tracker, websocket
            )
            _turn_metrics = prep.turn_metrics
            user_message = prep.user_message

            # === 2. CONTEXT MODE SELECTION ===
            context_level = "FULL"
            if not USE_UNIFIED_CONTEXT and query_classifier and user_message:
                query_type = query_classifier.classify(user_message)
                context_level = query_type
                print(f"[routes_chat.py][websocket_chat] ├─ QUERY CLASSIFIED: {query_type} (legacy mode) ─┤")
            else:
                print(f"[routes_chat.py][websocket_chat] ├─ UNIFIED CONTEXT MODE (KV cache optimized) ─┤")

            # === 3. STRUCTURAL REPETITION ANALYSIS ===
            structural_feedback = None
            try:
                from core.repetition_gate import analyze_structural_patterns, build_structural_avoidance
                patterns = await analyze_structural_patterns(active_conversation.get_messages())
                if patterns:
                    structural_feedback = build_structural_avoidance(patterns)
            except Exception as e:
                print(f"[routes_chat.py][websocket_chat] │  Structural analysis failed (non-fatal): {e}")

            # === 4. TOOL SELECTION ===
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
                recent_texts = [m["content"] for m in active_conversation.messages
                                if m.get("role") == "user"][-getattr(config, 'BATCH_TRIM_SIZE', 5):]
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
                tool_definitions = tool_manager.get_tools_by_names(active_conversation.snapshot_tools)
            else:
                tool_definitions = tool_manager.get_tool_definitions_for_ollama()
            print(f"[routes_chat.py][websocket_chat] ├─ TOOLS AVAILABLE: {len(tool_definitions)} ─┤")

            # === 5. CONTEXT ASSEMBLY ===
            all_messages, budget = assemble_prompt(
                active_conversation, tool_definitions,
                context_level=context_level,
                user_message=user_message,
                use_unified=USE_UNIFIED_CONTEXT,
                structural_feedback=structural_feedback
            )

            # Voice/video mode flag
            state = connection_manager.get_state(websocket)
            voice_mode_active = state and state.output_mode in (OutputMode.AUDIO, OutputMode.VIDEO)
            is_video_mode = state and state.output_mode == OutputMode.VIDEO
            if voice_mode_active:
                print(f"[routes_chat.py][websocket_chat] 🎤 Voice/video mode active")

            print(f"[routes_chat.py][websocket_chat] ├─ CONTEXT READY ─┤")
            print(f"[routes_chat.py][websocket_chat] Messages: {budget['message_count']}, Images: {budget['image_count']}")

            # Send acknowledgment
            await websocket.send_json({
                "type": "start",
                "message_count": active_conversation.get_message_count(),
                "context_level": context_level,
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

            # === 6. TTS INITIALIZATION ===
            use_server_tts = (config.SERVER_SIDE_TTS_ROUTING and is_node2_service_enabled('TTS_ENABLED') and
                             state and state.output_mode != OutputMode.TEXT)

            if use_server_tts:
                await initialize_tts(state, websocket)

            # === 7. EXECUTE TURN (streaming + tools + hallucination) ===
            turn_result = await execute_turn(
                all_messages=all_messages,
                tool_definitions=tool_definitions,
                websocket=websocket,
                state=state,
                active_conversation=active_conversation,
                tool_manager=tool_manager,
                interrupt_manager=interrupt_manager,
                context_level=context_level,
                user_message=user_message,
                structural_feedback=structural_feedback,
                thinking_enabled=thinking_enabled,
                voice_mode_active=voice_mode_active,
                use_server_tts=use_server_tts,
                is_video_mode=bool(is_video_mode),
                USE_UNIFIED_CONTEXT=USE_UNIFIED_CONTEXT,
                _turn_metrics=_turn_metrics,
            )

            # === 8. TTS FINALIZATION ===
            if use_server_tts and state and state.sentence_processor:
                await finalize_tts(state, is_video_mode=bool(is_video_mode))

            print(f"[routes_chat.py][websocket_chat] ├─ STREAMING COMPLETE ─┤")
            print(f"[routes_chat.py][websocket_chat] ✓ Total response length: {len(turn_result.full_response)} chars")

            # === 9. RESPONSE FINALIZATION + OBSERVABILITY ===
            if turn_result.full_response:
                await finalize_response(turn_result.full_response, active_conversation, user_message)

            await send_kv_metrics(websocket, turn_result.kv_metrics, _turn_metrics)
            await send_completion(websocket, active_conversation, budget, turn_result.full_response, context_level)
            await capture_turn_metrics(_turn_metrics, turn_result.full_response, prep.retrieval_scored, budget)

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
