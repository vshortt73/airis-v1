"""
Meeting Transcription MCP Server - Record, transcribe, and manage meetings

Provides a unified 'meeting' tool with actions:
- start: Begin recording a meeting
- stop: End recording and trigger transcription
- status: Check recording/processing progress
- list: View recent meetings
- get: Full transcript with speaker segments
- summarize: Generate AI summary + action items
- speakers: Map speaker labels to real names
- export: Generate downloadable document

!! CLAUDE: DATABASE SYNC REQUIRED !!
When adding or modifying tool parameters:
1. Update the Python function signature (this file)
2. UPDATE THE DATABASE: mcp_tools.input_schema must include new parameters
   - The model ONLY sees parameters defined in the database schema
   - Python parameters are invisible to the model without DB update
3. Create/update SQL in: database/sql/
4. Remind user to run the SQL and restart Iris
"""

import sys
import json
import psycopg2
from psycopg2.extras import DictCursor
from pathlib import Path
from typing import Dict, Any, Optional
import os
from datetime import datetime
from zoneinfo import ZoneInfo

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from app import config
from mcp_servers.base.base_server import IrisMCPServer

# ============================================================================
# SERVER INITIALIZATION
# ============================================================================

server = IrisMCPServer(
    name="Iris Meeting Server",
    description="Meeting recording, transcription, and management"
)


def get_db_connection():
    """Create database connection"""
    password = os.environ.get('AIRIS_DB_PASSWORD') or getattr(config, 'DB_PASSWORD', None)

    conn_params = {
        'host': config.DB_HOST,
        'port': config.DB_PORT,
        'database': config.DB_NAME,
        'user': config.DB_USER,
    }

    if password:
        conn_params['password'] = password

    return psycopg2.connect(**conn_params)


def get_timezone() -> ZoneInfo:
    """Get configured timezone"""
    tz_name = getattr(config, 'CALENDAR_TIMEZONE', 'America/New_York')
    return ZoneInfo(tz_name)


def _base_url() -> str:
    """Build the base URL for download links (respects SSL config)."""
    ssl_dir = PROJECT_ROOT / "ssl"
    if (ssl_dir / "cert.pem").exists() and (ssl_dir / "key.pem").exists():
        return f"https://localhost:8443"
    return f"http://localhost:{getattr(config, 'PORT', 8000)}"


def _resolve_meeting_id(meeting_id: Optional[int], require_completed: bool = False):
    """
    If meeting_id is provided, return it. Otherwise look up the most recent meeting.
    When require_completed=True, returns the most recent completed meeting.
    Returns (meeting_id, error_msg). error_msg is None on success.
    """
    if meeting_id:
        return meeting_id, None

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if require_completed:
            cursor.execute("""
                SELECT id, title FROM meeting_transcripts
                WHERE status = 'completed'
                ORDER BY started_at DESC LIMIT 1
            """)
        else:
            cursor.execute("""
                SELECT id, title FROM meeting_transcripts
                ORDER BY started_at DESC LIMIT 1
            """)
        row = cursor.fetchone()
        cursor.close()
        conn.close()

        if not row:
            return None, "No meetings found."
        return row[0], None
    except Exception as e:
        return None, f"Error finding meeting: {e}"


def format_duration(seconds: int) -> str:
    """Format seconds as human-readable duration"""
    if seconds is None:
        return "unknown"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours}h {minutes}m"
    elif minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def format_timestamp(seconds: float) -> str:
    """Format seconds as MM:SS or HH:MM:SS timestamp"""
    if seconds is None:
        return "00:00"
    hours = int(seconds) // 3600
    minutes = (int(seconds) % 3600) // 60
    secs = int(seconds) % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


# ============================================================================
# MEETING TOOL - Main entry point with subcommands
# ============================================================================

