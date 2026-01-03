"""
Ephemeral Chat Routes - No memory/persistence
For testing prompts and comparing model responses
Now with tool calling support!
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import httpx
import json
import sys
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, PROJECT_ROOT)

from app import config
from mcp_servers.tool_manager import ToolManager

router = APIRouter()

# Initialize tool manager (singleton)
tool_manager = ToolManager()


class ChatMessage(BaseModel):
    role: str
    content: str
    tool_calls: Optional[List[Dict[str, Any]]] = None


class ChatRequest(BaseModel):
    model: str
    messages: List[ChatMessage]
    stream: bool = True
    tools_enabled: bool = False


@router.get("/api/ephemeral/models")
async def get_available_models():
    """
    Fetch list of available models from Ollama
    Returns models from main Ollama instance
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{config.OLLAMA_BASE_URL}/api/tags")

            if response.status_code != 200:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to fetch models from Ollama: {response.status_code}"
                )

            data = response.json()
            models = data.get("models", [])

            # Extract just the names and basic info
            model_list = [
                {
                    "name": model.get("name"),
                    "size": model.get("size", 0),
                    "modified": model.get("modified_at", "")
                }
                for model in models
            ]

            print(f"[routes_ephemeral.py][get_available_models] Found {len(model_list)} models")

            return {
                "success": True,
                "models": model_list
            }

    except httpx.RequestError as e:
        print(f"[routes_ephemeral.py][get_available_models] ✗ Error connecting to Ollama: {e}")
        raise HTTPException(
            status_code=503,
            detail=f"Could not connect to Ollama: {str(e)}"
        )


@router.get("/api/ephemeral/tools")
async def get_available_tools():
    """
    Get list of available tools from ToolManager
    """
    try:
        tools = tool_manager.get_tool_definitions_for_ollama()
        print(f"[routes_ephemeral.py][get_available_tools] Found {len(tools)} tools")

        return {
            "success": True,
            "tools": tools,
            "count": len(tools)
        }
    except Exception as e:
        print(f"[routes_ephemeral.py][get_available_tools] ✗ Error: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get tools: {str(e)}"
        )


@router.post("/api/ephemeral/chat")
async def ephemeral_chat(request: ChatRequest):
    """
    Send messages to Ollama without any persistence
    Supports streaming responses and tool calling
    """
    print(f"[routes_ephemeral.py][ephemeral_chat] Model: {request.model}, Messages: {len(request.messages)}, Tools: {request.tools_enabled}")

    # Convert messages to Ollama format
    messages = []
    for msg in request.messages:
        message_dict = {"role": msg.role, "content": msg.content}
        if msg.tool_calls:
            message_dict["tool_calls"] = msg.tool_calls
        messages.append(message_dict)

    # If tools enabled, use dual-call pattern like main chat
    if request.tools_enabled:
        return StreamingResponse(
            chat_with_tools(request.model, messages),
            media_type="text/event-stream"
        )
    else:
        # Simple streaming without tools
        ollama_request = {
            "model": request.model,
            "messages": messages,
            "stream": True,
            "options": {
                "num_ctx": config.OLLAMA_CONTEXT_WINDOW
            }
        }

        return StreamingResponse(
            stream_ollama_response(ollama_request),
            media_type="text/event-stream"
        )


