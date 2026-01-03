# Fix Session IDs Script

Recreates `session_id` values in `chat_history` based on conversation time gaps.

## Problem

If every chat message got a unique session_id (instead of grouping messages into conversations), this script will fix it by recreating proper session boundaries based on time gaps between messages.

## How It Works

1. Loads all messages from `chat_history` ordered by `c_timestamp`
2. Groups messages into sessions based on time gaps
3. If gap between messages ≥ 20 minutes → new session
4. If gap < 20 minutes → same session
5. Generates new UUIDs for each session group
6. Updates `chat_history.session_id` for all messages

## Usage

### Step 1: Preview Changes (Dry Run)
```bash
export IRIS_DB_PASSWORD='yourpassword'
cd /iris-v3
python backend/memory/new/fix_session_ids.py --dry-run
```

This will show:
- Current session distribution
- New session distribution
- How many sessions will be created
- NO database changes will be made

### Step 2: Apply Changes
```bash
python backend/memory/new/fix_session_ids.py --commit
```

This will actually update the database.

## Options

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `--gap` | int | 20 | Gap in minutes to trigger new session |
| `--dry-run` | flag | True | Preview changes without applying |
| `--commit` | flag | False | Actually apply changes to database |

## Examples

### Use 30-minute gap instead of 20
```bash
python backend/memory/new/fix_session_ids.py --gap 30 --dry-run
python backend/memory/new/fix_session_ids.py --gap 30 --commit
```

### Use 15-minute gap
```bash
python backend/memory/new/fix_session_ids.py --gap 15 --commit
```

## Expected Output

```
============================================================
SESSION ID FIX SCRIPT
============================================================
Gap threshold: 20 minutes
Mode: DRY RUN (no changes)
============================================================

[Loading] Fetching all messages from chat_history...
[Loading] ✓ Loaded 1523 messages

[Current State] Session distribution:
  Total sessions: 1523
  Total messages: 1523
    Sessions with 1 message(s): 1523

[Regrouping] Creating new sessions with 20-minute gap threshold...
  [Session 1] 47 messages (gap: 25.3 min)
  [Session 2] 12 messages (gap: 31.2 min)
  [Session 3] 89 messages (gap: 22.1 min)
  ...

[Regrouping] ✓ Created 42 sessions from 1523 messages

[New State] Session distribution:
  Total sessions: 42
  Total messages: 1523
    Sessions with 1 message(s): 3
    Sessions with 2 message(s): 5
    Sessions with 12 message(s): 2
    Sessions with 47 message(s): 1
    Sessions with 89 message(s): 1
    ...

[Dry Run] Would update session_id for all messages
[Dry Run] Use --commit to apply changes
============================================================
DRY RUN COMPLETE - No changes made
Run with --commit to apply these changes
============================================================
```

## After Running

Once you've fixed the session IDs, you should:

1. **Re-run the topic segmentation script** with proper sessions:
```bash
python backend/memory/new/topic_segmentation.py --analysis-model llama3.1:8b --limit 10
```

2. **Verify the new sessions**:
```sql
-- Count messages per session
SELECT session_id, COUNT(*) as message_count
FROM chat_history
GROUP BY session_id
ORDER BY message_count DESC
LIMIT 20;

-- View a sample session
SELECT c_timestamp, role, LEFT(message, 50) as preview
FROM chat_history
WHERE session_id = 'some-session-uuid'
ORDER BY c_timestamp;
```

## Safety

- Script defaults to `--dry-run` mode
- Must explicitly use `--commit` to make changes
- Creates new UUIDs for session_ids (doesn't reuse old ones)
- All messages are updated in a single transaction
- Original timestamps are not modified

## Troubleshooting

### Database Connection
Ensure `IRIS_DB_PASSWORD` is set:
```bash
export IRIS_DB_PASSWORD='yourpassword'
```

### Verify Changes
After running with --commit, check the results:
```sql
SELECT COUNT(DISTINCT session_id) as total_sessions,
       COUNT(*) as total_messages,
       AVG(session_size) as avg_messages_per_session
FROM (
    SELECT session_id, COUNT(*) as session_size
    FROM chat_history
    GROUP BY session_id
) subq;
```
