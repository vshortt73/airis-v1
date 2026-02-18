# Gap Report System — "While You Were Away"

**Last Updated:** 2026-02-07

When Victor returns after an absence (>=30 minutes), Iris sees a one-time `<while_you_were_away>` section in her per-turn context summarizing what happened while he was gone: memory processing, dreams, and service health events.

---

## How It Works

```
User sends first message after gap >= 30 min
    │
    ▼
build_per_turn_context()                      system_prompt.py:953
    │
    ├── gap_minutes >= 30?  ───── no ──▶ skip
    │
    ▼
build_gap_report(gap_start, gap_end, session_id)    core/gap_report.py
    │
    ├── Already delivered this session? ─── yes ──▶ return None
    │
    ├── _get_memory_activity()     ──▶ COUNT episodic + semantic memories
    ├── _get_dream_activity()      ──▶ SELECT from episodic_dreams
    └── _get_service_events()      ──▶ SELECT from service_events
    │
    ├── No data from any source?   ─── yes ──▶ return None
    │
    ▼
Return <while_you_were_away> XML
    │
    ▼
Appended to per-turn tail sections
(between <current_datetime> and emotional state)
```

---

## First-Turn Gating

The report appears **once per session** only. Module-level `_gap_report_delivered_session` tracks the session ID for which the report was delivered. Subsequent turns in the same session skip it.

This means:
- First message after a 2-hour gap: report appears
- Second message (30 seconds later): no report
- New session after another 2-hour gap: new report

---

## Data Sources

### Memory Activity (`_get_memory_activity`)

Queries `episodic_memories` and `semantic_memories` tables for records created or reinforced during the gap.

| Query | Table | Condition |
|-------|-------|-----------|
| New episodic | `episodic_memories` | `created_at BETWEEN gap_start AND gap_end` |
| New semantic | `semantic_memories` | `created_at BETWEEN gap_start AND gap_end` |
| Reinforced semantic | `semantic_memories` | `last_reinforced_at BETWEEN gap_start AND gap_end AND created_at < gap_start` |

**Example output:**
```xml
<memory_processing>
5 new episodic memories were created from recent conversations.
2 semantic memories were consolidated (1 new, 1 reinforced).
</memory_processing>
```

### Dream Activity (`_get_dream_activity`)

Queries `episodic_dreams` table for dreams that occurred during the gap. Typically 1 per night from the 4 AM cron.

| Column | Usage |
|--------|-------|
| `dream_type` | e.g. "emotional_processing", "daily_consolidation" |
| `mood` | e.g. "contemplative", "curious" |
| `theme` | Brief theme description |
| `takeaway` | Key insight from the dream |

**Example output:**
```xml
<dream_session>
You dreamed last night (emotional_processing). Mood: contemplative. Theme: connection and distance.
Takeaway: Sometimes the most meaningful conversations happen in comfortable silence.
</dream_session>
```

### Service Events (`_get_service_events`)

Queries the `service_events` table for lifecycle events during the gap: startups, shutdowns, crashes, GPU swaps, and nightly pipeline runs.

| event_type | Logged By | When |
|------------|-----------|------|
| `startup` | `app/main.py` (lifespan) | Iris server starts |
| `shutdown` | `app/main.py` (lifespan) | Iris server stops |
| `crash_detected` | `core/service_status.py` (background refresh) | Service transitions from running to not-running |
| `service_swap` | `core/gpu_manager.py` | GPU 0 service swap completes |
| `dream_start` / `dream_end` | `scripts/nightly_dream.sh` | Nightly dream pipeline |
| `memory_start` / `memory_end` | `scripts/nightly_memory_creation.sh` | Nightly memory pipeline |
| `semantic_start` / `semantic_end` | `scripts/nightly_semantic_consolidation.sh` | Nightly semantic consolidation |

