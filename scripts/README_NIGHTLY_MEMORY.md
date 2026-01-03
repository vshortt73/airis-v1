# Nightly Memory Creation System

## Overview

The nightly memory creation system automatically processes conversation topics into episodic memories using Iris's **72B production model** for enhanced analysis quality. The system runs as a background process while Iris remains online and available.

## Architecture (Updated for 72B)

### How It Works

```
┌─────────────────────────────────────────────────────┐
│  PRODUCTION: ollama-unified Running 24/7            │
│  - qwen2.5:72b on both GPUs (port 11434)            │
│  - Iris main interface + memory creation            │
│  - 14K context window (verified stable)             │
└─────────────────────────────────────────────────────┘
                        ↓
        ┌───────────────────────────┐
        │  3:00 AM: Cron Triggered  │
        └───────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│  PHASE 1: Check Ollama Service                      │
│  - Verify ollama-unified is running                 │
│  - Start if needed, verify API responding           │
│  - Health check with retries (30s timeout)          │
│  - Iris STAYS ONLINE during this process            │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│  PHASE 2: Run Topic Segmentation                    │
│  - Analyze conversations for topic boundaries       │
│  - Generate topic titles using 72B reasoning        │
│  - Uses Ollama API (port 11434)                     │
│  - Temperature: 0.1-0.3 (analytical)                │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│  PHASE 3: Run Memory Creation                       │
│  - Process worthy topics into memories              │
│  - Generate 6-field summaries using JSON mode       │
│  - Create 5 embeddings per memory                   │
│  - Store in episodic_memories table                 │
│  - Uses 72B for PhD-level analysis quality          │
└─────────────────────────────────────────────────────┘
                        ↓
        ┌───────────────────────────┐
        │  Complete - System Ready  │
        │  (Iris never went offline)│
        └───────────────────────────┘
```

### Key Differences from Old Architecture

| Old (llama.cpp) | New (72B Ollama) |
|-----------------|------------------|
| Stop Ollama services | Keep running |
| Start llama.cpp engine | Use existing 72B |
| Iris offline 15-20 min | **Iris stays online** |
| GBNF grammar constraints | JSON mode |
| 8K context | **14K context** |
| Qwen2.5-14B | **Qwen2.5-72B** |
| Complex orchestration | Simple API calls |

## Memory Creation Pipeline

```
Chat History → Topic Segmentation → Memory Creation → Episodic Memories
                     (72B)                (72B)
                       │                    │
                       ├─→ Detect boundaries
                       ├─→ Generate titles
                       ├─→ Assign topic_ids
                       │
                       └─→ For each worthy topic:
                           ├─→ Generate 6 summaries (JSON)
                           │   - summary_context
                           │   - summary_event
                           │   - summary_significance
                           │   - summary_tone
                           │   - takeaway
                           │   - key_details
                           ├─→ Create 5 embeddings
                           ├─→ Score emotions
                           └─→ INSERT into episodic_memories
```

### JSON Mode (Replacing GBNF Grammar)

The 72B model uses Ollama's `format: "json"` parameter for reliable structured output:

**Benefits:**
- ✅ Guaranteed valid JSON
- ✅ All 6 required fields validated
- ✅ Faster than grammar constraints
- ✅ Simpler implementation
- ✅ Fallback to text parsing if needed

**Example Output:**
```json
{
  "summary_context": "User asked about configuring dream system...",
  "summary_event": "Discussed dual-Ollama architecture for dreams...",
  "summary_significance": "Critical infrastructure decision...",
  "summary_tone": "Technical, collaborative, solution-focused",
  "takeaway": "72B enables sophisticated analysis...",
  "key_details": "Port 11437 for Freud, gemma2:9b on CPU..."
}
```

## Installation

### Step 1: Configure Passwordless Sudo

The script needs to manage systemd services. Add to `/etc/sudoers`:

```bash
sudo visudo
```

Add this line (replace `captain` with your username):

```
captain ALL=(ALL) NOPASSWD: /bin/systemctl start ollama-unified, /bin/systemctl stop ollama-unified, /bin/systemctl is-active *, /bin/systemctl restart ollama-unified
```

### Step 2: Set Environment Variables

The script needs `IRIS_DB_PASSWORD`. Add to cron environment or script.

