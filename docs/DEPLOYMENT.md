# Iris v3 Deployment Guide

## Prerequisites

### Localhost (Main Server)
- Ubuntu 22.04+ or similar Linux
- Python 3.10+
- PostgreSQL 14+ with pgvector extension
- NVIDIA GPU with CUDA (RTX 5090 recommended)
- Ollama installed

### Node2 (GPU Server)
- Ubuntu 22.04+ or similar Linux
- Python 3.10+
- 2x NVIDIA GPUs (RTX 4080 Super + RTX 3060 recommended)
- Ollama installed
- SSH access from localhost

---

## Localhost Setup

### 1. Clone Repository
```bash
git clone <repo-url> /iris-v3
cd /iris-v3
```

### 2. Python Environment
```bash
python -m venv /venv/iris-v3
source /venv/iris-v3/bin/activate
pip install -r requirements.txt
```

### 3. PostgreSQL Setup
```bash
# Install PostgreSQL and pgvector
sudo apt install postgresql postgresql-contrib
sudo apt install postgresql-14-pgvector  # or your version

# Create database and user
sudo -u postgres psql
CREATE USER irisuser WITH PASSWORD 'your_secure_password';
CREATE DATABASE irisdb OWNER irisuser;
\c irisdb
CREATE EXTENSION vector;
GRANT ALL PRIVILEGES ON DATABASE irisdb TO irisuser;
\q

# Run migrations
export IRIS_DB_PASSWORD='your_secure_password'
for f in database/sql/*.sql; do
  psql -h localhost -U irisuser -d irisdb -f "$f"
done
```

### 4. Ollama Setup
```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Pull required model
ollama pull qwen3:32b
```

### 5. Environment Variables
```bash
# Add to ~/.bashrc or ~/.profile
export IRIS_DB_PASSWORD='your_secure_password'
```

### 6. Start Server
```bash
cd /iris-v3
source /venv/iris-v3/bin/activate
./scripts/start.sh
```

Server runs at `http://localhost:8000`

---

## Node2 Setup

### 1. SSH Configuration (on localhost)
```bash
# Generate SSH key if needed
ssh-keygen -t ed25519

# Copy to node2
ssh-copy-id captain@node2

# Test
ssh captain@node2 'echo OK'
```

### 2. Sudo Configuration (on node2)
```bash
# /etc/sudoers.d/iris
captain ALL=(ALL) NOPASSWD: /bin/systemctl start iris-*.service
captain ALL=(ALL) NOPASSWD: /bin/systemctl stop iris-*.service
captain ALL=(ALL) NOPASSWD: /bin/systemctl restart iris-*.service
captain ALL=(ALL) NOPASSWD: /bin/systemctl status iris-*.service
```

### 3. Install Services (on node2)

Copy service files from `scripts/systemd/` to `/etc/systemd/system/` on node2.

#### iris-vision.service
```ini
[Unit]
Description=Iris Vision Service (llava-phi-3)
After=network.target

[Service]
Type=simple
User=captain
Environment="CUDA_VISIBLE_DEVICES=0"
ExecStart=/usr/local/bin/ollama serve
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

#### iris-float.service
```ini
[Unit]
Description=Iris FLOAT Video Generation
After=network.target
Conflicts=iris-vision.service iris-freud.service

[Service]
Type=simple
User=captain
WorkingDirectory=/home/captain/FLOAT
Environment="CUDA_VISIBLE_DEVICES=0"
ExecStart=/home/captain/FLOAT/venv/bin/python server.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

#### iris-freud.service
```ini
[Unit]
Description=Iris Freud Dream Service (gemma-3-4b)
After=network.target
Conflicts=iris-vision.service iris-float.service

[Service]
Type=simple
User=captain
Environment="CUDA_VISIBLE_DEVICES=0"
Environment="OLLAMA_HOST=0.0.0.0:11435"
ExecStart=/usr/local/bin/ollama serve
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

#### iris-xtts.service
```ini
[Unit]
Description=Iris XTTS Text-to-Speech
After=network.target

[Service]
Type=simple
User=captain
WorkingDirectory=/home/captain/xtts
Environment="CUDA_VISIBLE_DEVICES=1"
ExecStart=/home/captain/xtts/venv/bin/python server.py --port 8700
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

#### iris-stt.service
```ini
[Unit]
Description=Iris STT Speech-to-Text (Whisper)
After=network.target

[Service]
Type=simple
User=captain
WorkingDirectory=/home/captain/whisper
Environment="CUDA_VISIBLE_DEVICES=1"
ExecStart=/home/captain/whisper/venv/bin/python server.py --port 8600
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

#### iris-sentiment.service
```ini
[Unit]
Description=Iris Sentiment Analysis (Mistral 7B)
After=network.target

[Service]
Type=simple
User=captain
Environment="CUDA_VISIBLE_DEVICES=1"
Environment="OLLAMA_HOST=0.0.0.0:11437"
ExecStart=/usr/local/bin/ollama serve
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 4. Enable Services
```bash
sudo systemctl daemon-reload
sudo systemctl enable iris-xtts iris-stt iris-sentiment
sudo systemctl start iris-xtts iris-stt iris-sentiment

# GPU 0 services are started on-demand by GPU Manager
# Only enable one at a time
sudo systemctl enable iris-vision
```

