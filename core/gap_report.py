"""
Gap Report Builder — "While You Were Away"

When Victor returns after a gap (>=30 min), builds a <while_you_were_away>
XML section for the per-turn context on the first turn only.

Reports on what happened during the gap:
- Memory processing (episodic + semantic)
- Dream sessions
- Service health events (restarts, crashes, GPU swaps)

Each section only appears if there's data. Empty gap = no report at all.
"""

import os
import psycopg2
from datetime import datetime
from app import config


def get_db_connection():
    """Create database connection"""
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


# Session ID for which we've already delivered the gap report
_gap_report_delivered_session = None


def build_gap_report(gap_start, gap_end, session_id):
    """
    Build <while_you_were_away> XML section.

    Returns None if:
    - Already delivered this session
    - No data found during the gap
    - Feature disabled in config

    Args:
        gap_start: datetime of last user message
        gap_end: datetime of current turn (now)
        session_id: Current session ID for first-turn gating
    """
    global _gap_report_delivered_session

    # First-turn gating: only deliver once per session
    if _gap_report_delivered_session == session_id:
        return None

    sections = []

    # Each getter returns a list of lines (may be empty)
    # Wrapped individually so one failure doesn't block others
    try:
        sections.extend(_get_memory_activity(gap_start, gap_end))
    except Exception as e:
        print(f"[gap_report.py] Memory activity query failed: {e}")

    try:
        sections.extend(_get_dream_activity(gap_start, gap_end))
    except Exception as e:
        print(f"[gap_report.py] Dream activity query failed: {e}")

    try:
        sections.extend(_get_service_events(gap_start, gap_end))
    except Exception as e:
        print(f"[gap_report.py] Service events query failed: {e}")

    if not sections:
        return None

    # Mark as delivered for this session
    _gap_report_delivered_session = session_id
    print(f"[gap_report.py] Gap report delivered ({len(sections)} section(s), session {session_id})")

    return "<while_you_were_away>\n" + "\n".join(sections) + "\n</while_you_were_away>"


def _get_memory_activity(gap_start, gap_end):
    """Count episodic and semantic memories created during the gap."""
    conn = get_db_connection()
    cur = conn.cursor()

    # Episodic memories created
    cur.execute(
        "SELECT COUNT(*) FROM episodic_memories WHERE created_at BETWEEN %s AND %s",
        (gap_start, gap_end)
    )
    episodic_count = cur.fetchone()[0]

    # Semantic memories created (new)
    cur.execute(
        "SELECT COUNT(*) FROM semantic_memories WHERE created_at BETWEEN %s AND %s",
        (gap_start, gap_end)
    )
    semantic_new = cur.fetchone()[0]

    # Semantic memories reinforced (updated but not newly created)
    cur.execute(
        "SELECT COUNT(*) FROM semantic_memories WHERE last_reinforced_at BETWEEN %s AND %s AND created_at < %s",
        (gap_start, gap_end, gap_start)
    )
    semantic_reinforced = cur.fetchone()[0]

    cur.close()
    conn.close()

    if episodic_count == 0 and semantic_new == 0 and semantic_reinforced == 0:
        return []

    lines = ["<memory_processing>"]

    if episodic_count > 0:
        lines.append(f"{episodic_count} new episodic memor{'y was' if episodic_count == 1 else 'ies were'} created from recent conversations.")

    if semantic_new > 0 or semantic_reinforced > 0:
        parts = []
        if semantic_new > 0:
            parts.append(f"{semantic_new} new")
        if semantic_reinforced > 0:
            parts.append(f"{semantic_reinforced} reinforced")
        lines.append(f"{semantic_new + semantic_reinforced} semantic memor{'y was' if (semantic_new + semantic_reinforced) == 1 else 'ies were'} consolidated ({', '.join(parts)}).")

    lines.append("</memory_processing>")
    return lines


def _get_dream_activity(gap_start, gap_end):
    """Get dream sessions that occurred during the gap."""
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        """SELECT dream_type, mood, theme, takeaway
           FROM episodic_dreams
           WHERE created_at BETWEEN %s AND %s
           ORDER BY created_at DESC""",
        (gap_start, gap_end)
    )
    dreams = cur.fetchall()
    cur.close()
    conn.close()

    if not dreams:
        return []

    lines = ["<dream_session>"]
    for dream_type, mood, theme, takeaway in dreams:
        line = f"You dreamed last night ({dream_type or 'processing'}). Mood: {mood or 'unknown'}."
        if theme:
            line += f" Theme: {theme}."
        lines.append(line)
        if takeaway:
            lines.append(f"Takeaway: {takeaway}")

    lines.append("</dream_session>")
    return lines


def _get_service_events(gap_start, gap_end):
    """Get service health events during the gap."""
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        """SELECT event_type, service_name, detail, created_at
           FROM service_events
           WHERE created_at BETWEEN %s AND %s
           ORDER BY created_at ASC""",
        (gap_start, gap_end)
    )
    events = cur.fetchall()
    cur.close()
    conn.close()

    if not events:
        return []

    lines = ["<service_health>"]

    has_crashes = False
    for event_type, service_name, detail, created_at in events:
        time_str = created_at.strftime("%I:%M %p").lstrip("0")

        if event_type == "crash_detected":
            has_crashes = True
            svc = service_name.replace("_", " ").title()
            lines.append(f"- {svc} crash detected at {time_str}." + (f" {detail}" if detail else ""))
        elif event_type == "startup":
            svc = service_name.replace("_", " ").title()
            lines.append(f"- {svc} started at {time_str}." + (f" {detail}" if detail else ""))
        elif event_type == "shutdown":
            svc = service_name.replace("_", " ").title()
            lines.append(f"- {svc} stopped at {time_str}." + (f" {detail}" if detail else ""))
        elif event_type == "service_swap":
            lines.append(f"- GPU swap: {service_name} at {time_str}." + (f" {detail}" if detail else ""))
        elif event_type in ("dream_start", "dream_end", "memory_start", "memory_end", "semantic_start", "semantic_end"):
            action = "started" if event_type.endswith("_start") else "completed"
            svc = service_name.replace("_", " ").title()
            lines.append(f"- {svc} {action} at {time_str}." + (f" {detail}" if detail else ""))

    if not has_crashes:
        lines.append("- No unexpected crashes or errors detected.")

    lines.append("</service_health>")
    return lines
