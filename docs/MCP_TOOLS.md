# Iris v3 MCP Tools Reference

## Overview

Iris uses 24 tools across 9 MCP (Model Context Protocol) servers. Most servers follow a **unified tool pattern** where a single tool accepts an `action` parameter to route operations.

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
| `get_system_health_statistics` | system | - | System health stats |
| `system_status_summary` | system | - | Human-readable status |
| `generate_alerts` | system | - | Health alerts |
| `linux_shell` | system | - | Safe shell execution |
| `database_query` | system | - | SQL query execution |

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
└── system/system_server.py  # 5 tools
```

---

## Tool Schema Synchronization

**IMPORTANT:** Tool definitions exist in TWO places:
1. Python code (`mcp_servers/*/server.py`)
2. Database (`mcp_tools.input_schema`)

**The model only sees the database schema.** When adding parameters:
1. Update Python function
2. Create SQL to update `mcp_tools.input_schema`
3. Run SQL
4. Restart Iris

---

*Last updated: 2026-01-24*
