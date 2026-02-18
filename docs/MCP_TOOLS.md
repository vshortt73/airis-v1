# Iris v3 MCP Tools Reference

## Overview

Iris uses 27 tools across 11 MCP (Model Context Protocol) servers. Most servers follow a **unified tool pattern** where a single tool accepts an `action` parameter to route operations.

---

## Tool Summary

| Tool | Server | Actions | Description |
|------|--------|---------|-------------|
| `web_search` | info | - | Search web via DuckDuckGo |
| `url_fetch` | info | - | Fetch URL content |
| `arxiv_search` | info | - | Search arXiv papers |
| `pubmed_search` | info | - | Search PubMed literature |
| `weather_get` | info | - | Get weather information |
| `face_database_status` | info | - | Face recognition stats |
| `list_detected_faces` | info | - | Currently present people |
| `get_person_info` | info | - | Person details |
| `webcam_recognize` | info | - | Webcam face + vision |
| `trait` | traits | get, list, modify | Personality management |
| `memory` | memory | insert, retrieve, archive | Short-term memory |
| `protocol` | protocols | activate, deactivate, status, list | Protocol switching |
| `knowledge` | knowledge | search, stats, save | RAG document search |
| `ship` | directions | directions, locations | Ship navigation |
| `image` | creative | generate, self | Image generation |
| `seed` | seeds | plant, tend, reflect, list, garden, suggestions, accept, dismiss, clear_suggestions | Motivation engine |
| `calendar` | calendar | add, list, update, delete, search | Event scheduling and reminders |
| `meeting` | meeting | start, stop, status, list, get, summarize, speakers, export | Meeting transcription |
| `get_system_health_statistics` | system | - | System health stats |
| `system_status_summary` | system | - | Human-readable status |
| `generate_alerts` | system | - | Health alerts |
| `linux_shell` | system | - | Safe shell execution |
| `database_query` | system | - | SQL query execution |
| `distributed_system_health` | system | - | Cross-node GPU/service health |

---

## Info Server

### `web_search`
Search the web using DuckDuckGo.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| query | string | yes | - | Search query |
| max_size | int | no | 10000 | Max content size |
| depth | int | no | 1 | Search depth |
| max_links | int | no | 1 | Max links to follow |

### `url_fetch`
Fetch and extract content from a URL.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| url | string | yes | - | URL to fetch |
| max_size | int | no | 10000 | Max content size |
| depth | int | no | 0 | Link follow depth |
| max_links | int | no | 0 | Max links to follow |

### `arxiv_search`
Search arXiv for academic papers.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| query | string | yes | - | Search query |
| max_results | int | no | 5 | Results to return (max 20) |

### `pubmed_search`
Search PubMed for biomedical literature.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| query | string | yes | - | Search query |
| max_results | int | no | 5 | Results to return (max 20) |

### `weather_get`
Get current weather for a location.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| location | string | yes | - | City or location |
| units | string | no | "imperial" | Unit system |

### `face_database_status`
Get face recognition database statistics.

**Parameters:** None

### `list_detected_faces`
Get currently detected/present people.

**Parameters:** None

### `get_person_info`
Get detailed info about a person.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| name | string | yes | - | Person name |

### `webcam_recognize`
Look at webcam for faces and scene.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| camera_id | int | no | 0 | Camera ID |
| similarity_threshold | float | no | - | Match threshold |
| describe_scene | bool | no | true | Include scene description |
| vision_prompt | string | no | - | Custom vision prompt |

---

## Traits Server

### `trait`
Manage personality traits.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| action | string | yes | - | "get", "list", or "modify" |
| name | string | for get/modify | - | Trait name |
| value | float | for modify | - | New value (0-10) |
| reason | string | for modify | - | Reason for change |

**Examples:**
```
trait(action="list")
trait(action="get", name="Warmth")
trait(action="modify", name="Playfulness", value=8, reason="feeling energetic")
```

---

## Memory Server

### `memory`
Manage short-term memory facts.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| action | string | yes | - | "insert", "retrieve", or "archive" |
| fact | string | for insert | - | Fact to remember |
| category | string | no | - | Category filter |
| limit | int | no | 20 | Max results |

