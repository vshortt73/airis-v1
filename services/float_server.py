#!/usr/bin/env python3
"""
FLOAT Video Generation API Server (STANDALONE - NOT CURRENTLY USED)

NOTE: Iris now uses the integrated endpoints added to Node2's existing
      /programs/float/app.py instead of this standalone server.
      This file is kept as a reference/backup.

If you need a standalone server (e.g., on a different port), this can be used.
Keeps FLOAT models warm in GPU memory for fast generation.
Integrates with local XTTS for text-to-video generation.

Usage:
    python float_server.py [--port 8800] [--float-path /programs/float]

API:
    POST /session             - Start session with reference image
    POST /generate            - Generate video from audio file
    POST /generate-from-text  - Generate video from text (uses local XTTS)
    DELETE /session/{id}      - End session
    GET /health               - Health check
    GET /warmup               - Warmup model (loads into GPU memory)
"""

import os
import sys
import uuid
import time
import shutil
import asyncio
import subprocess
import argparse
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
import uvicorn
import httpx
import re

# ============================================================================
# Configuration
# ============================================================================

FLOAT_PATH = Path(os.environ.get("FLOAT_PATH", "/programs/float"))
TEMP_DIR = Path("/tmp/float_server")
SESSIONS_DIR = TEMP_DIR / "sessions"
OUTPUT_DIR = TEMP_DIR / "output"

# GPU Configuration - Node2 has RTX 3060 (GPU 0) and RTX 4080 (GPU 1)
# Default to GPU 1 (4080) for FLOAT
CUDA_DEVICE = os.environ.get("CUDA_VISIBLE_DEVICES", "1")

# XTTS Configuration - local XTTS server on Node2
XTTS_URL = os.environ.get("XTTS_URL", "http://localhost:8700/speak_stream_mp3")

# ============================================================================
# Global State
# ============================================================================

sessions: Dict[str, dict] = {}
model_loaded = False
model_loading = False

# ============================================================================
# Pydantic Models
# ============================================================================

class SessionParams(BaseModel):
    seed: int = 15
    a_cfg_scale: float = 2.0
    e_cfg_scale: float = 1.0
    r_cfg_scale: float = 1.0
    nfe: int = 10
    emotion: str = "neutral"
    no_crop: bool = False

class GenerateRequest(BaseModel):
    session_id: str
    # Override session defaults if needed
    emotion: Optional[str] = None
    seed: Optional[int] = None

# ============================================================================
# Startup / Shutdown
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    # Startup
    print(f"[float_server] Starting FLOAT API Server")
    print(f"[float_server] FLOAT_PATH: {FLOAT_PATH}")
    print(f"[float_server] CUDA_VISIBLE_DEVICES: {CUDA_DEVICE}")

    # Create directories
    for dir_path in [TEMP_DIR, SESSIONS_DIR, OUTPUT_DIR]:
        dir_path.mkdir(parents=True, exist_ok=True)

    # Verify FLOAT installation
    if not (FLOAT_PATH / "generate.py").exists():
        print(f"[float_server] WARNING: generate.py not found at {FLOAT_PATH}")
    else:
        print(f"[float_server] FLOAT installation verified")

    # Optional: warmup model on startup
    if os.environ.get("FLOAT_WARMUP_ON_START", "0") == "1":
        print(f"[float_server] Warming up model...")
        await warmup_model()

    yield

    # Shutdown
    print(f"[float_server] Shutting down, cleaning temp files...")
    # Clean up old session files but keep recent ones
    try:
        for session_dir in SESSIONS_DIR.iterdir():
            if session_dir.is_dir():
                shutil.rmtree(session_dir, ignore_errors=True)
    except Exception as e:
        print(f"[float_server] Cleanup error: {e}")

app = FastAPI(
    title="FLOAT Video Generation API",
    description="Remote video generation service for Iris",
    version="1.0.0",
    lifespan=lifespan
)

# ============================================================================
# Helper Functions
# ============================================================================

