"""
Ephemeral Chat Routes - No memory/persistence
For testing prompts and comparing model responses
Now with tool calling support and vision!

Backend endpoints:
- /api/ephemeral/chat - Text chat via llama.cpp (OpenAI-compatible)
- /api/ephemeral/vision - Vision chat via node2 llama.cpp vision model
- /api/ephemeral/health - Check both text and vision services
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional, Union
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

# Endpoint configuration
LLAMA_CPP_URL = config.OLLAMA_BASE_URL  # Main llama.cpp on localhost:11434
VISION_URL = config.VISION_OLLAMA_URL    # Vision llama.cpp on node2:11435

# Available inference servers for ephemeral chat
INFERENCE_SERVERS = {
    "main": {
        "name": "Main (qwen3:32b)",
        "url": config.OLLAMA_BASE_URL,
        "endpoint": "/v1/chat/completions"
    },
    "node2_small": {
        "name": "Node2 Small (mistral:7b)",
        "url": "http://node2:11437",
        "endpoint": "/v1/chat/completions"
    }
}


class ChatMessage(BaseModel):
    role: str
    content: Union[str, List[Dict[str, Any]]]  # Can be string or multipart for vision
    tool_calls: Optional[List[Dict[str, Any]]] = None
    images: Optional[List[str]] = None  # Base64 encoded images


class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    stream: bool = True
    tools_enabled: bool = False
    model: Optional[str] = None  # Optional, uses server default
    server: Optional[str] = "main"  # Server to use: "main" or "node2_small"
    temperature: Optional[float] = 0.7  # Sampling temperature (0.0 = deterministic, 2.0 = very random)


class VisionRequest(BaseModel):
    messages: List[ChatMessage]
    images: List[str]  # Base64 encoded images (without data URI prefix)
    model: Optional[str] = "llama3.2-vision:11b"


@router.get("/api/ephemeral/servers")
async def get_available_servers():
    """
    Get list of available inference servers with health status
    """
    servers = []

    async with httpx.AsyncClient(timeout=5.0) as client:
        for key, server in INFERENCE_SERVERS.items():
            server_info = {
                "id": key,
                "name": server["name"],
                "url": server["url"],
                "ok": False,
                "model": None
            }

            try:
                # Try health endpoint first (llama.cpp style)
                response = await client.get(f"{server['url']}/health")
                if response.status_code == 200:
                    data = response.json()
                    server_info["ok"] = True
                    server_info["model"] = data.get("model", server["name"])
            except Exception:
                # Try models endpoint (Ollama style)
                try:
                    response = await client.get(f"{server['url']}/v1/models")
                    if response.status_code == 200:
                        server_info["ok"] = True
                        data = response.json()
                        if data.get("data"):
                            server_info["model"] = data["data"][0].get("id", server["name"])
                except Exception as e:
                    print(f"[routes_ephemeral.py][servers] {key} not available: {e}")

            servers.append(server_info)

    return {
        "success": True,
        "servers": servers
    }


@router.get("/api/ephemeral/health")
async def check_health():
    """
    Check health of both text and vision services
    """
    results = {
        "text": {"ok": False, "url": LLAMA_CPP_URL, "model": None},
        "vision": {"ok": False, "url": VISION_URL, "model": None}
    }

    async with httpx.AsyncClient(timeout=5.0) as client:
        # Check main llama.cpp
        try:
            response = await client.get(f"{LLAMA_CPP_URL}/health")
            if response.status_code == 200:
                data = response.json()
                results["text"]["ok"] = True
                results["text"]["model"] = data.get("model", "llama.cpp")
        except Exception as e:
            print(f"[routes_ephemeral.py][health] Text server error: {e}")

        # Check vision llama.cpp on node2
        try:
            response = await client.get(f"{VISION_URL}/health")
            if response.status_code == 200:
                data = response.json()
                results["vision"]["ok"] = True
                results["vision"]["model"] = data.get("model", "vision")
        except Exception as e:
            print(f"[routes_ephemeral.py][health] Vision server error: {e}")

    return {
        "success": results["text"]["ok"],  # At minimum text should work
        **results
    }


@router.get("/api/ephemeral/models")
async def get_available_models():
    """
    Get model info from llama.cpp server
    Returns info about loaded model
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # llama.cpp uses /health to report model info
            response = await client.get(f"{LLAMA_CPP_URL}/health")

            if response.status_code != 200:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to fetch model info: {response.status_code}"
                )

            data = response.json()
            model_name = data.get("model", "llama.cpp")

            print(f"[routes_ephemeral.py][get_available_models] Model: {model_name}")

            return {
                "success": True,
                "models": [{"name": model_name, "size": 0, "modified": ""}]
            }

    except httpx.RequestError as e:
        print(f"[routes_ephemeral.py][get_available_models] ✗ Error connecting to llama.cpp: {e}")
        raise HTTPException(
            status_code=503,
            detail=f"Could not connect to llama.cpp: {str(e)}"
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
    Send messages to inference server without any persistence
    Uses OpenAI-compatible API format
    Supports streaming responses and tool calling
    Supports multiple servers via 'server' parameter
    """
    # Get server configuration
    server_key = request.server or "main"
    server_config = INFERENCE_SERVERS.get(server_key, INFERENCE_SERVERS["main"])
    server_url = f"{server_config['url']}{server_config['endpoint']}"

    print(f"[routes_ephemeral.py][ephemeral_chat] Server: {server_key} ({server_config['name']})")
    print(f"[routes_ephemeral.py][ephemeral_chat] Messages: {len(request.messages)}, Tools: {request.tools_enabled}")

    # Convert messages to OpenAI format
    messages = []
    for msg in request.messages:
        message_dict = {"role": msg.role, "content": msg.content}
        if msg.tool_calls:
            message_dict["tool_calls"] = msg.tool_calls
        messages.append(message_dict)

    # Build request for OpenAI-compatible endpoint
    llama_request = {
        "messages": messages,
        "stream": True,
        "max_tokens": 2000,
        "temperature": request.temperature if request.temperature is not None else 0.7
    }

    # Add tools if enabled (only for main server which supports tools)
    if request.tools_enabled and server_key == "main":
        tools = tool_manager.get_tool_definitions_for_ollama()
        if tools:
            llama_request["tools"] = tools

    return StreamingResponse(
        stream_llama_response(llama_request, server_url),
        media_type="text/event-stream"
    )


@router.post("/api/ephemeral/vision")
async def ephemeral_vision(request: VisionRequest):
    """
    Send messages with images to vision model on node2
    Proxies request to avoid HTTPS mixed content issues
    Uses OpenAI-compatible API format with vision
    """
    print(f"[routes_ephemeral.py][vision] Messages: {len(request.messages)}, Images: {len(request.images)}")

    # Build messages with images in OpenAI vision format
    messages = []
    for msg in request.messages:
        if msg.role == "user" and request.images:
            # Build multipart content for vision
            content = []
            if msg.content:
                content.append({"type": "text", "text": msg.content})
            for img_base64 in request.images:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{img_base64}"},
                    "max_tokens": 2000
                })
            messages.append({"role": "user", "content": content})
        else:
            messages.append({"role": msg.role, "content": msg.content})

    # Build request for vision llama.cpp
    vision_request = {
        "messages": messages,
        "stream": False,  # Non-streaming for simplicity
        "temperature": config.VISION_TEMPERATURE
    }

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{VISION_URL}/v1/chat/completions",
                json=vision_request
            )

            if response.status_code != 200:
                print(f"[routes_ephemeral.py][vision] ✗ Error: {response.status_code}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Vision API error: {response.status_code}"
                )

            data = response.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")

            print(f"[routes_ephemeral.py][vision] ✓ Response: {len(content)} chars")

            return {
                "success": True,
                "content": content
            }

    except httpx.RequestError as e:
        print(f"[routes_ephemeral.py][vision] ✗ Connection error: {e}")
        raise HTTPException(
            status_code=503,
            detail=f"Could not connect to vision server: {str(e)}"
        )


async def stream_llama_response(llama_request: Dict[str, Any], server_url: str = None):
    """
    Stream response from inference server using OpenAI-compatible API
    Yields Server-Sent Events format
    Pass-through: server sends OpenAI-compatible format

    Args:
        llama_request: The request body for the API
        server_url: Full URL to the chat completions endpoint
    """
    if server_url is None:
        server_url = f"{LLAMA_CPP_URL}/v1/chat/completions"

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                server_url,
                json=llama_request
            ) as response:

                if response.status_code != 200:
                    error_msg = f"Server error: {response.status_code}"
                    yield f"data: {json.dumps({'error': error_msg})}\n\n"
                    return

                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue

                    # Pass through OpenAI SSE format unchanged
                    # Server sends: "data: {...}" with choices[0].delta.content
                    if line.startswith("data: "):
                        yield f"{line}\n\n"

                        # Check for end of stream
                        if line == "data: [DONE]":
                            break

    except httpx.RequestError as e:
        print(f"[routes_ephemeral.py][stream] ✗ Error: {e}")
        yield f"data: {json.dumps({'error': str(e)})}\n\n"