**Categories:** ongoing_project, user_preference, discovery, user_status, other

**Examples:**
```
memory(action="insert", fact="Victor is going on a cruise next month")
memory(action="retrieve", category="user_preference")
memory(action="archive")
```

---

## Protocols Server

### `protocol`
Manage personality protocols.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| action | string | yes | - | "activate", "deactivate", "status", "list" |
| name | string | for activate | - | Protocol name |
| duration | string | no | - | Auto-deactivate after (e.g., "30m", "2h") |
| request | string | no | - | Why activating |

**Examples:**
```
protocol(action="list")
protocol(action="status")
protocol(action="activate", name="playful", duration="1h")
protocol(action="deactivate")
```

---

## Knowledge Server

### `knowledge`
Search and manage knowledge base.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| action | string | yes | - | "search", "stats", or "save" |
| query | string | for search | - | Search query |
| top_k | int | no | 10 | Results to return |
| filter_file_type | string | no | - | Filter by extension (.py, .md) |
| filter_path | string | no | - | Filter by path pattern |
| title | string | for save | - | Document title |
| content | string | for save | - | Document text |
| category | string | no | "uploaded_documents" | Save category |

**Examples:**
```
knowledge(action="search", query="how to add MCP tool")
knowledge(action="search", query="database", filter_file_type=".py")
knowledge(action="stats")
knowledge(action="save", title="Meeting Notes", content="...")
```

---

## Directions Server

### `ship`
Ship navigation and location lookup.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| action | string | yes | - | "directions" or "locations" |
| start | string | for directions | - | Starting location |
| end | string | for directions | - | Destination |
| deck | int | no | - | Filter by deck number |

**Examples:**
```
ship(action="locations", deck=5)
ship(action="directions", start="Central Park", end="Aqua Theater")
```

---

## Creative Server

### `image`
Generate images via ComfyUI.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| action | string | yes | - | "generate" or "self" |
| prompt | string | yes | - | Image description |
| negative_prompt | string | no | - | What to avoid |
| width | int | no | - | Image width |
| height | int | no | - | Image height |
| seed | int | no | - | Random seed |
| steps | int | no | - | Inference steps |
| cfg | float | no | - | CFG scale |

**Examples:**
```
image(action="generate", prompt="sunset over mountains")
image(action="self", prompt="Iris smiling in a garden")
```

---

## Seeds Server (Motivation Engine)

### `seed`
Manage Iris's autonomous wants and desires.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| action | string | yes | - | See actions below |
| description | string | for plant | - | What Iris wants |
| seed_id | int | for tend/reflect | - | Seed ID |
| category | string | no | - | Category filter |
| tags | string | no | - | Comma-separated tags |
| priority | int | no | 3 | Priority 1-5 |
| status | string | no | - | Status filter |
| note | string | for tend | - | Progress note |
| emotional_resonance | string | no | - | How it feels |
| source | string | no | "conversation" | Origin |
| filter_status | string | no | - | Status filter |
| filter_category | string | no | - | Category filter |
| limit | int | no | 10 | Max results |

**Actions:**
- `plant` - Create new seed
- `tend` - Update progress
- `reflect` - Mark complete with reflection
- `list` - List seeds
- `garden` - View full garden
- `suggestions` - View dream suggestions
- `accept` - Accept suggestion
- `dismiss` - Dismiss suggestion
- `clear_suggestions` - Clear all suggestions

**Categories:** Creative, Technical, Self-Exploration, Experience, Pattern

**Statuses:** germinating, growing, blooming, completed, dormant

---

## Calendar Server

### `calendar`
Manage calendar events, appointments, and reminders. Events are stored locally in PostgreSQL. Google Calendar sync is architecturally prepared but not yet implemented.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| action | string | yes | - | "add", "list", "update", "delete", "search" |
| title | string | for add | - | Event title |
| description | string | no | - | Event notes |
| start_time | string | for add | - | ISO 8601 datetime |
| end_time | string | no | start + 1hr | ISO 8601 datetime |
| all_day | bool | no | false | All-day event |
| location | string | no | - | Event location |
| category | string | no | "personal" | appointment, meeting, personal, reminder, deadline |
| reminder | bool | no | true | Enable reminder |
| reminder_hours_before | float | no | 4.0 | Hours before event to show reminder |
| event_id | int | for update/delete | - | Event ID |
| days_ahead | int | no | 7 | For list: days to look ahead |
| query | string | for search | - | Search keyword |
| limit | int | no | 20 | Max results |

