"""
Face Recognition Background Monitoring Service

Periodically scans webcam feed and:
- Detects presence changes (entry/exit)
- Generates intelligent greetings based on absence duration and time of day
- Injects greetings into active conversation
"""

import os
import sys
import time
import threading
from datetime import datetime, timedelta
from typing import Optional, Dict, List

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)

from app import config
import psycopg2
import psycopg2.extras


# ============================================================================
# Database Connection
# ============================================================================

def get_db_connection():
    """Get database connection"""
    password = os.environ.get('AIRIS_DB_PASSWORD') or getattr(config, 'DB_PASSWORD', None)
    conn_params = {
        'host': config.DB_HOST,
        'port': config.DB_PORT,
        'database': config.DB_NAME,
        'user': config.DB_USER
    }
    if password:
        conn_params['password'] = password
    return psycopg2.connect(**conn_params)


def get_or_create_default_camera() -> int:
    """Get or create default browser webcam camera entry"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Check if default camera exists
        cursor.execute("""
            SELECT camera_id FROM face_cameras
            WHERE name = 'browser_webcam'
        """)

        result = cursor.fetchone()
        if result:
            camera_id = result[0]
        else:
            # Create default camera
            cursor.execute("""
                INSERT INTO face_cameras (name, camera_type, connection_string, location, enabled)
                VALUES ('browser_webcam', 'file', '/tmp/iris_webcam_cache/frame_latest.jpg', 'UI Interface', true)
                RETURNING camera_id
            """)
            camera_id = cursor.fetchone()[0]
            conn.commit()
            print(f"[face_monitor][get_or_create_default_camera] ✓ Created default camera (ID: {camera_id})")

        cursor.close()
        conn.close()
        return camera_id

    except Exception as e:
        print(f"[face_monitor][get_or_create_default_camera] ✗ Error: {e}")
        return 1  # Fallback to camera_id=1 if creation fails


# ============================================================================
# Presence State Management
# ============================================================================

def get_current_presence() -> List[Dict]:
    """Get currently present people"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cursor.execute("""
            SELECT * FROM face_presence_state
            WHERE is_present = true
            ORDER BY entered_at DESC
        """)

        present = cursor.fetchall()
        cursor.close()
        conn.close()

        return [dict(p) for p in present]
    except Exception as e:
        print(f"[face_monitor][get_current_presence] ✗ Error: {e}")
        return []


def update_presence(person_id: int, person_name: str, is_present: bool, camera_id: int = None):
    """Update presence state for person"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        now = datetime.now()

        # Get default camera if not provided
        if camera_id is None:
            camera_id = get_or_create_default_camera()

        if is_present:
            # Person entered - check if already marked present
            cursor.execute("""
                SELECT state_id, entered_at FROM face_presence_state
                WHERE person_id = %s AND is_present = true
            """, (person_id,))

            existing = cursor.fetchone()

            if not existing:
                # New entry
                cursor.execute("""
                    INSERT INTO face_presence_state
                    (person_id, person_name, camera_id, entered_at, last_seen_at, is_present)
                    VALUES (%s, %s, %s, %s, %s, true)
                """, (person_id, person_name, camera_id, now, now))
                print(f"[face_monitor][update_presence] ✓ {person_name} entered")
            else:
                # Update last_seen_at
                cursor.execute("""
                    UPDATE face_presence_state
                    SET last_seen_at = %s
                    WHERE state_id = %s
                """, (now, existing[0]))
        else:
            # Person exited
            cursor.execute("""
                UPDATE face_presence_state
                SET is_present = false,
                    exited_at = %s
                WHERE person_id = %s AND is_present = true
            """, (now, person_id))
            print(f"[face_monitor][update_presence] ✓ {person_name} exited")

        conn.commit()
        cursor.close()
        conn.close()

    except Exception as e:
        print(f"[face_monitor][update_presence] ✗ Error: {e}")