@server.register_tool
def meeting(
    action: str,
    meeting_title: str = None,
    meeting_type: str = "conference",
    meeting_id: int = None,
    calendar_event_id: int = None,
    speaker_map: str = None,
    query: str = None,
    format: str = "summary",
    limit: int = 10
) -> Dict[str, Any]:
    """
    Meeting recording and transcription management.

    Actions:
    - start: Begin recording a meeting (requires meeting_title)
    - stop: End recording and process audio (requires meeting_id)
    - status: Check recording/processing progress (meeting_id optional — defaults to latest)
    - list: View recent meetings (optional query, limit)
    - get: Full transcript with speaker segments (meeting_id optional — defaults to latest completed)
    - summarize: Generate AI summary + action items (requires meeting_id)
    - speakers: Map speaker labels to real names (requires meeting_id, speaker_map)
    - export: Generate downloadable document (meeting_id optional — defaults to latest completed, optional format: summary/notes/transcript)
    """

    if action == "start":
        return _start_meeting(meeting_title, meeting_type, calendar_event_id)
    elif action == "stop":
        return _stop_meeting(meeting_id)
    elif action == "status":
        return _meeting_status(meeting_id)
    elif action == "list":
        return _list_meetings(query, limit)
    elif action == "get":
        return _get_transcript(meeting_id)
    elif action == "summarize":
        return _summarize_meeting(meeting_id)
    elif action == "speakers":
        return _map_speakers(meeting_id, speaker_map)
    elif action == "export":
        return _export_meeting(meeting_id, format)
    else:
        return {"success": False, "error": f"Unknown action: {action}. Use: start, stop, status, list, get, summarize, speakers, export"}


# ============================================================================
# START - Begin recording a meeting
# ============================================================================