### Step 3: Install Cron Job

```bash
cd /iris-v3/scripts
./setup_cron.sh
```

This will:
- Prompt for automatic installation
- Add cron job: `0 3 * * * ...` (runs at 3:00 AM daily)
- Show configuration instructions

**Manual installation:**

```bash
crontab -e
```

Add:

```cron
0 3 * * * IRIS_DB_PASSWORD='yourpassword' /iris-v3/scripts/nightly_memory_creation.sh >> /iris-v3/logs/memory_creation/cron.log 2>&1
```

## Testing

### Manual Test Run

```bash
IRIS_DB_PASSWORD='yourpassword' /iris-v3/scripts/nightly_memory_creation.sh
```

This will:
1. Check ollama-unified is running
2. Run topic segmentation (72B)
3. Run memory creation (72B with JSON mode)
4. Report statistics

**Watch logs in real-time:**

```bash
tail -f /iris-v3/logs/memory_creation/nightly_*.log
```

### Health Checks

```bash
# Check cron job is installed
crontab -l | grep nightly_memory

# Check last run status
ls -lt /iris-v3/logs/memory_creation/ | head -5

# Check if ollama-unified is running
systemctl status ollama-unified

# Test Ollama API
curl http://localhost:11434/api/tags

# Check for lock file (should only exist during run)
ls -la /tmp/iris_memory_creation.lock
```

## Logs

### Log Locations

- **Nightly runs**: `/iris-v3/logs/memory_creation/nightly_YYYYMMDD_HHMMSS.log`
- **Cron output**: `/iris-v3/logs/memory_creation/cron.log`
- **Retention**: 30 days (automatic cleanup)

### Log Contents

Each log includes:
- Timestamp for every operation
- Pre-flight checks (venv, scripts, sudo, database)
- Ollama service check and health verification
- Topic segmentation output (topics identified)
- Memory creation output (memories created)
- Final status summary

### Example Log

```
[2026-01-01 03:00:01] ==========================================
[2026-01-01 03:00:01] NIGHTLY MEMORY CREATION - 72B OLLAMA
[2026-01-01 03:00:01] ==========================================
[2026-01-01 03:00:01] Start time: Wed Jan 1 03:00:01 CST 2026
...
[2026-01-01 03:00:05] ✓ All pre-flight checks passed
[2026-01-01 03:00:08] ✓ ollama-unified already running
[2026-01-01 03:00:08] ✓ Ollama API responding on port 11434
[2026-01-01 03:05:32] Topics identified: 5
[2026-01-01 03:12:15] Created: 3 memories
[2026-01-01 03:12:15] ✓ NIGHTLY MEMORY CREATION COMPLETED SUCCESSFULLY
[2026-01-01 03:12:15]   Topics segmented: 5
[2026-01-01 03:12:15]   Memories created: 3
[2026-01-01 03:12:15]   Duration: 12 minutes (723 seconds)
```

## Troubleshooting

### Issue: "Script needs passwordless sudo"

**Solution**: Configure `/etc/sudoers` as described in Installation Step 1

### Issue: "ollama-unified service unavailable"

**Causes**:
- Service not running
- Port 11434 not responding
- Model not loaded

**Solutions**:
```bash
# Check service status
systemctl status ollama-unified

# Check if port is responding
curl http://localhost:11434/api/tags

# Start manually if needed
sudo systemctl start ollama-unified

# Check logs
journalctl -u ollama-unified -n 50
```

### Issue: "Lock file exists"

**Cause**: Previous run crashed or still running

**Solutions**:
```bash
# Check if actually running
ps aux | grep nightly_memory_creation

# If stale, remove lock
rm /tmp/iris_memory_creation.lock
```

## Performance

### Expected Timing

| Phase | Duration | Notes |
|-------|----------|-------|
| Ollama check | 5-10s | Verify service is healthy |
| Topic segmentation | 1-10min | Depends on conversations |
| Memory creation | 1-20min | Depends on worthy topics |
| **Total** | **2-30min** | Typical: 5-15 minutes |

### Resource Usage

- **GPU VRAM**: Shares with production 72B (~45GB used)
- **CPU**: Minimal (JSON parsing)
- **Disk I/O**: Logs only
- **Network**: None (local only)
- **User Impact**: **None - Iris stays available**