def get_last_presence(person_id: int) -> Optional[Dict]:
    """Get last presence record for person (for calculating absence duration)"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cursor.execute("""
            SELECT * FROM face_presence_state
            WHERE person_id = %s
            ORDER BY entered_at DESC
            LIMIT 1
        """, (person_id,))

        record = cursor.fetchone()
        cursor.close()
        conn.close()

        return dict(record) if record else None
    except Exception as e:
        print(f"[face_monitor][get_last_presence] ✗ Error: {e}")
        return None


# ============================================================================
# Greeting Generation
# ============================================================================

def get_time_of_day_greeting() -> str:
    """Get appropriate greeting based on time of day"""
    hour = datetime.now().hour

    if 5 <= hour < 11:
        return "Good morning"
    elif 11 <= hour < 17:
        return "Good afternoon"
    elif 17 <= hour < 21:
        return "Good evening"
    else:
        return "Hey"


def calculate_absence_duration(last_presence: Optional[Dict]) -> Optional[float]:
    """Calculate how long person has been gone (in hours)"""
    if not last_presence:
        return None

    exited_at = last_presence.get('exited_at')
    if not exited_at:
        # Still present from before
        return 0.0

    # Calculate time since exit
    now = datetime.now()
    if isinstance(exited_at, str):
        exited_at = datetime.fromisoformat(exited_at)

    # Remove timezone info if present (for duration calculation)
    if exited_at.tzinfo is not None:
        exited_at = exited_at.replace(tzinfo=None)

    absence = now - exited_at
    return absence.total_seconds() / 3600.0  # Convert to hours


def should_greet(person_id: int, last_greeting_time: Optional[datetime]) -> bool:
    """Check if enough time has passed since last greeting (cooldown)"""
    if not last_greeting_time:
        return True

    # Cooldown: Don't greet too frequently (configurable in config.py)
    cooldown_minutes = getattr(config, 'FACE_GREETING_COOLDOWN_MINUTES', 15)
    now = datetime.now()
    if isinstance(last_greeting_time, str):
        last_greeting_time = datetime.fromisoformat(last_greeting_time)

    # Remove timezone info if present (for duration calculation)
    if hasattr(last_greeting_time, 'tzinfo') and last_greeting_time.tzinfo is not None:
        last_greeting_time = last_greeting_time.replace(tzinfo=None)

    time_since_last_greeting = now - last_greeting_time
    return time_since_last_greeting > timedelta(minutes=cooldown_minutes)


def prepare_greeting_context(person_name: str, relationship: str, absence_hours: Optional[float],
                            last_conversation_summary: Optional[str] = None) -> Optional[Dict]:
    """
    Prepare context for Iris to generate her own greeting

    Returns None if no greeting warranted (too short absence)
    Returns dict with context for Iris to use
    """

    # Just stepped out briefly - no greeting (configurable in config.py)
    min_absence_minutes = getattr(config, 'FACE_GREETING_MIN_ABSENCE_MINUTES', 5)
    min_absence_hours = min_absence_minutes / 60.0
    if absence_hours is not None and absence_hours < min_absence_hours:
        return None

    # Get time of day context
    hour = datetime.now().hour
    if 5 <= hour < 11:
        time_of_day = "morning"
    elif 11 <= hour < 17:
        time_of_day = "afternoon"
    elif 17 <= hour < 21:
        time_of_day = "evening"
    else:
        time_of_day = "night"

    # Categorize absence
    if absence_hours is None:
        absence_category = "first_time"
    elif absence_hours < 0.5:
        absence_category = "brief"  # 5-30 min
    elif absence_hours < 4:
        absence_category = "short"  # 30 min - 4 hours
    elif absence_hours < 12:
        absence_category = "long"   # 4-12 hours
    else:
        absence_category = "very_long"  # > 12 hours

    return {
        "person_name": person_name,
        "relationship": relationship,
        "time_of_day": time_of_day,
        "current_hour": hour,
        "absence_category": absence_category,
        "absence_hours": round(absence_hours, 1) if absence_hours else None,
        "last_conversation_topic": last_conversation_summary
    }


def prepare_unknown_greeting_context() -> Dict:
    """Prepare context for greeting unknown person"""
    hour = datetime.now().hour
    if 5 <= hour < 11:
        time_of_day = "morning"
    elif 11 <= hour < 17:
        time_of_day = "afternoon"
    elif 17 <= hour < 21:
        time_of_day = "evening"
    else:
        time_of_day = "night"

    return {
        "person_name": "unknown",
        "time_of_day": time_of_day,
        "current_hour": hour
    }


def get_last_conversation_context() -> Optional[str]:
    """Get brief summary of what was being discussed (for 'welcome back' messages)"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Get last few user messages to understand context
        cursor.execute("""
            SELECT message FROM chat_history
            WHERE role = 'user'
            ORDER BY c_timestamp DESC
            LIMIT 3
        """)

        messages = cursor.fetchall()
        cursor.close()
        conn.close()

        if not messages:
            return None

        # Very simple context extraction - just get key words from last message
        last_msg = messages[0][0] if messages else None
        if not last_msg:
            return None

        # Extract first few words as context (keep it brief)
        words = last_msg.split()[:5]
        return ' '.join(words) if words else None

    except Exception as e:
        print(f"[face_monitor][get_last_conversation_context] ✗ Error: {e}")
        return None


