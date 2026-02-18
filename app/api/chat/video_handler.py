"""
Video/HLS streaming: FLOAT session management, HLS segment streaming.

Extracted from routes_chat.py lines 481-767.
"""

import asyncio
import base64
import json
from typing import Optional
from datetime import datetime
from pathlib import Path
import uuid

from core.sentence_processor import TextBatch
from .connection_manager import ConnectionState


async def stream_batch_to_hls(state: ConnectionState, batch: TextBatch) -> dict:
    """
    Stream a text batch to HLS via FLOAT's streaming endpoint.

    This provides seamless video playback without gaps between chunks.
    Segments are added to the HLS playlist as they're generated.

    Args:
        state: Connection state with video session info
        batch: Text batch to process

    Returns:
        Dict with status and segments added
    """
    try:
        if not state.video_session_id:
            raise Exception("No video session ID - session not started?")

        from app.api.routes_video import (
            video_sessions, hls_sessions, HLSSession, get_float_url
        )
        from core.websocket_broadcast import broadcast
        import httpx

        session_id = state.video_session_id
        text = batch.text

        print(f"[video_handler][stream_hls] Streaming batch {batch.batch_index} to HLS: {text[:50]}...")

        # Validate session exists
        if session_id not in video_sessions:
            raise Exception(f"Session not found: {session_id}")

        session = video_sessions[session_id]
        if not session["active"]:
            raise Exception("Session not active")

        # Skip empty text
        if not text.strip():
            print(f"[video_handler][stream_hls] Text empty, skipping")
            return {"status": "skipped"}

        # Initialize HLS session if not exists
        if session_id not in hls_sessions:
            hls_sessions[session_id] = HLSSession(session_id)
            print(f"[video_handler][stream_hls] Initialized HLS session")

        hls = hls_sessions[session_id]
        remote_session_id = session.get("remote_session_id")

        if not remote_session_id:
            raise Exception("No remote session ID found")

        float_url = get_float_url()
        segments_added = 0

        # Ensure FLOAT is available (may have been swapped out for another GPU service)
        from core.gpu_manager import request_gpu
        gpu_success, gpu_error = await request_gpu("float")
        if not gpu_success:
            print(f"[video_handler][stream_hls] GPU request failed: {gpu_error}")
            return {"status": "gpu_unavailable", "error": gpu_error}

        # Stream to FLOAT and add segments as they arrive
        async with httpx.AsyncClient(timeout=300.0) as client:
            async with client.stream(
                "POST",
                f"{float_url}/stream-video-segments",
                data={
                    "session_id": remote_session_id,
                    "text": text,
                    "emotion": session["parameters"].get("emotion", "neutral"),
                    "buffer_chunks": "3",
                    "quality": state.video_quality
                }
            ) as response:
                if response.status_code != 200:
                    error = await response.aread()
                    raise Exception(f"FLOAT error: {error.decode()}")

                async for line in response.aiter_lines():
                    if not line:
                        continue

                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if data.get("error"):
                        print(f"[video_handler][stream_hls] Error from FLOAT: {data['error']}")
                        continue

                    if data.get("segment"):
                        segment_data = base64.b64decode(data["segment"])
                        duration = data.get("duration", 4.0)

                        # Add to HLS playlist
                        filename = hls.add_segment(segment_data, duration)
                        segments_added += 1

                        print(f"[video_handler][stream_hls] ✓ Segment {len(hls.segments)-1}: {duration:.1f}s")

                        # Broadcast progress to all clients
                        await broadcast({
                            "type": "hls_segment_ready",
                            "session_id": session_id,
                            "segment": filename,
                            "segment_index": len(hls.segments) - 1,
                            "duration": duration,
                            "is_last": data.get("is_last", False),
                            "playlist_url": f"/api/video/hls/{session_id}/playlist.m3u8"
                        })

        print(f"[video_handler][stream_hls] ✓ Batch complete: {segments_added} segments")
        return {"status": "complete", "segments_added": segments_added}

    except Exception as e:
        print(f"[video_handler][stream_hls] Error: {e}")
        import traceback
        traceback.print_exc()
        raise