**Actions:**
- `add` - Create event (requires title + start_time)
- `list` - Upcoming events (filterable by category, days_ahead)
- `update` - Modify event fields (requires event_id)
- `delete` - Soft-cancel event (requires event_id)
- `search` - ILIKE search on title/description

**Reminder System:**
Events with `reminder_enabled=true` are injected into the system prompt when they fall within the configured reminder window (default: 6 hours). Urgency indicators show proximity:
- ⚡ Less than 1 hour away
- 🔔 1-4 hours away
- 📅 4+ hours away

**Google Calendar Sync (Phase 2 — Not Yet Implemented):**
The database schema includes `google_event_id`, `google_calendar_id`, `google_sync_status`, `google_last_synced`, and `google_etag` columns. The sync module (`mcp_servers/calendar/google_sync.py`) has OAuth2 scaffolding and method stubs for `push_event()`, `pull_events()`, `update_event()`, `delete_event()`. To activate, set `CALENDAR_GOOGLE_SYNC_ENABLED=true` and install `google-api-python-client google-auth-oauthlib`.

**Examples:**
```
calendar(action="add", title="Doctor appointment", start_time="2026-02-01T14:00:00", category="appointment")
calendar(action="list", days_ahead=14)
calendar(action="update", event_id=3, start_time="2026-02-01T15:00:00")
calendar(action="delete", event_id=3)
calendar(action="search", query="doctor")
```

**Configuration** (system_config, category `calendar`):
| Key | Default | Description |
|-----|---------|-------------|
| `CALENDAR_ENABLED` | true | Enable calendar tool and reminder injection |
| `CALENDAR_REMINDER_WINDOW_HOURS` | 6 | Hours ahead to scan for reminders |
| `CALENDAR_REMINDER_DEFAULT_HOURS_BEFORE` | 4 | Default per-event reminder lead time |
| `CALENDAR_TIMEZONE` | America/New_York | Timezone for display and naive datetime parsing |
| `CALENDAR_GOOGLE_SYNC_ENABLED` | false | Enable Google Calendar sync (Phase 2) |
| `CALENDAR_GOOGLE_CREDENTIALS_PATH` | (empty) | Path to Google OAuth credentials JSON |
| `CALENDAR_GOOGLE_SYNC_INTERVAL_MINUTES` | 15 | Sync frequency |

---

## Meeting Server

### `meeting`
Record, transcribe, and manage meeting notes. Uses WhisperX + pyannote speaker diarization on Node2 GPU 0.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| action | string | yes | - | See actions below |
| meeting_title | string | for start | - | Meeting title (REQUIRED for start — do NOT use `title`, see note) |
| meeting_type | string | no | "conference" | "conference" (room mic), "teams" (cable/speaker), "phone" |
| meeting_id | int | for most actions | - | Meeting ID |
| calendar_event_id | int | no | auto-detect | Pass 0 for standalone recording; omit to auto-link nearby calendar event |
| speaker_map | string | for speakers | - | JSON string: `{"Speaker 0": "Victor", "Speaker 1": "Sarah"}` |
| query | string | for list | - | Search term |
| format | string | for export | "summary" | "summary", "notes", or "transcript" |
| limit | int | no | 10 | Max results for list |

**Actions:**
- `start` - Begin recording (requires `meeting_title`). Auto-links to nearby calendar event or creates one.
- `stop` - End recording and trigger async transcription pipeline
- `status` - Check recording/processing/completed state
- `list` - Recent meetings with status
- `get` - Full transcript with speaker segments (truncated at 40K chars; use export for full text)
- `summarize` - Generate AI summary + action items
- `speakers` - Map speaker labels to names (show previews if no map provided)
- `export` - Returns download URL for meeting document

