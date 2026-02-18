"""
Calendar MCP Server - Event scheduling and reminder management

Provides a unified 'calendar' tool with actions:
- add: Create a new calendar event
- list: View upcoming events
- update: Modify an existing event
- delete: Cancel an event (soft delete)
- search: Find events by keyword

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
import psycopg2
from psycopg2.extras import DictCursor
from pathlib import Path
from typing import Dict, Any, Optional
import os
from datetime import datetime, timedelta
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
    name="Iris Calendar Server",
    description="Calendar event management and reminders"
)


def get_db_connection():
    """Create database connection"""
    password = os.environ.get('IRIS_DB_PASSWORD') or getattr(config, 'DB_PASSWORD', None)

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


def parse_datetime(dt_string: str) -> datetime:
    """
    Parse an ISO 8601 datetime string, assuming local timezone if naive.

    Supports:
    - 2026-02-01T14:00:00 (naive -> local tz)
    - 2026-02-01T14:00:00-05:00 (aware -> kept as-is)
    - 2026-02-01 (date only -> midnight local tz)
    """
    if not dt_string:
        return None

    # Try parsing with timezone info first
    for fmt in [
        '%Y-%m-%dT%H:%M:%S%z',
        '%Y-%m-%dT%H:%M:%S',
        '%Y-%m-%dT%H:%M',
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%d %H:%M',
        '%Y-%m-%d',
    ]:
        try:
            dt = datetime.strptime(dt_string, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=get_timezone())
            return dt
        except ValueError:
            continue

    raise ValueError(f"Cannot parse datetime: '{dt_string}'. Use ISO 8601 format (e.g. 2026-02-01T14:00:00)")


def format_event_time(dt: datetime, all_day: bool = False) -> str:
    """Format a datetime for display in the configured timezone"""
    if dt is None:
        return "N/A"
    local_dt = dt.astimezone(get_timezone())
    if all_day:
        return local_dt.strftime('%A, %B %d, %Y')
    return local_dt.strftime('%A, %B %d, %Y at %I:%M %p')


# ============================================================================
# CALENDAR TOOL - Main entry point with subcommands
# ============================================================================

@server.register_tool
def calendar(
    action: str,
    title: str = None,
    description: str = None,
    start_time: str = None,
    end_time: str = None,
    all_day: bool = False,
    location: str = None,
    category: str = "personal",
    reminder: bool = True,
    reminder_hours_before: float = None,
    event_id: int = None,
    days_ahead: int = 7,
    query: str = None,
    limit: int = 20
) -> Dict[str, Any]:
    """
    Calendar event management - schedule, view, update, and search events.

    Actions:
    - add: Create a new event (requires title and start_time)
    - list: Show upcoming events (optional days_ahead, category filter)
    - update: Modify an event (requires event_id, plus fields to change)
    - delete: Cancel an event (requires event_id, soft delete)
    - search: Find events by keyword (requires query)

    Args:
        action: The action to perform (add, list, update, delete, search)
        title: Event title (required for add)
        description: Event description or notes
        start_time: ISO 8601 datetime string (required for add)
        end_time: ISO 8601 datetime string (defaults to start + 1hr)
        all_day: Whether this is an all-day event
        location: Event location
        category: appointment, meeting, personal, reminder, deadline
        reminder: Enable reminder (default: true)
        reminder_hours_before: Hours before event to show reminder (default from config)
        event_id: Event ID for update/delete
        days_ahead: For list: days to look ahead (default 7)
        query: For search: keyword to match
        limit: Max results (default 20)

    Returns:
        Result of the action with event information
    """

    if action == "add":
        return _add_event(title, description, start_time, end_time, all_day,
                          location, category, reminder, reminder_hours_before)
    elif action == "list":
        return _list_events(days_ahead, category, limit)
    elif action == "update":
        return _update_event(event_id, title, description, start_time, end_time,
                             all_day, location, category, reminder, reminder_hours_before)
    elif action == "delete":
        return _delete_event(event_id)
    elif action == "search":
        return _search_events(query, limit)
    else:
        return {"success": False, "error": f"Unknown action: {action}. Use: add, list, update, delete, search"}


# ============================================================================
# ADD - Create a new event
# ============================================================================

def _add_event(
    title: str,
    description: str = None,
    start_time_str: str = None,
    end_time_str: str = None,
    all_day: bool = False,
    location: str = None,
    category: str = "personal",
    reminder: bool = True,
    reminder_hours_before: float = None
) -> Dict[str, Any]:
    """Create a new calendar event"""

    if not title:
        return {"success": False, "error": "Event needs a title."}
    if not start_time_str:
        return {"success": False, "error": "Event needs a start_time (ISO 8601 format, e.g. 2026-02-01T14:00:00)."}

    try:
        start_dt = parse_datetime(start_time_str)
    except ValueError as e:
        return {"success": False, "error": str(e)}

    # Default end time: +1 hour (or end of day for all-day)
    end_dt = None
    if end_time_str:
        try:
            end_dt = parse_datetime(end_time_str)
        except ValueError as e:
            return {"success": False, "error": f"Invalid end_time: {e}"}
    elif all_day:
        end_dt = start_dt.replace(hour=23, minute=59, second=59)
    else:
        end_dt = start_dt + timedelta(hours=1)

    # Default reminder hours from config
    if reminder_hours_before is None:
        reminder_hours_before = float(getattr(config, 'CALENDAR_REMINDER_DEFAULT_HOURS_BEFORE', 4))

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO calendar_events (
                title, description, location,
                start_time, end_time, all_day,
                reminder_enabled, reminder_hours_before,
                category, source
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, created_at
        """, (
            title, description, location,
            start_dt, end_dt, all_day,
            reminder, reminder_hours_before,
            category, 'conversation'
        ))

        event_id, created_at = cursor.fetchone()
        conn.commit()

        # Phase 2: Google Calendar sync
        if getattr(config, 'CALENDAR_GOOGLE_SYNC_ENABLED', False):
            try:
                from mcp_servers.calendar.google_sync import GoogleCalendarSync
                sync = GoogleCalendarSync()
                sync.push_event(event_id, cursor=None)
            except Exception as e:
                print(f"[calendar] Google sync failed for event #{event_id}: {e}")

        cursor.close()
        conn.close()

        return {
            "success": True,
            "message": f"Event '#{event_id} {title}' scheduled for {format_event_time(start_dt, all_day)}.",
            "event": {
                "id": event_id,
                "title": title,
                "description": description,
                "location": location,
                "start_time": start_dt.isoformat(),
                "end_time": end_dt.isoformat() if end_dt else None,
                "all_day": all_day,
                "category": category,
                "reminder_enabled": reminder,
                "reminder_hours_before": reminder_hours_before,
                "created_at": created_at.isoformat() if created_at else None
            }
        }

    except Exception as e:
        return {"success": False, "error": f"Error creating event: {e}"}