# ============================================================================
# Greeting Injection
# ============================================================================

def inject_greeting_trigger(context: Dict):
    """
    Inject a greeting trigger that Iris will see and respond to naturally

    Builds a system message with instructions for Iris to greet the person
    based on the provided context (time of day, absence duration, etc.),
    then triggers the response via the system trigger API.
    """
    try:
        # Build instruction for Iris
        person_name = context.get('person_name')
        relationship = context.get('relationship', 'unknown')
        time_of_day = context.get('time_of_day')
        absence_category = context.get('absence_category')
        absence_hours = context.get('absence_hours')
        last_topic = context.get('last_conversation_topic')

        if person_name == "unknown":
            # Unknown person detected
            instruction = f"""[WEBCAM PRESENCE ALERT] An unknown person has appeared on the webcam.

IMPORTANT: Stop any ongoing conversation and send a greeting message.

Time: {time_of_day} (hour: {context['current_hour']})

Greet them naturally and let them know you don't recognize them yet. Be friendly and welcoming.

Do NOT continue any previous conversation topic."""
        else:
            # Known person detected
            instruction = f"""
═══════════════════════════════════════════════════════════════
🎥 WEBCAM PRESENCE ALERT - GREETING REQUIRED
═══════════════════════════════════════════════════════════════

{person_name} ({relationship}) has just entered and is now in front of the webcam.

⚠️ CRITICAL INSTRUCTION ⚠️
IGNORE ALL PREVIOUS CONVERSATION CONTEXT.
DO NOT continue any previous topic or conversation.
DO NOT respond to previous questions or requests.

YOUR ONLY TASK RIGHT NOW:
Send a natural greeting that acknowledges {person_name} has returned.

Time: {time_of_day} (hour {context['current_hour']})
Absence: {absence_category}"""

            if absence_hours is not None:
                instruction += f" ({absence_hours:.1f} hours)"

            instruction += f"""

YOUR GREETING MUST:
1. FIRST: Acknowledge their return with time-appropriate greeting based on absence
2. OPTIONALLY: Reference what you were last discussing (if you see it in recent messages)
3. NEVER: Continue or dive back into the previous topic

GREETING EXAMPLES:
- brief (5-30min): "Hey, you're back! Ready to pick up where we left off with [topic]?"
- short (30min-4hr): "Welcome back! Still thinking about [topic]?"
- long (4-12hr): "Good {time_of_day}! Haven't seen you since [earlier time]. Were you still working on [topic]?"
- very_long (>12hr): "Hey! It's been a while. I think we were discussing [topic] last time?"
- first_time: "Good {time_of_day}! First time seeing you today."

The GREETING is the priority. Mentioning the previous topic is optional and casual.
DO NOT continue the previous conversation. DO NOT provide information about the previous topic.

═══════════════════════════════════════════════════════════════"""

        print(f"[face_monitor][inject_greeting_trigger] ✓ Prepared greeting trigger for {person_name} ({absence_category})")

        # Trigger Iris's greeting response via API
        try:
            _trigger_greeting_response(instruction)
        except Exception as e:
            print(f"[face_monitor][inject_greeting_trigger] ✗ Failed to trigger response: {e}")

    except Exception as e:
        print(f"[face_monitor][inject_greeting_trigger] ✗ Error: {e}")