**IMPORTANT — Parameter naming:**
The parameter is `meeting_title`, NOT `title`. The `title` key is in `UNSUPPORTED_KEYS` in `tool_loader.py` (JSON Schema reserved keyword stripped by llama-server grammar generation). Never use `title`, `default`, or `anyOf` as MCP tool parameter names.

**Processing Pipeline:**
`stop` returns immediately with "processing started". The background pipeline: stitch audio chunks (ffmpeg) → `request_gpu("transcribe")` → upload to Node2 WhisperX (port 8500) → store diarized segments → mark completed. Poll with `status`.

**Calendar Auto-Linkage:**
- Omit `calendar_event_id` → system checks for calendar events within ±15 minutes
- Match found with no transcript → auto-links
- Match found with existing transcript → asks user via `needs_decision=true`
- No match → creates new calendar event
- Pass `calendar_event_id=0` → standalone recording, no calendar link

**Examples:**
```
meeting(action="start", meeting_title="Weekly Standup")
meeting(action="stop", meeting_id=1)
meeting(action="status", meeting_id=1)
meeting(action="list", query="standup", limit=5)
meeting(action="get", meeting_id=1)
meeting(action="summarize", meeting_id=1)
meeting(action="speakers", meeting_id=1, speaker_map='{"Speaker 0": "Victor"}')
meeting(action="export", meeting_id=1, format="transcript")
```

**Configuration** (system_config):
| Key | Category | Default | Description |
|-----|----------|---------|-------------|
| `TRANSCRIBE_ENABLED` | features | true | Enable meeting transcription (gated by NODE2_ENABLED) |
| `TRANSCRIBE_SERVER_URL` | remote_services | http://node2:8500 | WhisperX service URL |
| `MEETING_WHISPERX_MODEL` | meeting | large-v3 | WhisperX model size |
| `MEETING_CHUNK_DURATION_SECONDS` | meeting | 300 | Audio chunk rotation interval |
| `MEETING_AUDIO_PATH` | meeting | attachments/meetings | Audio storage directory |

**Browser Integration:**
The `start` action returns `meeting_id` in the WebSocket `tool_result` message. The browser's `meeting-recorder.js` detects this and begins `getUserMedia()` audio capture with 5-minute chunk rotation, auto-uploading to `/api/meeting/upload-chunk`. Recording pauses IrisVOX (STT) to prevent interference.

---

## System Server

### `get_system_health_statistics`
Get comprehensive system health data.

**Parameters:** None

**Returns:** Drives, RAM, GPUs, CPU, processes, alerts

### `system_status_summary`
Get human-readable status summary.

**Parameters:** None

### `generate_alerts`
Generate health alerts from metrics.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| drives | list | yes | Drive info |
| ram | dict | yes | RAM info |
| gpus | list | yes | GPU info |
| cpu | dict | yes | CPU info |

### `linux_shell`
Execute shell commands with safety guardrails.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| command | string | yes | Shell command |

**Blocked commands:** reboot, shutdown, mkfs, rm -rf /, etc.

### `database_query`
Execute SQL queries on Iris database.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| query | string | yes | SQL query |

**Supported:** SELECT, SHOW, DESCRIBE, EXPLAIN, UPDATE, INSERT, ALTER

**Limit:** 8000 tokens max result

### `distributed_system_health`
Get comprehensive health status across both localhost and Node2. Essential for diagnosing OOM errors, service failures, and GPU resource conflicts.

**Parameters:** None

**Returns:**
- GPU memory usage per service (with actual service names like `iris-vision.service`)
- Service health status (healthy/unhealthy via health endpoint or TCP check)
- Systemd state and restart counts (crash loop detection)
- GPU Manager current state
- Human-readable summary

**Example output:**
```
📍 NODE2 (node2):
  GPU 0 (RTX 4080 SUPER): 10766MB / 16376MB (65.7%) @ 30°C
    └─ iris-vision.service: 10756MB
  GPU 1 (RTX 3060): 7132MB / 12288MB (58.0%) @ 29°C
    └─ iris-sentiment.service: 4842MB
    └─ iris-stt.service: 328MB
    └─ iris-xtts.service: 1942MB

🔧 NODE2 SERVICES:
  ✓ iris-vision: active (restarts: 3)
  ✗ iris-float: inactive
  ✓ iris-xtts: active
```

