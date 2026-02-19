"""
Observability API endpoints for the Iris instrumentation dashboard.

Serves turn-level metrics, longitudinal drift metrics, and service events
for time-series visualization.
"""

from fastapi import APIRouter, Query
from datetime import datetime, timedelta
from typing import Optional

router = APIRouter(prefix="/api/observability", tags=["observability"])


def _parse_range(start: Optional[str], end: Optional[str], default_days: int = 7):
    """Parse ISO date strings into datetime objects with defaults."""
    end_dt = datetime.fromisoformat(end) if end else datetime.now()
    start_dt = datetime.fromisoformat(start) if start else (end_dt - timedelta(days=default_days))
    return start_dt, end_dt


@router.get("/turn-metrics")
async def get_turn_metrics(
    start: Optional[str] = Query(None, description="ISO datetime start"),
    end: Optional[str] = Query(None, description="ISO datetime end"),
    session_id: Optional[str] = Query(None),
    limit: int = Query(500, le=2000),
):
    """Per-turn metrics for time-series charts."""
    from database.metrics import get_turn_metrics as _get

    start_dt, end_dt = _parse_range(start, end, default_days=7)
    rows = _get(session_id=session_id, start=start_dt, end=end_dt, limit=limit)
    return {"count": len(rows), "metrics": rows}


@router.get("/drift-metrics")
async def get_drift_metrics(
    metric: Optional[str] = Query(None, description="Filter by metric_name"),
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
):
    """Longitudinal drift metrics for trend charts."""
    from database.metrics import get_drift_metrics as _get

    start_dt, end_dt = _parse_range(start, end, default_days=90)
    rows = _get(metric_name=metric, start=start_dt, end=end_dt)
    return {"count": len(rows), "metrics": rows}


@router.get("/events")
async def get_events(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
):
    """Service events for chart overlay markers (dreams, memory batches, restarts)."""
    import psycopg2
    import psycopg2.extras
    import os
    from app import config

    start_dt, end_dt = _parse_range(start, end, default_days=30)

    password = os.environ.get('AIRIS_DB_PASSWORD') or getattr(config, 'DB_PASSWORD', None)
    conn_params = {
        'host': config.DB_HOST,
        'port': config.DB_PORT,
        'database': config.DB_NAME,
        'user': config.DB_USER,
    }
    if password:
        conn_params['password'] = password

    conn = psycopg2.connect(**conn_params)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("""
        SELECT id, event_type, service_name, source, detail, created_at
        FROM service_events
        WHERE created_at >= %s AND created_at <= %s
        ORDER BY created_at ASC
    """, (start_dt, end_dt))

    rows = cur.fetchall()
    cur.close()
    conn.close()

    events = []
    for row in rows:
        d = dict(row)
        if d.get("created_at"):
            d["created_at"] = d["created_at"].isoformat()
        events.append(d)

    return {"count": len(events), "events": events}


@router.get("/summary")
async def get_summary():
    """Latest drift values + recent stats for overview cards."""
    from database.metrics import get_observability_summary
    return get_observability_summary()
