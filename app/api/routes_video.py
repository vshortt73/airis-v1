"""
Video Streaming API - Real-time FLOAT video generation for Iris
Uses remote FLOAT server on Node2 for video generation
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks, UploadFile, File, Form
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional, Dict, List
import uuid
import time
import os
import sys
from pathlib import Path
from datetime import datetime
import asyncio
import shutil
import httpx

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from database.config_loader import get_config, create_or_update_config
from app import config
from core.websocket_broadcast import broadcast

# Config keys for video settings
CONFIG_VIDEO_REFERENCE_IMAGE = "VIDEO_REFERENCE_IMAGE_PATH"

router = APIRouter(tags=["video"])

# Global state for video sessions
video_sessions: Dict[str, dict] = {}
video_queues: Dict[str, List[dict]] = {}

# Paths
TEMP_DIR = Path("/iris-v3/assets/temp")
REP_DIR = Path("/iris-v3/static")
VIDEO_DIR = TEMP_DIR / "videos"
UPLOAD_DIR = TEMP_DIR / "uploads"
REFERENCE_DIR = Path("/iris-v3/assets/video_references")
HLS_DIR = TEMP_DIR / "hls"  # HLS segments and playlists

# Ensure directories exist
for dir_path in [TEMP_DIR, VIDEO_DIR, UPLOAD_DIR, REFERENCE_DIR, HLS_DIR]:
    dir_path.mkdir(parents=True, exist_ok=True)


class HLSSession:
    """Manages HLS playlist and segments for a video session."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.dir = HLS_DIR / session_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.playlist_path = self.dir / "playlist.m3u8"
        self.segments: List[dict] = []
        self.target_duration = 4  # Max segment duration for HLS header
        self.is_complete = False
        self._write_playlist()

    def _write_playlist(self):
        """Write/update the HLS playlist file."""
        # Use VERSION:3 for maximum compatibility (version 7 can cause issues)
        lines = [
            "#EXTM3U",
            "#EXT-X-VERSION:3",
            f"#EXT-X-TARGETDURATION:{self.target_duration}",
            "#EXT-X-MEDIA-SEQUENCE:0",
            "#EXT-X-PLAYLIST-TYPE:EVENT",
        ]

        for i, seg in enumerate(self.segments):
            # No discontinuity markers needed - segments are remuxed with continuous timestamps
            lines.append(f"#EXTINF:{seg['duration']:.6f},")
            lines.append(seg['filename'])

        if self.is_complete:
            lines.append("#EXT-X-ENDLIST")

        # Ensure trailing newline (some parsers require it)
        self.playlist_path.write_text("\n".join(lines) + "\n")

    def add_segment(self, data: bytes, duration: float) -> str:
        """Add a segment and update playlist. Returns segment filename."""
        import subprocess

        idx = len(self.segments)
        filename = f"segment_{idx:03d}.ts"
        filepath = self.dir / filename

        # Calculate cumulative start time for this segment
        cumulative_time = sum(seg['duration'] for seg in self.segments)

        # Write raw segment to temp file
        temp_input = self.dir / f"_temp_in_{idx}.ts"
        temp_output = self.dir / f"_temp_out_{idx}.ts"
        temp_input.write_bytes(data)

        try:
            # FLOAT now outputs segments with PTS starting at 0 (fixed in stream_encoder.py)
            # We just need to offset each segment to its position in the cumulative timeline
            result = subprocess.run([
                'ffmpeg', '-y',
                '-i', str(temp_input),
                '-c', 'copy',  # No re-encoding, just remux
                '-muxdelay', '0',
                '-muxpreload', '0',
                '-output_ts_offset', str(cumulative_time),
                '-f', 'mpegts',
                str(temp_output)
            ], capture_output=True, timeout=10)

            if result.returncode == 0 and temp_output.exists():
                # Use the remuxed segment
                import shutil
                shutil.move(str(temp_output), str(filepath))
                print(f"[HLS] Segment {filename} at {cumulative_time:.2f}s ({duration:.2f}s)")
            else:
                # Fallback to raw segment if FFmpeg fails
                import shutil
                shutil.move(str(temp_input), str(filepath))
                print(f"[HLS] FFmpeg failed, using raw segment: {result.stderr.decode()[:100]}")
        except Exception as e:
            # Fallback to raw segment
            if temp_input.exists():
                import shutil
                shutil.move(str(temp_input), str(filepath))
            print(f"[HLS] Remux error, using raw segment: {e}")
        finally:
            # Cleanup temp files
            if temp_input.exists():
                temp_input.unlink()
            if temp_output.exists():
                temp_output.unlink()

        # Track segment
        self.segments.append({
            'filename': filename,
            'duration': duration,
            'size': filepath.stat().st_size if filepath.exists() else len(data)
        })

        # Update target duration if needed
        if duration > self.target_duration:
            self.target_duration = int(duration) + 1

        # Rewrite playlist (without discontinuity markers since timestamps are now continuous)
        self._write_playlist()

        print(f"[HLS] Added segment {filename}: {duration:.2f}s")
        return filename

    def complete(self):
        """Mark stream as complete (adds EXT-X-ENDLIST)."""
        self.is_complete = True
        self._write_playlist()
        print(f"[HLS] Session {self.session_id} complete: {len(self.segments)} segments")

    def reset_for_new_turn(self):
        """Reset session for a new turn (clears segments, removes ENDLIST)."""
        # Delete old segment files
        for seg in self.segments:
            seg_path = self.dir / seg['filename']
            if seg_path.exists():
                seg_path.unlink()

        # Reset state
        self.segments = []
        self.is_complete = False
        self.target_duration = 4

        # Rewrite empty playlist (EVENT type, no ENDLIST)
        self._write_playlist()
        print(f"[HLS] Session {self.session_id} reset for new turn")

    def cleanup(self):
        """Remove all HLS files for this session."""
        if self.dir.exists():
            shutil.rmtree(self.dir)
            print(f"[HLS] Cleaned up session {self.session_id}")


