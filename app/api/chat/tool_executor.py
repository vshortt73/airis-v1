"""
Tool execution pipeline: truncation, hallucination detection, execution, result processing.

Extracted from routes_chat.py lines 45-176 (truncation + hallucination detection),
and the inline tool execution blocks from websocket_chat.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Optional, List

from fastapi import WebSocket

from core.token_counter import TokenCounter
from database.persistence import get_db_connection
from app import config


# ---------------------------------------------------------------------------
# Tool result truncation with cumulative budget tracking
# ---------------------------------------------------------------------------
_PER_TOOL_RESULT_CAP = None  # Loaded from config on first use
_CUMULATIVE_TOOL_CAP = None  # 50% of context window, computed on first use


def _get_tool_caps():
    """Lazy-load tool result budget caps from config."""
    global _PER_TOOL_RESULT_CAP, _CUMULATIVE_TOOL_CAP
    if _PER_TOOL_RESULT_CAP is None:
        _PER_TOOL_RESULT_CAP = getattr(config, 'TOOL_RESULTS_BUDGET', 15000)
        ctx = getattr(config, 'OLLAMA_CONTEXT_WINDOW', 40960)
        _CUMULATIVE_TOOL_CAP = int(ctx * 0.50)
    return _PER_TOOL_RESULT_CAP, _CUMULATIVE_TOOL_CAP


def truncate_tool_content(tool_content: str, cumulative_tokens_used: int) -> tuple:
    """
    Truncate a single tool result, respecting both per-result and cumulative caps.

    Args:
        tool_content: The tool result string to (maybe) truncate
        cumulative_tokens_used: Total tool result tokens already consumed this turn

    Returns:
        (truncated_content, token_count) — the content and how many tokens it uses
    """
    per_cap, cumul_cap = _get_tool_caps()

    token_count = TokenCounter.count_tokens(tool_content)

    # How many tokens remain in the cumulative budget?
    remaining = max(0, cumul_cap - cumulative_tokens_used)

    # Effective cap is the stricter of per-result and remaining cumulative
    effective_cap = min(per_cap, remaining)

    if token_count <= effective_cap:
        return tool_content, token_count

    # Need to truncate
    target = max(500, effective_cap - 50)  # Leave room for notice, min 500 tokens
    encoder = TokenCounter.get_encoder()
    encoded = encoder.encode(tool_content)
    truncated = encoder.decode(encoded[:target])
    truncated += (
        f"\n\n[TRUNCATED — Result exceeded token budget "
        f"({token_count:,} tokens, cap {effective_cap:,}). "
        f"Data above is incomplete. Do not fabricate the missing portion.]"
    )
    final_count = TokenCounter.count_tokens(truncated)
    print(f"[tool_executor] ⚠ Tool result truncated: {token_count:,} → {final_count:,} tokens "
          f"(per-result cap: {per_cap:,}, cumulative remaining: {remaining:,})")
    return truncated, final_count


# ---------------------------------------------------------------------------
# Tool hallucination detection
# ---------------------------------------------------------------------------

def detect_tool_hallucination(response: str, tool_names: list) -> bool:
    """Detect when model narrates tool usage without actually calling tools.

    Returns True if the response contains strong signals of fabricated tool use:
    the model describes using specific tools by name in present/future tense
    without making actual API calls.

    The threshold is intentionally sensitive — a false positive only costs one
    retry, while a false negative saves a hallucinated response to context and
    worsens the self-reinforcing pattern.
    """
    if not response or len(response) < 40:
        return False

    response_lower = response.lower()

    # Narration phrases that precede or surround tool names
    narration_phrases = [
        "i'll use", "let me use", "i'm using", "i will use", "i'm going to use",
        "i'll call", "let me call", "i'm calling", "i will call",
        "let me search", "i'll search", "i'm searching", "i will search",
        "let me look up", "i'll look up", "i'm looking up",
        "let me fetch", "i'll fetch", "i'm fetching",
        "let me check", "i'll check", "i'm checking",
        "let me retrieve", "i'll retrieve", "i'm retrieving",
        "using the", "calling the", "invoking the",
    ]

    indicators = 0

    # Check 1: Known tool names mentioned in narration context
    tool_set = {name.lower() for name in tool_names if name}
    for tool_name in tool_set:
        if tool_name not in response_lower:
            continue

        idx = 0
        while True:
            idx = response_lower.find(tool_name, idx)
            if idx == -1:
                break

            # Get surrounding context
            before = response_lower[max(0, idx - 80):idx]
            after = response_lower[idx:min(len(response_lower), idx + len(tool_name) + 60)]

            if any(phrase in before or phrase in after for phrase in narration_phrases):
                indicators += 1

            idx += len(tool_name) + 1

    # Check 2: Generic "tool" narration patterns (no specific name needed)
    generic_patterns = [
        r"(?:i'll|let me|i'm going to|i will)\s+(?:use|call|invoke|run)\s+(?:the\s+)?\w+\s+tool",
        r"(?:i'll|let me|i'm going to|i will)\s+(?:search|look up|fetch|retrieve)\s+(?:that|this|the|some|for)",
    ]
    for pattern in generic_patterns:
        if re.search(pattern, response_lower):
            indicators += 1

    if indicators >= 1:
        print(f"[tool_executor] ⚠ TOOL HALLUCINATION DETECTED ({indicators} indicator(s))")
        return True

    return False


def get_tool_icon(tool_name: str) -> str:
    """Get tool icon from database."""
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
        print(f"[tool_executor] Error fetching icon: {e}")
        return "🔧"


# ---------------------------------------------------------------------------
# Spoiler detection: certain tool+action combos invalidate the prompt snapshot
# ---------------------------------------------------------------------------

def check_spoilers(tool_name: str, function_info: dict, result: dict, active_conversation):
    """Check if a successful tool call should invalidate the prompt snapshot."""
    if not result.get("success"):
        return
    try:
        args = function_info.get("arguments", {})
        if isinstance(args, str):
            args = json.loads(args)
        action = args.get("action", "")
        if tool_name == "trait" and action == "modify":
            active_conversation.invalidate_snapshot("trait_modify")
        elif tool_name == "memory" and action in ("insert", "archive"):
            active_conversation.invalidate_snapshot(f"memory_{action}")
        elif tool_name == "seed" and action in ("plant", "tend", "reflect", "accept", "dismiss", "clear_suggestions"):
            active_conversation.invalidate_snapshot(f"seed_{action}")
        elif tool_name == "calendar" and action in ("add", "update", "delete"):
            active_conversation.invalidate_snapshot(f"calendar_{action}")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Unified tool execution
# ---------------------------------------------------------------------------

TOOL_RESULT_INSTRUCTIONS = (
    "[TOOL RESULT]\n"
    "Present this information to the user in a natural, conversational way. "
    "Do not add false data or attempt to fill in gaps. "
    "Present only the data supplied below.\n\n"
    "Tool result data: "
)


@dataclass
class ToolExecutionResult:
    """Result of executing a batch of tool calls."""
    results: list = field(default_factory=list)
    cumulative_tokens: int = 0
    tools_used: list = field(default_factory=list)


async def execute_tool_calls(
    tool_calls: list,
    tool_manager,
    websocket: WebSocket,
    active_conversation,
    interrupt_manager,
) -> ToolExecutionResult:
    """
    Execute a batch of tool calls, handling UI notifications, smart tool miss detection,
    and snapshot invalidation on failure.

    Args:
        tool_calls: List of tool call dicts from the LLM response
        tool_manager: The MCP tool manager instance
        websocket: WebSocket connection for UI notifications
        active_conversation: Active conversation instance
        interrupt_manager: Interrupt manager for checking cancellation

    Returns:
        ToolExecutionResult with results, cumulative token count, and tools used
    """
    exec_result = ToolExecutionResult()

    # Send tool marker
    await websocket.send_json({
        "type": "tool_marker_start",
        "tool_count": len(tool_calls)
    })

    for tool_call in tool_calls:
        if interrupt_manager.is_interrupted():
            print(f"[tool_executor] ⚠ Interrupt detected - stopping tool execution")
            break

        function_info = tool_call.get("function", {})
        tool_name = function_info.get("name")
        arguments = function_info.get("arguments", {})
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {}

        print(f"[tool_executor] │  Executing: {tool_name}")
        print(f"[tool_executor] │  Arguments: {arguments}")

        tool_icon = get_tool_icon(tool_name)

        await websocket.send_json({
            "type": "tool_executing",
            "tool_name": tool_name,
            "tool_icon": tool_icon,
            "arguments": arguments,
            "in_bubble": True
        })

        result = await tool_manager.execute_tool(tool_name, arguments, require_confirmation=False)
        exec_result.results.append(result)
        exec_result.tools_used.append(tool_name)

        # Build result notification
        tool_result_msg = {
            "type": "tool_result",
            "tool_name": tool_name,
            "success": result["success"],
            "error": result.get("error"),
            "in_bubble": True
        }
        # Pass meeting_id to UI so browser recorder can start/stop
        if tool_name in ("meeting", "meeting_start") and result.get("success"):
            tool_data = result.get("result", {})
            if tool_data.get("meeting_id"):
                tool_result_msg["meeting_id"] = tool_data["meeting_id"]
            tool_result_msg["action"] = arguments.get("action", "start") if tool_name == "meeting" else "start"
        await websocket.send_json(tool_result_msg)

        if result["success"]:
            print(f"[tool_executor] │  ✓ Tool succeeded")
        else:
            print(f"[tool_executor] │  ✗ Tool failed: {result.get('error')}")
            active_conversation.invalidate_snapshot(
                reason=f"Tool '{tool_name}' failed: {result.get('error', 'unknown')[:80]}"
            )

        # Smart tool selection: detect tool_miss
        if getattr(config, 'SMART_TOOL_SELECTION', False) and active_conversation.snapshot_tools is not None:
            if tool_name not in active_conversation.snapshot_tools:
                from mcp_servers.tool_manager import ToolManager
                group = ToolManager.get_group_for_tool(tool_name)
                if group:
                    active_conversation.snapshot_force_groups.add(group)
                    active_conversation.invalidate_snapshot(f"tool_miss: {tool_name} (adding {group} group)")
                    print(f"[tool_executor] │  ⚠ Tool miss: {tool_name} not in snapshot, forcing {group} group")

    await websocket.send_json({"type": "tool_marker_end"})
    return exec_result


async def process_tool_results(
    tool_calls: list,
    results: list,
    active_conversation,
    websocket: WebSocket,
    cumulative_tokens: int = 0,
) -> int:
    """
    Save tool results to conversation + snapshot, handling images and truncation.

    Args:
        tool_calls: List of tool call dicts
        results: Corresponding list of execution results
        active_conversation: Active conversation instance
        websocket: WebSocket for sending tool images
        cumulative_tokens: Starting cumulative token count

    Returns:
        Updated cumulative token count after processing all results
    """
    for tool_call, result in zip(tool_calls, results):
        function_info = tool_call.get("function", {})
        tool_name = function_info.get("name")
        tool_call_id = tool_call.get("id")
        tool_result_data = result.get("result", {})

        # Check for generated images in tool result
        tool_images = []
        image_base64 = tool_result_data.get("image_base64")
        if image_base64:
            tool_images.append(image_base64)
            print(f"[tool_executor] │  📸 Tool returned an image")

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

        tool_content = TOOL_RESULT_INSTRUCTIONS + json.dumps(tool_result_data)

        # Enforce per-result AND cumulative tool token budget
        tool_content, tok_count = truncate_tool_content(tool_content, cumulative_tokens)
        cumulative_tokens += tok_count

        active_conversation.add_tool_message(
            content=tool_content,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            images=tool_images if tool_images else None
        )

        active_conversation.append_to_snapshot({
            "role": "tool",
            "content": tool_content,
            "tool_name": tool_name,
            "tool_call_id": tool_call_id
        })

        # Spoiler detection
        check_spoilers(tool_name, function_info, result, active_conversation)

    return cumulative_tokens
