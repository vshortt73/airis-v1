"""
Chat WebSocket API route with comprehensive logging and tool calling support
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import json
import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, PROJECT_ROOT)
from core.system_prompt import assemble_full_context
from ollama.client import chat_completion_stream, chat_completion_with_tools
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

@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """WebSocket endpoint for chat with comprehensive logging and tool calling"""
    await websocket.accept()
    
    # Ensure tool manager is connected
    await ensure_tool_manager_connected()
    
    print(f"[routes_chat.py][websocket_chat] WebSocket connected, Conversation History now has {active_conversation.get_message_count()} messages")
    
    try:
        while True:
            # Receive message from client (may include images)
            data = await websocket.receive_json()
            user_message = data.get("message", "").strip()
            user_images = data.get("images", [])  # List of base64 images
            
            if not user_message and not user_images:
                await websocket.send_json({
                    "type": "error",
                    "content": "Empty message"
                })
                continue
            
            print(f"[routes_chat.py][websocket_chat] ┌──────── NEW TURN ────────┐")
            print(f"[routes_chat.py][websocket_chat] User message: '{user_message[:50]}...'")
            if user_images:
                print(f"[routes_chat.py][websocket_chat] User attached {len(user_images)} image(s)")
            
            # Add user message with images to history (triggers save to DB)
            active_conversation.add_user_message(
                user_message,
                images=user_images if user_images else None
            )

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

            # Assemble full context with image loading
            all_messages, budget = assemble_full_context(active_conversation)
            
            print(f"[routes_chat.py][websocket_chat] ├─ CONTEXT READY ─┤")
            print(f"[routes_chat.py][websocket_chat] Messages: {budget['message_count']}, Images: {budget['image_count']}")
            
            # Send acknowledgment
            await websocket.send_json({
                "type": "start",
                "message_count": active_conversation.get_message_count()
            })
            
            # Get tool definitions
            tool_definitions = tool_manager.get_tool_definitions_for_ollama()
            print(f"[routes_chat.py][websocket_chat] ├─ TOOLS AVAILABLE: {len(tool_definitions)} ─┤")
            if tool_definitions:
                print(".")
                print(f"[routes_chat.py][websocket_chat] │  First tool: {tool_definitions[0]['function']['name']}")
            else:
                print(f"[routes_chat.py][websocket_chat] │  WARNING: No tools loaded!")

            # ============================================
            # ITERATIVE TOOL CALLING LOOP
            # ============================================
            # This loop allows Iris to chain multiple tool calls:
            # 1. Call Ollama with tools
            # 2. Execute requested tools
            # 3. Add results to context
            # 4. Call Ollama again to see if more tools needed
            # 5. Repeat until no more tools requested or max iterations
            # ============================================

            iteration = 0
            tools_were_used = False

            while iteration < MAX_TOOL_ITERATIONS:
                iteration += 1
                print(f"[routes_chat.py][websocket_chat] ├─ TOOL ITERATION {iteration}/{MAX_TOOL_ITERATIONS} ─┤")

                # Call Ollama with tools (non-streaming)
                print(f"[routes_chat.py][websocket_chat] ├─ CALLING OLLAMA (with tools) ─┤")
                response = await chat_completion_with_tools(all_messages, tools=tool_definitions)

                # Check if Ollama wants to use tools
                if not response.has_tool_calls():
                    print(f"[routes_chat.py][websocket_chat] ├─ NO TOOL CALLS (iteration {iteration}) ─┤")
                    break

                # Tools were requested
                tools_were_used = True
                print(f"[routes_chat.py][websocket_chat] ├─ TOOL CALLS DETECTED: {len(response.tool_calls)} ─┤")

                # Notify client that tools are being executed
                await websocket.send_json({
                    "type": "tool_start",
                    "tool_count": len(response.tool_calls),
                    "iteration": iteration
                })

                # Execute each tool call
                tool_results = []
                for tool_call in response.tool_calls:
                    function_info = tool_call.get("function", {})
                    tool_name = function_info.get("name")
                    arguments = function_info.get("arguments", {})

                    print(f"[routes_chat.py][websocket_chat] │  Executing: {tool_name}")
                    print(f"[routes_chat.py][websocket_chat] │  Arguments: {arguments}")

                    # Get tool icon from database
                    tool_icon = get_tool_icon(tool_name)

                    # Notify client which tool is being executed (with icon)
                    await websocket.send_json({
                        "type": "tool_executing",
                        "tool_name": tool_name,
                        "tool_icon": tool_icon,
                        "arguments": arguments
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

                        # Notify client of success
                        await websocket.send_json({
                            "type": "tool_result",
                            "tool_name": tool_name,
                            "success": True
                        })
                    else:
                        print(f"[routes_chat.py][websocket_chat] │  ✗ Tool failed: {result.get('error')}")

                        # Notify client of failure
                        await websocket.send_json({
                            "type": "tool_result",
                            "tool_name": tool_name,
                            "success": False,
                            "error": result.get("error")
                        })

                # Add tool calls and results to conversation history
                # Format: assistant message with tool_calls, then tool messages with results
                active_conversation.add_assistant_message(
                    content="",  # Empty content when using tools
                    tool_calls=response.tool_calls  # ← Save just the tool_calls array
                )

                for tool_call, result in zip(response.tool_calls, tool_results):
                    function_info = tool_call.get("function", {})
                    tool_name = function_info.get("name")
                    tool_call_id = tool_call.get("id")  # Extract the call ID from Ollama response

                    print(f"[routes_chat.py][websocket_chat] │  Tool call ID: {tool_call_id}")

                    result_instructions = "reply to the user with this tool data in a conversational manner. provide all data to the user: "
                    # Add tool result message
                    active_conversation.add_tool_message(
                        content=result_instructions + "" + json.dumps(result.get("result", {})),
                        tool_name=tool_name,
                        tool_call_id=tool_call_id  # Pass the call ID to link with the tool call
                    )
                print(f"[routes_chat.py][websocket_chat] tool data for Iris: {json.dumps(result.get('result', {})),}")

                # Reassemble context with tool results for next iteration
                all_messages, budget = assemble_full_context(active_conversation)

                print(f"[routes_chat.py][websocket_chat] ├─ CONTEXT UPDATED (with tool results) ─┤")
                print(f"[routes_chat.py][websocket_chat] Messages: {budget['message_count']}")

                # Continue to next iteration to see if more tools needed

            # After loop: either no more tools requested or max iterations reached
            if iteration >= MAX_TOOL_ITERATIONS and response.has_tool_calls():
                print(f"[routes_chat.py][websocket_chat] ⚠ MAX ITERATIONS REACHED - proceeding to response")

            print(f"[routes_chat.py][websocket_chat] ├─ TOOL LOOP COMPLETE (iterations: {iteration}) ─┤")
            
            # Second call to Ollama to generate final response (streaming)

            print(f"[routes_chat.py][websocket_chat] ├─ STREAMING FINAL RESPONSE ─┤")
            
            full_response = ""
            async for chunk in chat_completion_stream(all_messages):
                full_response += chunk
                await websocket.send_json({
                    "type": "chunk",
                    "content": chunk
                })
            
            print(f"[routes_chat.py][websocket_chat] ✓ Streaming complete ({len(full_response)} chars)")
            
            # Add complete response to history (triggers save to DB)
            active_conversation.add_assistant_message(full_response)
            
            # Send completion signal
            await websocket.send_json({
                "type": "done",
                "message_count": active_conversation.get_message_count()
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
