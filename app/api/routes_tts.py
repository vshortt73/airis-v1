"""
TTS API route - proxies requests to XTTS server to avoid CORS issues
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import httpx
import os
import sys
import re

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, PROJECT_ROOT)

router = APIRouter(tags=["tts"])

# XTTS server configuration
# Note: No trailing slash - XTTS redirects if present
XTTS_SERVER_URL = "http://iris-desktop:8700/speak_stream_mp3"

class TTSRequest(BaseModel):
    text: str

def clean_text_for_tts(text: str) -> str:
    """
    Clean text for TTS by removing markdown formatting and special characters

    Args:
        text: Raw text with possible markdown formatting

    Returns:
        Cleaned text suitable for TTS
    """
    # Remove markdown bold/italic
    text = re.sub(r'\*\*\*(.+?)\*\*\*', r'\1', text)  # ***bold italic***
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)      # **bold**
    text = re.sub(r'\*(.+?)\*', r'\1', text)          # *italic*
    text = re.sub(r'__(.+?)__', r'\1', text)          # __bold__
    text = re.sub(r'_(.+?)_', r'\1', text)            # _italic_

    # Remove markdown headers
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)

    # Remove markdown horizontal rules
    text = re.sub(r'^---+$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\*\*\*+$', '', text, flags=re.MULTILINE)

    # Remove markdown links but keep text
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)

    # Remove markdown code blocks
    text = re.sub(r'```[^\n]*\n.*?```', '', text, flags=re.DOTALL)
    text = re.sub(r'`([^`]+)`', r'\1', text)

    # Remove markdown lists markers
    text = re.sub(r'^[\*\-\+]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\d+\.\s+', '', text, flags=re.MULTILINE)

    # Replace newlines with spaces
    text = text.replace('\n', ' ')

    # Remove multiple spaces
    text = re.sub(r'\s+', ' ', text)

    # Remove leading/trailing whitespace
    text = text.strip()

    return text

@router.post("/api/tts/speak")
async def speak(request: TTSRequest):
    """
    Proxy TTS requests to XTTS server

    Args:
        request: TTSRequest with text to speak

    Returns:
        Audio stream (OGG format)
    """
    try:
        # Clean text for TTS (remove markdown, special chars, etc.)
        cleaned_text = clean_text_for_tts(request.text)

        # Skip if text becomes empty after cleaning
        if not cleaned_text:
            print(f"[routes_tts.py][speak] ⚠ Text empty after cleaning, skipping")
            raise HTTPException(status_code=400, detail="Text empty after cleaning")

        print(f"[routes_tts.py][speak] Original: {request.text[:50]}...")
        print(f"[routes_tts.py][speak] Cleaned: {cleaned_text[:50]}...")
        print(f"[routes_tts.py][speak] Target URL: {XTTS_SERVER_URL}")

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            # Forward request to XTTS server with cleaned text
            response = await client.post(
                XTTS_SERVER_URL,
                json={"text": cleaned_text},
                headers={"Content-Type": "application/json"}
            )

            print(f"[routes_tts.py][speak] XTTS response status: {response.status_code}")
            print(f"[routes_tts.py][speak] XTTS response headers: {response.headers}")

            if response.status_code != 200:
                # Log the error response body
                error_body = response.text[:500]  # First 500 chars
                print(f"[routes_tts.py][speak] ✗ XTTS server error: {response.status_code}")
                print(f"[routes_tts.py][speak] ✗ XTTS error response: {error_body}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"XTTS server error: {error_body}"
                )

            print(f"[routes_tts.py][speak] ✓ TTS completed successfully, audio size: {len(response.content)} bytes")

            # Return audio stream with proper headers
            return StreamingResponse(
                iter([response.content]),
                media_type="audio/mpeg",
                headers={
                    "Content-Type": "audio/mpeg",
                    "Cache-Control": "no-cache"
                }
            )

    except httpx.TimeoutException:
        print(f"[routes_tts.py][speak] ✗ XTTS server timeout")
        raise HTTPException(status_code=504, detail="XTTS server timeout")
    except httpx.ConnectError:
        print(f"[routes_tts.py][speak] ✗ Cannot connect to XTTS server")
        raise HTTPException(status_code=503, detail="Cannot connect to XTTS server")
    except Exception as e:
        print(f"[routes_tts.py][speak] ✗ Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
