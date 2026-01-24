# Iris v3 API Reference

## Overview

Iris v3 exposes 130+ API endpoints across multiple feature areas. The main server runs on port 8000.

---

## Chat & Conversation

| Method | Path | Description |
|--------|------|-------------|
| WebSocket | `/ws/chat` | Real-time chat with tool calling |
| POST | `/api/test` | Simple test endpoint |
| POST | `/api/ui/notify` | Broadcast UI notification |
| POST | `/api/system/trigger` | Trigger Iris from system event |

### WebSocket `/ws/chat`

**Send:**
```json
{
  "message": "Hello Iris",
  "images": ["data:image/jpeg;base64,..."],
  "documents": [{"content": "base64...", "filename": "doc.pdf"}],
  "sender": "user",
  "thinking": true
}
```

**Receive message types:**
- `start` - Generation started, includes `context_level`, `tokens`
- `chunk` - Text chunk from model
- `tool_executing` - Tool started, includes `tool_name`, `tool_icon`
- `tool_result` - Tool completed
- `done` - Generation complete
- `interrupted` - User stopped generation
- `error` - Error occurred

---

## Context & Sessions

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/conversation/context` | Full context with messages |
| GET | `/api/conversation/context/summary` | Token statistics only |
| GET | `/api/conversation/info` | Current conversation info |
| GET | `/api/conversation/messages` | Messages with verbose/summary status |
| GET | `/api/conversation/raw` | Exact context sent to model |
| GET | `/api/sessions/recent` | List recent sessions |
| POST | `/api/sessions/load/{session_id}` | Load existing session |
| POST | `/api/sessions/new` | Create new session |
| POST | `/api/sessions/clear` | Clear in-memory history |

---

## Text-to-Speech (TTS)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/tts/speak` | Generate speech (MP3) |
| POST | `/api/tts/speak_with_phonemes` | Speech with Rhubarb lip-sync |
| POST | `/api/tts/speak_with_whisperx` | Speech with WhisperX phonemes |
| POST | `/api/tts/speak_with_wav2vec2` | Speech with Wav2Vec2 phonemes |
| POST | `/api/tts/analyze_uploaded_audio` | Analyze audio for phonemes |

### POST `/api/tts/speak`
```json
{"text": "Hello world"}
```
Returns: `audio/mpeg` stream

---

## Speech-to-Text (STT)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/stt-upload` | Transcribe uploaded audio |
| GET | `/stt-health` | Check STT server health |

---

## Vision

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/vision/analyze` | Analyze single image |
| POST | `/api/vision/batch` | Analyze multiple images |
| GET | `/api/vision/status` | Vision system status |
| POST | `/api/vision/unload` | Force model unload |
| GET | `/api/vision/config` | Vision configuration |

### POST `/api/vision/analyze`
```json
{
  "image": "base64...",
  "prompt": "What do you see?"
}
```

---

## Video Streaming

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/video/upload-image` | Upload reference image |
| GET | `/api/video/saved-image` | Get saved reference path |
| POST | `/api/video/save-reference-image` | Save reference permanently |
| POST | `/api/video/start-session-saved` | Start with saved reference |
| POST | `/api/video/start-session` | Start with uploaded image |
| POST | `/api/video/queue-chunk` | Queue text for video |
| GET | `/api/video/session-status/{id}` | Session status |
| GET | `/api/video/chunk-status/{id}/{idx}` | Chunk status |
| GET | `/api/video/stream/{chunk_id}` | Stream video chunk |
| POST | `/api/video/end-session/{id}` | End session |
| GET | `/api/video/health` | Video system health |

### HLS Streaming

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/video/hls/{id}/playlist.m3u8` | HLS playlist |
| GET | `/api/video/hls/{id}/{filename}` | HLS segment |
| POST | `/api/video/hls/init/{id}` | Initialize HLS session |
| POST | `/api/video/hls/stream` | Generate HLS segments |
| POST | `/api/video/hls/complete/{id}` | Mark HLS complete |
| DELETE | `/api/video/hls/{id}` | Clean up HLS session |

---

## GPU Management

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/gpu/status` | Current GPU state |
| POST | `/api/gpu/request/{service}` | Request service (vision/float/freud) |
| POST | `/api/gpu/detect` | Re-detect running service |
| GET | `/api/gpu/services` | List available services |

### GET `/api/gpu/status`
```json
{
  "current_service": "vision",
  "state": "ready",
  "last_activity": "2026-01-24T12:00:00Z"
}
```

---

## Admin Console

### Service Management

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/services/all` | All service statuses |
| GET | `/api/admin/services/check` | Check specific service |
| POST | `/api/admin/services/control` | Start/stop/restart service |
| GET | `/api/admin/services/mcp` | MCP server status |
| GET | `/api/admin/services/face-monitor` | Face monitor status |

### Configuration

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/config` | Current configuration |
| POST | `/api/admin/config/update` | Update config value |
| POST | `/api/admin/config/reload` | Force config reload |