async def run_float_subprocess(
    ref_path: str,
    aud_path: str,
    output_path: str,
    params: dict
) -> dict:
    """Run FLOAT generation as subprocess"""

    cmd = [
        sys.executable, str(FLOAT_PATH / "generate.py"),
        "--res_video_path", output_path,
        "--ref_path", ref_path,
        "--aud_path", aud_path,
        "--a_cfg_scale", str(params.get("a_cfg_scale", 2.0)),
        "--r_cfg_scale", str(params.get("r_cfg_scale", 1.0)),
        "--e_cfg_scale", str(params.get("e_cfg_scale", 1.0)),
        "--emo", params.get("emotion", "neutral"),
        "--nfe", str(params.get("nfe", 10)),
        "--seed", str(params.get("seed", 15))
    ]

    if params.get("no_crop", False):
        cmd.append("--no_crop")

    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = CUDA_DEVICE

    print(f"[float_server] Running: {' '.join(cmd)}")

    start_time = time.time()

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: subprocess.run(
            cmd,
            env=env,
            cwd=str(FLOAT_PATH),
            capture_output=True,
            text=True,
            check=False
        )
    )

    generation_time = time.time() - start_time

    if result.returncode != 0:
        error_msg = result.stderr[:1000] if result.stderr else "Unknown error"
        print(f"[float_server] FLOAT failed: {error_msg}")
        raise Exception(f"FLOAT generation failed: {error_msg}")

    print(f"[float_server] Generation complete in {generation_time:.2f}s")

    return {
        "success": True,
        "generation_time": generation_time,
        "output_path": output_path
    }


def clean_text_for_tts(text: str) -> str:
    """Clean text for TTS - remove emojis, markdown, etc."""
    # Remove emojis
    emoji_pattern = re.compile("["
        u"\U0001F600-\U0001F64F"
        u"\U0001F300-\U0001F5FF"
        u"\U0001F680-\U0001F6FF"
        u"\U0001F1E0-\U0001F1FF"
        u"\U00002702-\U000027B0"
        u"\U000024C2-\U0001F251"
        "]+", flags=re.UNICODE)
    text = emoji_pattern.sub('', text)

    # Remove markdown formatting
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)  # Bold
    text = re.sub(r'\*(.+?)\*', r'\1', text)      # Italic
    text = re.sub(r'_(.+?)_', r'\1', text)        # Underline
    text = re.sub(r'~~(.+?)~~', r'\1', text)      # Strikethrough
    text = re.sub(r'`(.+?)`', r'\1', text)        # Code

    # Remove action markers like *smiles* or *laughs*
    text = re.sub(r'\*[^*]+\*', '', text)

    # Clean up whitespace
    text = ' '.join(text.split())

    return text.strip()


async def generate_tts_audio(text: str, output_path: Path) -> float:
    """Generate TTS audio using local XTTS server"""
    start_time = time.time()

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            XTTS_URL,
            json={"text": text, "temperature": 0.2, "speed": 1.0}
        )
        response.raise_for_status()

        with open(output_path, "wb") as f:
            f.write(response.content)

    return time.time() - start_time


async def warmup_model():
    """Pre-load FLOAT models into GPU memory"""
    global model_loaded, model_loading

    if model_loaded or model_loading:
        return

    model_loading = True
    print(f"[float_server] Warming up FLOAT model...")

    try:
        # Create a dummy audio file for warmup
        warmup_dir = TEMP_DIR / "warmup"
        warmup_dir.mkdir(exist_ok=True)

        # Check if we have a test audio or create silence
        warmup_audio = warmup_dir / "silence.wav"
        if not warmup_audio.exists():
            # Create 1 second of silence using ffmpeg
            subprocess.run([
                "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=22050:cl=mono",
                "-t", "1", str(warmup_audio)
            ], capture_output=True, check=False)

        # We need a reference image - skip if none available
        if not warmup_audio.exists():
            print(f"[float_server] Warmup skipped - no test audio")
            model_loading = False
            return

        # Model will be loaded on first real request
        model_loaded = True
        print(f"[float_server] Model warmup prepared")

    except Exception as e:
        print(f"[float_server] Warmup error: {e}")
    finally:
        model_loading = False