async def chat_with_tools(model: str, messages: List[Dict[str, Any]]):
    """
    Handle chat with tool calling support using dual-call pattern
    """
    try:
        # Get tool definitions
        tools = tool_manager.get_tool_definitions_for_ollama()
        print(f"[routes_ephemeral.py][chat_with_tools] Loaded {len(tools)} tools")

        # First call: Non-streaming to check for tool requests
        first_request = {
            "model": model,
            "messages": messages,
            "tools": tools,
            "stream": False,
            "options": {
                "num_ctx": config.OLLAMA_CONTEXT_WINDOW
            }
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{config.OLLAMA_BASE_URL}/api/chat",
                json=first_request
            )

            if response.status_code != 200:
                yield f"data: {json.dumps({'error': f'Ollama error: {response.status_code}'})}\n\n"
                return

            first_response = response.json()
            message = first_response.get("message", {})
            tool_calls = message.get("tool_calls", [])

            # If no tools requested, stream the direct response
            if not tool_calls:
                content = message.get("content", "")
                yield f"data: {json.dumps({'content': content, 'done': True})}\n\n"
                return

            # Tools were requested - send tool call info to client
            print(f"[routes_ephemeral.py][chat_with_tools] Model requested {len(tool_calls)} tool(s)")
            yield f"data: {json.dumps({'tool_calls': tool_calls})}\n\n"

            # Execute tools
            tool_messages = []
            for tool_call in tool_calls:
                function = tool_call.get("function", {})
                tool_name = function.get("name")
                arguments = function.get("arguments", {})

                print(f"[routes_ephemeral.py][chat_with_tools] Executing tool: {tool_name}")

                try:
                    # Execute via ToolManager
                    result = await tool_manager.execute_tool(tool_name, arguments)

                    # Create tool message
                    tool_message = {
                        "role": "tool",
                        "content": json.dumps(result)
                    }
                    tool_messages.append(tool_message)

                    # Send tool result to client
                    yield f"data: {json.dumps({'tool_result': {'name': tool_name, 'result': result}})}\n\n"

                except Exception as e:
                    error_result = {"success": False, "error": str(e)}
                    tool_message = {
                        "role": "tool",
                        "content": json.dumps(error_result)
                    }
                    tool_messages.append(tool_message)
                    yield f"data: {json.dumps({'tool_result': {'name': tool_name, 'result': error_result}})}\n\n"

            # Add assistant message with tool calls to conversation
            messages.append({
                "role": "assistant",
                "content": message.get("content", ""),
                "tool_calls": tool_calls
            })

            # Add tool results to conversation
            messages.extend(tool_messages)

            # Second call: Streaming for final response
            second_request = {
                "model": model,
                "messages": messages,
                "stream": True,
                "options": {
                    "num_ctx": config.OLLAMA_CONTEXT_WINDOW
                }
            }

            # Stream final response
            async with client.stream("POST", f"{config.OLLAMA_BASE_URL}/api/chat", json=second_request) as stream_response:
                if stream_response.status_code != 200:
                    yield f"data: {json.dumps({'error': f'Ollama error: {stream_response.status_code}'})}\n\n"
                    return

                async for line in stream_response.aiter_lines():
                    if line.strip():
                        try:
                            chunk = json.loads(line)
                            if "message" in chunk:
                                content = chunk["message"].get("content", "")
                                done = chunk.get("done", False)
                                yield f"data: {json.dumps({'content': content, 'done': done})}\n\n"
                                if done:
                                    break
                        except json.JSONDecodeError:
                            continue

    except Exception as e:
        print(f"[routes_ephemeral.py][chat_with_tools] ✗ Error: {e}")
        yield f"data: {json.dumps({'error': str(e)})}\n\n"


async def stream_ollama_response(ollama_request: Dict[str, Any]):
    """
    Stream response from Ollama (simple, no tools)
    Yields Server-Sent Events format
    """
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                f"{config.OLLAMA_BASE_URL}/api/chat",
                json=ollama_request
            ) as response:

                if response.status_code != 200:
                    error_msg = f"Ollama error: {response.status_code}"
                    yield f"data: {json.dumps({'error': error_msg})}\n\n"
                    return

                async for line in response.aiter_lines():
                    if line.strip():
                        try:
                            chunk = json.loads(line)

                            # Extract content from chunk
                            if "message" in chunk:
                                content = chunk["message"].get("content", "")
                                done = chunk.get("done", False)

                                # Send as SSE
                                yield f"data: {json.dumps({'content': content, 'done': done})}\n\n"

                                if done:
                                    break

                        except json.JSONDecodeError:
                            print(f"[routes_ephemeral.py][stream] Could not parse line: {line}")
                            continue

    except httpx.RequestError as e:
        print(f"[routes_ephemeral.py][stream] ✗ Error: {e}")
        yield f"data: {json.dumps({'error': str(e)})}\n\n"
