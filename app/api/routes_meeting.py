"""
Meeting Recording & Transcription API
Handles audio chunk uploads, processing pipeline, and export downloads.

Endpoints:
  POST /api/meeting/upload-chunk  - Receive audio chunk from browser
  GET  /api/meeting/status/{id}   - Recording/processing status
  POST /api/meeting/process/{id}  - Trigger transcription pipeline
  GET  /api/meeting/export/{id}   - Download meeting document
"""

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, BackgroundTasks
from fastapi.responses import PlainTextResponse
from typing import Optional
import os
import sys
import json
import subprocess
import asyncio
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app import config
from core.node2_check import is_node2_service_enabled

router = APIRouter(prefix="/api/meeting", tags=["meeting"])


def _get_audio_base() -> Path:
    """Get base path for meeting audio storage."""
    base = getattr(config, 'MEETING_AUDIO_PATH', 'attachments/meetings')
    return PROJECT_ROOT / base


def _check_enabled():
    """Check if transcription feature is enabled."""
    if not is_node2_service_enabled("TRANSCRIBE_ENABLED"):
        raise HTTPException(status_code=503, detail="Meeting transcription is disabled")


# ============================================================================
# UPLOAD CHUNK - Receive audio from browser MediaRecorder
# ============================================================================

@router.post("/upload-chunk")
async def upload_chunk(
    file: UploadFile = File(...),
    meeting_id: int = Form(...),
    chunk_index: int = Form(...)
):
    """
    Receive an audio chunk from the browser's MediaRecorder.
    Chunks are stored as individual files for resilience.
    """
    import psycopg2

    # Verify meeting exists and is recording
    password = os.environ.get('IRIS_DB_PASSWORD') or getattr(config, 'DB_PASSWORD', '')
    conn = psycopg2.connect(
        host=config.DB_HOST, port=config.DB_PORT,
        database=config.DB_NAME, user=config.DB_USER,
        password=password
    )
    cursor = conn.cursor()

    cursor.execute(
        "SELECT status FROM meeting_transcripts WHERE id = %s",
        (meeting_id,)
    )
    row = cursor.fetchone()
    if not row:
        cursor.close()
        conn.close()
        raise HTTPException(status_code=404, detail=f"Meeting #{meeting_id} not found")
    if row[0] != 'recording':
        cursor.close()
        conn.close()
        raise HTTPException(status_code=400, detail=f"Meeting #{meeting_id} is not recording (status: {row[0]})")

    # Save chunk to disk
    chunk_dir = _get_audio_base() / str(meeting_id)
    chunk_dir.mkdir(parents=True, exist_ok=True)

    # Determine extension from content type
    ext = ".webm"
    if file.content_type and "ogg" in file.content_type:
        ext = ".ogg"

    chunk_path = chunk_dir / f"chunk_{chunk_index:04d}{ext}"
    content = await file.read()
    with open(chunk_path, "wb") as f:
        f.write(content)

    # Update chunk count (use greatest to handle re-uploads)
    cursor.execute("""
        UPDATE meeting_transcripts
        SET audio_chunks = GREATEST(audio_chunks, %s + 1)
        WHERE id = %s
    """, (chunk_index, meeting_id))
    conn.commit()

    cursor.close()
    conn.close()

    print(f"[meeting] Chunk {chunk_index} saved for meeting #{meeting_id} ({len(content)} bytes)")

    return {
        "success": True,
        "meeting_id": meeting_id,
        "chunk_index": chunk_index,
        "size_bytes": len(content)
    }


# ============================================================================
# STATUS - Check meeting progress
# ============================================================================

