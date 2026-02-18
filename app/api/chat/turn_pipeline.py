"""
Core turn execution: streaming call, tool loop, hallucination intervention.

Extracted from routes_chat.py lines 1814-2639.
"""

import json
import asyncio
from dataclasses import dataclass, field
from typing import Optional

from fastapi import WebSocket

from inference.client import (
    chat_completion_stream, chat_completion_stream_with_tools,
    chat_completion_forced_tool_call,
)
from core.sentence_processor import SentenceProcessor, OutputMode
from core.system_prompt import assemble_prompt
from app import config

from .connection_manager import ConnectionState, InterruptManager
from .tool_executor import (
    detect_tool_hallucination, execute_tool_calls, process_tool_results,
    get_tool_icon, truncate_tool_content, TOOL_RESULT_INSTRUCTIONS,
    check_spoilers,
)
from .tts_handler import tts_video_processor


# Voice/video mode system instruction (appended at message tail to preserve KV cache prefix)
VOICE_MODE_INSTRUCTION = {
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
}


@dataclass
class TurnResult:
    """Result of a complete turn execution."""
    full_response: str = ""
    tool_response: Optional[object] = None
    kv_metrics: Optional[dict] = None
    tool_calls_count: int = 0
    tools_used: list = field(default_factory=list)
    tool_iterations: int = 0


def apply_no_think(messages: list) -> list:
    """
    Append /no_think to the last user message for LLM calls.
    Returns a modified copy (does not mutate original).
    """
    if not messages:
        return messages

    modified = list(messages)

    for i in range(len(modified) - 1, -1, -1):
        if modified[i].get('role') == 'user':
            msg_copy = dict(modified[i])
            content = msg_copy.get('content', '')
            if isinstance(content, str) and '/no_think' not in content:
                msg_copy['content'] = content + ' /no_think'
                modified[i] = msg_copy
            break

    return modified


# ---------------------------------------------------------------------------
# Primary streaming call
# ---------------------------------------------------------------------------

async def _stream_with_tools(
    llm_messages: list,
    tool_definitions: list,
    websocket: WebSocket,
    state: Optional[ConnectionState],
    interrupt_manager: InterruptManager,
    use_server_tts: bool,
    is_video_mode: bool,
) -> tuple:
    """
    Execute the primary streaming call with tool detection.

    Returns:
        (full_response, tool_response, kv_metrics, thinking_active)
    """
    full_response = ""
    tool_response = None
    kv_metrics = None
    thinking_active = False

    # Concurrent WebSocket listener for interrupt messages during streaming
    async def listen_for_interrupt():
        try:
            while not interrupt_manager.is_interrupted():
                try:
                    data = await asyncio.wait_for(websocket.receive_json(), timeout=0.1)
                    if data.get("type") == "interrupt":
                        print("[turn_pipeline] ⚠ Interrupt received during streaming")
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

            if final_response:
                tool_response = final_response
                if tool_response.cache_tokens or tool_response.prompt_tokens:
                    kv_metrics = {
                        "cache_n": tool_response.cache_tokens,
                        "prompt_n": tool_response.prompt_tokens,
                        "efficiency": tool_response.cache_efficiency,
                        "predicted_n": tool_response.predicted_n,
                        "predicted_ms": tool_response.predicted_ms,
                        "prompt_ms": tool_response.prompt_ms,
                        "gen_tok_per_sec": tool_response.gen_tok_per_sec,
                        "prompt_tok_per_sec": tool_response.prompt_tok_per_sec
                    }

            if interrupt_manager.is_interrupted():
                print(f"[turn_pipeline] ⚠ Interrupt detected")
                if use_server_tts and state and state.tts_task:
                    state.tts_task.cancel()
                    state.tts_queue_complete = True
                    print(f"[turn_pipeline] ⚠ TTS task cancelled")
                await websocket.send_json({
                    "type": "interrupted",
                    "message": "Generation stopped"
                })
                break

    except Exception as stream_error:
        print(f"[turn_pipeline] ⚠ Streaming failed: {stream_error}")
        import traceback
        traceback.print_exc()
        await websocket.send_json({
            "type": "error",
            "content": f"Streaming failed: {str(stream_error)}"
        })
    finally:
        if thinking_active:
            thinking_active = False
            try:
                await websocket.send_json({"type": "thinking_end"})
            except Exception:
                pass
        interrupt_listener.cancel()
        try:
            await interrupt_listener
        except asyncio.CancelledError:
            pass

    return full_response, tool_response, kv_metrics


# ---------------------------------------------------------------------------
# Follow-up streaming (iterative tool loop)
# ---------------------------------------------------------------------------

