# Troubleshooting Guide

## Service Not Responding

```bash
# Check service status
ssh node2 'systemctl status iris-vision'
ssh node2 'systemctl status iris-sentiment'

# View logs
ssh node2 'journalctl -u iris-vision -n 50'

# Restart service
ssh node2 'sudo systemctl restart iris-vision'
```

## GPU Manager Issues

```bash
# Check current GPU state
curl http://localhost:8000/api/gpu/status | jq

# Force re-detect
curl -X POST http://localhost:8000/api/gpu/detect | jq

# Test SSH connectivity
ssh -o BatchMode=yes captain@node2 'echo OK'

# Test sudo access
ssh captain@node2 'sudo systemctl status iris-vision'
```

## Emotional State Not Updating

```bash
# Check sentiment service
curl http://node2:11437/health

# Test sentiment analysis
python -c "
import asyncio
from core.emotional_state import get_emotional_tracker
async def test():
    tracker = get_emotional_tracker()
    await tracker.load_state()
    result = await tracker.process_message('Hello!')
    print(result)
asyncio.run(test())
"
```

## Video Not Generating

1. Check GPU manager state: `curl http://localhost:8000/api/gpu/status`
2. Verify FLOAT is running: `curl http://node2:8000/`
3. Check TTS is enabled in browser (speech toggle)
4. Look for `[TTS] → Routing to VIDEO` in browser console

## Vision Returns "I cannot see images"

This error means the vision model received the request but couldn't process the image. Common causes:

1. **Wrong model running on port 11435** — Freud (text-only) instead of Vision
   ```bash
   ssh node2 'systemctl status iris-vision iris-freud'
   ```

2. **Vision service in crash loop** — OOM from another GPU 0 service hogging memory
   ```bash
   # Check for crash loop
   ssh node2 'journalctl -u iris-vision -n 20 | grep -E "(OOM|memory|restart|failed)"'

   # Check what's using GPU 0 memory
   ssh node2 'nvidia-smi --query-compute-apps=pid,name,used_memory --format=csv'
   ```

3. **ComfyUI or other service not stopped** — GPU Manager only stopped tracked service
   ```bash
   # Stop ALL GPU 0 services manually
   ssh node2 'sudo systemctl stop iris-vision iris-float iris-freud iris-transcribe comfyui'

   # Then restart just vision
   ssh node2 'sudo systemctl start iris-vision'
   ```

4. **Health check false positive** — Service responded to `/health` before model fully loaded
   ```bash
   # Check if model actually loaded (look for "ready" in logs)
   ssh node2 'journalctl -u iris-vision -n 50 | grep -E "(ready|loaded|warmup)"'
   ```

## Identifying GPU Processes

Node2 services use `setproctitle` (Python) or `exec -a` wrappers (llama-server) to show service names in nvidia-smi:

```bash
# nvidia-smi shows actual service names
ssh node2 'nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv'

# Output:
# pid, process_name, used_gpu_memory [MiB]
# 940483, iris-vision.service, 10756 MiB
# 941040, iris-sentiment.service, 4842 MiB
# 941316, iris-stt.service, 328 MiB
# 941502, iris-xtts.service, 1942 MiB
```

**Implementation:**
- Python services: `setproctitle.setproctitle("iris-xxx.service")` at top of entry point
- llama-server services: Wrapper scripts using `exec -a iris-xxx.service /programs/llama.cpp/...`

Wrapper locations:
- `/programs/vision/start.sh` - Vision service
- `/programs/llama.cpp/start-sentiment.sh` - Sentiment service

## Using the Distributed Health Tool

Iris has a `distributed_system_health` MCP tool for comprehensive diagnostics:

```bash
# Iris can call this tool, or test directly:
curl http://localhost:8000/api/tools/distributed_system_health | jq '.summary'
```

Returns: GPU memory per service (both nodes), service health status, systemd state, restart counts (crash loop detection), and GPU Manager state.

## Testing Commands

```bash
# Test database connection
python tests/test_database.py

# Test context inspection
curl http://localhost:8000/api/conversation/context/summary | jq

# Test MCP infrastructure
python mcp_servers/mcp_client.py
python mcp_servers/tool_manager.py

# Test GPU manager
python core/gpu_manager.py

# Test emotional state
python core/emotional_state.py

# Test Node2 services
curl http://node2:11435/health  # Vision/Freud
curl http://node2:8000/health   # FLOAT (returns HTML)
curl http://node2:8700/health   # XTTS
curl http://node2:8600/health   # STT
curl http://node2:11437/health  # Sentiment
curl http://node2:8500/health   # Transcribe (WhisperX)

# Test meeting transcription system
python tests/test_meeting.py
python tests/test_meeting.py --full  # includes transcription pipeline
```
