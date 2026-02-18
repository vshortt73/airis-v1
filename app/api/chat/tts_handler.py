"""
TTS/audio processing: XTTS calls, background TTS/video processor.

Extracted from routes_chat.py lines 439-478 (call_xtts), 770-868 (tts_video_processor).
"""

import asyncio
import base64

import httpx
from fastapi import WebSocket

from app import config
from core.sentence_processor import SentenceProcessor, OutputMode
from .connection_manager import ConnectionState


async def call_xtts(text: str) -> bytes:
    """
    Call XTTS server directly to generate audio for text.

    Uses httpx (same as routes_tts.py) for consistent behavior.

    Args:
        text: Text to synthesize (should already be cleaned by SentenceProcessor)

    Returns:
        Audio bytes (MP3 format)
    """
    xtts_url = f"{config.XTTS_SERVER_URL}/speak_stream_mp3"

    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            response = await client.post(
                xtts_url,
                json={"text": text},
                headers={"Content-Type": "application/json"}
            )

            if response.status_code != 200:
                raise Exception(f"XTTS error {response.status_code}: {response.text[:100]}")

            audio_data = response.content
            content_type = response.headers.get('content-type', 'unknown')
            first_bytes = audio_data[:10].hex() if audio_data else 'empty'
            print(f"[tts_handler][call_xtts] ✓ Got {len(audio_data)} bytes ({content_type}), starts with: {first_bytes}")
            return audio_data

    except httpx.TimeoutException:
        print(f"[tts_handler][call_xtts] Timeout calling {xtts_url}")
        raise
    except Exception as e:
        print(f"[tts_handler][call_xtts] Error: {e}")
        raise


async def tts_video_processor(websocket: WebSocket, state: ConnectionState):
    """
    Background processor for TTS/video generation.

    Runs in parallel with text streaming, processing batches as they become available.
    Sends audio chunks or video notifications back to the client.
    """
    from .video_handler import stream_batch_to_hls

    print(f"[tts_handler][tts_processor] Started for mode: {state.output_mode.value}")
    sentence_index = 0

    # For VIDEO mode: Reset HLS session for new turn
    if state.output_mode == OutputMode.VIDEO and state.video_session_id:
        try:
            from app.api.routes_video import hls_sessions
            if state.video_session_id in hls_sessions:
                hls_sessions[state.video_session_id].reset_for_new_turn()
                print(f"[tts_handler][tts_processor] ✓ HLS session reset for new turn")
                # Tell browser to reload playlist for this turn
                await websocket.send_json({
                    "type": "hls_new_turn",
                    "session_id": state.video_session_id,
                    "playlist_url": f"/api/video/hls/{state.video_session_id}/playlist.m3u8"
                })
        except Exception as e:
            print(f"[tts_handler][tts_processor] HLS reset error: {e}")

    try:
        while True:
            # Check if we have batches to process
            if state.tts_queue:
                batch = state.tts_queue.pop(0)
                print(f"[tts_handler][tts_processor] Processing batch {batch.batch_index}: {batch.text[:50]}...")

                if state.output_mode == OutputMode.AUDIO:
                    # Generate audio via XTTS
                    try:
                        audio_bytes = await call_xtts(batch.text)
                        audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')

                        await websocket.send_json({
                            "type": "audio_chunk",
                            "audio": audio_b64,
                            "format": "mpeg",
                            "sentence_index": sentence_index,
                            "is_last": False
                        })
                        sentence_index += 1
                        print(f"[tts_handler][tts_processor] ✓ Audio chunk sent ({len(audio_bytes)} bytes)")
                    except Exception as e:
                        print(f"[tts_handler][tts_processor] ✗ TTS error: {e}")

                elif state.output_mode == OutputMode.VIDEO:
                    # Stream to HLS for seamless playback
                    try:
                        result = await stream_batch_to_hls(state, batch)
                        print(f"[tts_handler][tts_processor] ✓ HLS batch streamed: {result.get('segments_added', 0)} segments")
                    except Exception as e:
                        print(f"[tts_handler][tts_processor] ✗ HLS stream error: {e}")

            elif state.tts_queue_complete:
                # No more batches coming and queue is empty
                break
            else:
                # Wait for more batches
                await asyncio.sleep(0.05)

        # Send final message
        if state.output_mode == OutputMode.AUDIO:
            await websocket.send_json({
                "type": "audio_chunk",
                "is_last": True
            })
        elif state.output_mode == OutputMode.VIDEO:
            # Complete the HLS session
            try:
                from app.api.routes_video import hls_sessions
                if state.video_session_id and state.video_session_id in hls_sessions:
                    hls_sessions[state.video_session_id].complete()
                    print(f"[tts_handler][tts_processor] ✓ HLS session completed")
            except Exception as e:
                print(f"[tts_handler][tts_processor] HLS complete error: {e}")

            await websocket.send_json({
                "type": "hls_stream_complete",
                "session_id": state.video_session_id,
                "playlist_url": f"/api/video/hls/{state.video_session_id}/playlist.m3u8"
            })

        print(f"[tts_handler][tts_processor] ✓ Completed")

    except asyncio.CancelledError:
        print(f"[tts_handler][tts_processor] Cancelled")
    except Exception as e:
        print(f"[tts_handler][tts_processor] Error: {e}")
        import traceback
        traceback.print_exc()


async def initialize_tts(state: ConnectionState, websocket: WebSocket) -> asyncio.Task:
    """
    Initialize TTS routing for a new response.

    Creates a SentenceProcessor, clears the TTS queue, and starts the background
    processor task.

    Returns:
        The background asyncio.Task running tts_video_processor
    """
    state.sentence_processor = SentenceProcessor()
    state.tts_queue = []
    state.tts_queue_complete = False
    task = asyncio.create_task(tts_video_processor(websocket, state))
    state.tts_task = task
    print(f"[tts_handler] ├─ SERVER-SIDE TTS ROUTING ({state.output_mode.value}) ─┤")
    return task


async def finalize_tts(state: ConnectionState, is_video_mode: bool = False):
    """
    Finalize TTS routing: flush remaining text and wait for processor to finish.

    Args:
        state: Connection state with TTS processor info
        is_video_mode: Whether output mode is VIDEO (affects sentence processor finalization)
    """
    if state.sentence_processor:
        final_batches = state.sentence_processor.finalize(is_video_mode)
        for batch in final_batches:
            state.tts_queue.append(batch)

    state.tts_queue_complete = True

    if state.tts_task:
        try:
            await asyncio.wait_for(state.tts_task, timeout=300.0)
        except asyncio.TimeoutError:
            print(f"[tts_handler] ⚠ TTS processor timed out after 300s")
            state.tts_task.cancel()
        except Exception as e:
            print(f"[tts_handler] ⚠ TTS processor error: {e}")

    print(f"[tts_handler] ├─ TTS ROUTING COMPLETE ─┤")