async def _followup_stream(
    llm_messages: list,
    tool_definitions: list,
    websocket: WebSocket,
    state: Optional[ConnectionState],
    interrupt_manager: InterruptManager,
    use_server_tts: bool,
    is_video_mode: bool,
    is_final_iteration: bool,
) -> tuple:
    """
    Execute a follow-up streaming call (with or without tools).

    Returns:
        (full_response, followup_tool_response, kv_metrics)
    """
    full_response = ""
    followup_tool_response = None
    kv_metrics = None
    thinking_active = False

    async def listen_for_interrupt_followup():
        try:
            while not interrupt_manager.is_interrupted():
                try:
                    data = await asyncio.wait_for(websocket.receive_json(), timeout=0.1)
                    if data.get("type") == "interrupt":
                        print("[turn_pipeline] ⚠ Interrupt received during follow-up")
                        interrupt_manager.request_interrupt()
                        break
                except asyncio.TimeoutError:
                    continue
                except Exception:
                    break
        except Exception:
            pass

    interrupt_listener = asyncio.create_task(listen_for_interrupt_followup())

    try:
        if is_final_iteration:
            async for chunk in chat_completion_stream(llm_messages):
                if chunk:
                    if isinstance(chunk, dict) and "__timings__" in chunk:
                        kv_metrics = {
                            "cache_n": chunk["cache_n"],
                            "prompt_n": chunk["prompt_n"],
                            "efficiency": chunk["efficiency"]
                        }
                        print(f"[turn_pipeline] ├─ KV CACHE METRICS (follow-up) ─┤")
                        print(f"[turn_pipeline] │  {chunk['cache_n']:,} cached + {chunk['prompt_n']:,} new = {chunk['cache_n'] + chunk['prompt_n']:,} tokens ({chunk['efficiency']:.1f}%)")
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
                        print(f"[turn_pipeline] ⚠ Interrupt detected")
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
                    print(f"[turn_pipeline] ⚠ Interrupt detected")
                    if use_server_tts and state and state.tts_task:
                        state.tts_task.cancel()
                        state.tts_queue_complete = True
                    await websocket.send_json({"type": "interrupted", "message": "Generation stopped"})
                    break

    except Exception as followup_error:
        print(f"[turn_pipeline] ⚠ Follow-up streaming failed: {followup_error}")
        import traceback
        traceback.print_exc()
    finally:
        interrupt_listener.cancel()
        try:
            await interrupt_listener
        except asyncio.CancelledError:
            pass

    return full_response, followup_tool_response, kv_metrics


# ---------------------------------------------------------------------------
# Hallucination intervention
# ---------------------------------------------------------------------------