# ============================================================================
# API Endpoints
# ============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    float_available = (FLOAT_PATH / "generate.py").exists()
    checkpoints_exist = (FLOAT_PATH / "checkpoints" / "float.pth").exists()

    return {
        "status": "healthy" if float_available else "degraded",
        "float_available": float_available,
        "checkpoints_loaded": checkpoints_exist,
        "model_warm": model_loaded,
        "active_sessions": len(sessions),
        "cuda_device": CUDA_DEVICE,
        "timestamp": datetime.now().isoformat()
    }

@app.post("/warmup")
async def warmup():
    """Explicitly warm up the model"""
    await warmup_model()
    return {"status": "warm", "model_loaded": model_loaded}

@app.post("/session")
async def create_session(
    reference_image: UploadFile = File(...),
    seed: int = Form(15),
    a_cfg_scale: float = Form(2.0),
    e_cfg_scale: float = Form(1.0),
    r_cfg_scale: float = Form(1.0),
    nfe: int = Form(10),
    emotion: str = Form("neutral"),
    no_crop: bool = Form(False)
):
    """
    Create a new video session with a reference image.
    The reference image is cached for all subsequent generate calls.
    """
    try:
        session_id = str(uuid.uuid4())
        session_dir = SESSIONS_DIR / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        # Save reference image
        ref_extension = Path(reference_image.filename).suffix or ".png"
        ref_path = session_dir / f"reference{ref_extension}"

        content = await reference_image.read()
        with open(ref_path, "wb") as f:
            f.write(content)

        # Store session
        sessions[session_id] = {
            "session_id": session_id,
            "ref_path": str(ref_path),
            "params": {
                "seed": seed,
                "a_cfg_scale": a_cfg_scale,
                "e_cfg_scale": e_cfg_scale,
                "r_cfg_scale": r_cfg_scale,
                "nfe": nfe,
                "emotion": emotion,
                "no_crop": no_crop
            },
            "created_at": datetime.now().isoformat(),
            "chunks_generated": 0
        }

        print(f"[float_server] Session created: {session_id}")

        return {
            "session_id": session_id,
            "status": "active"
        }

    except Exception as e:
        print(f"[float_server] Session creation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/generate")