async def queue_video_chunk(state: ConnectionState, batch: TextBatch) -> dict:
    """
    Queue a video chunk for FLOAT processing (LEGACY - use stream_batch_to_hls instead).

    Calls video queue logic directly to avoid HTTP self-call issues.

    Args:
        state: Connection state with video session info
        batch: Text batch to process

    Returns:
        Dict with chunk_id and status
    """
    try:
        if not state.video_session_id:
            raise Exception("No video session ID - session not started?")

        from app.api.routes_video import video_sessions, video_queues, process_queue

        session_id = state.video_session_id
        chunk_index = state.video_chunk_index
        text = batch.text

        print(f"[video_handler][queue_video_chunk] Queueing chunk {chunk_index} for session {session_id}")
        state.video_chunk_index += 1

        # Validate session exists
        if session_id not in video_sessions:
            raise Exception(f"Session not found: {session_id}")

        if not video_sessions[session_id]["active"]:
            raise Exception("Session not active")

        # Skip empty text
        if not text.strip():
            print(f"[video_handler][queue_video_chunk] Text empty, skipping")
            return {"chunk_id": f"{session_id}_chunk_{chunk_index}", "status": "skipped"}

        # Create chunk job
        chunk_id = f"{session_id}_chunk_{chunk_index}"
        chunk_job = {
            "chunk_id": chunk_id,
            "chunk_index": chunk_index,
            "text": text,
            "status": "queued",
            "video_path": None,
            "created_at": datetime.now().isoformat(),
            "tts_time": 0,
            "video_time": 0,
            "total_time": 0
        }

        video_queues[session_id].append(chunk_job)
        video_sessions[session_id]["chunks_submitted"] += 1

        print(f"[video_handler][queue_video_chunk] ✓ Chunk queued: {chunk_id}")
        print(f"[video_handler][queue_video_chunk] Queue length: {len(video_queues[session_id])}")

        # Check if processor needs to be started
        chunks_processing = sum(1 for c in video_queues[session_id] if c["status"] == "processing")
        if len(video_queues[session_id]) == 1 or chunks_processing == 0:
            print(f"[video_handler][queue_video_chunk] Starting video processor")
            asyncio.create_task(process_queue(session_id))
        else:
            print(f"[video_handler][queue_video_chunk] Processor already running ({chunks_processing} processing)")

        return {
            "chunk_id": chunk_id,
            "status": "queued",
            "position": len(video_queues[session_id])
        }

    except Exception as e:
        print(f"[video_handler][queue_video_chunk] Error: {e}")
        import traceback
        traceback.print_exc()
        raise


async def start_video_session_for_connection(state: ConnectionState) -> Optional[str]:
    """
    Start a video session for a connection.

    Uses the saved reference image. Returns session_id or None on failure.
    Calls video session logic directly to avoid HTTP self-call issues.
    """
    try:
        from core.gpu_manager import request_gpu
        from app.api.routes_video import (
            video_sessions, video_queues, create_remote_float_session,
            CONFIG_VIDEO_REFERENCE_IMAGE
        )
        from database.config_loader import get_config

        print(f"[video_handler][start_video_session] Requesting GPU for FLOAT...")

        # Request GPU for FLOAT service
        success, error = await request_gpu("float")
        if not success:
            print(f"[video_handler][start_video_session] GPU request failed: {error}")
            return None

        # Get saved reference image path
        saved_path = get_config(CONFIG_VIDEO_REFERENCE_IMAGE)
        if not saved_path or not Path(saved_path).exists():
            print(f"[video_handler][start_video_session] No saved reference image found")
            return None

        image_path = Path(saved_path)
        print(f"[video_handler][start_video_session] Using reference image: {image_path}")

        # Create remote FLOAT session
        print(f"[video_handler][start_video_session] Creating remote FLOAT session...")
        default_params = {
            "seed": 15,
            "a_cfg_scale": 2.0,
            "e_cfg_scale": 1.0,
            "r_cfg_scale": 1.0,
            "nfe": 10,
            "emotion": "neutral",
            "no_crop": False
        }
        remote_session_id = await create_remote_float_session(str(image_path), default_params)
        print(f"[video_handler][start_video_session] Remote FLOAT session: {remote_session_id}")

        # Create local session
        session_id = str(uuid.uuid4())

        video_sessions[session_id] = {
            "session_id": session_id,
            "remote_session_id": remote_session_id,
            "image_id": "saved",
            "image_path": str(image_path),
            "image_filename": image_path.name,
            "parameters": default_params,
            "created_at": datetime.now().isoformat(),
            "chunks_submitted": 0,
            "chunks_completed": 0,
            "chunks_failed": 0,
            "active": True,
            "current_chunk": None
        }

        video_queues[session_id] = []

        print(f"[video_handler][start_video_session] ✓ Session created: {session_id}")
        return session_id

    except Exception as e:
        print(f"[video_handler][start_video_session] Error: {e}")
        import traceback
        traceback.print_exc()
        return None