async def _handle_hallucination_intervention(
    all_messages: list,
    tool_definitions: list,
    websocket: WebSocket,
    state: Optional[ConnectionState],
    active_conversation,
    tool_manager,
    interrupt_manager: InterruptManager,
    thinking_enabled: bool,
    voice_mode_active: bool,
    use_server_tts: bool,
    is_video_mode: bool,
    context_level: str,
    user_message: str,
    USE_UNIFIED_CONTEXT: bool,
    structural_feedback,
) -> str:
    """
    Handle tool hallucination intervention: forced tool call + retry.

    Returns:
        The new full_response after intervention (may be empty if forced call fails).
    """
    # Cancel any TTS processing the hallucinated response
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

    # Rebuild context (don't save the hallucinated response)
    retry_messages, budget = assemble_prompt(
        active_conversation, tool_definitions,
        context_level=context_level,
        user_message=user_message,
        use_unified=USE_UNIFIED_CONTEXT,
        structural_feedback=structural_feedback
    )
    retry_llm_messages = apply_no_think(list(retry_messages)) if not thinking_enabled else list(retry_messages)

    # PHASE 1: Forced tool call (non-streaming, tool_choice=required)
    forced_result = await chat_completion_forced_tool_call(
        retry_llm_messages, tool_definitions
    )

    if not forced_result or not forced_result.get("tool_calls"):
        print(f"[turn_pipeline] ⚠ Forced tool call returned no results, keeping original response")
        return ""

    forced_tool_calls = forced_result["tool_calls"]
    forced_content = forced_result.get("content", "") or ""
    print(f"[turn_pipeline] ├─ FORCED RETRY: {len(forced_tool_calls)} TOOL CALL(S) ─┤")

    # Execute forced tool calls
    exec_result = await execute_tool_calls(
        forced_tool_calls, tool_manager, websocket,
        active_conversation, interrupt_manager,
    )

    # Save assistant message with tool calls
    active_conversation.add_assistant_message(content=forced_content, tool_calls=forced_tool_calls)
    active_conversation.append_to_snapshot({
        "role": "assistant", "content": forced_content, "tool_calls": forced_tool_calls
    })

    # Save tool results
    await process_tool_results(
        forced_tool_calls, exec_result.results,
        active_conversation, websocket, cumulative_tokens=0
    )

    # PHASE 2: Stream the follow-up presentation of tool results
    followup_msgs, budget = assemble_prompt(
        active_conversation, tool_definitions,
        context_level=context_level,
        user_message=user_message,
        use_unified=USE_UNIFIED_CONTEXT,
        structural_feedback=structural_feedback
    )
    followup_llm = apply_no_think(list(followup_msgs)) if not thinking_enabled else list(followup_msgs)

    if voice_mode_active:
        followup_llm.append(VOICE_MODE_INSTRUCTION)

    full_response = ""

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
        print(f"[turn_pipeline] ⚠ Retry follow-up failed: {followup_err}")

    print(f"[turn_pipeline] ├─ HALLUCINATION INTERVENTION COMPLETE ─┤")
    return full_response


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def execute_turn(
    all_messages: list,
    tool_definitions: list,
    websocket: WebSocket,
    state: Optional[ConnectionState],
    active_conversation,
    tool_manager,
    interrupt_manager: InterruptManager,
    context_level: str,
    user_message: str,
    structural_feedback,
    thinking_enabled: bool,
    voice_mode_active: bool,
    use_server_tts: bool,
    is_video_mode: bool,
    USE_UNIFIED_CONTEXT: bool,
    _turn_metrics: dict,
) -> TurnResult:
    """
    Execute a complete turn: primary streaming, tool execution, iterative tool loop,
    and hallucination intervention.

    Args:
        all_messages: Assembled context messages
        tool_definitions: Available tool definitions
        websocket: WebSocket connection
        state: Connection state (for TTS routing)
        active_conversation: Active conversation instance
        tool_manager: MCP tool manager
        interrupt_manager: Interrupt manager
        context_level: Context tier string
        user_message: Original user message
        structural_feedback: Structural repetition avoidance feedback
        thinking_enabled: Whether thinking mode is enabled
        voice_mode_active: Whether voice/video mode is active
        use_server_tts: Whether server-side TTS is active
        is_video_mode: Whether output mode is VIDEO
        USE_UNIFIED_CONTEXT: Whether unified context is enabled
        _turn_metrics: Mutable metrics dict

    Returns:
        TurnResult with full response and metrics
    """
    result = TurnResult()
    websocket._hallucination_retried = False  # Reset per-turn

    print(f"[turn_pipeline] ├─ STREAMING WITH TOOLS ─┤")

    # Prepare LLM messages
    llm_messages = apply_no_think(all_messages) if not thinking_enabled else list(all_messages)
    if not thinking_enabled:
        print(f"[turn_pipeline] 🧠 Thinking disabled - /no_think applied")

    if voice_mode_active:
        llm_messages.append(VOICE_MODE_INSTRUCTION)

    # === Primary streaming call ===
    full_response, tool_response, kv_metrics = await _stream_with_tools(
        llm_messages, tool_definitions, websocket, state,
        interrupt_manager, use_server_tts, is_video_mode,
    )

    result.full_response = full_response
    result.tool_response = tool_response
    result.kv_metrics = kv_metrics

    # === Initial tool execution ===
    if tool_response and tool_response.has_tool_calls():
        print(f"[turn_pipeline] ├─ EXECUTING {len(tool_response.tool_calls)} TOOL(S) ─┤")

        exec_result = await execute_tool_calls(
            tool_response.tool_calls, tool_manager, websocket,
            active_conversation, interrupt_manager,
        )

        # Observability
        _turn_metrics["tool_calls_count"] = len(tool_response.tool_calls)
        _turn_metrics["tools_used"] = list({
            tc.get("function", {}).get("name", "unknown") for tc in tool_response.tool_calls
        })

        # Save assistant message with tool calls
        active_conversation.add_assistant_message(content=full_response, tool_calls=tool_response.tool_calls)
        snapshot_assistant_msg = {"role": "assistant", "content": full_response}
        if tool_response.tool_calls:
            snapshot_assistant_msg["tool_calls"] = tool_response.tool_calls
        active_conversation.append_to_snapshot(snapshot_assistant_msg)

        # Process tool results (save to conversation + truncate)
        await process_tool_results(
            tool_response.tool_calls, exec_result.results,
            active_conversation, websocket, cumulative_tokens=0
        )

        # Reassemble context with tool results
        all_messages, budget = assemble_prompt(
            active_conversation, tool_definitions,
            context_level=context_level,
            user_message=user_message,
            use_unified=USE_UNIFIED_CONTEXT,
            structural_feedback=structural_feedback
        )
        print(f"[turn_pipeline] ├─ CONTEXT UPDATED (with tool results) ─┤")

        # === Iterative tool loop ===
        MAX_TOOL_ITERATIONS = 5
        _prev_tool_sig = None

        for tool_iteration in range(MAX_TOOL_ITERATIONS):
            is_final_iteration = (tool_iteration == MAX_TOOL_ITERATIONS - 1)
            iteration_label = f"iteration {tool_iteration + 1}/{MAX_TOOL_ITERATIONS}"

            print(f"[turn_pipeline] ├─ FOLLOW-UP STREAMING ({iteration_label}) ─┤")
            llm_messages = apply_no_think(all_messages) if not thinking_enabled else list(all_messages)

            if voice_mode_active:
                llm_messages.append(VOICE_MODE_INSTRUCTION)

            # Reset TTS for follow-up
            if use_server_tts and state:
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
                state.tts_task = asyncio.create_task(tts_video_processor(websocket, state))

            # Follow-up streaming call
            iter_response, followup_tool_response, iter_kv = await _followup_stream(
                llm_messages, tool_definitions, websocket, state,
                interrupt_manager, use_server_tts, is_video_mode, is_final_iteration,
            )
            full_response = iter_response
            if iter_kv:
                kv_metrics = iter_kv

            # Check if follow-up triggered more tool calls
            if followup_tool_response and followup_tool_response.has_tool_calls() and not interrupt_manager.is_interrupted():
                # Circuit breaker: detect repeated identical tool calls (stuck loop)
                _cur_tool_sig = json.dumps(
                    [(tc.get("function", {}).get("name"), tc.get("function", {}).get("arguments"))
                     for tc in followup_tool_response.tool_calls],
                    sort_keys=True
                )
                if _cur_tool_sig == _prev_tool_sig:
                    print(f"[turn_pipeline] ⚠ STUCK LOOP DETECTED — same tool call repeated")
                    print(f"[turn_pipeline] ⚠ Making final text-only call so Iris can respond")
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
                        print(f"[turn_pipeline] ⚠ Stuck loop recovery call failed: {recovery_err}")
                    break
                _prev_tool_sig = _cur_tool_sig

                print(f"[turn_pipeline] ├─ ITERATIVE TOOL CALL ({iteration_label}) ─┤")
                print(f"[turn_pipeline] ├─ EXECUTING {len(followup_tool_response.tool_calls)} TOOL(S) ─┤")

                iter_exec_result = await execute_tool_calls(
                    followup_tool_response.tool_calls, tool_manager, websocket,
                    active_conversation, interrupt_manager,
                )

                # Save assistant + tool results
                active_conversation.add_assistant_message(content=full_response, tool_calls=followup_tool_response.tool_calls)
                active_conversation.append_to_snapshot({
                    "role": "assistant", "content": full_response,
                    "tool_calls": followup_tool_response.tool_calls
                })

                await process_tool_results(
                    followup_tool_response.tool_calls, iter_exec_result.results,
                    active_conversation, websocket, cumulative_tokens=0
                )

                # Reassemble context for next iteration
                all_messages, budget = assemble_prompt(
                    active_conversation, tool_definitions,
                    context_level=context_level,
                    user_message=user_message,
                    use_unified=USE_UNIFIED_CONTEXT,
                    structural_feedback=structural_feedback
                )
                print(f"[turn_pipeline] ├─ CONTEXT UPDATED (iteration {tool_iteration + 2}) ─┤")
                continue  # Loop back for another follow-up
            else:
                # No more tool calls - done
                _turn_metrics["tool_iterations"] = tool_iteration + 1
                break

    # === Hallucination intervention ===
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
        if detect_tool_hallucination(full_response, _tool_names_for_check):
            print(f"[turn_pipeline] ╔═══════════════════════════════════════╗")
            print(f"[turn_pipeline] ║  TOOL HALLUCINATION INTERVENTION      ║")
            print(f"[turn_pipeline] ║  Discarding response, retrying...     ║")
            print(f"[turn_pipeline] ╚═══════════════════════════════════════╝")
            print(f"[turn_pipeline] │  Hallucinated response ({len(full_response)} chars): {full_response[:200]}...")
            websocket._hallucination_retried = True

            await websocket.send_json({
                "type": "hallucination_retry",
                "reason": "Model narrated tool usage instead of calling tools. Retrying."
            })

            new_response = await _handle_hallucination_intervention(
                all_messages, tool_definitions, websocket, state,
                active_conversation, tool_manager, interrupt_manager,
                thinking_enabled, voice_mode_active, use_server_tts,
                is_video_mode, context_level, user_message,
                USE_UNIFIED_CONTEXT, structural_feedback,
            )
            if new_response:
                full_response = new_response

    result.full_response = full_response
    result.kv_metrics = kv_metrics
    return result
