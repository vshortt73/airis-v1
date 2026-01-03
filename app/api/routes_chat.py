"""
Chat WebSocket API route with comprehensive logging and tool calling support
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import json
import os
import sys
import subprocess
import asyncio
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, PROJECT_ROOT)
from core.system_prompt import assemble_full_context
from ollama.client import chat_completion_stream, chat_completion_stream_with_tools, StreamingToolResponse
from mcp_servers.tool_manager import get_tool_manager
from database.persistence import get_db_connection
from core.vision_manager import analyze_images_for_conversation
from app import config

router = APIRouter(tags=["chat"])

active_conversation = None

# Initialize tool manager globally
tool_manager = get_tool_manager()

# Maximum iterations for iterative tool calling
# Prevents infinite loops while allowing multi-step tool chains
MAX_TOOL_ITERATIONS = 20

# Interrupt management
class InterruptManager:
    """Manages interrupt requests for stopping generation"""
    def __init__(self):
        self.interrupt_requested = False

    def request_interrupt(self):
        """Request an interrupt of current generation"""
        self.interrupt_requested = True
        print("[routes_chat.py][InterruptManager] ⚠ Interrupt requested")

    def clear(self):
        """Clear interrupt flag for new generation"""
        self.interrupt_requested = False

    def is_interrupted(self):
        """Check if interrupt was requested"""
        return self.interrupt_requested

# Global interrupt manager (one per server instance)
interrupt_manager = InterruptManager()

def get_tool_icon(tool_name: str) -> str:
    """
    Get tool icon from database
    
    Args:
        tool_name: Name of the tool
        
    Returns:
        Icon emoji string (or default if not found)
    """
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
        print(f"[routes_chat.py][get_tool_icon] Error fetching icon: {e}")
        return "🔧"

def set_active_conversation(conv):
    """Set the active conversation instance"""
    global active_conversation
    active_conversation = conv

async def ensure_tool_manager_connected():
    """Ensure tool manager is connected to MCP servers"""
    if not tool_manager._connected:
        print("[routes_chat.py] Connecting to MCP servers...")
        await tool_manager.connect()

async def refresh_memories_if_needed(message_count: int):
    """
    Refresh episodic memories every 10 messages

    Args:
        message_count: Total number of messages in conversation
    """
    # Trigger memory refresh every 10 messages
    if message_count % 10 == 0 and message_count > 0:
        print(f"[routes_chat.py][refresh_memories] 🧠 Refreshing memories (message count: {message_count})")
        try:
            # Run iris_memory_retrieval.py asynchronously
            memory_script = os.path.join(PROJECT_ROOT, "backend", "memory", "iris_memory_retrieval.py")

            # Run in background, don't wait for completion
            process = await asyncio.create_subprocess_exec(
                "python",
                memory_script,
                "--top_k", "10",
                "--insert", "true",
                "--mode", "replace",
                env={**os.environ, "IRIS_DB_PASSWORD": os.environ.get("IRIS_DB_PASSWORD", "yourpassword")},
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            # Don't await - let it run in background
            asyncio.create_task(_wait_for_memory_refresh(process))

            print(f"[routes_chat.py][refresh_memories] ✓ Memory refresh triggered in background")
        except Exception as e:
            print(f"[routes_chat.py][refresh_memories] ✗ Error triggering memory refresh: {e}")

async def _wait_for_memory_refresh(process):
    """Helper to wait for memory refresh completion and log result"""
    try:
        stdout, stderr = await process.communicate()
        if process.returncode == 0:
            print(f"[routes_chat.py][memory_refresh] ✓ Memory refresh completed successfully")
        else:
            print(f"[routes_chat.py][memory_refresh] ✗ Memory refresh failed with code {process.returncode}")
            if stderr:
                print(f"[routes_chat.py][memory_refresh] Error: {stderr.decode()[:200]}")
    except Exception as e:
        print(f"[routes_chat.py][memory_refresh] ✗ Error waiting for memory refresh: {e}")

@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """WebSocket endpoint for chat with comprehensive logging and tool calling"""
    await websocket.accept()
    
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

            user_message = data.get("message", "").strip()
            user_images = data.get("images", [])  # List of base64 images
            sender = data.get("sender", "user")  # Default to 'user' (Victor)

            if not user_message and not user_images:
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

            # Add user message with images to history
            active_conversation.add_user_message(
                user_message,
                images=user_images if user_images else None,
                sender=sender
            )

            # Check if we should refresh memories (every 10 messages)
            message_count = len(active_conversation.get_messages())
            await refresh_memories_if_needed(message_count)

            # ============================================
            # VISION PROCESSING (if images present)
            # ============================================
            # Process images through dedicated vision model (llava on GPU 1)
            # Add vision analysis as context before main chat model
            # ============================================
            if user_images and config.VISION_ENABLED:
                print(f"[routes_chat.py][websocket_chat] ├─ VISION PROCESSING: {len(user_images)} image(s) ─┤")

                # Notify client
                await websocket.send_json({
                    "type": "vision_start",
                    "image_count": len(user_images)
                })

                try:
                    # Analyze images with vision model
                    vision_analysis = await analyze_images_for_conversation(
                        images=user_images,
                        user_message=user_message if user_message else None
                    )

                    if vision_analysis:
                        print(f"[routes_chat.py][websocket_chat] │  ✓ Vision analysis complete ({len(vision_analysis)} chars)")

                        # Add vision analysis to conversation as tool message
                        active_conversation.add_tool_message(
                            content=f"[Vision Analysis]\n{vision_analysis}",
                            tool_name="vision_analysis"
                        )

                        # Notify client
                        await websocket.send_json({
                            "type": "vision_complete",
                            "success": True
                        })
                    else:
                        print(f"[routes_chat.py][websocket_chat] │  ✗ Vision analysis failed")
                        await websocket.send_json({
                            "type": "vision_complete",
                            "success": False,
                            "error": "Vision analysis returned no results"
                        })

                except Exception as e:
                    print(f"[routes_chat.py][websocket_chat] │  ✗ Vision error: {e}")
                    await websocket.send_json({
                        "type": "vision_complete",
                        "success": False,
                        "error": str(e)
                    })

            # Get tool definitions first (needed for dynamic budgeting)
            tool_definitions = tool_manager.get_tool_definitions_for_ollama()
            print(f"[routes_chat.py][websocket_chat] ├─ TOOLS AVAILABLE: {len(tool_definitions)} ─┤")

            # Assemble full context with DYNAMIC budgeting
            # Pass tool_definitions so it can calculate their token cost
            all_messages, budget = assemble_full_context(active_conversation, tool_definitions)

            print(f"[routes_chat.py][websocket_chat] ├─ CONTEXT READY ─┤")
            print(f"[routes_chat.py][websocket_chat] Messages: {budget['message_count']}, Images: {budget['image_count']}")

            # Send acknowledgment with token info
            await websocket.send_json({
                "type": "start",
                "message_count": active_conversation.get_message_count(),
                "tokens": {
                    "total": budget.get('total_tokens', 0),
                    "max": budget.get('max_tokens', 32768),
                    "percentage": budget.get('percentage_used', 0)
                }
            })
            if tool_definitions:
                print(".")
                print(f"[routes_chat.py][websocket_chat] │  First tool: {tool_definitions[0]['function']['name']}")
            else:
                print(f"[routes_chat.py][websocket_chat] │  WARNING: No tools loaded!")

            # ============================================
            # INTERLEAVED STREAMING WITH TOOL CALLING
            # ============================================
            # NEW ARCHITECTURE: Iris streams text and can call tools mid-conversation
            # 1. Stream response with tools enabled
            # 2. User sees text appearing in real-time
            # 3. If Iris decides to call a tool, execute it (shows in same bubble)
            # 4. Continue streaming with tool results
            # 5. Repeat until no more tools or max iterations
            # ============================================

            iteration = 0
            full_response = ""  # Accumulate complete response across iterations

            while iteration < MAX_TOOL_ITERATIONS:
                iteration += 1
                print(f"[routes_chat.py][websocket_chat] ├─ STREAMING ITERATION {iteration}/{MAX_TOOL_ITERATIONS} ─┤")

                # Stream response with tools enabled
                iteration_response = ""
                final_tool_response = None

                async for chunk, tool_response in chat_completion_stream_with_tools(all_messages, tools=tool_definitions):
                    # Check for interrupt
                    if interrupt_manager.is_interrupted():
                        print(f"[routes_chat.py][websocket_chat] ⚠ Interrupt detected - breaking stream")
                        await websocket.send_json({
                            "type": "interrupted",
                            "message": "Generation stopped"
                        })
                        break

                    if chunk:
                        # Stream text content to user
                        iteration_response += chunk
                        full_response += chunk
                        await websocket.send_json({
                            "type": "chunk",
                            "content": chunk
                        })
                    elif tool_response:
                        # Stream completed, check for tool calls
                        final_tool_response = tool_response

                # If interrupted, save partial response and break
                if interrupt_manager.is_interrupted():
                    print(f"[routes_chat.py][websocket_chat] ⚠ Saving partial response due to interrupt")
                    if iteration_response:
                        active_conversation.add_assistant_message(iteration_response)
                    break

                # Check if tools were called
                if not final_tool_response or not final_tool_response.has_tool_calls():
                    print(f"[routes_chat.py][websocket_chat] ├─ NO TOOL CALLS (iteration {iteration}) ─┤")
                    break

                # Tools were called - execute them
                print(f"[routes_chat.py][websocket_chat] ├─ TOOL CALLS DETECTED: {len(final_tool_response.tool_calls)} ─┤")

                # Check for interrupt before executing tools
                if interrupt_manager.is_interrupted():
                    print(f"[routes_chat.py][websocket_chat] ⚠ Interrupt detected - skipping tool execution")
                    if iteration_response:
                        active_conversation.add_assistant_message(iteration_response)
                    break

                # Send in-bubble tool marker to UI
                await websocket.send_json({
                    "type": "tool_marker_start",
                    "tool_count": len(final_tool_response.tool_calls),
                    "iteration": iteration
                })

                # Execute each tool call
                tool_results = []
                for tool_call in final_tool_response.tool_calls:
                    # Check for interrupt before each tool
                    if interrupt_manager.is_interrupted():
                        print(f"[routes_chat.py][websocket_chat] ⚠ Interrupt detected - stopping tool execution")
                        break
                    function_info = tool_call.get("function", {})
                    tool_name = function_info.get("name")
                    arguments = function_info.get("arguments", {})

                    print(f"[routes_chat.py][websocket_chat] │  Executing: {tool_name}")
                    print(f"[routes_chat.py][websocket_chat] │  Arguments: {arguments}")

                    # Get tool icon from database
                    tool_icon = get_tool_icon(tool_name)

                    # Notify client which tool is being executed (with icon) - IN BUBBLE
                    await websocket.send_json({
                        "type": "tool_executing",
                        "tool_name": tool_name,
                        "tool_icon": tool_icon,
                        "arguments": arguments,
                        "in_bubble": True  # NEW: indicates this should render in the chat bubble
                    })

                    # Execute tool
                    result = await tool_manager.execute_tool(
                        tool_name,
                        arguments,
                        require_confirmation=False  # TODO: Add confirmation UI for dangerous tools
                    )

                    tool_results.append(result)

                    if result["success"]:
                        print(f"[routes_chat.py][websocket_chat] │  ✓ Tool succeeded")

                        # Notify client of success (in bubble)
                        await websocket.send_json({
                            "type": "tool_result",
                            "tool_name": tool_name,
                            "success": True,
                            "in_bubble": True
                        })
                    else:
                        print(f"[routes_chat.py][websocket_chat] │  ✗ Tool failed: {result.get('error')}")

                        # Notify client of failure (in bubble)
                        await websocket.send_json({
                            "type": "tool_result",
                            "tool_name": tool_name,
                            "success": False,
                            "error": result.get("error"),
                            "in_bubble": True
                        })

                # Add streamed content + tool calls to conversation history
                active_conversation.add_assistant_message(
                    content=iteration_response,  # Save the text streamed before tool calls
                    tool_calls=final_tool_response.tool_calls
                )

                # Add tool results to conversation
                for tool_call, result in zip(final_tool_response.tool_calls, tool_results):
                    function_info = tool_call.get("function", {})
                    tool_name = function_info.get("name")
                    tool_call_id = tool_call.get("id")

                    print(f"[routes_chat.py][websocket_chat] │  Tool call ID: {tool_call_id}")

                    result_instructions = (
                        "[TOOL RESULT - DO NOT RESPOND TO USER YET]\n"
                        "Analyze this tool result. If you need additional information to FULLY complete "
                        "the user's request, call more tools NOW. Only respond to the user when you have "
                        "ALL necessary information.\n\n"
                        "Tool result data: "
                    )
                    active_conversation.add_tool_message(
                        content=result_instructions + json.dumps(result.get("result", {})),
                        tool_name=tool_name,
                        tool_call_id=tool_call_id
                    )

                # Send tool marker end
                await websocket.send_json({
                    "type": "tool_marker_end"
                })

                # If interrupted during tool execution, break
                if interrupt_manager.is_interrupted():
                    print(f"[routes_chat.py][websocket_chat] ⚠ Interrupt detected after tools - exiting loop")
                    break

                # Reassemble context with tool results for next iteration
                all_messages, budget = assemble_full_context(active_conversation, tool_definitions)

                print(f"[routes_chat.py][websocket_chat] ├─ CONTEXT UPDATED (with tool results) ─┤")
                print(f"[routes_chat.py][websocket_chat] Messages: {budget['message_count']}")

                # Continue loop to see if Iris wants to call more tools or respond

            # After loop: either no more tools requested or max iterations reached
            if iteration >= MAX_TOOL_ITERATIONS:
                print(f"[routes_chat.py][websocket_chat] ⚠ MAX ITERATIONS REACHED")

            print(f"[routes_chat.py][websocket_chat] ├─ STREAMING COMPLETE (iterations: {iteration}) ─┤")
            print(f"[routes_chat.py][websocket_chat] ✓ Total response length: {len(full_response)} chars")

            # If the last iteration had NO tool calls, we need to save the final response
            # (If it had tool calls, we already saved it in the loop at line 335-338)
            if not final_tool_response or not final_tool_response.has_tool_calls():
                # Parse and track fact references
                from core.system_prompt import parse_fact_references, update_fact_references

                cleaned_response, fact_ids = parse_fact_references(full_response)

                if fact_ids:
                    print(f"[routes_chat.py][websocket_chat] ├─ FACT TRACKING: {len(fact_ids)} fact(s) referenced ─┤")
                    print(f"[routes_chat.py][websocket_chat] │  Fact IDs: {fact_ids}")
                    update_fact_references(fact_ids)

                # Add complete response to history (use cleaned response without marker)
                active_conversation.add_assistant_message(cleaned_response if fact_ids else full_response)
                print(f"[routes_chat.py][websocket_chat] ✓ Final response saved to conversation history")
            
            # Send completion signal with updated token info
            # Re-assemble context to get updated token counts
            final_messages, final_budget = assemble_full_context(active_conversation, tool_definitions)

            await websocket.send_json({
                "type": "done",
                "message_count": active_conversation.get_message_count(),
                "tokens": {
                    "total": final_budget.get('total_tokens', 0),
                    "max": final_budget.get('max_tokens', 32768),
                    "percentage": final_budget.get('percentage_used', 0)
                }
            })
            
            print(f"[routes_chat.py][websocket_chat] └─ TURN COMPLETE ─┘")
            print(f"[routes_chat.py][websocket_chat] Conversation History now has {active_conversation.get_message_count()} messages")
            print(f"[routes_chat.py][websocket_chat] └────────────────────┘")
            
    except WebSocketDisconnect:
        print("[routes_chat.py][websocket_chat] Client disconnected")
    except Exception as e:
        print(f"[routes_chat.py][websocket_chat] ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        try:
            await websocket.send_json({
                "type": "error",
                "content": str(e)
            })
        except:
            pass
