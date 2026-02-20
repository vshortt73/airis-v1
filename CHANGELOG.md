# Changelog

All notable changes to Airis v1 are documented here.

Format: [Keep a Changelog](https://keepachangelog.com/). Versioning: `1.MINOR.PATCH`.

---

## [1.0.0-alpha] - 2026-02-19

First deployable release. Fresh Ubuntu to running companion in one command.

### Added
- **One-command installer** (`scripts/install.sh`) — `curl | bash` installs system packages, PostgreSQL + pgvector, Python venv, CPU-only PyTorch, lean requirements, database bootstrap, embedding model setup, and systemd service
- **Interactive bootstrap** (`scripts/bootstrap_airisdb.sh`) — Prompts for database password, inference server URL, and port. Writes `/etc/airis/env`. Detects and reuses existing config on re-run
- **Progressive activation** (`core/progressive_activation.py`) — Bloom levels 0-5. Companion starts empty and grows as relationship data accumulates. Configurable thresholds in `system_config`
- **Bloom tracking table** — Single-row `bloom_tracking` table records current level, conversation count, memory count
- **Systemd service** (`scripts/airis.service`) — Production service with auto-restart, environment file sourcing
- **Client box requirements** (`requirements-client.txt`) — 31 packages (down from 379). CPU-only torch, no GPU/vision/audio dependencies
- **pg_hba.conf auto-configuration** — Installer ensures PostgreSQL allows password auth over TCP for fresh installs
- **Warm gold + calm blue UI** — Distinct from Iris purple/teal color scheme

### Changed
- **Database isolation** — `AIRIS_DB_*` env vars, defaults to `airisdb`/`airisuser` (completely separate from Iris)
- **Venv renamed** — `/venv/iris-v3` to `/venv/airis` across all scripts, services, and SQL config
- **Config externalization** — All DB connection params driven by environment variables. No hardcoded credentials
- **Inference via network** — Client box has no local LLM. Connects to facility sglang server over network. URL configured during bootstrap
- **Node2/GPU disabled by default** — `NODE2_ENABLED`, `GPU_MANAGER_ENABLED`, `TTS_ENABLED`, `STT_ENABLED`, `DREAMS_ENABLED`, `TRANSCRIBE_ENABLED` all default to `false`
- **Module-scope config guards** — 9 files fixed with `getattr()` pattern to prevent import crashes when Node2 config attributes don't exist
- **SQL grants use CURRENT_USER** — No more hardcoded `irisuser` in table grants
- **Startup banner** — "Airis" branding, not "Iris"
- **System instructions** — Rewritten as generic companion identity, not Iris personality

### Removed
- **Moltbook tool** — Iris-specific social feature, not applicable to companion deployment
- **Hardcoded Iris paths** — `/iris-v3` references replaced with `/airis-v1` in all functional files
- **Node2 path config** — No `LLAMA_SERVER_PATH`, `EMOTION_MODEL_PATH`, or other GPU/Node2 paths in default config

---

*Forked from Iris v3.1.0 (February 2026)*
