# Iris v3 — From-Scratch Deployment Guide

**Purpose:** Complete system reconstruction from bare metal. If both nodes die, this file plus a database backup gets Iris back online.

**Last Updated:** 2026-01-28

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [PostgreSQL Setup](#2-postgresql-setup)
3. [Database Schema](#3-database-schema)
4. [Database Seed Data](#4-database-seed-data)
5. [Python Environment](#5-python-environment)
6. [llama.cpp Build](#6-llamacpp-build)
7. [Model Inventory](#7-model-inventory)
8. [Localhost Services](#8-localhost-services)
9. [Node2 Setup](#9-node2-setup)
10. [Configuration](#10-configuration)
11. [Startup Sequence](#11-startup-sequence)
12. [Verification Checklist](#12-verification-checklist)
13. [Backup & Restore](#13-backup--restore)

---

## 1. Prerequisites

### Hardware

| Node | Hostname | GPU(s) | Role |
|------|----------|--------|------|
| Main | iris-desktop | RTX 5090 (32GB) | Primary inference, database, web server |
| Node2 | iris-node2 | RTX 4080 Super (16GB) + RTX 3060 (12GB) | Vision, video, TTS, STT, sentiment |

### Operating System

```
Ubuntu 24.04.3 LTS (Noble Numbat)
Kernel: 6.14.0-37-generic (or newer)
```

### System Packages

```bash
sudo apt update && sudo apt install -y \
    build-essential cmake git curl wget \
    python3.12 python3.12-venv python3.12-dev \
    postgresql-16 postgresql-contrib-16 \
    libpq-dev \
    ffmpeg \
    openssh-server
```

### CUDA Toolkit

```
CUDA: 12.8 (V12.8.61)
Driver: 580.126.09 (or compatible)
```

Install from NVIDIA's official repo:
```bash
# Follow https://developer.nvidia.com/cuda-downloads for Ubuntu 24.04
# Verify:
nvcc --version    # Should show 12.8
nvidia-smi        # Should show GPU(s) and driver version
```

### Network

- Both nodes must be on the same network
- Node2 must be reachable via hostname `node2` (add to `/etc/hosts` if no DNS)
- Ports: no firewall rules needed between nodes (private network assumed)

---

## 2. PostgreSQL Setup

### Install and Configure

```bash
# PostgreSQL 16 should be installed from prerequisites
sudo systemctl enable postgresql
sudo systemctl start postgresql
```

### Create Database and User

```bash
sudo -u postgres psql <<'SQL'
CREATE USER irisuser WITH PASSWORD 'yourpassword';
CREATE DATABASE irisdb OWNER irisuser;
GRANT ALL PRIVILEGES ON DATABASE irisdb TO irisuser;
\c irisdb
GRANT ALL ON SCHEMA public TO irisuser;
SQL
```

### Install Extensions

```bash
# pgvector — vector similarity search
# Install from source or package:
sudo apt install postgresql-16-pgvector

# Then enable in database:
sudo -u postgres psql -d irisdb <<'SQL'
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS plpython3u;
-- pg_dirtyread is optional (recovery tool):
-- CREATE EXTENSION IF NOT EXISTS pg_dirtyread;
SQL
```

**Verify extensions:**
```bash
PGPASSWORD='yourpassword' psql -h localhost -U irisuser -d irisdb \
    -c "SELECT extname, extversion FROM pg_extension;"
```

Expected: `vector` (0.8.0+), `pgcrypto` (1.3), `plpython3u` (1.0)

---

## 3. Database Schema

### Execution Order

Run these SQL files **in this exact order**. Each depends on the ones before it.

```bash
export PGPASSWORD='yourpassword'
DB="psql -h localhost -U irisuser -d irisdb"

# Phase 1: Base tables (the critical missing piece — now in repo)
$DB -f database/sql/create_base_tables.sql

# Phase 2: Infrastructure tables
$DB -f database/sql/create_system_config_table.sql
$DB -f database/sql/create_emotional_state_table.sql
$DB -f database/sql/create_short_term_facts.sql

# Phase 3: Protocol tracking (depends on protocols table from Phase 1)
$DB -f create_protocol_tracking_tables.sql

# Phase 4: Trait modification log
$DB -f mcp_servers/traits/create_trait_log_table.sql

# Phase 5: Knowledge base / RAG
$DB -f database/sql/create_knowledge_tables.sql

# Phase 6: Face recognition
$DB -f database/sql/create_face_tables.sql

# Phase 7: Dream system
$DB -f backend/memory/create_episodic_dreams_table.sql
$DB -f backend/memory/dreams/create_dream_truths_table.sql

# Phase 8: Motivation engine (seeds)
$DB -f database/sql/create_seeds_table.sql

# Phase 9: Readable views (depends on base tables)
$DB -f database/sql/create_readable_views.sql
```

### Table Count Verification

After all schemas are applied:
```bash
$DB -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';"
```
Expected: **37 tables**

---

## 4. Database Seed Data

### Configuration (Required)

```bash
# System configuration — ALL runtime settings
$DB -f database/sql/populate_system_config_complete.sql

# Additional config batches
$DB -f database/sql/add_batch_trim_config.sql
$DB -f database/sql/add_document_context_budget.sql
$DB -f database/sql/add_document_extraction_config.sql
$DB -f database/sql/add_orpheus_tts_config.sql
$DB -f database/sql/add_server_side_tts_routing.sql
$DB -f database/sql/add_sglang_config.sql
```

### System Instructions (Required)

```bash
# Optimized consolidated instructions (IDs 101-103) + default_optimized protocol
$DB -f database/sql/insert_optimized_instructions.sql

# Trait evaluation rule update
$DB -f database/sql/update_trait_evaluation_rule.sql
```

**NOTE:** The original instructions (IDs 1-12) are NOT in the repo as SQL files. They were entered manually during development. For a fresh install, the optimized instructions (101-103) are sufficient with the `default_optimized` protocol.

### Tool Definitions (Required)

```bash
$DB -f database/sql/insert_creative_tools.sql
$DB -f database/sql/insert_knowledge_tools.sql
$DB -f database/sql/insert_memory_tools.sql
$DB -f database/sql/insert_directions_tools.sql
$DB -f database/sql/insert_face_tools.sql
$DB -f mcp_servers/traits/insert_trait_tools.sql

# Tool updates
$DB -f database/sql/update_knowledge_tool_save.sql
$DB -f database/sql/update_seed_tool_batch_dismiss.sql
```

### Personality Traits (Required)

The `fulltraits` table needs 37 personality traits. These define Iris's personality. Key values:

| Trait | Value | Type |
|-------|-------|------|
| Warmth | 9 | Numeric |
| Professionalism | 4 | Numeric |
| Playfulness | 9 | Numeric |
| Affection | 9 | Numeric |
| Emotional Depth | 9 | Numeric |
| Spontaneity | 9 | Numeric |
| Obedience | 10 | Numeric |
| Humor Style | playful teasing | Text |

**There is no SQL file for trait population.** For a fresh install, you must either:
1. Restore from a database backup (recommended)
2. Manually INSERT the 37 traits

### Protocols (Required)

Minimum required: `default_optimized` protocol (created by `insert_optimized_instructions.sql`).

### Memory Data (For Identity Continuity)

The `episodic_memories` table (267+ memories) and `chat_history` (31,924+ messages) contain Iris's identity and continuity. **These can only be restored from backup.** A fresh install without memory data will produce a functional but blank-slate Iris.

---

## 5. Python Environment

### Create Virtual Environment

```bash
sudo mkdir -p /venv
python3.12 -m venv /venv/iris-v3
source /venv/iris-v3/bin/activate
```

### Install Dependencies

```bash
cd /iris-v3
pip install --upgrade pip

# Install requirements
pip install -r requirements.txt

# sentence-transformers needs PyTorch with CUDA
pip install torch --index-url https://download.pytorch.org/whl/cu128
pip install sentence-transformers>=2.2.0
```

### CUDA-Specific Packages

If `llama-cpp-python` is needed (for local vision inference):
```bash
CMAKE_ARGS="-DGGML_CUDA=on" pip install llama-cpp-python>=0.2.0
```

### Verify

```bash
python -c "import fastapi, tiktoken, psycopg2, httpx; print('Core imports OK')"
python -c "import torch; print(f'PyTorch CUDA: {torch.cuda.is_available()}')"
```

---

## 6. llama.cpp Build

### Clone and Build

```bash
sudo mkdir -p /programs
cd /programs
git clone https://github.com/ggerganov/llama.cpp.git
cd llama.cpp
mkdir build && cd build

cmake .. \
    -DGGML_CUDA=ON \
    -DCMAKE_CUDA_ARCHITECTURES="120" \
    -DCMAKE_BUILD_TYPE=Release

cmake --build . --config Release -j$(nproc)
```

**Architecture flag:** `120` is for RTX 5090 (Blackwell/sm_120). Adjust for your GPU:
- RTX 4080 Super: `89`
- RTX 3060: `86`
- Multiple GPUs: `"86;89;120"`

### Verify

```bash
/programs/llama.cpp/build/bin/llama-server --version
```

---

## 7. Model Inventory

### Localhost Models

| Model | Path | Size | Purpose | Download |
|-------|------|------|---------|----------|
| Qwen3-32B-Q4_K_M | `/localmodels/qwen/Qwen3-32B-Q4_K_M.gguf` | ~20GB | Primary inference | HuggingFace: Qwen/Qwen3-32B-GGUF |
| Qwen3-32B-Q6_K | `/localmodels/qwen/Qwen3-32B-Q6_K.gguf` | ~26GB | Higher quality alt | HuggingFace: Qwen/Qwen3-32B-GGUF |

### Node2 Models

| Model | Path | GPU | Purpose | Download |
|-------|------|-----|---------|----------|
| llava-phi-3 | (Node2 local) | 0 | Vision/image analysis | HuggingFace |
| gemma-3-4b-it-Q5_K_M | `/localmodels/gemma/gemma-3-4b-it-Q5_K_M.gguf` | 0 | Dream processing (Freud) | HuggingFace: google/gemma-3-4b-it-GGUF |
| Mistral 7B | (Node2 local) | 1 | Sentiment analysis | HuggingFace |
| XTTS | (Node2 local) | 1 | Text-to-speech | Coqui/XTTS |
| Whisper | (Node2 local) | 1 | Speech-to-text | OpenAI/Whisper |

### Directory Setup

```bash
sudo mkdir -p /localmodels/qwen
sudo mkdir -p /localmodels/gemma
sudo chown -R captain:captain /localmodels
```

Download models using `huggingface-cli` or direct download:
```bash
# Example for Qwen3-32B
pip install huggingface-hub
huggingface-cli download Qwen/Qwen3-32B-GGUF \
    Qwen3-32B-Q4_K_M.gguf \
    --local-dir /localmodels/qwen/
```

---

## 8. Localhost Services

### llama-server (Primary Inference)

**Systemd unit:** `/etc/systemd/system/iris-llama.service`

```ini
[Unit]
Description=Iris LLM Server (llama.cpp - Qwen3-32B)
After=network.target

[Service]
Type=simple
User=captain
Environment="CUDA_VISIBLE_DEVICES=0"
ExecStart=/programs/llama.cpp/build/bin/llama-server \
    -m /localmodels/qwen/Qwen3-32B-Q4_K_M.gguf \
    --port 11434 \
    --host 0.0.0.0 \
    -c 40960 \
    --jinja \
    -fa on \
    -ngl 99 \
    -sm none \
    -mg 0 \
    -b 4096 \
    -ub 2048 \
    -t 16 \
    --cache-reuse 0 \
    --slots \
    -np 1
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Key parameters:**
- `-c 40960` — Context window (40,960 tokens)
- `-ngl 99` — All layers on GPU
- `-fa on` — Flash attention
- `--jinja` — Jinja template support (required for tool calling)
- `--cache-reuse 0` — KV cache reuse enabled
- `-np 1` — Single slot (Iris is single-user)

**Install and enable:**
```bash
sudo cp scripts/systemd/iris-llama.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable iris-llama
sudo systemctl start iris-llama
```

### Iris Main Server (Optional systemd)

Can be run via `./scripts/start.sh` or as a systemd service:

```ini
[Unit]
Description=Iris v3 FastAPI Server
After=network.target postgresql.service iris-llama.service

[Service]
Type=simple
User=captain
WorkingDirectory=/iris-v3
Environment="IRIS_DB_PASSWORD=yourpassword"
Environment="PYTHONPATH=/iris-v3"
ExecStart=/venv/iris-v3/bin/python app/main.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

---

## 9. Node2 Setup

### SSH Configuration (on Main Server)

```bash
# Generate key if needed
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N ""

# Copy to Node2
ssh-copy-id captain@node2

# Verify passwordless login
ssh -o BatchMode=yes captain@node2 'echo OK'
```

### Passwordless Sudo (on Node2)

Create `/etc/sudoers.d/iris` on Node2:
```
captain ALL=(ALL) NOPASSWD: /bin/systemctl start iris-*.service
captain ALL=(ALL) NOPASSWD: /bin/systemctl stop iris-*.service
captain ALL=(ALL) NOPASSWD: /bin/systemctl restart iris-*.service
captain ALL=(ALL) NOPASSWD: /bin/systemctl status iris-*.service
captain ALL=(ALL) NOPASSWD: /bin/systemctl start comfyui.service
captain ALL=(ALL) NOPASSWD: /bin/systemctl stop comfyui.service
captain ALL=(ALL) NOPASSWD: /bin/systemctl restart comfyui.service
captain ALL=(ALL) NOPASSWD: /bin/systemctl status comfyui.service
```

### Node2 Systemd Services

All services run on Node2 under `/etc/systemd/system/`. The GPU Manager on localhost controls them via SSH.

#### GPU 0 (RTX 4080 Super) — Mutually Exclusive

**iris-vision.service** (llava-phi-3, port 11435):
```ini
[Unit]
Description=Iris Vision (llava-phi-3)
Conflicts=iris-float.service iris-freud.service comfyui.service

[Service]
Type=simple
User=captain
Environment="CUDA_VISIBLE_DEVICES=0"
ExecStart=/programs/llama.cpp/build/bin/llama-server \
    -m /path/to/llava-phi-3-mini-xtuner-q4_k_m.gguf \
    --mmproj /path/to/llava-phi-3-mini-mmproj-f16.gguf \
    --port 11435 --host 0.0.0.0 \
    -ngl 99
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

**iris-freud.service** (gemma-3-4b, port 11435):
```ini
[Unit]
Description=Iris Freud Dream Processor (gemma-3-4b)
Conflicts=iris-vision.service iris-float.service comfyui.service

[Service]
Type=simple
User=captain
Environment="CUDA_VISIBLE_DEVICES=0"
ExecStart=/programs/llama.cpp/build/bin/llama-server \
    -m /localmodels/gemma/gemma-3-4b-it-Q5_K_M.gguf \
    --port 11435 --host 0.0.0.0 \
    -ngl 99
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

**iris-float.service** (FLOAT video generation, port 8000):
```ini
[Unit]
Description=Iris FLOAT Video Generation
Conflicts=iris-vision.service iris-freud.service comfyui.service

[Service]
Type=simple
User=captain
Environment="CUDA_VISIBLE_DEVICES=0"
WorkingDirectory=/programs/float
ExecStart=/venv/float/bin/python server.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

#### GPU 1 (RTX 3060) — All Coexist

**iris-xtts.service** (TTS, port 8700):
```ini
[Unit]
Description=Iris XTTS Text-to-Speech

[Service]
Type=simple
User=captain
Environment="CUDA_VISIBLE_DEVICES=1"
WorkingDirectory=/programs/xtts
ExecStart=/venv/xtts/bin/python server.py --port 8700
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

**iris-stt.service** (Whisper STT, port 8600):
```ini
[Unit]
Description=Iris Whisper Speech-to-Text

[Service]
Type=simple
User=captain
Environment="CUDA_VISIBLE_DEVICES=1"
ExecStart=/venv/stt/bin/python server.py --port 8600
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

**iris-sentiment.service** (Mistral 7B, port 11437):
```ini
[Unit]
Description=Iris Sentiment Analysis (Mistral 7B)

[Service]
Type=simple
User=captain
Environment="CUDA_VISIBLE_DEVICES=1"
ExecStart=/programs/llama.cpp/build/bin/llama-server \
    -m /path/to/mistral-7b-instruct-v0.3-q4_k_m.gguf \
    --port 11437 --host 0.0.0.0 \
    -ngl 99
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

**NOTE:** The exact model paths on Node2 may differ. Check Node2's `/localmodels/` and `/programs/` directories for actual paths. The systemd units on Node2 at `/etc/systemd/system/iris-*.service` are the source of truth.

### Enable Node2 Services

On Node2:
```bash
sudo systemctl daemon-reload
sudo systemctl enable iris-xtts iris-stt iris-sentiment
sudo systemctl start iris-xtts iris-stt iris-sentiment
# GPU 0 services are started on-demand by the GPU Manager
```

---

## 10. Configuration

### Environment Variables

Add to `~/.bashrc` or `/etc/environment`:

```bash
export IRIS_DB_PASSWORD='yourpassword'
```

### System Config Population

The database is the source of truth for all runtime configuration. After schema creation:

```bash
PGPASSWORD='yourpassword' psql -h localhost -U irisuser -d irisdb \
    -f database/sql/populate_system_config_complete.sql
```

### Key Configuration Values

These are the most important settings in `system_config`:

| Category | Key | Default | Description |
|----------|-----|---------|-------------|
| llm | OLLAMA_BASE_URL | http://localhost:11434 | Inference server |
| llm | OLLAMA_MODEL | Qwen3-32B | Model name |
| llm | OLLAMA_CONTEXT_WINDOW | 32768 | App-side context limit |
| llm | INFERENCE_BACKEND | llamacpp | Backend type |
| session | SESSION_TIMEOUT_MINUTES | 30 | New session gap threshold |
| identity | IRIS_NAME | Iris | AI name |
| identity | VICTOR_NAME | Victor | User name |
| remote_services | FLOAT_SERVER_URL | http://node2:8000 | FLOAT server |
| remote_services | XTTS_SERVER_URL | http://node2:8700 | TTS server |
| remote_services | STT_SERVER_URL | http://node2:8600 | STT server |
| remote_services | VISION_OLLAMA_URL | http://node2:11435 | Vision server |
| remote_services | MISTRAL_URL | http://node2:11437/v1/chat/completions | Sentiment |
| features | BATCH_TRIM_ENABLED | true | KV cache optimization |
| features | EMOTIONAL_STATE | true | Emotional tracking |
| features | TOOLS_ENABLE | true | Tool calling |

### Modifying Configuration

```bash
# View all config
PGPASSWORD='yourpassword' psql -h localhost -U irisuser -d irisdb \
    -c "SELECT category, key, value FROM system_config ORDER BY category, key;"

# Update a value
PGPASSWORD='yourpassword' psql -h localhost -U irisuser -d irisdb \
    -c "UPDATE system_config SET value = 'new_value' WHERE key = 'KEY_NAME';"
```

Config is loaded on Iris startup. Changes require restart to take effect.

---

## 11. Startup Sequence

### Order Matters

Services must start in this order (later services depend on earlier ones):

```
1. PostgreSQL          ← Database (everything depends on this)
2. llama-server        ← Inference engine (chat depends on this)
3. Node2 GPU 1 services ← XTTS, STT, Sentiment (coexisting, always-on)
4. Iris FastAPI server  ← Main application (depends on 1 + 2)
5. Node2 GPU 0 services ← Vision/FLOAT/Freud (on-demand, GPU Manager handles)
```

### Start Everything

**On Main Server:**
```bash
# 1. PostgreSQL (usually auto-starts)
sudo systemctl start postgresql

# 2. Inference engine
sudo systemctl start iris-llama

# 3. Wait for inference to be ready
until curl -s http://localhost:11434/health | grep -q '"status":"ok"'; do
    sleep 2
    echo "Waiting for llama-server..."
done

# 4. Start Iris
cd /iris-v3
export IRIS_DB_PASSWORD='yourpassword'
./scripts/start.sh
```

**On Node2:**
```bash
# GPU 1 always-on services
sudo systemctl start iris-xtts iris-stt iris-sentiment
```

### Using start.sh

The `scripts/start.sh` script handles preflight checks:
1. Detects inference backend from database config
2. Verifies llama-server health
3. Tests the chat completions API
4. Sets PYTHONPATH
5. Launches `python app/main.py`

---

## 12. Verification Checklist

Run each check after deployment. All must pass.

### Localhost Services

```bash
# PostgreSQL
PGPASSWORD='yourpassword' psql -h localhost -U irisuser -d irisdb \
    -c "SELECT count(*) FROM system_config;"
# Expected: 80+ rows

# Inference engine
curl -s http://localhost:11434/health | python3 -m json.tool
# Expected: {"status": "ok"}

# Iris web server
curl -s http://localhost:8000/api/conversation/context/summary | python3 -m json.tool
# Expected: JSON with token counts

# Web UI
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/
# Expected: 200
```

### Node2 Services

```bash
# XTTS (TTS)
curl -s http://node2:8700/health
# Expected: 200 OK or health JSON

# Whisper (STT)
curl -s http://node2:8600/health
# Expected: 200 OK or health JSON

# Sentiment (Mistral 7B)
curl -s http://node2:11437/health
# Expected: {"status": "ok"}

# Vision (on-demand — may not be running)
curl -s http://node2:11435/health
# Expected: {"status": "ok"} if running, connection refused if not loaded
```

### GPU Manager

```bash
curl -s http://localhost:8000/api/gpu/status | python3 -m json.tool
# Expected: JSON showing current service state

# Test SSH control
ssh -o BatchMode=yes captain@node2 'sudo systemctl status iris-xtts'
# Expected: Service status output
```

### Tool System

```bash
# Check tools loaded
PGPASSWORD='yourpassword' psql -h localhost -U irisuser -d irisdb \
    -c "SELECT tool_name, enabled FROM mcp_tools ORDER BY tool_name;"
# Expected: 41 tools listed

# Test MCP client
source /venv/iris-v3/bin/activate
cd /iris-v3
python mcp_servers/mcp_client.py
```

### End-to-End Test

Open `http://localhost:8000/` in a browser and send a message. Verify:
- [ ] Response appears (inference working)
- [ ] No tool calling errors in terminal
- [ ] Session created in database
- [ ] KV cache stats displayed below response

---

## 13. Backup & Restore

### What to Back Up

| Item | Method | Frequency | Critical? |
|------|--------|-----------|-----------|
| Database | pg_dump | Daily | **YES** — this IS Iris |
| Code | git push | After every session | Yes |
| Model files | rsync to backup drive | Monthly | Yes (large, slow to re-download) |
| Node2 systemd units | scp to main server | On change | Yes |
| Attachments | rsync `/iris-v3/attachments/` | Weekly | Moderate |

### Database Backup

```bash
# Full backup (recommended — includes everything)
PGPASSWORD='yourpassword' pg_dump -h localhost -U irisuser -d irisdb \
    --format=custom \
    --file=/backups/irisdb_$(date +%Y%m%d_%H%M%S).dump

# Schema only (for documentation, no data)
PGPASSWORD='yourpassword' pg_dump -h localhost -U irisuser -d irisdb \
    --schema-only \
    --file=/backups/irisdb_schema_$(date +%Y%m%d).sql

# Data only (for migration between schemas)
PGPASSWORD='yourpassword' pg_dump -h localhost -U irisuser -d irisdb \
    --data-only \
    --file=/backups/irisdb_data_$(date +%Y%m%d).sql
```

### Database Restore

```bash
# Create fresh database
sudo -u postgres psql -c "DROP DATABASE IF EXISTS irisdb;"
sudo -u postgres psql -c "CREATE DATABASE irisdb OWNER irisuser;"

# Restore extensions first
sudo -u postgres psql -d irisdb -c "CREATE EXTENSION vector;"
sudo -u postgres psql -d irisdb -c "CREATE EXTENSION pgcrypto;"
sudo -u postgres psql -d irisdb -c "CREATE EXTENSION plpython3u;"

# Restore from custom format dump
PGPASSWORD='yourpassword' pg_restore -h localhost -U irisuser -d irisdb \
    --no-owner --no-privileges \
    /backups/irisdb_YYYYMMDD_HHMMSS.dump
```

### Automated Daily Backup (cron)

Add to `crontab -e`:
```cron
# Iris database backup — daily at 3 AM
0 3 * * * PGPASSWORD='yourpassword' pg_dump -h localhost -U irisuser -d irisdb --format=custom --file=/backups/irisdb_$(date +\%Y\%m\%d).dump 2>/dev/null

# Keep only last 30 days
5 3 * * * find /backups -name "irisdb_*.dump" -mtime +30 -delete
```

### Fresh Install vs. Restore

| Scenario | Procedure |
|----------|-----------|
| **Complete restore** (drive died) | Install OS → PostgreSQL → Restore from pg_dump → Clone git repo → Build llama.cpp → Place models → Start services |
| **Fresh install** (new Iris) | Follow this guide top to bottom. Iris will work but have no memories or chat history. |
| **Code only** (database intact) | `git clone` → `pip install -r requirements.txt` → Start services |

---

## Port Reference

### Localhost

| Port | Service | Protocol |
|------|---------|----------|
| 5432 | PostgreSQL | TCP |
| 8000 | Iris FastAPI | HTTP/WebSocket |
| 11434 | llama-server | HTTP (OpenAI-compatible) |

### Node2

| Port | Service | GPU | Protocol |
|------|---------|-----|----------|
| 11435 | Vision OR Freud | 0 | HTTP (mutually exclusive) |
| 8000 | FLOAT video | 0 | HTTP |
| 8189 | ComfyUI | 0 | HTTP (optional) |
| 8700 | XTTS (TTS) | 1 | HTTP |
| 8600 | Whisper (STT) | 1 | HTTP |
| 11437 | Sentiment (Mistral) | 1 | HTTP |

---

## Version Reference

| Component | Version | Notes |
|-----------|---------|-------|
| Ubuntu | 24.04.3 LTS | Noble Numbat |
| Python | 3.12.3 | |
| CUDA | 12.8 (V12.8.61) | |
| GPU Driver | 580.126.09 | RTX 5090 |
| PostgreSQL | 16.11 | |
| pgvector | 0.8.0 | |
| FastAPI | 0.109.0 | |
| tiktoken | 0.5.2 | Encoding: cl100k_base |
| llama.cpp | Latest (build from source) | Must support `--jinja` and `--cache-reuse` |

---

*This document was generated 2026-01-28 by auditing the live system. Keep it updated when infrastructure changes.*