@router.get("/status/{meeting_id}")
async def meeting_status(meeting_id: int):
    """Get recording/processing status for a meeting."""
    import psycopg2

    password = os.environ.get('IRIS_DB_PASSWORD') or getattr(config, 'DB_PASSWORD', '')
    conn = psycopg2.connect(
        host=config.DB_HOST, port=config.DB_PORT,
        database=config.DB_NAME, user=config.DB_USER,
        password=password
    )
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, title, status, audio_chunks, duration_seconds,
               speaker_count, processing_started_at, processing_ended_at
        FROM meeting_transcripts WHERE id = %s
    """, (meeting_id,))
    row = cursor.fetchone()

    cursor.close()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail=f"Meeting #{meeting_id} not found")

    return {
        "meeting_id": row[0],
        "title": row[1],
        "status": row[2],
        "audio_chunks": row[3] or 0,
        "duration_seconds": row[4],
        "speaker_count": row[5],
        "processing_started_at": row[6].isoformat() if row[6] else None,
        "processing_ended_at": row[7].isoformat() if row[7] else None
    }


# ============================================================================
# PROCESS - Trigger transcription pipeline (background task)
# ============================================================================

@router.post("/process/{meeting_id}")
async def process_meeting(meeting_id: int, background_tasks: BackgroundTasks):
    """
    Trigger the transcription pipeline for a meeting.
    Called by the MCP stop action. Runs in the background.

    Pipeline:
    1. Stitch audio chunks with ffmpeg
    2. Request GPU (swap to transcribe service)
    3. Upload to WhisperX on Node2
    4. Store diarized segments in DB
    """
    _check_enabled()

    import psycopg2
    password = os.environ.get('IRIS_DB_PASSWORD') or getattr(config, 'DB_PASSWORD', '')
    conn = psycopg2.connect(
        host=config.DB_HOST, port=config.DB_PORT,
        database=config.DB_NAME, user=config.DB_USER,
        password=password
    )
    cursor = conn.cursor()

    cursor.execute(
        "SELECT status, audio_chunks FROM meeting_transcripts WHERE id = %s",
        (meeting_id,)
    )
    row = cursor.fetchone()

    if not row:
        cursor.close()
        conn.close()
        raise HTTPException(status_code=404, detail=f"Meeting #{meeting_id} not found")
    if row[0] not in ('processing', 'recording'):
        cursor.close()
        conn.close()
        raise HTTPException(status_code=400, detail=f"Meeting #{meeting_id} status is '{row[0]}', expected 'processing' or 'recording'")
    if (row[1] or 0) == 0:
        cursor.close()
        conn.close()
        raise HTTPException(status_code=400, detail=f"Meeting #{meeting_id} has no audio chunks")

    # If still recording, update to processing (browser-initiated stop)
    if row[0] == 'recording':
        cursor.execute(
            "UPDATE meeting_transcripts SET status = 'processing', ended_at = NOW() WHERE id = %s",
            (meeting_id,)
        )
        conn.commit()

    cursor.close()
    conn.close()

    # Run pipeline in background
    background_tasks.add_task(_run_transcription_pipeline, meeting_id)

    return {"success": True, "message": f"Processing started for meeting #{meeting_id}"}


async def _run_transcription_pipeline(meeting_id: int):
    """
    Background task: stitch audio, transcribe on Node2, store segments.
    """
    import psycopg2
    import httpx

    password = os.environ.get('IRIS_DB_PASSWORD') or getattr(config, 'DB_PASSWORD', '')

    def get_conn():
        return psycopg2.connect(
            host=config.DB_HOST, port=config.DB_PORT,
            database=config.DB_NAME, user=config.DB_USER,
            password=password
        )

    try:
        # Mark processing started
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE meeting_transcripts
            SET processing_started_at = NOW()
            WHERE id = %s
        """, (meeting_id,))
        conn.commit()
        cursor.close()
        conn.close()

        print(f"[meeting] Starting transcription pipeline for meeting #{meeting_id}")

        # Step 1: Stitch audio chunks with ffmpeg
        chunk_dir = _get_audio_base() / str(meeting_id)
        chunks = sorted(chunk_dir.glob("chunk_*"))

        if not chunks:
            raise Exception("No audio chunks found")

        stitched_path = chunk_dir / "stitched.webm"

        if len(chunks) == 1:
            # Single chunk — just use it directly
            stitched_path = chunks[0]
            print(f"[meeting] Single chunk, using directly: {stitched_path}")
        else:
            # Multiple chunks — concat with ffmpeg
            concat_file = chunk_dir / "concat.txt"
            with open(concat_file, "w") as f:
                for chunk in chunks:
                    f.write(f"file '{chunk.name}'\n")

            print(f"[meeting] Stitching {len(chunks)} chunks with ffmpeg...")
            result = await asyncio.to_thread(
                subprocess.run,
                [
                    "ffmpeg", "-y",
                    "-f", "concat", "-safe", "0",
                    "-i", str(concat_file),
                    "-c", "copy",
                    str(stitched_path)
                ],
                capture_output=True, timeout=120
            )
            if result.returncode != 0:
                stderr = result.stderr.decode() if result.stderr else ""
                raise Exception(f"ffmpeg concat failed: {stderr[:500]}")
            print(f"[meeting] Stitched audio: {stitched_path}")

        # Step 2: Request GPU for transcription
        from core.gpu_manager import request_gpu
        print(f"[meeting] Requesting GPU for transcribe service...")
        success, error = await request_gpu("transcribe")
        if not success:
            raise Exception(f"GPU request failed: {error}")

        # Step 3: Upload to WhisperX service on Node2
        transcribe_url = getattr(config, 'TRANSCRIBE_SERVER_URL', 'http://node2:8500')
        print(f"[meeting] Uploading audio to {transcribe_url}/transcribe...")

        async with httpx.AsyncClient(timeout=600.0) as client:
            with open(stitched_path, "rb") as audio_file:
                files = {"file": (stitched_path.name, audio_file, "audio/webm")}
                response = await client.post(f"{transcribe_url}/transcribe", files=files)

        if response.status_code != 200:
            raise Exception(f"Transcription failed (HTTP {response.status_code}): {response.text[:500]}")

        result = response.json()
        segments = result.get("segments", [])
        speaker_count = result.get("speaker_count", 0)
        duration = result.get("duration", 0)

        print(f"[meeting] Transcription complete: {len(segments)} segments, {speaker_count} speakers, {duration:.0f}s")

        # Step 4: Store segments in DB
        conn = get_conn()
        cursor = conn.cursor()

        # Clear any existing segments (in case of re-processing)
        cursor.execute("DELETE FROM meeting_segments WHERE transcript_id = %s", (meeting_id,))

        for i, seg in enumerate(segments):
            cursor.execute("""
                INSERT INTO meeting_segments
                    (transcript_id, speaker_label, start_time, end_time, text,
                     confidence, words, segment_order)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                meeting_id,
                seg.get("speaker", "Speaker 0"),
                seg.get("start", 0),
                seg.get("end", 0),
                seg.get("text", ""),
                seg.get("confidence"),
                json.dumps(seg.get("words", [])),
                i
            ))

        # Update meeting record
        cursor.execute("""
            UPDATE meeting_transcripts SET
                status = 'completed',
                processing_ended_at = NOW(),
                speaker_count = %s,
                duration_seconds = %s,
                whisperx_model = %s
            WHERE id = %s
        """, (speaker_count, int(duration), result.get("model", "large-v3"), meeting_id))

        conn.commit()
        cursor.close()
        conn.close()

        print(f"[meeting] Meeting #{meeting_id} transcription stored successfully")

        # Notify UI with download links
        try:
            from core.ui_notify import ui_msg, PROTOCOL, ACTIVE_PORT
            base = f"{PROTOCOL}://localhost:{ACTIVE_PORT}"
            export_url = f"{base}/api/meeting/export/{meeting_id}?format=transcript"
            ui_msg(
                f"Meeting transcription complete ({len(segments)} segments, {speaker_count} speakers). "
                f"Download: {export_url}",
                "success"
            )
        except Exception:
            pass

    except Exception as e:
        print(f"[meeting] Transcription pipeline failed for meeting #{meeting_id}: {e}")
        import traceback
        traceback.print_exc()

        # Mark as failed
        try:
            conn = get_conn()
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE meeting_transcripts
                SET status = 'failed', processing_ended_at = NOW()
                WHERE id = %s
            """, (meeting_id,))
            conn.commit()
            cursor.close()
            conn.close()
        except Exception:
            pass

        try:
            from core.ui_notify import ui_msg
            ui_msg(f"Meeting transcription failed: {e}", "error")
        except Exception:
            pass