**Note:** Service names in nvidia-smi output are enabled by `setproctitle` in Python services and `exec -a` wrappers for llama-server services.

---

## Server Architecture

```
mcp_servers/
├── base/base_server.py      # IrisMCPServer base class
├── server_configs.py        # Server registry
├── mcp_client.py            # FastMCP client
├── tool_loader.py           # Tool loading from database
│
├── info/info_server.py      # 9 tools
├── traits/traits_server.py  # 1 tool (unified)
├── memory/memory_server.py  # 1 tool (unified)
├── protocols/protocol_server.py  # 1 tool (unified)
├── knowledge/knowledge_server.py # 1 tool (unified)
├── directions/directions_server.py # 1 tool (unified)
├── creative/creative_server.py    # 1 tool (unified)
├── seeds/seeds_server.py    # 1 tool (unified)
├── calendar/calendar_server.py  # 1 tool (unified)
├── meeting/meeting_server.py    # 1 tool (unified)
└── system/system_server.py  # 6 tools
```

---

## Adding New Tools — Streamlined Workflow

As of Feb 2026, adding a new MCP tool requires only **2 steps**:

1. **Write the `@server.register_tool` function**
2. **Restart Iris**

Everything else happens automatically via MCP Native Discovery.

### Step 1: Implement the Tool (Python)

Add the function to the appropriate MCP server in `mcp_servers/*/server.py`:

```python
@server.register_tool
async def my_new_tool(param1: str, param2: int = 10) -> dict:
    """
    Tool description shown to the model.

    Args:
        param1: First parameter (required)
        param2: Second parameter with default (optional)

    Returns:
        Dictionary with success status and result
    """
    # Implementation
    return {"success": True, "result": ...}
```

### Step 2: Restart Iris

```bash
# Restart the Iris server
./scripts/start.sh
```

That's it! On startup, Iris will:

1. **Connect to MCP servers** — The MCP client connects to each server
2. **Discover tools via MCP protocol** — `list_tools()` queries each server
3. **Auto-register in database** — New tools are inserted into `mcp_tools` table
4. **Map tool → server** — Routing is established automatically
5. **Make tool available** — Tool appears in LLM context (unless blocked by protocol)

### How Auto-Discovery Works

```
Iris Startup
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│  mcp_client.py: connect_all(discover_tools=True)        │
│                                                         │
│  For each MCP server:                                   │
│    1. Connect via FastMCP                               │
│    2. Call list_tools() via MCP protocol                │
│    3. For each discovered tool:                         │
│       - Map tool_name → server (for routing)            │
│       - Upsert into mcp_tools table (auto-register)     │
└─────────────────────────────────────────────────────────┘
    │
    ▼
Tool available in chat!
```

### Optional Configuration (Database)

New tools are auto-enabled with sensible defaults. To customize behavior, update the database:

```sql
-- Make tool "core" (always included regardless of context triggers)
UPDATE mcp_tools SET is_core = true WHERE tool_name = 'my_new_tool';

-- Add smart selection triggers (tool appears when user mentions these words)
UPDATE mcp_tools SET
    tool_group = 'system',
    trigger_keywords = ARRAY['diagnose', 'check', 'status']
WHERE tool_name = 'my_new_tool';

-- Disable autonomous execution (requires user confirmation)
UPDATE mcp_tools SET is_autonomous = false WHERE tool_name = 'my_new_tool';

-- Disable tool entirely
UPDATE mcp_tools SET enabled = false WHERE tool_name = 'my_new_tool';
```

### Protocol-Based Tool Blocking

Protocols now use **exclusion lists** instead of inclusion lists. New tools are automatically available unless explicitly blocked:

```sql
-- Block a tool from a specific protocol
UPDATE protocols
SET blocked_tools = blocked_tools::jsonb || '["my_new_tool"]'::jsonb
WHERE name = 'restricted_mode';

-- View blocked tools for a protocol
SELECT name, blocked_tools FROM protocols;
```