def _start_meeting(
    title: str = None,
    meeting_type: str = "conference",
    calendar_event_id: int = None
) -> Dict[str, Any]:
    """
    Create a new meeting record and return the meeting ID for the browser recorder.

    Calendar event linkage logic:
    1. If calendar_event_id provided → use it directly
    2. Otherwise, look for a calendar event within ±15 minutes of now
       a. Found, no existing transcript → link to it
       b. Found, already has a transcript → return a prompt asking user: append or standalone?
       c. Not found → auto-create a calendar event
    """

    if not title:
        return {"success": False, "error": "Meeting needs a title. Call meeting(action='start', meeting_title='Your Meeting Name') with the meeting_title parameter."}

    if meeting_type not in ("conference", "teams", "phone"):
        meeting_type = "conference"

    audio_base = getattr(config, 'MEETING_AUDIO_PATH', 'attachments/meetings')

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        tz = get_timezone()
        now = datetime.now(tz)
        calendar_event_msg = ""

        if not calendar_event_id:
            # Look for a calendar event within ±15 minutes of now
            from datetime import timedelta
            window_start = now - timedelta(minutes=15)
            window_end = now + timedelta(minutes=15)

            cursor.execute("""
                SELECT id, title, start_time
                FROM calendar_events
                WHERE status = 'active'
                  AND start_time >= %s
                  AND start_time <= %s
                ORDER BY ABS(EXTRACT(EPOCH FROM (start_time - %s)))
                LIMIT 1
            """, (window_start, window_end, now))
            nearby_event = cursor.fetchone()

            if nearby_event:
                event_id, event_title, event_start = nearby_event

                # Check if this event already has a transcript
                cursor.execute("""
                    SELECT id, title, status
                    FROM meeting_transcripts
                    WHERE calendar_event_id = %s
                    ORDER BY id DESC LIMIT 1
                """, (event_id,))
                existing_transcript = cursor.fetchone()

                if existing_transcript:
                    # Already has a transcript — ask the user what to do
                    cursor.close()
                    conn.close()
                    return {
                        "success": False,
                        "needs_decision": True,
                        "message": (
                            f"Found calendar event '#{event_id} {event_title}' near the current time, "
                            f"but it already has a transcript (meeting #{existing_transcript[0]} '{existing_transcript[1]}', "
                            f"status: {existing_transcript[2]}). "
                            f"Should I link this new recording to the same event (e.g. continuing the meeting), "
                            f"or create a standalone recording? "
                            f"To link: meeting(action='start', meeting_title='{title}', calendar_event_id={event_id}). "
                            f"To create standalone: meeting(action='start', meeting_title='{title}', calendar_event_id=0)."
                        ),
                        "existing_event_id": event_id,
                        "existing_event_title": event_title,
                        "existing_transcript_id": existing_transcript[0]
                    }
                else:
                    # Event exists, no transcript yet — link to it
                    calendar_event_id = event_id
                    calendar_event_msg = f" Linked to calendar event '#{event_id} {event_title}'."
            else:
                # No nearby event — create one
                cursor.execute("""
                    INSERT INTO calendar_events (title, description, start_time, category, source)
                    VALUES (%s, %s, %s, 'meeting', 'conversation')
                    RETURNING id
                """, (title, f"Meeting recording ({meeting_type})", now))
                calendar_event_id = cursor.fetchone()[0]
                conn.commit()
                calendar_event_msg = f" Calendar event #{calendar_event_id} created."

        elif calendar_event_id == 0:
            # Explicit standalone — create a new calendar event, don't link to existing
            cursor.execute("""
                INSERT INTO calendar_events (title, description, start_time, category, source)
                VALUES (%s, %s, %s, 'meeting', 'conversation')
                RETURNING id
            """, (title, f"Standalone meeting recording ({meeting_type})", now))
            calendar_event_id = cursor.fetchone()[0]
            conn.commit()
            calendar_event_msg = f" New calendar event #{calendar_event_id} created (standalone)."

        cursor.execute("""
            INSERT INTO meeting_transcripts (title, meeting_type, status, calendar_event_id)
            VALUES (%s, %s, 'recording', %s)
            RETURNING id, started_at
        """, (title, meeting_type, calendar_event_id))

        meeting_id, started_at = cursor.fetchone()
        conn.commit()

        # Create audio storage directory
        audio_dir = Path(PROJECT_ROOT) / audio_base / str(meeting_id)
        audio_dir.mkdir(parents=True, exist_ok=True)

        # Update audio_path in DB
        cursor.execute("""
            UPDATE meeting_transcripts SET audio_path = %s WHERE id = %s
        """, (str(audio_dir), meeting_id))
        conn.commit()

        cursor.close()
        conn.close()

        return {
            "success": True,
            "message": f"Meeting '#{meeting_id} {title}' started.{calendar_event_msg} Recording is active — audio chunks will be uploaded by the browser.",
            "meeting_id": meeting_id,
            "title": title,
            "meeting_type": meeting_type,
            "calendar_event_id": calendar_event_id,
            "started_at": started_at.isoformat() if started_at else None,
            "instructions": "The browser will now record audio and upload chunks to /api/meeting/upload-chunk. Say 'stop the meeting' when done."
        }

    except Exception as e:
        return {"success": False, "error": f"Error starting meeting: {e}"}


# ============================================================================
# STOP - End recording and trigger processing
# ============================================================================

def _stop_meeting(meeting_id: int = None) -> Dict[str, Any]:
    """Stop recording and trigger async transcription processing."""

    if not meeting_id:
        return {"success": False, "error": "Which meeting? Provide meeting_id."}

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Verify meeting exists and is recording
        cursor.execute("""
            SELECT id, title, status, audio_chunks, started_at
            FROM meeting_transcripts WHERE id = %s
        """, (meeting_id,))
        row = cursor.fetchone()

        if not row:
            cursor.close()
            conn.close()
            return {"success": False, "error": f"Meeting #{meeting_id} not found."}

        if row[2] != 'recording':
            cursor.close()
            conn.close()
            return {"success": False, "error": f"Meeting #{meeting_id} is not recording (status: {row[2]})."}

        chunk_count = row[3] or 0
        if chunk_count == 0:
            cursor.close()
            conn.close()
            return {"success": False, "error": f"Meeting #{meeting_id} has no audio chunks uploaded yet."}

        # Mark as processing
        cursor.execute("""
            UPDATE meeting_transcripts
            SET status = 'processing', ended_at = NOW()
            WHERE id = %s
            RETURNING ended_at
        """, (meeting_id,))
        ended_at = cursor.fetchone()[0]
        conn.commit()

        # Calculate duration
        started_at = row[4]
        if started_at and ended_at:
            duration = int((ended_at - started_at).total_seconds())
            cursor.execute("""
                UPDATE meeting_transcripts SET duration_seconds = %s WHERE id = %s
            """, (duration, meeting_id))
            conn.commit()
        else:
            duration = None

        cursor.close()
        conn.close()

        return {
            "success": True,
            "message": f"Meeting '#{meeting_id} {row[1]}' stopped. {chunk_count} audio chunk(s) recorded ({format_duration(duration)}). Transcription processing has been triggered — use meeting(action='status', meeting_id={meeting_id}) to check progress.",
            "meeting_id": meeting_id,
            "title": row[1],
            "chunks": chunk_count,
            "duration": format_duration(duration),
            "next_step": f"Processing will stitch audio, transcribe with WhisperX, and diarize speakers. This runs in the background."
        }

    except Exception as e:
        return {"success": False, "error": f"Error stopping meeting: {e}"}


