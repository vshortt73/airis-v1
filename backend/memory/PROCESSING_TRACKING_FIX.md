# Memory Processing Tracking Fix

## Problem

The memory creation pipeline had a critical issue: when topics were evaluated as "not worthy" of creating a memory, they were simply skipped without any tracking. This meant that every time the script ran, it would re-evaluate the same "not worthy" topics over and over, wasting computational resources.

## Solution

Instead of creating a separate tracking table, we added a simple `memory_processed_at` column to the existing `chat_history` table. This marks topics as processed regardless of whether they resulted in a memory being created.

### Changes Made

**1. Database Schema** (`add_memory_processed_column.sql`)
- Added `memory_processed_at TIMESTAMPTZ` column to `chat_history`
- `NULL` = topic not yet evaluated
- Non-NULL timestamp = topic evaluated at this time (may or may not have created a memory)
- Added indexes for efficient querying

**2. Code Updates** (`memory_creation.py`)
- Added `mark_topic_as_processed()` function to update the timestamp
- Modified `create_memory_from_topic()` to mark topics as processed **before** checking worthiness
- Updated `process_all_worthy_topics()` query to filter by `memory_processed_at IS NULL` instead of checking `episodic_memories` table

## Benefits

1. **Prevents Redundant Processing**: Topics are only evaluated once
2. **Simple Design**: No new tables, just one column
3. **Efficient Queries**: Indexed for fast lookups
4. **Clear Semantics**: NULL = unprocessed, timestamp = processed
5. **Historical Data**: Know when each topic was evaluated

## Migration Steps

### 1. Apply Database Migration

```bash
# Set database password
export IRIS_DB_PASSWORD='your_password'

# Run migration script
python /iris-v3/backend/memory/apply_processing_migration.py
```

Or manually apply the SQL:

```bash
export PGPASSWORD="$IRIS_DB_PASSWORD"
psql -h localhost -U iris -d iris -f /iris-v3/backend/memory/add_memory_processed_column.sql
```

### 2. Verify Migration

The migration script will show:
- Total topics in database
- Unprocessed topics (ready for evaluation)
- Already processed topics (if any)

### 3. Run Memory Creation Pipeline

The memory creation pipeline has TWO steps that must be run in order:

**Step 1: Topic Segmentation** (creates topics from chat logs)
```bash
python /iris-v3/backend/memory/new/topic_segmentation.py
```

**Step 2: Memory Creation** (evaluates topics and creates memories)
```bash
# Process all unprocessed topics
python /iris-v3/backend/memory/new/memory_creation.py

# Or with a limit for testing
python /iris-v3/backend/memory/new/memory_creation.py --limit 10

# Or a specific topic
python /iris-v3/backend/memory/new/memory_creation.py --session-id <uuid> --topic-id <id>
```

**Automated via Cron**: The nightly cron job (`/iris-v3/scripts/nightly_memory_creation.sh`) now runs BOTH steps automatically.

## Behavior After Migration

### Before
```
Run 1: Evaluate 100 topics → 30 worthy, 70 not worthy
Run 2: Evaluate 70 topics (same not worthy ones) → 0 worthy, 70 not worthy (wasted work!)
Run 3: Evaluate 70 topics (same not worthy ones) → 0 worthy, 70 not worthy (wasted work!)
```

### After
```
Run 1: Evaluate 100 topics → 30 worthy (marked), 70 not worthy (also marked)
Run 2: Evaluate 0 topics → nothing to process (all marked)
Run 3: Evaluate 0 topics → nothing to process (all marked)
```

## Useful Queries

### Find unprocessed topics
```sql
SELECT DISTINCT session_id, topic_id, COUNT(*) as message_count
FROM chat_history
WHERE topic_id IS NOT NULL
  AND topic_id != 0
  AND memory_processed_at IS NULL
GROUP BY session_id, topic_id
ORDER BY session_id, topic_id;
```

### Find topics processed in last 24 hours
```sql
SELECT DISTINCT session_id, topic_id, memory_processed_at,
       (SELECT COUNT(*) FROM episodic_memories em
        WHERE em.session_id = ch.session_id
          AND em.topic_id = ch.topic_id) as has_memory
FROM chat_history ch
WHERE memory_processed_at >= NOW() - INTERVAL '24 hours'
ORDER BY memory_processed_at DESC;
```

### Manually mark a topic as processed
```sql
UPDATE chat_history
SET memory_processed_at = NOW()
WHERE session_id = 'your-session-id' AND topic_id = 123;
```

### Reset processing status (for re-processing)
```sql
-- Reset ALL topics (use with caution!)
UPDATE chat_history SET memory_processed_at = NULL WHERE topic_id IS NOT NULL;

-- Reset specific topic
UPDATE chat_history SET memory_processed_at = NULL
WHERE session_id = 'your-session-id' AND topic_id = 123;
```

## Edge Cases Handled

1. **Topic worthy but memory creation fails**: Still marked as processed to prevent retry loops. Check logs and fix manually if needed.

2. **Topic evaluation fails**: Not marked as processed (exception occurs before marking), so will retry next run.

3. **Existing episodic_memories**: Topics that already have memories are still unprocessed in chat_history. They'll be evaluated once, see they're worthy, but the INSERT will be skipped (you may want to add UNIQUE constraint on episodic_memories to handle this).

## Future Enhancements

If you need to re-process topics (e.g., improved evaluation logic), you can:

1. Reset all topics: `UPDATE chat_history SET memory_processed_at = NULL`
2. Add a "processing version" column to track algorithm versions
3. Create a separate "processing_override" flag to force re-evaluation

## Files Changed

- `backend/memory/add_memory_processed_column.sql` - Database migration
- `backend/memory/apply_processing_migration.py` - Migration script
- `backend/memory/new/memory_creation.py` - Updated processing logic
- `backend/memory/PROCESSING_TRACKING_FIX.md` - This document