# ============================================================================
# EXPORT - Download meeting document
# ============================================================================

@router.get("/export/{meeting_id}")
async def export_meeting(meeting_id: int, format: str = "summary"):
    """
    Generate and download a meeting document.

    Formats:
    - summary: Title, date, attendees, AI summary, action items
    - notes: Summary + key quotes organized by topic
    - transcript: Full diarized transcript with timestamps
    """
    import psycopg2

    if format not in ("summary", "notes", "transcript"):
        format = "summary"

    password = os.environ.get('IRIS_DB_PASSWORD') or getattr(config, 'DB_PASSWORD', '')
    conn = psycopg2.connect(
        host=config.DB_HOST, port=config.DB_PORT,
        database=config.DB_NAME, user=config.DB_USER,
        password=password
    )
    cursor = conn.cursor()

    # Get meeting info
    cursor.execute("""
        SELECT id, title, status, meeting_type, duration_seconds,
               speaker_count, started_at, ended_at,
               summary, action_items, participant_names
        FROM meeting_transcripts WHERE id = %s
    """, (meeting_id,))
    meeting = cursor.fetchone()

    if not meeting:
        cursor.close()
        conn.close()
        raise HTTPException(status_code=404, detail=f"Meeting #{meeting_id} not found")

    if meeting[2] != 'completed':
        cursor.close()
        conn.close()
        raise HTTPException(status_code=400, detail=f"Meeting not yet transcribed (status: {meeting[2]})")

    # Get segments
    cursor.execute("""
        SELECT speaker_label, start_time, end_time, text
        FROM meeting_segments
        WHERE transcript_id = %s
        ORDER BY segment_order
    """, (meeting_id,))
    segments = cursor.fetchall()

    cursor.close()
    conn.close()

    # Parse participant names
    participant_names = meeting[10] or {}
    if isinstance(participant_names, str):
        participant_names = json.loads(participant_names)

    action_items = meeting[9] or []
    if isinstance(action_items, str):
        action_items = json.loads(action_items)

    # Format duration
    duration_secs = meeting[4] or 0
    hours = duration_secs // 3600
    minutes = (duration_secs % 3600) // 60
    if hours > 0:
        duration_str = f"{hours}h {minutes}m"
    else:
        duration_str = f"{minutes}m"

    # Build header
    from zoneinfo import ZoneInfo
    tz_name = getattr(config, 'CALENDAR_TIMEZONE', 'America/New_York')
    tz = ZoneInfo(tz_name)
    started = meeting[6].astimezone(tz) if meeting[6] else None

    lines = []
    lines.append(f"# {meeting[1]}")
    lines.append("")
    lines.append(f"**Date:** {started.strftime('%A, %B %d, %Y at %I:%M %p') if started else 'Unknown'}")
    lines.append(f"**Duration:** {duration_str}")
    lines.append(f"**Type:** {meeting[3]}")
    lines.append(f"**Speakers:** {meeting[5] or 'Unknown'}")

    if participant_names:
        attendees = ", ".join(participant_names.values())
        lines.append(f"**Attendees:** {attendees}")

    lines.append("")
    lines.append("---")
    lines.append("")

    if format == "summary":
        # Summary format: overview + action items
        if meeting[8]:
            lines.append("## Summary")
            lines.append("")
            lines.append(meeting[8])
            lines.append("")

        if action_items:
            lines.append("## Action Items")
            lines.append("")
            for item in action_items:
                if isinstance(item, dict):
                    lines.append(f"- [ ] {item.get('task', item)}")
                else:
                    lines.append(f"- [ ] {item}")
            lines.append("")
        elif not meeting[8]:
            lines.append("*No summary generated yet. Use meeting(action='summarize') to generate one.*")
            lines.append("")

    elif format == "notes":
        # Notes format: summary + key quotes
        if meeting[8]:
            lines.append("## Summary")
            lines.append("")
            lines.append(meeting[8])
            lines.append("")

        if action_items:
            lines.append("## Action Items")
            lines.append("")
            for item in action_items:
                if isinstance(item, dict):
                    lines.append(f"- [ ] {item.get('task', item)}")
                else:
                    lines.append(f"- [ ] {item}")
            lines.append("")

        # Add key segments (longer statements likely contain more substance)
        lines.append("## Key Discussion Points")
        lines.append("")
        for seg in segments:
            text = seg[3].strip()
            if len(text) > 80:  # Only include substantive statements
                speaker = participant_names.get(seg[0], seg[0])
                timestamp = _format_ts(seg[1])
                lines.append(f"> [{timestamp}] **{speaker}:** {text}")
                lines.append("")

    elif format == "transcript":
        # Full transcript
        lines.append("## Full Transcript")
        lines.append("")
        for seg in segments:
            speaker = participant_names.get(seg[0], seg[0])
            start_ts = _format_ts(seg[1])
            end_ts = _format_ts(seg[2])
            lines.append(f"**[{start_ts} - {end_ts}] {speaker}:**")
            lines.append(seg[3].strip())
            lines.append("")

    # Footer
    lines.append("---")
    lines.append(f"*Generated by Iris Meeting Transcription System*")

    content = "\n".join(lines)
    filename = f"Meeting - {meeting[1]} - {format}.txt"
    # Sanitize filename
    filename = "".join(c for c in filename if c.isalnum() or c in " -_.").strip()

    return PlainTextResponse(
        content=content,
        media_type="text/plain",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )


def _format_ts(seconds: float) -> str:
    """Format seconds as MM:SS or HH:MM:SS"""
    if seconds is None:
        return "00:00"
    s = int(seconds)
    hours = s // 3600
    minutes = (s % 3600) // 60
    secs = s % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"