# Active HLS sessions
hls_sessions: Dict[str, HLSSession] = {}

# Remote FLOAT server configuration
# Default to Node2's Tailscale address
FLOAT_SERVER_URL = getattr(config, 'FLOAT_SERVER_URL', 'http://node2:8800')


def get_float_url() -> str:
    """Get the FLOAT server URL from config or environment"""
    # Check environment first
    env_url = os.environ.get('FLOAT_SERVER_URL')
    if env_url:
        return env_url
    # Then config
    return getattr(config, 'FLOAT_SERVER_URL', 'http://node2:8800')


# Pydantic models
class StartSessionRequest(BaseModel):
    seed: int = 15
    a_cfg_scale: float = 2.0
    e_cfg_scale: float = 1.0
    r_cfg_scale: float = 1.0
    nfe: int = 10
    emotion: str = "neutral"  # Valid: angry, disgust, fear, happy, neutral, sad, surprise
    no_crop: bool = False


class QueueChunkRequest(BaseModel):
    session_id: str
    text: str
    chunk_index: int


class SessionStatusResponse(BaseModel):
    session_id: str
    active: bool
    chunks_submitted: int
    chunks_completed: int
    chunks_failed: int
    current_chunk: Optional[int]


@router.post("/api/video/upload-image")
async def upload_image(file: UploadFile = File(...)):
    """Upload reference image for video session"""
    try:
        # Validate file type
        if not file.content_type or not file.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="File must be an image")

        # Save image
        image_id = str(uuid.uuid4())
        file_extension = Path(file.filename).suffix or ".jpg"
        image_path = UPLOAD_DIR / f"{image_id}{file_extension}"

        contents = await file.read()
        with open(image_path, "wb") as f:
            f.write(contents)

        print(f"[routes_video.py] Image uploaded: {image_path}")

        return {
            "image_id": image_id,
            "filename": file.filename,
            "path": str(image_path)
        }

    except Exception as e:
        print(f"[routes_video.py] Image upload error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/video/saved-image")
async def get_saved_image():
    """Get the saved reference image path from config"""
    try:
        saved_path = get_config(CONFIG_VIDEO_REFERENCE_IMAGE)

        if not saved_path:
            return {"has_saved_image": False, "path": None, "filename": None}

        # Verify file still exists
        if not Path(saved_path).exists():
            print(f"[routes_video.py] Saved image no longer exists: {saved_path}")
            return {"has_saved_image": False, "path": None, "filename": None}
        
        shutil.copy(saved_path, f"{REP_DIR}/{Path(saved_path).name}")

        return {
            "has_saved_image": True,
            "path": saved_path,
            "filename": Path(saved_path).name
        }

    except Exception as e:
        print(f"[routes_video.py] Get saved image error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/video/save-reference-image")