# ============================================================================
# LIST - View upcoming events
# ============================================================================

def _list_events(
    days_ahead: int = 7,
    category: str = None,
    limit: int = 20
) -> Dict[str, Any]:
    """List upcoming events"""

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        tz = get_timezone()
        now = datetime.now(tz)
        end_window = now + timedelta(days=days_ahead)

        query = """
            SELECT id, title, description, location,
                   start_time, end_time, all_day,
                   category, status, reminder_enabled
            FROM calendar_events
            WHERE status = 'active'
              AND start_time >= %s
              AND start_time <= %s
        """
        params = [now, end_window]

        if category:
            query += " AND category = %s"
            params.append(category)

        query += " ORDER BY start_time ASC LIMIT %s"
        params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        if not rows:
            return {
                "success": True,
                "message": f"No events scheduled in the next {days_ahead} day(s).",
                "events": [],
                "count": 0
            }

        events = []
        for row in rows:
            events.append({
                "id": row[0],
                "title": row[1],
                "description": row[2],
                "location": row[3],
                "start_time": format_event_time(row[4], row[6]),
                "end_time": format_event_time(row[5], row[6]) if row[5] else None,
                "all_day": row[6],
                "category": row[7],
                "status": row[8],
                "reminder_enabled": row[9]
            })

        return {
            "success": True,
            "events": events,
            "count": len(events),
            "window": f"Next {days_ahead} day(s)"
        }

    except Exception as e:
        return {"success": False, "error": f"Error listing events: {e}"}


# ============================================================================
# UPDATE - Modify an existing event
# ============================================================================

