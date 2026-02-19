"""
Service Events Logger

Fire-and-forget helper for logging service lifecycle events to the
service_events table. Used by gap report system to build
"while you were away" reports.

Never raises — all errors are silently swallowed to avoid
impacting the calling code path.
"""

import os
import psycopg2
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


def log_service_event(event_type, service_name, source, detail=None):
    """
    Log a service event. Fire-and-forget — never raises.

    Args:
        event_type: startup, shutdown, crash_detected, service_swap,
                    dream_start, dream_end, memory_start, memory_end,
                    semantic_start, semantic_end
        service_name: iris_server, iris_vision, iris_freud, nightly_dream, etc.
        source: lifespan, gpu_manager, nightly_dream, background_health, etc.
        detail: Optional human-readable detail string
    """
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO service_events (event_type, service_name, source, detail) VALUES (%s, %s, %s, %s)",
            (event_type, service_name, source, detail)
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception:
        pass