async def save_reference_image(image_id: str):
    """Save an uploaded image as the persistent reference image"""
    try:
        # Find the uploaded image
        image_files = list(UPLOAD_DIR.glob(f"{image_id}.*"))
        if not image_files:
            raise HTTPException(status_code=404, detail="Image not found in uploads")

        source_path = image_files[0]

        # Copy to permanent reference directory with a fixed name
        dest_path = REFERENCE_DIR / f"reference{source_path.suffix}"

        # Remove old reference if exists
        for old_file in REFERENCE_DIR.glob("reference.*"):
            old_file.unlink()

        shutil.copy2(source_path, dest_path)

        # Save path to config
        create_or_update_config(
            key=CONFIG_VIDEO_REFERENCE_IMAGE,
            value=str(dest_path),
            category='video',
            value_type='string',
            description='Path to the saved video reference image',
            modified_by='video_api'
        )

        print(f"[routes_video.py] Reference image saved: {dest_path}")

        return {
            "success": True,
            "path": str(dest_path),
            "filename": dest_path.name
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"[routes_video.py] Save reference image error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def create_remote_float_session(image_path: str, params: dict) -> str:
    """Create a session on the remote FLOAT server"""
    float_url = get_float_url()

    async with httpx.AsyncClient(timeout=60.0) as client:
        # Read image file
        with open(image_path, "rb") as f:
            image_data = f.read()

        # Create multipart form data
        files = {
            "reference_image": (Path(image_path).name, image_data, "image/png")
        }
        data = {
            "seed": str(params.get("seed", 15)),
            "a_cfg_scale": str(params.get("a_cfg_scale", 2.0)),
            "e_cfg_scale": str(params.get("e_cfg_scale", 1.0)),
            "r_cfg_scale": str(params.get("r_cfg_scale", 1.0)),
            "nfe": str(params.get("nfe", 10)),
            "emotion": params.get("emotion", "neutral"),
            "no_crop": str(params.get("no_crop", False)).lower()
        }

        response = await client.post(
            f"{float_url}/session",
            files=files,
            data=data
        )
        response.raise_for_status()
        result = response.json()

        return result["session_id"]


async def end_remote_float_session(remote_session_id: str):
    """End a session on the remote FLOAT server"""
    float_url = get_float_url()

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.delete(f"{float_url}/session/{remote_session_id}")
            # Don't raise on 404 - session might already be gone
            if response.status_code not in [200, 404]:
                response.raise_for_status()
    except Exception as e:
        print(f"[routes_video.py] Warning: Failed to end remote session: {e}")


@router.post("/api/video/start-session-saved")
async def start_session_with_saved_image(params: StartSessionRequest):
    """Start a new video session using the saved reference image"""
    try:
        # Request GPU for FLOAT service
        from core.gpu_manager import request_gpu

        success, error = await request_gpu("float")
        if not success:
            raise HTTPException(status_code=503, detail=f"Video unavailable: {error}")

        saved_path = get_config(CONFIG_VIDEO_REFERENCE_IMAGE)

        if not saved_path or not Path(saved_path).exists():
            raise HTTPException(status_code=404, detail="No saved reference image found")

        image_path = Path(saved_path)

        # Create session on remote FLOAT server
        print(f"[routes_video.py] Creating remote FLOAT session...")
        remote_session_id = await create_remote_float_session(
            str(image_path),
            params.model_dump()
        )
        print(f"[routes_video.py] Remote FLOAT session created: {remote_session_id}")

        # Create local session
        session_id = str(uuid.uuid4())

        video_sessions[session_id] = {
            "session_id": session_id,
            "remote_session_id": remote_session_id,  # Track remote session
            "image_id": "saved",
            "image_path": str(image_path),
            "image_filename": image_path.name,
            "parameters": params.model_dump(),
            "created_at": datetime.now().isoformat(),
            "chunks_submitted": 0,
            "chunks_completed": 0,
            "chunks_failed": 0,
            "active": True,
            "current_chunk": None
        }

        video_queues[session_id] = []

        print(f"[routes_video.py] Session started: {session_id}")

        return {
            "session_id": session_id,
            "status": "active",
            "image_path": str(image_path),
            "mode": "remote"
        }

    except httpx.HTTPError as e:
        print(f"[routes_video.py] FLOAT server error: {e}")
        raise HTTPException(status_code=502, detail=f"FLOAT server error: {e}")
    except HTTPException:
        raise
    except Exception as e:
        print(f"[routes_video.py] Start session error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/video/start-session")
async def start_session(image_id: str, params: StartSessionRequest):
    """Start a new video streaming session"""
    try:
        # Request GPU for FLOAT service
        from core.gpu_manager import request_gpu

        success, error = await request_gpu("float")
        if not success:
            raise HTTPException(status_code=503, detail=f"Video unavailable: {error}")

        # Find image file
        image_files = list(UPLOAD_DIR.glob(f"{image_id}.*"))
        if not image_files:
            raise HTTPException(status_code=404, detail="Image not found")

        image_path = image_files[0]

        # Create session on remote FLOAT server
        print(f"[routes_video.py] Creating remote FLOAT session...")
        remote_session_id = await create_remote_float_session(
            str(image_path),
            params.model_dump()
        )
        print(f"[routes_video.py] Remote FLOAT session created: {remote_session_id}")

        # Create local session
        session_id = str(uuid.uuid4())

        video_sessions[session_id] = {
            "session_id": session_id,
            "remote_session_id": remote_session_id,
            "image_id": image_id,
            "image_path": str(image_path),
            "image_filename": image_path.name,
            "parameters": params.model_dump(),
            "created_at": datetime.now().isoformat(),
            "chunks_submitted": 0,
            "chunks_completed": 0,
            "chunks_failed": 0,
            "active": True,
            "current_chunk": None
        }

        video_queues[session_id] = []

        print(f"[routes_video.py] Session started: {session_id}")

        return {
            "session_id": session_id,
            "status": "active",
            "mode": "remote"
        }

    except httpx.HTTPError as e:
        print(f"[routes_video.py] FLOAT server error: {e}")
        raise HTTPException(status_code=502, detail=f"FLOAT server error: {e}")
    except Exception as e:
        print(f"[routes_video.py] Start session error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/video/queue-chunk")
async def queue_chunk(request: QueueChunkRequest, background_tasks: BackgroundTasks):
    """Queue a text chunk for video generation via remote FLOAT server"""
    try:
        session_id = request.session_id

        if session_id not in video_sessions:
            raise HTTPException(status_code=404, detail="Session not found")

        if not video_sessions[session_id]["active"]:
            raise HTTPException(status_code=400, detail="Session not active")

        # Create chunk job
        chunk_id = f"{session_id}_chunk_{request.chunk_index}"

        # Store the original text - cleaning happens on the remote server
        print(f"[routes_video.py] Chunk received: {chunk_id} - '{request.text[:50]}...'")

        if not request.text.strip():
            print(f"[routes_video.py] Text empty, skipping chunk")
            return {
                "chunk_id": chunk_id,
                "status": "skipped",
                "reason": "Text empty"
            }

        # Create chunk job
        chunk_job = {
            "chunk_id": chunk_id,
            "chunk_index": request.chunk_index,
            "text": request.text,
            "status": "queued",
            "video_path": None,
            "created_at": datetime.now().isoformat(),
            "tts_time": 0,
            "video_time": 0,
            "total_time": 0
        }

        video_queues[session_id].append(chunk_job)
        video_sessions[session_id]["chunks_submitted"] += 1

        print(f"[routes_video.py] Chunk queued: {chunk_id}")
        print(f"[routes_video.py] Queue length: {len(video_queues[session_id])}")

        # Check if processor needs to be started
        chunks_processing = sum(1 for c in video_queues[session_id] if c["status"] == "processing")
        if len(video_queues[session_id]) == 1 or chunks_processing == 0:
            print(f"[routes_video.py] Starting video processor")
            background_tasks.add_task(process_queue, session_id)
        else:
            print(f"[routes_video.py] Processor already running ({chunks_processing} processing)")

        return {
            "chunk_id": chunk_id,
            "status": "queued",
            "position": len(video_queues[session_id])
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"[routes_video.py] Queue chunk error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def process_queue(session_id: str):
    """Process video generation queue for a session"""
    print(f"[routes_video.py] process_queue started for session {session_id}")

    while True:
        if session_id not in video_queues or len(video_queues[session_id]) == 0:
            print(f"[routes_video.py] process_queue: No more chunks, exiting")
            break

        # Get next queued chunk
        next_chunk = None
        for chunk in video_queues[session_id]:
            if chunk["status"] == "queued":
                next_chunk = chunk
                break

        if not next_chunk:
            print(f"[routes_video.py] process_queue: No queued chunks found, exiting")
            break

        print(f"[routes_video.py] Processing chunk {next_chunk['chunk_index']}: {next_chunk['text'][:50]}...")

        # Mark as processing
        next_chunk["status"] = "processing"
        video_sessions[session_id]["current_chunk"] = next_chunk["chunk_index"]

        try:
            # Generate video via remote FLOAT server
            await generate_chunk_video_remote(session_id, next_chunk)
            next_chunk["status"] = "completed"
            video_sessions[session_id]["chunks_completed"] += 1
            print(f"[routes_video.py] Chunk completed: {next_chunk['chunk_id']}")

            # Push notification to WebSocket clients
            await broadcast({
                "type": "video_chunk_ready",
                "session_id": session_id,
                "chunk_index": next_chunk["chunk_index"],
                "status": "completed",
                "video_path": next_chunk.get("video_path")
            })

        except Exception as e:
            next_chunk["status"] = "failed"
            next_chunk["error"] = str(e)
            video_sessions[session_id]["chunks_failed"] += 1
            print(f"[routes_video.py] Chunk failed: {next_chunk['chunk_id']} - {e}")

            # Push failure notification to WebSocket clients
            await broadcast({
                "type": "video_chunk_ready",
                "session_id": session_id,
                "chunk_index": next_chunk["chunk_index"],
                "status": "failed",
                "error": str(e)
            })

            import traceback
            traceback.print_exc()


async def generate_chunk_video_remote(session_id: str, chunk: dict):
    """Generate video via remote FLOAT server (TTS + video in one call)"""

    session = video_sessions[session_id]
    remote_session_id = session.get("remote_session_id")

    if not remote_session_id:
        raise Exception("No remote session ID found")

    float_url = get_float_url()
    start_time = time.time()

    print(f"[routes_video.py] Calling remote FLOAT generate-from-text...")

    # Use generate-from-text endpoint - TTS happens on Node2
    async with httpx.AsyncClient(timeout=300.0) as client:  # 5 min timeout for generation
        data = {
            "session_id": remote_session_id,
            "text": chunk["text"],
            "emotion": session["parameters"].get("emotion", "neutral")
        }

        response = await client.post(
            f"{float_url}/generate-from-text",
            data=data
        )
        response.raise_for_status()

        # Extract timing from headers
        tts_time = float(response.headers.get("X-TTS-Time", 0))
        gen_time = float(response.headers.get("X-Generation-Time", 0))
        total_time = float(response.headers.get("X-Total-Time", time.time() - start_time))

        # Save video locally
        video_path = VIDEO_DIR / f"{chunk['chunk_id']}.mp4"
        with open(video_path, "wb") as f:
            f.write(response.content)

        chunk["video_path"] = str(video_path)
        chunk["tts_time"] = tts_time
        chunk["video_time"] = gen_time
        chunk["total_time"] = total_time

        print(f"[routes_video.py] Video complete: {gen_time:.2f}s (TTS: {tts_time:.2f}s, Total: {total_time:.2f}s)")


@router.get("/api/video/session-status/{session_id}")
async def get_session_status(session_id: str):
    """Get status of a video session"""
    if session_id not in video_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = video_sessions[session_id]

    return SessionStatusResponse(**session)


@router.get("/api/video/chunk-status/{session_id}/{chunk_index}")
async def get_chunk_status(session_id: str, chunk_index: int):
    """Get status of a specific chunk"""
    if session_id not in video_queues:
        raise HTTPException(status_code=404, detail="Session not found")

    for chunk in video_queues[session_id]:
        if chunk["chunk_index"] == chunk_index:
            return {
                "chunk_id": chunk["chunk_id"],
                "chunk_index": chunk["chunk_index"],
                "status": chunk["status"],
                "video_path": chunk.get("video_path"),
                "tts_time": chunk.get("tts_time", 0),
                "video_time": chunk.get("video_time", 0),
                "total_time": chunk.get("total_time", 0)
            }

    raise HTTPException(status_code=404, detail="Chunk not found")


@router.get("/api/video/stream/{chunk_id}")
async def stream_video(chunk_id: str):
    """Stream a generated video chunk"""
    # Find video file
    video_files = list(VIDEO_DIR.glob(f"{chunk_id}.mp4"))

    if not video_files:
        raise HTTPException(status_code=404, detail="Video not found")

    video_path = video_files[0]

    return FileResponse(
        video_path,
        media_type="video/mp4",
        headers={
            "Accept-Ranges": "bytes",
            "Cache-Control": "no-cache"
        }
    )


@router.post("/api/video/end-session/{session_id}")
async def end_session(session_id: str):
    """End a video session and clean up"""
    if session_id not in video_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = video_sessions[session_id]
    session["active"] = False

    # End remote session
    remote_session_id = session.get("remote_session_id")
    if remote_session_id:
        await end_remote_float_session(remote_session_id)

    print(f"[routes_video.py] Session ended: {session_id}")

    return {"status": "ended"}


@router.get("/api/video/health")
async def health_check():
    """Check if video system is ready"""
    float_url = get_float_url()

    try:
        # Check remote FLOAT server health
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{float_url}/health")
            remote_health = response.json() if response.status_code == 200 else None

        return {
            "status": "healthy" if remote_health else "degraded",
            "mode": "remote",
            "float_server_url": float_url,
            "float_server_status": remote_health,
            "active_sessions": len([s for s in video_sessions.values() if s["active"]])
        }
    except Exception as e:
        return {
            "status": "error",
            "mode": "remote",
            "float_server_url": float_url,
            "error": str(e),
            "active_sessions": len([s for s in video_sessions.values() if s["active"]])
        }


# ============================================================================
# STREAMING VIDEO GENERATION - Real-time video streaming via MSE
# ============================================================================

from fastapi.responses import StreamingResponse

@router.post("/api/video/stream")
async def stream_video(
    session_id: str = Form(...),
    text: str = Form(...),
    emotion: Optional[str] = Form(None),
    seed: Optional[int] = Form(None)
):
    """
    Stream video in real-time using fragmented MP4 (fMP4).

    This proxies to FLOAT's streaming endpoint and forwards the video
    segments as they're generated. First frames appear within ~500ms.

    Client should use Media Source Extensions (MSE) to play this stream.
    """
    if session_id not in video_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = video_sessions[session_id]
    remote_session_id = session.get("remote_session_id")

    if not remote_session_id:
        raise HTTPException(status_code=400, detail="No remote session found")

    float_url = get_float_url()

    async def proxy_stream():
        """Proxy the video stream from FLOAT server."""
        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                # Stream from FLOAT's streaming endpoint
                async with client.stream(
                    "POST",
                    f"{float_url}/stream-video",
                    data={
                        "session_id": remote_session_id,
                        "text": text,
                        "emotion": emotion or session["parameters"].get("emotion", "neutral"),
                        "seed": str(seed) if seed else ""
                    }
                ) as response:
                    if response.status_code != 200:
                        error = await response.aread()
                        print(f"[routes_video] Stream error from FLOAT: {error}")
                        return

                    # Forward chunks as they arrive
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        yield chunk

                    print("[routes_video] Stream complete")

        except Exception as e:
            print(f"[routes_video] Stream proxy error: {e}")
            import traceback
            traceback.print_exc()

    return StreamingResponse(
        proxy_stream(),
        media_type="video/mp4",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "X-Session-ID": session_id
        }
    )


@router.post("/api/video/stream-ndjson")
async def stream_video_ndjson(
    session_id: str = Form(...),
    text: str = Form(...),
    emotion: Optional[str] = Form(None),
    seed: Optional[int] = Form(None),
    buffer_chunks: Optional[int] = Form(4),
    quality: Optional[str] = Form("high")
):
    """
    Stream video as newline-delimited JSON with base64-encoded segments.

    Each line is a JSON object:
    {"segment": "<base64>", "chunk_idx": N, "total_chunks": M, "is_last": bool}

    buffer_chunks controls how many FLOAT chunks (~1 sec each) are buffered
    before encoding into a single video segment. Default 4 = ~4 second segments.
    This gives more download time on slow connections.

    quality controls video bitrate for different connection speeds:
        - high: 2Mbps (WiFi/wired)
        - medium: 1Mbps (decent mobile)
        - low: 500kbps (4G/slow connections)

    This format is easier to handle in JavaScript without MSE complexity.
    """
    if session_id not in video_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = video_sessions[session_id]
    remote_session_id = session.get("remote_session_id")

    if not remote_session_id:
        raise HTTPException(status_code=400, detail="No remote session found")

    float_url = get_float_url()

    async def proxy_ndjson():
        """Proxy the NDJSON stream from FLOAT server."""
        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                async with client.stream(
                    "POST",
                    f"{float_url}/stream-video-segments",
                    data={
                        "session_id": remote_session_id,
                        "text": text,
                        "emotion": emotion or session["parameters"].get("emotion", "neutral"),
                        "seed": str(seed) if seed else "",
                        "buffer_chunks": str(buffer_chunks or 4),
                        "quality": quality or "high"
                    }
                ) as response:
                    if response.status_code != 200:
                        error_bytes = await response.aread()
                        try:
                            # Try to parse as JSON and extract detail
                            import json
                            error_data = json.loads(error_bytes.decode('utf-8'))
                            error_msg = error_data.get('detail', str(error_data))
                        except:
                            error_msg = error_bytes.decode('utf-8', errors='replace')
                        # Escape quotes for JSON
                        error_msg = error_msg.replace('"', '\\"')
                        yield f'{{"error": "{error_msg}"}}\n'
                        return

                    # Debug: save segments to disk for inspection
                    # Use global counter stored in session to avoid overwriting
                    import base64
                    debug_dir = VIDEO_DIR / "debug_segments" / session_id
                    debug_dir.mkdir(parents=True, exist_ok=True)

                    # Get/initialize global segment counter for this session
                    if "debug_segment_counter" not in session:
                        session["debug_segment_counter"] = 0

                    print(f"[DEBUG] Saving segments to {debug_dir} (starting at #{session['debug_segment_counter']})")

                    async for line in response.aiter_lines():
                        if line:
                            yield line + "\n"

                            # Parse and save segment
                            try:
                                import json
                                data = json.loads(line)
                            except json.JSONDecodeError as e:
                                print(f"[DEBUG] JSON parse error: {e}, line: {line[:100]}")
                                continue

                            # Save segment to disk FIRST (before anything else can fail)
                            if data.get("segment"):
                                try:
                                    segment_data = base64.b64decode(data["segment"])
                                    idx = data.get("chunk_idx", 0)
                                    global_idx = session["debug_segment_counter"]
                                    segment_file = debug_dir / f"segment_{global_idx:03d}.mp4"
                                    with open(segment_file, "wb") as f:
                                        f.write(segment_data)
                                    print(f"[DEBUG] ✓ Saved {segment_file.name} ({len(segment_data)} bytes, {data.get('duration', '?')}s)")
                                    session["debug_segment_counter"] += 1
                                except Exception as e:
                                    print(f"[DEBUG] ✗ Failed to save segment: {e}")
                            elif data.get("error"):
                                print(f"[DEBUG] Error from FLOAT: {data.get('error')}")

                            # Broadcast progress to WebSocket
                            try:
                                idx = data.get("chunk_idx") or data.get("segment_idx")
                                total = data.get("total_chunks") or data.get("total_segments")
                                if idx is not None:
                                    await broadcast({
                                        "type": "video_stream_progress",
                                        "session_id": session_id,
                                        "chunk_idx": idx,
                                        "total_chunks": total,
                                        "is_last": data.get("is_last", False)
                                    })
                            except Exception as e:
                                print(f"[DEBUG] Broadcast error (non-fatal): {e}")

                    print(f"[DEBUG] Stream complete, total segments saved: {session['debug_segment_counter']}")

        except Exception as e:
            yield f'{{"error": "{str(e)}"}}\n'

    return StreamingResponse(
        proxy_ndjson(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Session-ID": session_id
        }
    )


# =============================================================================
# HLS Streaming Endpoints
# =============================================================================

@router.get("/api/video/hls/{session_id}/playlist.m3u8")
async def get_hls_playlist(session_id: str):
    """Serve the HLS playlist for a session."""
    if session_id not in hls_sessions:
        raise HTTPException(status_code=404, detail="HLS session not found")

    hls = hls_sessions[session_id]
    if not hls.playlist_path.exists():
        raise HTTPException(status_code=404, detail="Playlist not ready")

    return FileResponse(
        hls.playlist_path,
        media_type="application/vnd.apple.mpegurl",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Access-Control-Allow-Origin": "*"
        }
    )


