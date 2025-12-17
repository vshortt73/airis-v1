# Iris v3 - Organized Architecture

AI Assistant with time-based session management, token governance, and proper context handling.

## Quick Start

### 1. Set Database Password (Required First!)

```bash
# REQUIRED: Set your PostgreSQL password
export IRIS_DB_PASSWORD='your_actual_password'

# Make it permanent (add to ~/.bashrc or ~/.zshrc):
echo "export IRIS_DB_PASSWORD='your_actual_password'" >> ~/.bashrc
source ~/.bashrc
```

### 2. Install and Run

```bash
cd /home/user/iris-v3

# Install dependencies (if not already done)
pip install -r requirements.txt

# Start server
./scripts/start.sh
```

Open browser: `http://localhost:8000`

## Features

✅ **Time-Based Sessions** - 30-minute threshold, auto-detection
✅ **Token Governance** - tiktoken counting, multi-level limits
✅ **Context Inspection** - API endpoints to view what's sent to Ollama
✅ **Ollama Compliance** - Proper tool message formatting
✅ **Clean Architecture** - Organized modules, proper separation
✅ **Vision System** - Dual Ollama setup with GPU isolation (llava on GPU 1)

## Architecture

```
iris-v3-organized/
├── app/                    # FastAPI application
│   ├── config.py          # All settings
│   ├── main.py            # App entry point
│   └── api/               # API routes
│       ├── routes_chat.py      # WebSocket chat
│       ├── routes_session.py   # Session management
│       └── routes_context.py   # Context inspection
├── core/                   # Core functionality
│   ├── conversation.py    # History management
│   ├── system_prompt.py   # DB-driven prompts
│   └── token_counter.py   # tiktoken integration
├── database/               # Database operations
│   └── persistence.py     # Sessions & messages
├── ollama/                 # Ollama client
│   └── client.py          # Streaming API
├── static/                 # Web UI
│   └── index.html
├── tests/                  # Test scripts
├── scripts/                # Utility scripts
└── docs/                   # Documentation
```

## Configuration

Edit `app/config.py`:

```python
# Session timeout
SESSION_TIMEOUT_MINUTES = 30

# Context limits
MAX_CONVERSATION_TURNS = 30
MAX_CONTEXT_TOKENS = 12000
MAX_TOTAL_MESSAGES = 100

# Ollama
OLLAMA_CONTEXT_WINDOW = 16384
```

## API Endpoints

**Chat:**
- `GET /` - Web interface
- `WS /ws/chat` - WebSocket chat

**Sessions:**
- `GET /api/sessions/recent` - List recent sessions
- `POST /api/sessions/new` - Create new session
- `POST /api/sessions/load/{id}` - Load session

**Context:**
- `GET /api/conversation/context` - Full context with messages
- `GET /api/conversation/context/summary` - Token stats only
- `GET /api/conversation/info` - Basic info

**Health:**
- `GET /api/health` - System status

## Testing

```bash
# Test database
python tests/test_database.py

# Test context inspection
curl http://localhost:8000/api/conversation/context/summary | jq
```

## Key Features Explained

### Time-Based Sessions
- Gap < 30 min → Continue session
- Gap ≥ 30 min → New session
- Survives server restarts

### Token Governance
1. Load last 30 conversation turns
2. Include all tool messages
3. Truncate if > 12000 tokens
4. Truncate if > 100 messages

### Context Inspection
View exactly what's sent to Ollama:
```bash
curl http://localhost:8000/api/conversation/context | jq
```

## Troubleshooting

**Database connection failed:**
```bash
export IRIS_DB_PASSWORD='your_password'
python tests/test_database.py
```

**Import errors:**
```bash
export PYTHONPATH="$(pwd):$PYTHONPATH"
```

**Context issues:**
```bash
# Enable debug logging
# In app/config.py: CONTEXT_DEBUG = True
```

## Development

Run directly:
```bash
python app/main.py
```

## Documentation

See `docs/` directory for:
- Detailed setup instructions
- Architecture documentation  
- API reference
- Migration guides

## Version

**Iris v3.0.0** - Organized Architecture Release

Built: December 2025
