"""
Speech-to-Text routes - calls remote Whisper server on Node2
"""

import os
import sys
from pathlib import Path

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import JSONResponse
import httpx

# Add project root for config import
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app import config

router = APIRouter()

# Remote STT server on Node2
STT_SERVER_URL = getattr(config, 'STT_SERVER_URL', 'http://node2:8600')


def get_stt_url() -> str:
    """Get the STT server URL from config or environment"""
    env_url = os.environ.get('STT_SERVER_URL')
    if env_url:
        return env_url
    return getattr(config, 'STT_SERVER_URL', 'http://node2:8600')


@router.post("/stt-upload")
async def stt_upload(file: UploadFile = File(...)):
    """
    Accept audio file, transcribe via remote Whisper server, return transcript
    """
    try:
        stt_url = get_stt_url()

        # Read the uploaded file
        content = await file.read()
        filename = file.filename or "audio.webm"

        # Send to remote STT server
        async with httpx.AsyncClient(timeout=60.0) as client:
            files = {"file": (filename, content, file.content_type or "audio/webm")}
            response = await client.post(f"{stt_url}/transcribe", files=files)

            if response.status_code != 200:
                print(f"[STT] Remote server error: {response.status_code}")
                return JSONResponse(
                    {"transcript": "[ERROR]", "error": f"STT server error: {response.status_code}"},
                    status_code=500
                )

            result = response.json()
            transcript = result.get("transcript", "[ERROR]")

            # Log transcription
            transcribe_time = result.get("transcribe_time", 0)
            print(f"[STT] Transcribed in {transcribe_time:.2f}s: '{transcript[:50]}...'")

            return JSONResponse({"transcript": transcript})

    except httpx.ConnectError as e:
        print(f"[STT] Connection error: {e}")
        return JSONResponse(
            {"transcript": "[ERROR]", "error": "STT server unavailable"},
            status_code=503
        )
    except Exception as e:
        print(f"[STT] Error: {e}")
        return JSONResponse(
            {"transcript": "[ERROR]", "error": str(e)},
            status_code=500
        )


@router.get("/stt-health")
async def stt_health():
    """Check STT server health"""
    try:
        stt_url = get_stt_url()

        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{stt_url}/health")

            if response.status_code == 200:
                remote_health = response.json()
                return {
                    "status": "healthy",
                    "mode": "remote",
                    "stt_server_url": stt_url,
                    "stt_server_status": remote_health
                }
            else:
                return {
                    "status": "degraded",
                    "mode": "remote",
                    "stt_server_url": stt_url,
                    "error": f"Server returned {response.status_code}"
                }

    except Exception as e:
        return {
            "status": "error",
            "mode": "remote",
            "stt_server_url": get_stt_url(),
            "error": str(e)
        }