def _update_event(
    event_id: int,
    title: str = None,
    description: str = None,
    start_time_str: str = None,
    end_time_str: str = None,
    all_day: bool = None,
    location: str = None,
    category: str = None,
    reminder: bool = None,
    reminder_hours_before: float = None
) -> Dict[str, Any]:
    """Update an existing event - only provided fields are changed"""

    if not event_id:
        return {"success": False, "error": "Which event? Provide event_id."}

    # Build dynamic SET clause
    updates = []
    params = []

    if title is not None:
        updates.append("title = %s")
        params.append(title)

    if description is not None:
        updates.append("description = %s")
        params.append(description)

    if start_time_str is not None:
        try:
            start_dt = parse_datetime(start_time_str)
            updates.append("start_time = %s")
            params.append(start_dt)
        except ValueError as e:
            return {"success": False, "error": f"Invalid start_time: {e}"}

    if end_time_str is not None:
        try:
            end_dt = parse_datetime(end_time_str)
            updates.append("end_time = %s")
            params.append(end_dt)
        except ValueError as e:
            return {"success": False, "error": f"Invalid end_time: {e}"}

    if all_day is not None:
        updates.append("all_day = %s")
        params.append(all_day)

    if location is not None:
        updates.append("location = %s")
        params.append(location)

    if category is not None:
        updates.append("category = %s")
        params.append(category)

    if reminder is not None:
        updates.append("reminder_enabled = %s")
        params.append(reminder)

    if reminder_hours_before is not None:
        updates.append("reminder_hours_before = %s")
        params.append(reminder_hours_before)

    if not updates:
        return {"success": False, "error": "No fields to update. Provide at least one field to change."}

    params.append(event_id)

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(f"""
            UPDATE calendar_events SET {', '.join(updates)}
            WHERE id = %s AND status = 'active'
            RETURNING id, title, start_time, all_day
        """, params)

        result = cursor.fetchone()
        conn.commit()
        cursor.close()
        conn.close()

        if not result:
            return {"success": False, "error": f"Event #{event_id} not found or already cancelled."}

        return {
            "success": True,
            "message": f"Event #{result[0]} '{result[1]}' updated. Scheduled for {format_event_time(result[2], result[3])}.",
            "event_id": result[0],
            "title": result[1]
        }

    except Exception as e:
        return {"success": False, "error": f"Error updating event: {e}"}


# ============================================================================
# DELETE - Cancel an event (soft delete)
# ============================================================================

def _delete_event(event_id: int) -> Dict[str, Any]:
    """Cancel an event (soft delete - sets status to 'cancelled')"""

    if not event_id:
        return {"success": False, "error": "Which event? Provide event_id."}

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE calendar_events
            SET status = 'cancelled'
            WHERE id = %s AND status = 'active'
            RETURNING id, title, start_time, google_event_id
        """, (event_id,))

        result = cursor.fetchone()
        conn.commit()

        if not result:
            cursor.close()
            conn.close()
            return {"success": False, "error": f"Event #{event_id} not found or already cancelled."}

        # Phase 2: Delete from Google Calendar if synced
        if result[3] and getattr(config, 'CALENDAR_GOOGLE_SYNC_ENABLED', False):
            try:
                from mcp_servers.calendar.google_sync import GoogleCalendarSync
                sync = GoogleCalendarSync()
                sync.delete_event(result[3])
            except Exception as e:
                print(f"[calendar] Google sync delete failed for event #{event_id}: {e}")

        cursor.close()
        conn.close()

        return {
            "success": True,
            "message": f"Event #{result[0]} '{result[1]}' cancelled.",
            "event_id": result[0],
            "title": result[1]
        }

    except Exception as e:
        return {"success": False, "error": f"Error cancelling event: {e}"}


# ============================================================================
# SEARCH - Find events by keyword
# ============================================================================

def _search_events(query: str, limit: int = 20) -> Dict[str, Any]:
    """Search events by title or description keyword"""

    if not query:
        return {"success": False, "error": "Provide a search query."}

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        search_pattern = f"%{query}%"

        cursor.execute("""
            SELECT id, title, description, location,
                   start_time, end_time, all_day,
                   category, status
            FROM calendar_events
            WHERE status = 'active'
              AND (title ILIKE %s OR description ILIKE %s)
            ORDER BY start_time DESC
            LIMIT %s
        """, (search_pattern, search_pattern, limit))

        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        if not rows:
            return {
                "success": True,
                "message": f"No events found matching '{query}'.",
                "events": [],
                "count": 0
            }

        events = []
        for row in rows:
            events.append({
                "id": row[0],
                "title": row[1],
                "description": row[2],
                "location": row[3],
                "start_time": format_event_time(row[4], row[6]),
                "end_time": format_event_time(row[5], row[6]) if row[5] else None,
                "all_day": row[6],
                "category": row[7],
                "status": row[8]
            })

        return {
            "success": True,
            "events": events,
            "count": len(events),
            "query": query
        }

    except Exception as e:
        return {"success": False, "error": f"Error searching events: {e}"}


# ============================================================================
@server.register_tool
def calendar_add(
    title: str,
    start_time: str,
    end_time: str = None,
    description: str = None,
    location: str = None,
    category: str = "personal",
    all_day: bool = False,
    reminder: bool = True,
    reminder_hours_before: float = None,
) -> Dict[str, Any]:
    """Add a new event to the calendar."""
    return _add_event(title, description, start_time, end_time, all_day,
                      location, category, reminder, reminder_hours_before)


# SERVER STARTUP
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("IRIS CALENDAR SERVER")
    print("=" * 60)
    print("Tool available: calendar")
    print("Tools: calendar(action, ...), calendar_add(title, start_time, ...)")
    print("Starting server...")
    print("=" * 60)
    server.run()