@router.get("/api/video/hls/{session_id}/{filename}")
async def get_hls_segment(session_id: str, filename: str):
    """Serve an HLS segment file."""
    if session_id not in hls_sessions:
        raise HTTPException(status_code=404, detail="HLS session not found")

    hls = hls_sessions[session_id]
    segment_path = hls.dir / filename

    if not segment_path.exists():
        raise HTTPException(status_code=404, detail="Segment not found")

    # MPEG-TS segments
    media_type = "video/mp2t" if filename.endswith(".ts") else "video/mp4"

    return FileResponse(
        segment_path,
        media_type=media_type,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Access-Control-Allow-Origin": "*"
        }
    )


@router.post("/api/video/hls/init/{session_id}")
async def init_hls_session(session_id: str):
    """Initialize HLS session for a video session."""
    if session_id not in video_sessions:
        raise HTTPException(status_code=404, detail="Video session not found")

    # Create or reset HLS session
    if session_id in hls_sessions:
        hls_sessions[session_id].cleanup()

    hls_sessions[session_id] = HLSSession(session_id)

    return {
        "status": "initialized",
        "playlist_url": f"/api/video/hls/{session_id}/playlist.m3u8"
    }


@router.post("/api/video/hls/stream")
async def stream_to_hls(
    session_id: str = Form(...),
    text: str = Form(...),
    emotion: Optional[str] = Form(None),
    seed: Optional[int] = Form(None),
    buffer_chunks: Optional[int] = Form(4),
    quality: Optional[str] = Form("high")
):
    """
    Generate video and add segments to HLS playlist.

    Unlike stream-ndjson, this endpoint:
    1. Saves segments directly to disk
    2. Updates the HLS playlist as segments arrive
    3. Returns only when generation is complete

    Frontend uses hls.js to play from the playlist URL.
    """
    if session_id not in video_sessions:
        raise HTTPException(status_code=404, detail="Video session not found")

    # Initialize HLS session if not exists
    if session_id not in hls_sessions:
        hls_sessions[session_id] = HLSSession(session_id)

    hls = hls_sessions[session_id]
    session = video_sessions[session_id]
    remote_session_id = session.get("remote_session_id")

    if not remote_session_id:
        raise HTTPException(status_code=400, detail="No remote session found")

    float_url = get_float_url()
    segments_added = 0

    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            async with client.stream(
                "POST",
                f"{float_url}/stream-video-segments",
                data={
                    "session_id": remote_session_id,
                    "text": text,
                    "emotion": emotion or session["parameters"].get("emotion", "neutral"),
                    "seed": str(seed) if seed else "",
                    "buffer_chunks": str(buffer_chunks or 4),
                    "quality": quality or "high"
                }
            ) as response:
                if response.status_code != 200:
                    error = await response.aread()
                    raise HTTPException(status_code=response.status_code, detail=error.decode())

                import json
                import base64

                async for line in response.aiter_lines():
                    if not line:
                        continue

                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if data.get("error"):
                        print(f"[HLS] Error from FLOAT: {data['error']}")
                        continue

                    if data.get("segment"):
                        segment_data = base64.b64decode(data["segment"])
                        duration = data.get("duration", 4.0)

                        # Add to HLS playlist
                        filename = hls.add_segment(segment_data, duration)
                        segments_added += 1

                        # Broadcast progress
                        await broadcast({
                            "type": "hls_segment_ready",
                            "session_id": session_id,
                            "segment": filename,
                            "segment_index": len(hls.segments) - 1,
                            "duration": duration,
                            "is_last": data.get("is_last", False)
                        })

    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"FLOAT server error: {str(e)}")

    return {
        "status": "complete",
        "segments_added": segments_added,
        "total_segments": len(hls.segments),
        "playlist_url": f"/api/video/hls/{session_id}/playlist.m3u8"
    }


@router.post("/api/video/hls/complete/{session_id}")
async def complete_hls_session(session_id: str):
    """Mark HLS session as complete (adds EXT-X-ENDLIST to playlist)."""
    if session_id not in hls_sessions:
        raise HTTPException(status_code=404, detail="HLS session not found")

    hls_sessions[session_id].complete()

    return {"status": "complete", "segments": len(hls_sessions[session_id].segments)}


@router.delete("/api/video/hls/{session_id}")
async def cleanup_hls_session(session_id: str):
    """Clean up HLS session files."""
    if session_id in hls_sessions:
        hls_sessions[session_id].cleanup()
        del hls_sessions[session_id]

    return {"status": "cleaned"}