def _trigger_greeting_response(greeting_instruction: str):
    """
    Trigger Iris's greeting response via system trigger API

    Uses MINIMAL context (GREETING mode) to avoid overwhelming the greeting
    with previous conversation context.
    """
    try:
        import httpx

        print(f"[face_monitor][_trigger_greeting_response] Triggering greeting via API...")

        # Call system trigger endpoint with GREETING context mode
        # This will use minimal context to avoid overwhelming the greeting instruction
        protocol = "https" if os.path.exists(config.SSL_CERT_PATH) else "http"
        api_url = f"{protocol}://localhost:{config.PORT}/api/system/trigger"
        payload = {
            "content": greeting_instruction,
            "allow_tools": False,  # Skip tool evaluation for greetings
            "context_mode": "GREETING"  # Use minimal context for greeting
        }

        # Disable SSL verification for self-signed certificate
        with httpx.Client(timeout=60.0, verify=False) as client:
            response = client.post(api_url, json=payload)
            response.raise_for_status()
            result = response.json()

            if result.get('success'):
                assistant_message = result.get('response', '')
                print(f"[face_monitor][_trigger_greeting_response] ✓ Greeting generated: {assistant_message[:80]}...")
            else:
                error = result.get('error', 'Unknown error')
                print(f"[face_monitor][_trigger_greeting_response] ✗ API error: {error}")

    except Exception as e:
        print(f"[face_monitor][_trigger_greeting_response] ✗ Error: {e}")
        import traceback
        traceback.print_exc()


def update_last_greeting_time(person_id: int):
    """Update last greeting time for person"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE face_presence_state
            SET last_greeting_at = %s
            WHERE person_id = %s AND is_present = true
        """, (datetime.now(), person_id))

        conn.commit()
        cursor.close()
        conn.close()

    except Exception as e:
        print(f"[face_monitor][update_last_greeting_time] ✗ Error: {e}")


# ============================================================================
# Monitoring Loop
# ============================================================================

