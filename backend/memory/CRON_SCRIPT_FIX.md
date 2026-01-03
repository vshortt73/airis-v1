# Cron Script Fix: Two-Step Memory Pipeline

## Problem

The nightly memory creation cron job (`/iris-v3/scripts/nightly_memory_creation.sh`) was only running the **memory creation** step, but it was missing the critical **topic segmentation** step that must run first.

Without topic segmentation, there are no topics to evaluate for memory creation!

## The Two-Step Pipeline

The memory system requires two sequential steps:

### Step 1: Topic Segmentation
**Script**: `/iris-v3/backend/memory/new/topic_segmentation.py`

**What it does**:
- Analyzes chat_history to identify conversation topic boundaries using LLM
- Assigns `topic_id` to each message based on detected boundaries
- Generates descriptive titles (`conv_title`) for each topic
- Updates chat_history with topic assignments

**Example**:
```
Input: 100 chat messages (no topics assigned)
Output: Messages grouped into 8 topics with IDs and titles
  - Topic 1: "Python Installation" (messages 0-15)
  - Topic 2: "Database Connection Issues" (messages 16-42)
  - Topic 3: "API Design Discussion" (messages 43-99)
  ...
```

### Step 2: Memory Creation
**Script**: `/iris-v3/backend/memory/new/memory_creation.py`

**What it does**:
- Finds topics that haven't been processed yet (`memory_processed_at IS NULL`)
- Evaluates each topic for "worthiness" using psychological scoring
- Creates episodic_memory entries for worthy topics
- Marks ALL topics as processed (whether worthy or not)

**Example**:
```
Input: 8 unprocessed topics
Processing:
  - Topic 1: Not worthy (too brief) → marked as processed
  - Topic 2: Worthy → created memory #123, marked as processed
  - Topic 3: Worthy → created memory #124, marked as processed
  - Topic 4: Not worthy (low significance) → marked as processed
  ...
Output: 3 new memories created from 8 topics
```

## Fix Applied

Updated `/iris-v3/scripts/nightly_memory_creation.sh` to run BOTH steps:

### Before (BROKEN)
```bash
# PHASE 3: Run memory creation
run_memory_creation()  # ✗ No topics exist to process!
```

### After (FIXED)
```bash
# PHASE 3A: Run topic segmentation
run_topic_segmentation()  # ✓ Creates topics from chat logs

# PHASE 3B: Run memory creation
run_memory_creation()     # ✓ Evaluates newly created topics
```

## Changes Made

**1. Added topic segmentation script path**:
```bash
TOPIC_SEGMENTATION_SCRIPT="$PROJECT_ROOT/backend/memory/new/topic_segmentation.py"
```

**2. Added pre-flight check**:
```bash
if [ ! -f "$TOPIC_SEGMENTATION_SCRIPT" ]; then
    log_error "Topic segmentation script not found: $TOPIC_SEGMENTATION_SCRIPT"
    exit 1
fi
```

**3. Added topic segmentation function**:
```bash
run_topic_segmentation() {
    log "STEP 1/2: RUNNING TOPIC SEGMENTATION"
    "$VENV_PYTHON" "$TOPIC_SEGMENTATION_SCRIPT" 2>&1 | tee -a "$LOG_FILE"
    # Returns exit code
}
```

**4. Updated memory creation to Step 2/2**:
```bash
run_memory_creation() {
    log "STEP 2/2: RUNNING MEMORY CREATION"
    "$VENV_PYTHON" "$MEMORY_SCRIPT" 2>&1 | tee -a "$LOG_FILE"
    # Returns exit code
}
```

**5. Updated orchestration to run both steps**:
```bash
# PHASE 3A: Run topic segmentation
if ! run_topic_segmentation; then
    log_error "Topic segmentation failed - ABORTING memory creation"
    # Cleanup and exit
    exit 1
fi

# PHASE 3B: Run memory creation
run_memory_creation
```

**6. Enhanced statistics tracking**:
```bash
# Extract statistics
memories_created=$(grep -oP "Created: \K\d+" "$MEMORY_OUTPUT")
topics_segmented=$(grep -oP "Topics identified: \K\d+" "$LOG_FILE" | tail -1)

# Report to Iris
insert_system_message "Memory processing completed: $memories_created new memories created from $topics_segmented topics."
```

## Error Handling

If topic segmentation fails:
1. Abort memory creation (no point without topics)
2. Stop llama.cpp engine
3. Restart Ollama services
4. Notify Iris of the failure
5. Exit with error code

If memory creation fails:
1. Topic segmentation results are preserved (topics still assigned)
2. Ollama services are still restored
3. Next run will process the already-segmented topics

## Testing the Fix

### Manual Test
```bash
# Set password
export IRIS_DB_PASSWORD='your_password'

# Run the full script
/iris-v3/scripts/nightly_memory_creation.sh
```

Watch the logs for:
```
STEP 1/2: RUNNING TOPIC SEGMENTATION
✓ Topic segmentation completed successfully
STEP 2/2: RUNNING MEMORY CREATION
✓ Memory creation completed successfully
Topics segmented: 12
Memories created: 5
```

### Check Cron Job
```bash
# View crontab
crontab -l

# Should have something like:
# 0 3 * * * /iris-v3/scripts/nightly_memory_creation.sh
```

### Verify Next Run
After cron runs, check the logs:
```bash
# View most recent log
ls -lht /iris-v3/logs/memory_creation/
tail -100 /iris-v3/logs/memory_creation/nightly_*.log
```

## Impact

**Before this fix**:
- Cron job ran nightly but found 0 topics to process (because topics were never created)
- Chat history accumulated without topic assignments
- No memories were ever created

**After this fix**:
- Cron job segments chat logs into topics
- Evaluates topics and creates memories
- Both steps tracked in logs with statistics

## Files Changed

- `/iris-v3/scripts/nightly_memory_creation.sh` - Added topic segmentation step
- `/iris-v3/backend/memory/CRON_SCRIPT_FIX.md` - This documentation

## Related Documentation

- `/iris-v3/backend/memory/PROCESSING_TRACKING_FIX.md` - Processing tracking to prevent re-evaluation
- `/iris-v3/scripts/README_NIGHTLY_MEMORY.md` - Original cron job documentation