---

## Configuration

### Database Config (Source of Truth)

All configuration lives in `system_config` table:

```bash
# Populate default config
psql -h localhost -U irisuser -d irisdb \
  -f database/sql/populate_system_config_complete.sql
```

### Key Configuration Values

| Category | Key | Default | Description |
|----------|-----|---------|-------------|
| llm | OLLAMA_HOST | localhost | Ollama server |
| llm | OLLAMA_PORT | 11434 | Ollama port |
| llm | OLLAMA_MODEL | qwen3:32b | Model name |
| llm | OLLAMA_CONTEXT_WINDOW | 32768 | Context size |
| remote_services | NODE2_HOST | node2 | Node2 hostname |
| remote_services | XTTS_URL | http://node2:8700 | TTS server |
| remote_services | STT_URL | http://node2:8600 | STT server |
| remote_services | VISION_URL | http://node2:11435 | Vision server |
| remote_services | SENTIMENT_URL | http://node2:11437 | Sentiment server |
| tokens | VERBOSE_TOKEN_BUDGET | 3000 | Recent messages |
| tokens | SUMMARY_TOKEN_BUDGET | 17000 | Summarized messages |
| tokens | DOCUMENT_CONTEXT_BUDGET | 8000 | Uploaded documents |

### Modify Config
```bash
# Via admin UI
http://localhost:8000/static/admin.html

# Or via SQL
UPDATE system_config SET value = '4000'
WHERE key = 'VERBOSE_TOKEN_BUDGET';
```

---

## Cron Jobs

### Nightly Memory Creation
```bash
# /etc/cron.d/iris-memory
0 3 * * * captain /iris-v3/scripts/nightly_memory_creation.sh
```

### Nightly Dream Processing
```bash
# /etc/cron.d/iris-dream
0 4 * * * captain /iris-v3/scripts/nightly_dream.sh
```

### Knowledge Base Indexing
```bash
# /etc/cron.d/iris-knowledge
0 5 * * * captain /iris-v3/scripts/index_knowledge.sh
```

---

## Health Checks

### Check All Services
```bash
curl http://localhost:8000/api/admin/services/all | jq
```

### Individual Service Health
```bash
# Main Ollama
curl http://localhost:11434/api/tags

# Vision (node2)
curl http://node2:11435/api/tags

# XTTS
curl http://node2:8700/health

# STT
curl http://node2:8600/health

# Sentiment
curl http://node2:11437/api/tags
```

### GPU Status
```bash
curl http://localhost:8000/api/gpu/status | jq
```

---

## Troubleshooting

### Service Not Responding
```bash
# Check status
ssh node2 'systemctl status iris-vision'

# View logs
ssh node2 'journalctl -u iris-vision -n 50'

# Restart
ssh node2 'sudo systemctl restart iris-vision'
```

### GPU Manager Issues
```bash
# Check state
curl http://localhost:8000/api/gpu/status | jq

# Force re-detect
curl -X POST http://localhost:8000/api/gpu/detect | jq

# Test SSH
ssh -o BatchMode=yes captain@node2 'echo OK'
```

### Database Connection
```bash
# Test connection
PGPASSWORD=$IRIS_DB_PASSWORD psql -h localhost -U irisuser -d irisdb -c "SELECT 1"

# Check pgvector
PGPASSWORD=$IRIS_DB_PASSWORD psql -h localhost -U irisuser -d irisdb -c "SELECT * FROM pg_extension WHERE extname = 'vector'"
```

### Memory Issues
```bash
# Check token usage
curl http://localhost:8000/api/conversation/context/summary | jq

# Clear conversation (in-memory only)
curl -X POST http://localhost:8000/api/sessions/clear
```

---

## Dependencies

### Python Packages (requirements.txt)
```
fastapi
uvicorn[standard]
websockets
wsproto
psycopg2-binary
tiktoken
sentence-transformers
numpy
bcrypt
httpx
python-multipart
python-docx
odfpy
PyMuPDF
```

### System Packages
```bash
# Ubuntu/Debian
sudo apt install postgresql postgresql-contrib
sudo apt install postgresql-14-pgvector
sudo apt install ffmpeg  # for audio processing
```

### Ollama Models
```bash
# Localhost
ollama pull qwen3:32b

# Node2 - Vision
ollama pull llava-phi-3

# Node2 - Freud
ollama pull gemma-3-4b

# Node2 - Sentiment
ollama pull mistral:7b
```

---

## Security Notes

1. **Database password** - Always use `IRIS_DB_PASSWORD` environment variable
2. **SSH keys** - Use key-based auth for node2, never password
3. **No secrets in code** - All credentials via environment
4. **Protocol passphrases** - bcrypt hashed in database
5. **SSL/HTTPS** - Configure reverse proxy for production

---

*Last updated: 2026-01-24*
