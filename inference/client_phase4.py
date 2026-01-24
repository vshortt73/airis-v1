"""
Ollama API client for Iris v3
Clean streaming interface with explicit context window
"""

import httpx
from typing import Dict, List, AsyncIterator
import sys
import os; PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..' if '__file__' in dir() else '.')); sys.path.insert(0, PROJECT_ROOT)
from app import config

async def chat_completion_stream(
    messages: List[Dict[str, str]]
) -> AsyncIterator[str]:
    """
    Send chat completion request to Ollama and stream response
    Supports vision - messages can contain "images" field with base64 encoded images
    
    Args:
        messages: List of message dicts with "role", "content", and optional "images" keys
        
    Yields:
        Chunks of response text as they arrive
    """
    
    url = f"{config.OLLAMA_BASE_URL}/api/chat"
    
    # Log vision usage
    image_count = sum(len(msg.get("images", [])) for msg in messages)
    if image_count > 0:
        print(f"[client.py][chat_completion_stream] Vision enabled: {image_count} image(s) in context")
    
    payload = {
        "model": config.OLLAMA_MODEL,
        "messages": messages,  # Messages can now contain "images" field
        "stream": True,
        "options": {
            "num_ctx": config.OLLAMA_CONTEXT_WINDOW,  # CRITICAL: Explicit context window
            "temperature": 0.7,
        }
    }
    
    print(f"[client.py][chat_completion_stream] Querying Ollama at {config.OLLAMA_BASE_URL}/api/chat")
    
    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream("POST", url, json=payload) as response:
            response.raise_for_status()
            
            async for line in response.aiter_lines():
                if line.strip():
                    import json
                    try:
                        chunk = json.loads(line)
                        if "message" in chunk and "content" in chunk["message"]:
                            yield chunk["message"]["content"]
                    except json.JSONDecodeError:
                        continue