### Token Budget

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/token-budget` | Token budget info |
| POST | `/api/admin/token-budget/update` | Update budget config |
| POST | `/api/admin/summaries/backfill` | Trigger summary backfill |

### Stats & Logs

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/stats` | System statistics |
| GET | `/api/admin/logs/recent` | Recent log entries |
| GET | `/api/admin/logs/service/{name}` | Service journalctl logs |
| GET | `/api/admin/database/stats` | Database statistics |
| GET | `/api/admin/health/detailed` | Comprehensive health check |

### STT Configuration

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/stt/config` | STT configuration |
| POST | `/api/admin/stt/config` | Update STT config |
| POST | `/api/admin/stt/update-model` | Change Whisper model |

### Actions

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/admin/actions/clear-webcam-cache` | Clear webcam cache |
| POST | `/api/admin/actions/reset-face-presence` | Reset presence state |

---

## Protocols

| Method | Path | Description |
|--------|------|-------------|
| GET | `/protocols` | List all protocols |
| GET | `/protocols/{id}` | Get protocol by ID |
| POST | `/protocols` | Create protocol |
| PUT | `/protocols/{id}` | Update protocol |
| DELETE | `/protocols/{id}` | Delete protocol |
| POST | `/protocols/{id}/duplicate` | Duplicate protocol |
| GET | `/protocols/status/active` | Active protocol status |
| GET | `/protocols/options/instructions` | Available instructions |
| POST | `/protocols/instructions` | Create instruction |
| GET | `/protocols/options/traits` | Available traits |
| GET | `/protocols/options/tools` | Available tools |

---

## Face Recognition

### Persons

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/faces/persons` | List all persons |
| GET | `/api/faces/persons/{id}` | Get person by ID |
| POST | `/api/faces/persons` | Create person |
| PUT | `/api/faces/persons/{id}` | Update person |
| DELETE | `/api/faces/persons/{id}` | Delete person |
| POST | `/api/faces/persons/{id}/train` | Upload training images |
| GET | `/api/faces/persons/{id}/embeddings` | Get embeddings |

### Cameras

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/faces/cameras` | List all cameras |
| GET | `/api/faces/cameras/{id}` | Get camera by ID |
| POST | `/api/faces/cameras` | Create camera |
| PUT | `/api/faces/cameras/{id}` | Update camera |
| DELETE | `/api/faces/cameras/{id}` | Delete camera |
| GET | `/api/faces/cameras/{id}/test` | Test camera connection |

### Recognition

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/faces/recognize` | Recognize faces in image |
| POST | `/api/faces/recognize/camera/{id}` | Capture & recognize |
| GET | `/api/faces/presence` | Current presence state |
| GET | `/api/faces/stats` | Recognition statistics |
| GET | `/api/faces/monitoring/status` | Monitor status |
| POST | `/api/faces/webcam_frame` | Cache webcam frame |
| GET | `/api/faces/webcam_frame/status` | Webcam frame status |
| GET | `/api/faces/health` | Face system health |

---

## Ephemeral Chat

Stateless chat without persistence, OpenAI-compatible.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/ephemeral/servers` | Available inference servers |
| GET | `/api/ephemeral/health` | Service health |
| GET | `/api/ephemeral/models` | Model info |
| GET | `/api/ephemeral/tools` | Available tools |
| POST | `/api/ephemeral/chat` | Stateless chat |
| POST | `/api/ephemeral/vision` | Vision chat |

---

## Florence2 Vision

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/florence2/status` | Service status |
| GET | `/api/florence2/tasks` | Available tasks |
| POST | `/api/florence2/load` | Load model |
| POST | `/api/florence2/unload` | Unload model |
| POST | `/api/florence2/analyze` | Analyze image |
| POST | `/api/florence2/analyze/upload` | Analyze uploaded file |
| POST | `/api/florence2/caption` | Generate caption |
| POST | `/api/florence2/detect` | Detect objects |
| POST | `/api/florence2/ocr` | Extract text |
| POST | `/api/florence2/ground` | Phrase grounding |
| POST | `/api/florence2/segment` | Segmentation |
| POST | `/api/florence2/batch` | Multiple tasks |
| POST | `/api/florence2/cascade/caption-ground` | Caption then ground |

---

## PaddleOCR

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/ocr/status` | Service status |
| POST | `/api/ocr/load` | Load OCR engine |
| POST | `/api/ocr/unload` | Unload engine |
| POST | `/api/ocr/analyze` | Run OCR |
| POST | `/api/ocr/analyze/upload` | Analyze uploaded file |
| POST | `/api/ocr/detect` | Detect text regions only |
| POST | `/api/ocr/batch` | Batch OCR |
| POST | `/api/ocr/text` | Extract text only |
| POST | `/api/ocr/spatial` | Text with spatial layout |
| GET | `/api/ocr/health` | Health check |

---

## Common Response Patterns

### Success
```json
{
  "success": true,
  "data": {...}
}
```

### Error
```json
{
  "success": false,
  "error": "Error message"
}
```

### Streaming
Many endpoints support streaming responses via:
- Server-Sent Events (SSE)
- WebSocket
- Chunked transfer encoding

---

*Last updated: 2026-01-24*
