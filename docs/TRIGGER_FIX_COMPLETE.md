# Trigger System Complete Diagnosis and Fix

## Final Root Cause Analysis

The live_memories update system was failing due to **THREE cascading issues**:

### Issue 1: Wrong Ollama Model Name ✅ FIXED
- **Problem**: Python script used `mistral-small-3.2-24b` (doesn't exist)
- **Available**: `mistral-small3.2:latest`
- **Fix**: Updated model name in lines 230 and 271 of `/iris-v2/utilities/v4_memory/v3_facet_memory.py`

### Issue 2: Wrong Embedding Model Path ✅ FIXED
- **Problem**: Script looked for model at `/models/llm_models/huggingface/models/all-mpnet-base-v2/` (doesn't exist)
- **Actual Location**: `/home/captain/.cache/huggingface/hub/models--sentence-transformers--all-mpnet-base-v2/`
- **Fix**: Updated line 52 to use: `SentenceTransformer("all-mpnet-base-v2", cache_folder="/home/captain/.cache/huggingface/hub")`

### Issue 3: Cache Permission Error ⚠️ NEEDS FIX
- **Problem**: PostgreSQL trigger runs as `postgres` user, which cannot access `/home/captain/.cache/`
- **Error**: `PermissionError at /home/captain/.cache/huggingface/hub/models--sentence-transformers--all-mpnet-base-v2/refs`
- **Impact**: Script fails when triggered automatically, but works when run manually as captain
- **Status**: Requires sudo to fix

## What's Been Fixed

1. ✅ **Added Database Logging** (`trigger_log` table)
2. ✅ **Fixed Ollama Model Name** (mistral-small3.2:latest)
3. ✅ **Fixed Embedding Model Path** (use huggingface cache)
4. ✅ **Created Monitoring Tools** (check_trigger_status.sh, test_trigger.sh)
5. ✅ **Verified Script Works** (when run as captain user)
6. ⚠️ **Need Permission Fix** (for postgres user access)

## Files Modified

| File | Change | Backup |
|------|--------|--------|
| `/iris-v2/utilities/v4_memory/v3_facet_memory.py` | Fixed model names and paths | `.backup` file created |
| Database | Added `trigger_log` table | N/A |
| Database | Updated trigger function to `python_memory_trigger_v2()` | Old function remains |

## New Scripts Created

| Script | Purpose |
|--------|---------|
| `/iris-v3/scripts/check_trigger_status.sh` | Monitor trigger status and logs |
| `/iris-v3/scripts/test_trigger.sh` | Insert test messages to trigger system |
| `/iris-v3/scripts/fix_trigger_permissions.sh` | Fix log file permissions |
| `/iris-v3/scripts/fix_model_permissions.sh` | Fix model cache permissions for postgres |

## How to Complete the Fix

### Step 1: Fix Model Cache Permissions (Required)
```bash
sudo /iris-v3/scripts/fix_model_permissions.sh
```

### Step 2 (Optional): Fix Log File Permissions
```bash
sudo /iris-v3/scripts/fix_trigger_permissions.sh
```

### Step 3: Reset and Test
```bash
# Reset counter
export PGPASSWORD='yourpassword'
psql -h localhost -U irisuser -d irisdb -c "UPDATE insert_counter SET count_value = 0 WHERE table_name = 'chat_history';"

# Run test
/iris-v3/scripts/test_trigger.sh

# Wait for processing (script takes ~60 seconds)
sleep 65

# Check results
psql -h localhost -U irisuser -d irisdb -c "SELECT COUNT(*), MAX(injected_at) FROM live_memories;"
```

### Step 4: Verify Success
```bash
# Check trigger log
/iris-v3/scripts/check_trigger_status.sh

# Check wrapper log for success message
tail -30 /iris-v2/tmp/wrapper_debug.log
# Should show: "Python script completed successfully"

# Verify live_memories was updated recently
psql -h localhost -U irisuser -d irisdb -c "SELECT * FROM live_memories ORDER BY injected_at DESC LIMIT 5;"
```

## System Architecture

### Complete Flow:
1. **INSERT** into `chat_history` (via API or direct SQL)
2. **Trigger Fires**: `chat_history_python_trigger_v2()`
3. **Counter Increments**: Tracked in `insert_counter` table
4. **Database Logging**: Every event logged to `trigger_log` table
5. **At Count 10**: Calls `/var/lib/postgresql/scripts/run_processing.sh`
6. **Wrapper Script** (runs as postgres user):
   - Activates `/venv/iris-venv/`
   - Executes `/iris-v2/utilities/v4_memory/v3_facet_memory.py`
   - Logs to `/iris-v2/tmp/wrapper_debug.log` (after permissions fix)
7. **Python Script** (~60 seconds runtime):
   - Loads embedding model `all-mpnet-base-v2` from cache
   - Loads emotion models from `/models/misc/`
   - Queries last 15 messages from `chat_history`
   - Uses Ollama (`mistral-small3.2:latest`) to analyze conversation
   - Retrieves relevant memories from database
   - Ranks memories using multi-factor algorithm
   - **UPDATES `live_memories` table** with top 10 memories
8. **Counter Resets**: Ready for next batch

### Model Requirements:
- **Ollama Model**: `mistral-small3.2:latest` (✅ installed)
- **Embedding Model**: `all-mpnet-base-v2` (✅ cached)
- **Emotion Models**: In `/models/misc/` (✅ exist)
  - `emotion_model_balanced/`
  - `valence_model/`
  - `arousal_model/`

### Performance:
- **Trigger Overhead**: < 1ms per message
- **Batch Processing**: ~60 seconds for 10 messages
- **Batch Size**: Configurable (currently 10)

## Monitoring Commands

### Quick Status Check:
```bash
/iris-v3/scripts/check_trigger_status.sh
```

### Watch for Trigger Events:
```bash
watch -n 2 'psql -h localhost -U irisuser -d irisdb -c "SELECT * FROM trigger_log ORDER BY event_time DESC LIMIT 5;"'
```

### Monitor Wrapper Script:
```bash
tail -f /iris-v2/tmp/wrapper_debug.log
```

### Check Live Memories:
```bash
psql -h localhost -U irisuser -d irisdb -c "SELECT COUNT(*), MAX(injected_at) as last_update, MIN(injected_at) as first_update FROM live_memories;"
```

## Troubleshooting

### Trigger Not Firing?
```bash
# Check trigger exists
psql -h localhost -U irisuser -d irisdb -c "SELECT trigger_name FROM information_schema.triggers WHERE event_object_table = 'chat_history';"

# Check counter
psql -h localhost -U irisuser -d irisdb -c "SELECT * FROM insert_counter WHERE table_name = 'chat_history';"
```

### Script Not Running?
```bash
# Check wrapper script exists and is executable
ls -la /var/lib/postgresql/scripts/run_processing.sh

# Check Python script exists
ls -la /iris-v2/utilities/v4_memory/v3_facet_memory.py

# Test manually as captain
source /venv/iris-venv/bin/activate
cd /iris-v2/utilities/v4_memory
python3 v3_facet_memory.py
```

### Permission Errors?
```bash
# Check model cache permissions
ls -la /home/captain/.cache/huggingface/hub/models--sentence-transformers--all-mpnet-base-v2/refs

# Run fix script
sudo /iris-v3/scripts/fix_model_permissions.sh
```

### live_memories Not Updating?
```bash
# Check if script completed successfully
tail -50 /iris-v2/tmp/wrapper_debug.log | grep -E "(completed|ERROR|❌)"

# Check for database errors
psql -h localhost -U irisuser -d irisdb -c "SELECT * FROM trigger_log WHERE error IS NOT NULL ORDER BY event_time DESC LIMIT 5;"
```

## Expected Behavior After Fix

1. Every 10 messages inserted into `chat_history` triggers processing
2. `trigger_log` table shows each trigger event
3. Wrapper script logs to `/iris-v2/tmp/wrapper_debug.log`
4. Python script completes in ~60 seconds
5. `live_memories` table contains 10 most relevant memories
6. Timestamp in `live_memories.injected_at` is recent

## Configuration

### Change Batch Size:
Edit trigger function in database:
```sql
-- Change line: trigger_batch_size = 10
-- To: trigger_batch_size = 20  (or desired value)
```

### Change Number of Memories:
Default is 10 memories. To change:
```bash
# Edit the script
vim /iris-v2/utilities/v4_memory/v3_facet_memory.py
# Find: parser.add_argument("--top_k", type=int, default=10, ...)
# Change: default=10 to desired number
```

### Disable Memory Processing:
```sql
-- Drop the trigger
DROP TRIGGER chat_history_python_trigger_v2 ON chat_history;
```

## Contact/Notes

- Python script takes ~60 seconds due to model loading and Ollama API calls
- Normal operation: No errors in wrapper_debug.log
- The script silently fails if it can't connect to port 8083 (status API) - this is expected
- Backup created at: `/iris-v2/utilities/v4_memory/v3_facet_memory.py.backup`