# ============================================================================
# STATUS - Check meeting progress
# ============================================================================

def _meeting_status(meeting_id: int = None) -> Dict[str, Any]:
    """Check the status of a meeting recording or transcription. Defaults to most recent meeting."""

    meeting_id, err = _resolve_meeting_id(meeting_id, require_completed=False)
    if err:
        return {"success": False, "error": err}

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, title, status, audio_chunks, duration_seconds,
                   speaker_count, started_at, ended_at,
                   processing_started_at, processing_ended_at,
                   meeting_type
            FROM meeting_transcripts WHERE id = %s
        """, (meeting_id,))
        row = cursor.fetchone()

        if not row:
            cursor.close()
            conn.close()
            return {"success": False, "error": f"Meeting #{meeting_id} not found."}

        # Count segments if completed
        segment_count = 0
        if row[2] == 'completed':
            cursor.execute("SELECT COUNT(*) FROM meeting_segments WHERE transcript_id = %s", (meeting_id,))
            segment_count = cursor.fetchone()[0]

        cursor.close()
        conn.close()

        status_info = {
            "success": True,
            "meeting_id": row[0],
            "title": row[1],
            "status": row[2],
            "meeting_type": row[10],
            "audio_chunks": row[3] or 0,
            "duration": format_duration(row[4]),
            "speaker_count": row[5],
            "started_at": row[6].isoformat() if row[6] else None,
            "ended_at": row[7].isoformat() if row[7] else None,
        }

        if row[2] == 'processing':
            status_info["message"] = f"Meeting #{meeting_id} is being transcribed. Please wait..."
            if row[8]:
                status_info["processing_started_at"] = row[8].isoformat()
        elif row[2] == 'completed':
            base = _base_url()
            status_info["message"] = f"Meeting #{meeting_id} transcription complete. {segment_count} segments, {row[5] or '?'} speakers."
            status_info["segment_count"] = segment_count
            status_info["download_links"] = {
                "transcript": f"{base}/api/meeting/export/{meeting_id}?format=transcript",
                "summary": f"{base}/api/meeting/export/{meeting_id}?format=summary",
                "notes": f"{base}/api/meeting/export/{meeting_id}?format=notes",
            }
        elif row[2] == 'recording':
            status_info["message"] = f"Meeting #{meeting_id} is recording. {row[3] or 0} chunks uploaded."
        elif row[2] == 'failed':
            status_info["message"] = f"Meeting #{meeting_id} transcription failed. Check server logs."

        return status_info

    except Exception as e:
        return {"success": False, "error": f"Error checking status: {e}"}


# ============================================================================
# LIST - Recent meetings
# ============================================================================

def _list_meetings(query: str = None, limit: int = 10) -> Dict[str, Any]:
    """List recent meetings, optionally filtered by search term."""

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        if query:
            cursor.execute("""
                SELECT id, title, status, meeting_type, duration_seconds,
                       speaker_count, started_at
                FROM meeting_transcripts
                WHERE title ILIKE %s OR
                      summary ILIKE %s
                ORDER BY started_at DESC
                LIMIT %s
            """, (f"%{query}%", f"%{query}%", limit))
        else:
            cursor.execute("""
                SELECT id, title, status, meeting_type, duration_seconds,
                       speaker_count, started_at
                FROM meeting_transcripts
                ORDER BY started_at DESC
                LIMIT %s
            """, (limit,))

        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        if not rows:
            msg = f"No meetings found matching '{query}'." if query else "No meetings recorded yet."
            return {"success": True, "message": msg, "meetings": [], "count": 0}

        meetings = []
        for row in rows:
            tz = get_timezone()
            started = row[6].astimezone(tz) if row[6] else None
            meetings.append({
                "id": row[0],
                "title": row[1],
                "status": row[2],
                "meeting_type": row[3],
                "duration": format_duration(row[4]),
                "speaker_count": row[5],
                "date": started.strftime('%A, %B %d at %I:%M %p') if started else "Unknown"
            })

        return {
            "success": True,
            "meetings": meetings,
            "count": len(meetings)
        }

    except Exception as e:
        return {"success": False, "error": f"Error listing meetings: {e}"}


# ============================================================================
# GET - Full transcript
# ============================================================================

def _get_transcript(meeting_id: int = None) -> Dict[str, Any]:
    """Get the full transcript with speaker segments. Defaults to most recent completed meeting."""

    meeting_id, err = _resolve_meeting_id(meeting_id, require_completed=True)
    if err:
        return {"success": False, "error": err}

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Get meeting info
        cursor.execute("""
            SELECT id, title, status, duration_seconds, speaker_count,
                   participant_names, started_at, summary
            FROM meeting_transcripts WHERE id = %s
        """, (meeting_id,))
        meeting = cursor.fetchone()

        if not meeting:
            cursor.close()
            conn.close()
            return {"success": False, "error": f"Meeting #{meeting_id} not found."}

        if meeting[2] != 'completed':
            cursor.close()
            conn.close()
            return {"success": False, "error": f"Meeting #{meeting_id} is not yet transcribed (status: {meeting[2]})."}

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

        # Map speaker labels to names if available
        participant_names = meeting[5] or {}
        if isinstance(participant_names, str):
            participant_names = json.loads(participant_names)

        # Build transcript text (token-conscious: structured but compact)
        transcript_lines = []
        for seg in segments:
            speaker = participant_names.get(seg[0], seg[0])
            timestamp = format_timestamp(seg[1])
            transcript_lines.append(f"[{timestamp}] {speaker}: {seg[3]}")

        transcript_text = "\n".join(transcript_lines)

        # Token budget check: truncate if transcript is very long
        # (the tool result budget in routes_chat.py will handle final truncation,
        # but we can be proactive for readability)
        max_chars = 40000  # ~10K tokens rough estimate
        truncated = False
        if len(transcript_text) > max_chars:
            transcript_text = transcript_text[:max_chars]
            truncated = True

        tz = get_timezone()
        started = meeting[6].astimezone(tz) if meeting[6] else None

        result = {
            "success": True,
            "meeting_id": meeting[0],
            "title": meeting[1],
            "date": started.strftime('%A, %B %d, %Y at %I:%M %p') if started else "Unknown",
            "duration": format_duration(meeting[3]),
            "speaker_count": meeting[4],
            "segment_count": len(segments),
            "transcript": transcript_text
        }

        if meeting[7]:
            result["summary"] = meeting[7]

        if truncated:
            result["note"] = "Transcript truncated for context window. Use meeting(action='export', meeting_id=...) for the full document."

        if participant_names:
            result["speakers"] = participant_names

        return result

    except Exception as e:
        return {"success": False, "error": f"Error getting transcript: {e}"}


# ============================================================================
# SUMMARIZE - Generate AI summary
# ============================================================================

def _summarize_meeting(meeting_id: int = None) -> Dict[str, Any]:
    """Generate a summary and action items for a meeting using the main LLM."""

    if not meeting_id:
        return {"success": False, "error": "Which meeting? Provide meeting_id."}

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Get meeting and segments
        cursor.execute("""
            SELECT id, title, status, participant_names, duration_seconds
            FROM meeting_transcripts WHERE id = %s
        """, (meeting_id,))
        meeting = cursor.fetchone()

        if not meeting:
            cursor.close()
            conn.close()
            return {"success": False, "error": f"Meeting #{meeting_id} not found."}

        if meeting[2] != 'completed':
            cursor.close()
            conn.close()
            return {"success": False, "error": f"Meeting #{meeting_id} not yet transcribed (status: {meeting[2]})."}

        # Get segments for summary
        cursor.execute("""
            SELECT speaker_label, text
            FROM meeting_segments
            WHERE transcript_id = %s
            ORDER BY segment_order
        """, (meeting_id,))
        segments = cursor.fetchall()

        participant_names = meeting[3] or {}
        if isinstance(participant_names, str):
            participant_names = json.loads(participant_names)

        # Build compact transcript for summarization
        transcript_lines = []
        for seg in segments:
            speaker = participant_names.get(seg[0], seg[0])
            transcript_lines.append(f"{speaker}: {seg[1]}")

        transcript_text = "\n".join(transcript_lines)

        # Truncate if too long for summarization prompt
        if len(transcript_text) > 30000:
            transcript_text = transcript_text[:30000] + "\n[... transcript truncated for summarization ...]"

        cursor.close()
        conn.close()

        # Return the transcript with instructions for the LLM to summarize
        # The MCP tool result goes back to the LLM which will generate the summary
        return {
            "success": True,
            "message": f"Here is the transcript for meeting '#{meeting_id} {meeting[1]}' ({format_duration(meeting[4])}). Please summarize it with key discussion points, decisions made, and action items.",
            "meeting_id": meeting_id,
            "title": meeting[1],
            "transcript_for_summary": transcript_text,
            "instructions": "Summarize this meeting transcript. Include: 1) Key discussion topics, 2) Decisions made, 3) Action items with owners if identifiable. After presenting the summary, save it with the database_query tool: UPDATE meeting_transcripts SET summary = '...' WHERE id = " + str(meeting_id)
        }

    except Exception as e:
        return {"success": False, "error": f"Error preparing summary: {e}"}


# ============================================================================
# SPEAKERS - Map speaker labels to names
# ============================================================================

def _map_speakers(meeting_id: int = None, speaker_map: str = None) -> Dict[str, Any]:
    """Map WhisperX speaker labels to real participant names."""

    if not meeting_id:
        return {"success": False, "error": "Which meeting? Provide meeting_id."}

    if not speaker_map:
        # Show current speakers so the user can map them
        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            cursor.execute("""
                SELECT speaker_label, COUNT(*) as segments,
                       MIN(text) as first_words,
                       MIN(segment_order) as first_order
                FROM meeting_segments
                WHERE transcript_id = %s
                GROUP BY speaker_label
                ORDER BY first_order
            """, (meeting_id,))
            speakers = cursor.fetchall()

            # Get existing names
            cursor.execute("""
                SELECT participant_names FROM meeting_transcripts WHERE id = %s
            """, (meeting_id,))
            existing = cursor.fetchone()
            existing_names = existing[0] if existing and existing[0] else {}
            if isinstance(existing_names, str):
                existing_names = json.loads(existing_names)

            cursor.close()
            conn.close()

            speaker_info = []
            for sp in speakers:
                name = existing_names.get(sp[0], "unmapped")
                # Show first few words to help identify the speaker
                preview = sp[2][:100] if sp[2] else ""
                speaker_info.append({
                    "label": sp[0],
                    "current_name": name,
                    "segment_count": sp[1],
                    "first_words": preview
                })

            return {
                "success": True,
                "message": f"Meeting #{meeting_id} has {len(speakers)} speakers. Provide speaker_map as JSON to assign names.",
                "speakers": speaker_info,
                "example": '{"Speaker 0": "Victor", "Speaker 1": "Sarah"}',
                "instructions": "Call meeting(action='speakers', meeting_id=" + str(meeting_id) + ", speaker_map='{...}') with the name mapping."
            }

        except Exception as e:
            return {"success": False, "error": f"Error listing speakers: {e}"}

    # Apply speaker name mapping
    try:
        name_map = json.loads(speaker_map)
    except json.JSONDecodeError as e:
        return {"success": False, "error": f"Invalid JSON in speaker_map: {e}. Example: {{\"Speaker 0\": \"Victor\"}}"}

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Merge with existing names
        cursor.execute("""
            SELECT participant_names FROM meeting_transcripts WHERE id = %s
        """, (meeting_id,))
        existing = cursor.fetchone()
        if not existing:
            cursor.close()
            conn.close()
            return {"success": False, "error": f"Meeting #{meeting_id} not found."}

        existing_names = existing[0] if existing[0] else {}
        if isinstance(existing_names, str):
            existing_names = json.loads(existing_names)

        existing_names.update(name_map)

        cursor.execute("""
            UPDATE meeting_transcripts
            SET participant_names = %s
            WHERE id = %s
        """, (json.dumps(existing_names), meeting_id))

        # Update speaker count
        cursor.execute("""
            SELECT COUNT(DISTINCT speaker_label) FROM meeting_segments WHERE transcript_id = %s
        """, (meeting_id,))
        speaker_count = cursor.fetchone()[0]
        cursor.execute("""
            UPDATE meeting_transcripts SET speaker_count = %s WHERE id = %s
        """, (speaker_count, meeting_id))

        conn.commit()
        cursor.close()
        conn.close()

        return {
            "success": True,
            "message": f"Speaker names updated for meeting #{meeting_id}.",
            "participant_names": existing_names
        }

    except Exception as e:
        return {"success": False, "error": f"Error mapping speakers: {e}"}


# ============================================================================
# EXPORT - Generate downloadable document
# ============================================================================

def _export_meeting(meeting_id: int = None, export_format: str = "summary") -> Dict[str, Any]:
    """Generate a download URL for a meeting document. Defaults to most recent completed meeting."""

    meeting_id, err = _resolve_meeting_id(meeting_id, require_completed=True)
    if err:
        return {"success": False, "error": err}

    if export_format not in ("summary", "notes", "transcript"):
        export_format = "summary"

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, title, status FROM meeting_transcripts WHERE id = %s
        """, (meeting_id,))
        meeting = cursor.fetchone()

        cursor.close()
        conn.close()

        if not meeting:
            return {"success": False, "error": f"Meeting #{meeting_id} not found."}

        if meeting[2] != 'completed':
            return {"success": False, "error": f"Meeting #{meeting_id} not yet transcribed (status: {meeting[2]})."}

        base = _base_url()
        download_url = f"{base}/api/meeting/export/{meeting_id}?format={export_format}"

        format_labels = {
            "summary": "Summary (concise overview + action items)",
            "notes": "Notes (summary + key quotes by topic)",
            "transcript": "Full Transcript (all speaker turns with timestamps)"
        }

        return {
            "success": True,
            "message": f"Download ready: {download_url}",
            "download_url": download_url,
            "all_formats": {
                "summary": f"{base}/api/meeting/export/{meeting_id}?format=summary",
                "notes": f"{base}/api/meeting/export/{meeting_id}?format=notes",
                "transcript": f"{base}/api/meeting/export/{meeting_id}?format=transcript",
            },
            "format": export_format,
            "format_description": format_labels.get(export_format, export_format),
            "title": meeting[1]
        }

    except Exception as e:
        return {"success": False, "error": f"Error exporting meeting: {e}"}


@server.register_tool
def meeting_start(
    meeting_title: str,
    meeting_type: str = "conference",
    calendar_event_id: int = None,
) -> Dict[str, Any]:
    """Start recording a new meeting."""
    return _start_meeting(meeting_title, meeting_type, calendar_event_id)


# ============================================================================
# SERVER STARTUP
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("IRIS MEETING SERVER")
    print("=" * 60)
    print("Tools: meeting(action, ...), meeting_start(meeting_title, ...)")
    print("Starting server...")
    print("=" * 60)
    server.run()
