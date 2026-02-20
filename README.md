# Airis v1 — AI Companion for Assisted Living

A relational AI companion built for the **Designed Around Dignity (DAD) Foundation**. One box, one person. The data on the box belongs to them.

Airis is not an assistant — it's a companion. It remembers, it grows, and it makes people feel seen.

## Install

On a fresh Ubuntu machine:

```bash
curl -sL https://raw.githubusercontent.com/vshortt73/airis-v1/main/scripts/install.sh | bash
```

The installer handles everything: system packages, PostgreSQL + pgvector, Python venv, dependencies, database bootstrap, and systemd service. It will ask for:

- **Database password** — for the `airisuser` PostgreSQL user
- **Inference server URL** — the facility server running sglang (e.g., `http://192.168.1.50:11434`)
- **Airis port** — default `9000`

## After Install

```bash
# Start
sudo systemctl start airis

# Stop
sudo systemctl stop airis

# Logs
sudo journalctl -u airis -f

# Manual start (for debugging)
/airis-v1/scripts/start.sh
```

Open browser: `http://localhost:9000`

## Architecture

```
Client Box (no GPU)                    Facility Server (GPU)
┌──────────────────────┐              ┌──────────────────────┐
│  Airis (FastAPI)     │   network    │  sglang              │
│  PostgreSQL + pgvec  │ ──────────── │  Qwen3-32B           │
│  Embeddings (CPU)    │              │  (shared across boxes)│
│  sentence-transformers│              └──────────────────────┘
└──────────────────────┘
```

- **Client box**: Runs the companion server, database, and CPU-based embeddings. No GPU required.
- **Facility server**: Runs sglang with Qwen3-32B (or similar). Shared across all client boxes on the network. Stateless — resident data never leaves the client box.

## Progressive Activation (Bloom Levels)

The companion starts empty and grows with the relationship:

| Level | Name | Unlocks |
|-------|------|---------|
| 0 | Seed | System instructions only (cold start) |
| 1 | Facts | Short-term facts included in prompt |
| 2 | Memory | Episodic memory retrieval activates |
| 3 | Personality | Traits shape companion behavior |
| 4 | Knowledge | Semantic memories (distilled insights) |
| 5 | Full Bloom | Dreams, dream truths, inner drive |

Thresholds are configurable in `system_config` (category `activation`).

## Configuration

All runtime config lives in the `system_config` database table. Key settings:

| Category | Key | Description |
|----------|-----|-------------|
| `llm` | `OLLAMA_BASE_URL` | Inference server URL (set during install) |
| `server` | `PORT` | Airis server port |
| `activation` | `MEMORY_THRESHOLD` | Memories needed for bloom level 2 |
| `features` | `NODE2_ENABLED` | Enable/disable Node2 services (default: false) |

Deployment-specific config is stored in `/etc/airis/env`:

```bash
AIRIS_DB_PASSWORD=...
AIRIS_INFERENCE_URL=http://facility-server:11434
AIRIS_PORT=9000
```

## Re-running Bootstrap

If you need to re-bootstrap the database (e.g., after a schema update):

```bash
/airis-v1/scripts/bootstrap_airisdb.sh
```

It will detect your existing `/etc/airis/env` and offer to reuse it.

## Key Directories

```
/airis-v1/              # Application code
/venv/airis/            # Python virtual environment
/etc/airis/env          # Deployment config (password, inference URL, port)
/models/                # Embedding model (all-mpnet-base-v2)
```

## Embedding Model

The embedding model (`all-mpnet-base-v2`, ~420MB) runs on CPU. Options:

1. **Copy from facility server**: `scp -r user@server:/models/llm_models/huggingface/models/all-mpnet-base-v2 /models/llm_models/huggingface/models/all-mpnet-base-v2`
2. **Auto-download**: Airis downloads it from HuggingFace on first start (requires internet)

## Development

```bash
source /venv/airis/bin/activate
export AIRIS_DB_PASSWORD='...'
python app/main.py
```

## Version

**Airis v1.0.0-alpha** — DAD Foundation Client Box

Built on Iris v3 core. Forked February 2026.

## License

Designed Around Dignity (DAD) Foundation. All rights reserved.