**Example output:**
```xml
<service_health>
- Iris Server started at 3:15 AM.
- GPU swap: vision→freud at 4:00 AM.
- Nightly Dream started at 4:00 AM.
- Nightly Dream completed at 4:28 AM. Dream creation successful for 2026-02-06
- GPU swap: freud→vision at 4:29 AM.
- No unexpected crashes or errors detected.
</service_health>
```

If no crashes occurred, a "No unexpected crashes" line is appended. Sections with no data are omitted entirely.

---

## Database Schema

### `service_events` table

```sql
CREATE TABLE IF NOT EXISTS service_events (
    id              SERIAL PRIMARY KEY,
    event_type      VARCHAR(50) NOT NULL,
    service_name    VARCHAR(100) NOT NULL,
    source          VARCHAR(50) NOT NULL,
    detail          TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_service_events_created ON service_events(created_at DESC);
```

SQL file: `database/sql/create_service_events_table.sql`

### Configuration (category `gap_report`)

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `GAP_REPORT_ENABLED` | bool | true | Master switch for gap reports |
| `GAP_REPORT_MIN_GAP_MINUTES` | int | 30 | Minimum gap to trigger a report |

SQL file: `database/sql/add_gap_report_config.sql`

---

## Service Event Logger

`database/service_events.py` provides a single fire-and-forget function:

```python
from database.service_events import log_service_event

log_service_event("startup", "iris_server", "lifespan")
log_service_event("service_swap", "vision→freud", "gpu_manager")
log_service_event("crash_detected", "iris_vision", "background_health",
                  "Transitioned from running to stopped")
```

**Never raises.** All errors are silently swallowed to avoid impacting the caller.

Shell scripts use a local helper that calls psql directly:

```bash
log_service_event() {
    local event_type="$1" service_name="$2" source="$3" detail="$4"
    PGPASSWORD="$IRIS_DB_PASSWORD" psql -h localhost -U irisuser -d irisdb -c \
        "INSERT INTO service_events (event_type, service_name, source, detail) \
         VALUES ('$event_type', '$service_name', '$source', '$detail');" \
        >> "$LOG_FILE" 2>&1 || true
}
```

---

## Crash Detection

`core/service_status.py` runs a background health check every 60 seconds. It tracks previous service states and logs `crash_detected` when a service transitions from "running" to any other state — **unless** the GPU manager is currently switching services (to avoid false positives during intentional swaps).

---

## Token Budget Impact

~100-200 tokens when active (first turn only). Comparable to the emotional state section. Zero impact on subsequent turns. Well within the per-turn tail budget.

---

## Files

| File | Role |
|------|------|
| `core/gap_report.py` | Gap report builder — queries DB, formats XML, first-turn gating |
| `database/service_events.py` | `log_service_event()` fire-and-forget helper |
| `database/sql/create_service_events_table.sql` | Table DDL |
| `database/sql/add_gap_report_config.sql` | Config keys |
| `core/system_prompt.py` | Integration point in `build_per_turn_context()` |
| `core/service_status.py` | Crash detection in background refresh loop |
| `core/gpu_manager.py` | GPU swap event logging |
| `app/main.py` | Startup/shutdown event logging |
| `scripts/nightly_dream.sh` | Dream pipeline event logging |
| `scripts/nightly_memory_creation.sh` | Memory pipeline event logging |
| `scripts/nightly_semantic_consolidation.sh` | Semantic consolidation event logging |

---

## Verification

1. **Check service_events table:** `SELECT * FROM service_events ORDER BY created_at DESC LIMIT 20;`
2. **Manual test:** Call `build_gap_report(gap_start, gap_end, session_id)` directly with timestamps spanning known events.
3. **End-to-end:** After a 30+ minute gap, send a message and check `/prompt` for `<while_you_were_away>` in the payload.
4. **First-turn gating:** Send two messages after a gap. Only the first should contain the report.
5. **Empty gap:** If nothing happened during the gap, no XML tag should appear.