async def generate_video(
    audio: UploadFile = File(...),
    session_id: str = Form(...),
    emotion: Optional[str] = Form(None),
    seed: Optional[int] = Form(None)
):
    """
    Generate video from audio using session's reference image.
    Returns the generated video file.
    """
    try:
        if session_id not in sessions:
            raise HTTPException(status_code=404, detail="Session not found")

        session = sessions[session_id]
        session_dir = SESSIONS_DIR / session_id

        # Save audio file
        audio_id = str(uuid.uuid4())
        audio_extension = Path(audio.filename).suffix or ".mp3"
        audio_path = session_dir / f"{audio_id}{audio_extension}"

        content = await audio.read()
        with open(audio_path, "wb") as f:
            f.write(content)

        # Prepare output path
        video_id = str(uuid.uuid4())
        video_path = OUTPUT_DIR / f"{video_id}.mp4"

        # Merge params with overrides
        params = session["params"].copy()
        if emotion:
            params["emotion"] = emotion
        if seed is not None:
            params["seed"] = seed

        # Run FLOAT
        result = await run_float_subprocess(
            ref_path=session["ref_path"],
            aud_path=str(audio_path),
            output_path=str(video_path),
            params=params
        )

        session["chunks_generated"] += 1

        # Clean up audio file
        try:
            audio_path.unlink()
        except:
            pass

        # Return video file
        if not video_path.exists():
            raise HTTPException(status_code=500, detail="Video generation failed - no output file")

        return FileResponse(
            video_path,
            media_type="video/mp4",
            filename=f"{video_id}.mp4",
            headers={
                "X-Generation-Time": str(result["generation_time"]),
                "X-Session-ID": session_id
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"[float_server] Generation error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/generate-from-text")
async def generate_video_from_text(
    session_id: str = Form(...),
    text: str = Form(...),
    emotion: Optional[str] = Form(None),
    seed: Optional[int] = Form(None)
):
    """
    Generate video directly from text.
    Uses local XTTS to generate audio, then FLOAT to generate video.
    This is the most efficient path - no audio transfer over network.
    """
    try:
        if session_id not in sessions:
            raise HTTPException(status_code=404, detail="Session not found")

        session = sessions[session_id]
        session_dir = SESSIONS_DIR / session_id

        # Clean text for TTS
        cleaned_text = clean_text_for_tts(text)
        if not cleaned_text:
            raise HTTPException(status_code=400, detail="Text empty after cleaning")

        print(f"[float_server] Generating from text: '{cleaned_text[:50]}...'")

        # Generate TTS audio locally
        audio_id = str(uuid.uuid4())
        audio_path = session_dir / f"{audio_id}.mp3"

        tts_time = await generate_tts_audio(cleaned_text, audio_path)
        print(f"[float_server] TTS complete: {tts_time:.2f}s")

        # Prepare output path
        video_id = str(uuid.uuid4())
        video_path = OUTPUT_DIR / f"{video_id}.mp4"

        # Merge params with overrides
        params = session["params"].copy()
        if emotion:
            params["emotion"] = emotion
        if seed is not None:
            params["seed"] = seed

        # Run FLOAT
        result = await run_float_subprocess(
            ref_path=session["ref_path"],
            aud_path=str(audio_path),
            output_path=str(video_path),
            params=params
        )

        session["chunks_generated"] += 1
        total_time = tts_time + result["generation_time"]

        # Clean up audio file
        try:
            audio_path.unlink()
        except:
            pass

        # Return video file
        if not video_path.exists():
            raise HTTPException(status_code=500, detail="Video generation failed - no output file")

        return FileResponse(
            video_path,
            media_type="video/mp4",
            filename=f"{video_id}.mp4",
            headers={
                "X-TTS-Time": str(tts_time),
                "X-Generation-Time": str(result["generation_time"]),
                "X-Total-Time": str(total_time),
                "X-Session-ID": session_id
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"[float_server] Text generation error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/session/{session_id}")
async def delete_session(session_id: str):
    """End a session and clean up resources"""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    # Clean up session directory
    session_dir = SESSIONS_DIR / session_id
    if session_dir.exists():
        shutil.rmtree(session_dir, ignore_errors=True)

    # Remove from memory
    session = sessions.pop(session_id)

    print(f"[float_server] Session ended: {session_id} ({session['chunks_generated']} chunks generated)")

    return {
        "status": "ended",
        "chunks_generated": session["chunks_generated"]
    }

@app.get("/sessions")
async def list_sessions():
    """List active sessions"""
    return {
        "sessions": [
            {
                "session_id": s["session_id"],
                "created_at": s["created_at"],
                "chunks_generated": s["chunks_generated"]
            }
            for s in sessions.values()
        ]
    }

# ============================================================================
# Main Entry Point
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="FLOAT Video Generation API Server")
    parser.add_argument("--port", type=int, default=8800, help="Port to listen on")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--float-path", type=str, default=None, help="Path to FLOAT installation")
    parser.add_argument("--cuda-device", type=str, default=None, help="CUDA device to use")
    args = parser.parse_args()

    global FLOAT_PATH, CUDA_DEVICE

    if args.float_path:
        FLOAT_PATH = Path(args.float_path)
    if args.cuda_device:
        CUDA_DEVICE = args.cuda_device

    print(f"[float_server] Starting on {args.host}:{args.port}")
    print(f"[float_server] FLOAT_PATH: {FLOAT_PATH}")
    print(f"[float_server] CUDA_DEVICE: {CUDA_DEVICE}")

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="info"
    )

if __name__ == "__main__":
    main()