def scan_and_process():
    """Scan webcam feed and process presence changes"""
    try:
        from core import face_recognition as fr

        # Check if webcam frame is available
        WEBCAM_CACHE_DIR = "/tmp/iris_webcam_cache"
        latest_frame_path = os.path.join(WEBCAM_CACHE_DIR, "frame_latest.jpg")

        print(f"[face_monitor][scan_and_process] Checking for webcam frame at {latest_frame_path}")

        if not os.path.exists(latest_frame_path):
            # No webcam feed active
            print(f"[face_monitor][scan_and_process] No webcam frame found - skipping scan")
            return

        # Check if frame is stale (older than 15 seconds)
        file_mtime = datetime.fromtimestamp(os.path.getmtime(latest_frame_path))
        age = datetime.now() - file_mtime
        print(f"[face_monitor][scan_and_process] Frame age: {age.total_seconds():.1f} seconds")

        if age > timedelta(seconds=15):
            # Webcam not actively streaming
            print(f"[face_monitor][scan_and_process] Frame too old ({age.total_seconds():.1f}s) - skipping scan")
            return

        print(f"[face_monitor][scan_and_process] Processing frame...")

        # Load and recognize
        img = fr.load_image_from_path(latest_frame_path)
        if img is None:
            return

        results = fr.recognize_face(img, similarity_threshold=config.FACE_SIMILARITY_THRESHOLD)

        # Get current presence state
        currently_present = get_current_presence()
        currently_present_ids = {p['person_id'] for p in currently_present}

        # Process recognized faces
        recognized_ids = set()
        for result in results:
            if result.get('best_match'):
                match = result['best_match']
                person_id = match['person_id']
                person_name = match['name']
                relationship = match.get('relationship', 'unknown')

                recognized_ids.add(person_id)

                # Check if this is a new entry
                if person_id not in currently_present_ids:
                    # Person just entered
                    # Get last presence BEFORE updating (to calculate absence from previous session)
                    last_presence = get_last_presence(person_id)
                    absence_hours = calculate_absence_duration(last_presence)
                    print(f"[face_monitor][scan_and_process] Absence calculated: {absence_hours} hours")

                    # Now update presence
                    update_presence(person_id, person_name, is_present=True)

                    # Check if we should greet
                    last_greeting = last_presence.get('last_greeting_at') if last_presence else None
                    should_greet_result = should_greet(person_id, last_greeting)
                    print(f"[face_monitor][scan_and_process] Should greet? {should_greet_result} (last_greeting: {last_greeting})")

                    if should_greet_result:
                        # Get conversation context for short absences
                        last_topic = get_last_conversation_context() if (absence_hours and absence_hours < 0.5) else None

                        # Prepare greeting context for Iris to use
                        greeting_context = prepare_greeting_context(person_name, relationship, absence_hours, last_topic)
                        print(f"[face_monitor][scan_and_process] Greeting context prepared: {greeting_context is not None}")

                        if greeting_context:
                            inject_greeting_trigger(greeting_context)
                            update_last_greeting_time(person_id)
                        else:
                            print(f"[face_monitor][scan_and_process] No greeting - absence too short (<5 min)")
                else:
                    # Person still present - update last_seen
                    update_presence(person_id, person_name, is_present=True)
            else:
                # Unknown face detected - greet them
                unknown_context = prepare_unknown_greeting_context()
                inject_greeting_trigger(unknown_context)
                print(f"[face_monitor] ⚠️ Unknown person detected")

        # Check for exits (people who were present but not recognized now)
        for present_person in currently_present:
            if present_person['person_id'] not in recognized_ids:
                # Person no longer visible - mark as exited after grace period
                last_seen = present_person.get('last_seen_at')
                if isinstance(last_seen, str):
                    last_seen = datetime.fromisoformat(last_seen)

                # Remove timezone info if present
                if last_seen and hasattr(last_seen, 'tzinfo') and last_seen.tzinfo is not None:
                    last_seen = last_seen.replace(tzinfo=None)

                # Grace period: 10 seconds (2 missed scans)
                if last_seen and (datetime.now() - last_seen) > timedelta(seconds=10):
                    update_presence(present_person['person_id'], present_person['person_name'], is_present=False)

    except Exception as e:
        print(f"[face_monitor][scan_and_process] ✗ Error: {e}")
        import traceback
        traceback.print_exc()


# ============================================================================
# Background Service
# ============================================================================

_monitor_thread = None
_stop_event = threading.Event()


def start_monitoring(interval_seconds: int = 5):
    """Start background monitoring service"""
    global _monitor_thread, _stop_event

    if _monitor_thread and _monitor_thread.is_alive():
        print("[face_monitor] Monitoring already running")
        return

    _stop_event.clear()

    def monitor_loop():
        print(f"[face_monitor] ✓ Background monitoring started (interval: {interval_seconds}s)")
        while not _stop_event.is_set():
            scan_and_process()
            time.sleep(interval_seconds)
        print("[face_monitor] Monitoring stopped")

    _monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
    _monitor_thread.start()


def stop_monitoring():
    """Stop background monitoring service"""
    global _stop_event
    _stop_event.set()
    print("[face_monitor] Stopping monitoring...")


if __name__ == "__main__":
    # Test mode
    print("Starting face monitor in test mode...")
    start_monitoring(interval_seconds=5)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop_monitoring()
        print("Stopped.")
