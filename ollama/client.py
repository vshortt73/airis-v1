"""
Ollama API client for Iris v3
Clean streaming interface with explicit context window and tool calling support
"""

import httpx
from typing import Dict, List, AsyncIterator, Optional, Any
import json
import sys
import os; PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..' if '__file__' in dir() else '.')); sys.path.insert(0, PROJECT_ROOT)
from app import config


class ToolCallResponse:
    """Response object that may contain tool calls"""
    
    def __init__(self, response_data: Dict[str, Any]):
        self.raw_response = response_data
        self.message = response_data.get("message", {})
        self.tool_calls = self.message.get("tool_calls", [])
    
    def has_tool_calls(self) -> bool:
        """Check if response contains tool calls"""
        return len(self.tool_calls) > 0
    
    def get_content(self) -> str:
        """Get text content from response"""
        return self.message.get("content", "")


async def chat_completion_with_tools(
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None
) -> ToolCallResponse:
    """
    Send chat completion request to Ollama with tool definitions (non-streaming)
    
    This is used for the FIRST call when tools are available - Ollama will
    decide whether to call a tool or respond directly.
    
    Args:
        messages: List of message dicts with "role" and "content" keys
        tools: Optional list of tool definitions in Ollama format:
               [{
                   "type": "function",
                   "function": {
                       "name": "weather_get",
                       "description": "...",
                       "parameters": {...}
                   }
               }]
    
    Returns:
        ToolCallResponse object containing either tool calls or text response
    """
    
    url = f"{config.OLLAMA_BASE_URL}/api/chat"
    
    payload = {
        "model": config.OLLAMA_MODEL,
        "messages": messages,
        "stream": False,  # Non-streaming for tool calls
        "options": {
            "num_ctx": config.OLLAMA_CONTEXT_WINDOW,
            "temperature": 0.7,
        }
    }
    

    # Add tools if provided
    if tools:
        payload["tools"] = tools
        print(f"[client.py][chat_completion_with_tools] Sending {len(tools)} tools to Ollama")
    
    print(f"[client.py][chat_completion_with_tools] querying Ollama at {config.OLLAMA_BASE_URL}/api/chat")
    #print(f"[client.py][chat_completion_with_tools] === PAYLOAD DEBUG ===")
    print(f"[client.py][chat_completion_with_tools] Model: {payload.get('model')}")
    #print(f"[client.py][chat_completion_with_tools] Messages: {len(payload.get('messages', []))}")
    #print(f"[client.py][chat_completion_with_tools] Tools in payload: {'tools' in payload}")
    if 'tools' in payload:

       # print(f"[client.py][chat_completion_with_tools] First tool: {payload['tools'][0]['function']['name'] if payload['tools'] else 'none'}")
        import json
       # print(f"[client.py][chat_completion_with_tools] First tool JSON:")
        print(json.dumps(payload['tools'][0], indent=2))
   # print(f"[client.py][chat_completion_with_tools] Full payload keys: {list(payload.keys())}")
   # print(f"[client.py][chat_completion_with_tools] ===================")

    print(f"[client.py][chat_completion_with_tools] Tool count in payload: {len(payload['tools'])}")
   #print("================================================================")
   #print(payload)
   #print("================================================================")


    async with httpx.AsyncClient(timeout=600.0) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        
        response_data = response.json()
        tool_response = ToolCallResponse(response_data)
        
        if tool_response.has_tool_calls():
            print(f"[client.py][chat_completion_with_tools] Ollama returned {len(tool_response.tool_calls)} tool call(s)")
            for tool_call in tool_response.tool_calls:
                print(f"  - {tool_call.get('function', {}).get('name')}")
        else:
            print(f"[client.py][chat_completion_with_tools] Ollama responded directly (no tool calls)")
        
        return tool_response


async def chat_completion_stream(
    messages: List[Dict[str, str]]
) -> AsyncIterator[str]:
    """
    Send chat completion request to Ollama and stream response
    
    This is used for:
    1. Regular chat without tools
    2. SECOND call after tool results are added to conversation
    
    Args:
        messages: List of message dicts with "role" and "content" keys
        
    Yields:
        Chunks of response text as they arrive
    """
    
    url = f"{config.OLLAMA_BASE_URL}/api/chat"
    
    payload = {
        "model": config.OLLAMA_MODEL,
        "messages": messages,
        "stream": True,
        "options": {
            "num_ctx": config.OLLAMA_CONTEXT_WINDOW,  # CRITICAL: Explicit context window
            "temperature": 0.7,
        }
    }
    print(f"[client.py][chat_completion_stream] querying Ollama at {config.OLLAMA_BASE_URL}/api/chat")
    async with httpx.AsyncClient(timeout=600.0) as client:
       
        async with client.stream("POST", url, json=payload) as response:
            response.raise_for_status()
            
            async for line in response.aiter_lines():
                if line.strip():
                    try:
                        chunk = json.loads(line)
                        if "message" in chunk and "content" in chunk["message"]:
                            yield chunk["message"]["content"]
                    except json.JSONDecodeError:
                        continue