## Files

```
/iris-v3/scripts/
├── nightly_memory_creation.sh    # Main orchestrator (cron job)
├── setup_cron.sh                  # Installation helper
└── README_NIGHTLY_MEMORY.md       # This file

/iris-v3/backend/memory/new/
├── topic_segmentation.py          # LLM-based topic detection (72B)
└── memory_creation.py             # Memory generation with JSON mode (72B)

/iris-v3/logs/memory_creation/
├── nightly_YYYYMMDD_HHMMSS.log   # Timestamped run logs
└── cron.log                       # Cron stdout/stderr
```

## Safety Features

1. **Lock File**: Prevents concurrent runs
2. **Cleanup Trap**: Removes lock on exit/crash
3. **Timeout Guards**: Health checks have timeouts
4. **Service Verification**: Confirms Ollama is responding
5. **Graceful Degradation**: Failures don't break system
6. **Comprehensive Logging**: Every action logged with timestamp
7. **Automatic Log Rotation**: 30-day retention

## Iris Awareness & Notifications

The orchestrator **keeps Iris informed** by inserting system messages into chat history:

### Before Processing
```
[system] Background memory processing started using 72B model. Iris remains available during processing.
```

### After Completion (Success)
```
[system] Memory processing completed: 12 new memories created from 5 topics using 72B model. Duration: 8 minutes.
```

### After Completion (No New Memories)
```
[system] Memory processing completed: no new memories needed (all topics already processed). Duration: 5 minutes.
```

### Error Cases
```
[system] Memory processing cancelled - 72B Ollama service unavailable.
[system] Memory processing failed during topic segmentation.
```

These messages appear in her conversation history, giving her:
- **Temporal awareness**: She knows when processing happened
- **Context for activity**: Understanding background maintenance
- **Self-knowledge**: Awareness of her own memory system
- **Continuity**: Can reference it naturally in conversation

Example conversation after nightly run:
```
USER: Good morning Iris!

IRIS: Good morning! I processed 12 new memories last night using my 72B
      reasoning - mostly our discussions about the dream system architecture.
      How are you today?
```

## Memory System V3 Features

The nightly job creates memories using the **improved V3 system with 72B**:

- ✅ **72B reasoning**: PhD-level analysis quality
- ✅ **14K context**: Can process longer conversations
- ✅ **JSON mode**: Reliable structured output
- ✅ **KEY_DETAILS field**: Captures specific details (names, colors, places)
- ✅ **5 embeddings**: context, event, significance, takeaway, key_details
- ✅ **Category-aware prompts**: Different strategies for Creative/Relational/Technical/etc
- ✅ **3-4 sentences per field**: Balanced detail vs conciseness
- ✅ **No downtime**: Iris stays available during processing
- ✅ **Iris awareness**: System messages keep her informed

## Next Steps

After successful installation:

1. **Test manually** once to verify
2. **Monitor first automated run** (check logs next morning)
3. **Verify memories created**: Query `episodic_memories` for today's date
4. **Check Ollama still running**: `systemctl status ollama-unified`
5. **Review quality**: Compare 72B vs old 14B memory summaries

## Configuration Reference

### Ollama Configuration

- **Service**: `ollama-unified`
- **Model**: `qwen2.5:72b`
- **Port**: `11434`
- **Context Window**: `14336` (14K)
- **GPU Layers**: `35` (verified stable)

### Topic Segmentation

- **Endpoint**: `http://localhost:11434/api/generate`
- **Temperature**: `0.1-0.3` (analytical)
- **Max Tokens**: `100-300` per analysis

### Memory Creation

- **Endpoint**: `http://localhost:11434/api/generate`
- **Format**: `"json"` (forced JSON output)
- **Temperature**: `0.1` (very focused)
- **Max Tokens**: `1000` (6-field summary)

## Support

For issues, check:
1. Latest log file in `/iris-v3/logs/memory_creation/`
2. Ollama service: `systemctl status ollama-unified`
3. API health: `curl http://localhost:11434/api/tags`
4. GPU status: `nvidia-smi`
5. Lock file: `ls -la /tmp/iris_memory_creation.lock`