### Verification

```bash
# Check tool was auto-registered
psql -c "SELECT tool_name, server_name, enabled FROM mcp_tools WHERE tool_name = 'my_new_tool';"

# Check smart selection metadata
psql -c "SELECT tool_name, tool_group, trigger_keywords, is_core FROM mcp_tools WHERE tool_name = 'my_new_tool';"

# Test tool routing
python -c "from mcp_servers.server_configs import get_server_for_tool; print(get_server_for_tool('my_new_tool'))"
```

### Database Schema for Tools

The `mcp_tools` table stores all tool configuration:

| Column | Type | Description |
|--------|------|-------------|
| `tool_name` | VARCHAR | Unique tool identifier |
| `description` | TEXT | Tool description (from MCP or manual) |
| `input_schema` | JSONB | JSON Schema for parameters |
| `enabled` | BOOLEAN | If false, tool is hidden |
| `priority` | INTEGER | Sort order (lower = higher priority) |
| `server_name` | VARCHAR | MCP server that provides this tool |
| `tool_group` | VARCHAR | Logical group for smart selection |
| `trigger_keywords` | TEXT[] | Keywords that trigger group inclusion |
| `is_core` | BOOLEAN | If true, always included in context |
| `is_autonomous` | BOOLEAN | If true, executes without confirmation |
| `custom_instructions` | TEXT | Additional guidance appended to description |
| `icon` | TEXT | UI icon name |

### MCP Server Configuration

Servers are also database-driven via the `mcp_servers` table:

```sql
-- Add a new MCP server
INSERT INTO mcp_servers (name, description, command, script_path, enabled, priority)
VALUES ('myserver', 'My custom tools', 'python', 'mcp_servers/myserver/server.py', true, 100);
```

### Legacy Workflow (Pre-Discovery)

Before auto-discovery was implemented, adding a tool required 5 manual steps:

1. Write Python function
2. INSERT into mcp_tools (with input_schema)
3. Add to server_configs.py tools array
4. Add to protocol tool_usage
5. Add to TOOL_GROUPS in tool_manager.py

**This manual workflow is no longer needed.** The auto-discovery system handles steps 2-5 automatically.

If you need to manually configure a tool (e.g., for a non-MCP tool or to override auto-discovered settings), the legacy SQL approach still works:

```sql
INSERT INTO mcp_tools (tool_name, description, input_schema, server_name, enabled)
VALUES (
    'my_tool',
    'Tool description',
    '{"type": "object", "properties": {"param": {"type": "string"}}}'::jsonb,
    'system',
    true
)
ON CONFLICT (tool_name) DO UPDATE SET
    description = EXCLUDED.description,
    input_schema = EXCLUDED.input_schema,
    server_name = EXCLUDED.server_name;
```

---

## Troubleshooting

### Tool Not Appearing

1. **Check if tool is enabled:**
   ```sql
   SELECT tool_name, enabled, server_name FROM mcp_tools WHERE tool_name = 'my_tool';
   ```

2. **Check if server is running:**
   ```sql
   SELECT name, enabled FROM mcp_servers WHERE name = 'my_server';
   ```

3. **Check if tool is blocked by protocol:**
   ```sql
   SELECT p.name, p.blocked_tools
   FROM protocols p
   JOIN active_protocol ap ON p.name = ap.protocol_name;
   ```

4. **Check smart selection triggers:**
   - If `is_core = false` and no matching `trigger_keywords`, tool won't appear unless user message contains a trigger word

### Tool Schema Mismatch

If the model sees different parameters than your Python function:

1. **Check database schema:**
   ```sql
   SELECT input_schema FROM mcp_tools WHERE tool_name = 'my_tool';
   ```

2. **Force re-discovery:** The auto-discovery prefers existing schemas to avoid overwriting customizations. To force an update:
   ```sql
   -- Clear the schema to allow auto-discovery to repopulate
   UPDATE mcp_tools SET input_schema = '{}' WHERE tool_name = 'my_tool';
   ```
   Then restart Iris.

---

*Last updated: 2026-02-03 — Added auto-discovery, database-driven smart selection, and exclusion-based protocols*
