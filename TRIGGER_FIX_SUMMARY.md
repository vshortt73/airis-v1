# Trigger System Diagnosis and Fix Summary

## Problem Identified

The live_memories update system was failing due to **two issues**:

### Issue 1: Wrong Model Name (FIXED ✅)
- **Problem**: Python script was trying to use `mistral-small-3.2-24b` which doesn't exist
- **Available**: `mistral-small3.2:latest`
- **Fix Applied**: Updated `/iris-v2/utilities/v4_memory/v3_facet_memory.py` to use correct model name
- **Backup**: Created at `/iris-v2/utilities/v4_memory/v3_facet_memory.py.backup`

### Issue 2: Log File Permissions (NEEDS FIX ⚠️)
- **Problem**: Log file `/iris-v2/tmp/wrapper_debug.log` has restrictive permissions (600, captain:root)
- **Impact**: PostgreSQL trigger runs as `postgres` user and cannot write to log
- **Result**: Wrapper script silently fails when trying to log
- **Status**: Script probably runs but can't write logs

## What Was Done

### 1. Added Comprehensive Logging
- Created `trigger_log` table in database to track trigger execution
- Updated trigger function to `python_memory_trigger_v2()` with detailed logging
- Every trigger fire, counter increment, and script execution is now logged in the database

### 2. Fixed Model Name
- Changed model references from `mistral-small-3.2-24b` to `mistral-small3.2:latest`
- Original file backed up

### 3. Created Monitoring Tools
- **`/iris-v3/scripts/check_trigger_status.sh`**: View trigger status, logs, and counters
- **`/iris-v3/scripts/test_trigger.sh`**: Insert test messages to trigger the system

### 4. Removed Duplicate Triggers
- Removed old `test_trigger_name` trigger
- Only `chat_history_python_trigger_v2` is active now

## Current Status

✅ **Trigger mechanism**: Working (logs show trigger fired and script was called)
✅ **Model name**: Fixed
✅ **Database logging**: Working
⚠️ **Wrapper script logging**: Blocked by permissions
❓ **live_memories updates**: Unclear (need to verify after fixing permissions)

## How to Fix

### Quick Fix (Run these commands):

```bash
# Fix log file permissions
sudo chmod 666 /iris-v2/tmp/wrapper_debug.log

# Or create a new log file with proper permissions
sudo touch /var/log/iris_memory_trigger.log
sudo chmod 666 /var/log/iris_memory_trigger.log
sudo chown postgres:postgres /var/log/iris_memory_trigger.log

# Update wrapper script to use new log location
sudo sed -i 's|/iris-v2/tmp/wrapper_debug.log|/var/log/iris_memory_trigger.log|g' /var/lib/postgresql/scripts/run_processing.sh
```

### Test After Fix:

```bash
# 1. Check current status
/iris-v3/scripts/check_trigger_status.sh

# 2. If counter is not at 0, reset it
psql -h localhost -U irisuser -d irisdb -c "UPDATE insert_counter SET count_value = 0 WHERE table_name = 'chat_history';"

# 3. Run test (inserts 10 messages to trigger batch)
/iris-v3/scripts/test_trigger.sh

# 4. Wait a few seconds, then check logs
tail -f /var/log/iris_memory_trigger.log  # or the log file you're using

# 5. Verify live_memories was updated
psql -h localhost -U irisuser -d irisdb -c "SELECT * FROM live_memories ORDER BY injected_at DESC LIMIT 5;"
```

## Monitoring Going Forward

### Check Trigger Status:
```bash
/iris-v3/scripts/check_trigger_status.sh
```

### View Database Logs:
```bash
psql -h localhost -U irisuser -d irisdb -c "SELECT * FROM trigger_log ORDER BY event_time DESC LIMIT 20;"
```

### Watch Wrapper Log:
```bash
tail -f /var/log/iris_memory_trigger.log  # or wherever you set the log
```

### Check Live Memories:
```bash
psql -h localhost -U irisuser -d irisdb -c "SELECT COUNT(*), MAX(injected_at) FROM live_memories;"
```

## System Architecture

### Trigger Flow:
1. **INSERT** into `chat_history`
2. **Trigger fires**: `python_memory_trigger_v2()`
3. **Counter increments**: Tracked in `insert_counter` table
4. **At count 10**: Calls `/var/lib/postgresql/scripts/run_processing.sh`
5. **Wrapper script**:
   - Activates venv `/venv/iris-venv/`
   - Runs `/iris-v2/utilities/v4_memory/v3_facet_memory.py`
   - Logs to `/iris-v2/tmp/wrapper_debug.log` (or new location)
6. **Python script**:
   - Uses Ollama model `mistral-small3.2:latest`
   - Processes recent messages
   - Updates `live_memories` table

### Batch Size:
- Current setting: **10 messages** per trigger
- Configurable in trigger function: `trigger_batch_size = 10`

## Files Modified

1. `/iris-v2/utilities/v4_memory/v3_facet_memory.py` - Fixed model name
2. Database function `python_memory_trigger_v2()` - Added logging
3. Created `/iris-v3/scripts/check_trigger_status.sh` - Status monitoring
4. Created `/iris-v3/scripts/test_trigger.sh` - Testing tool
5. Created `trigger_log` table - Stores trigger execution history

## Next Steps

1. Fix log file permissions (see commands above)
2. Test the system with `/iris-v3/scripts/test_trigger.sh`
3. Verify live_memories is being updated
4. Monitor with `/iris-v3/scripts/check_trigger_status.sh`
5. Consider adjusting batch size if needed (currently 10 messages)
