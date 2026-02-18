# Deployability Audit — Hardcoded Dependency Manifest

**Purpose:** Complete inventory of every hardcoded value preventing Iris v3 from being deployable to another machine, user, or identity. This is the roadmap for abstraction work.

**Audit Date:** 2026-01-30
**Last Updated:** 2026-01-30 (post-centralization pass)

---

## Summary

| Category | Count | Severity | Status |
|----------|-------|----------|--------|
| Node2 hostname/SSH references | ~70 | High — blocks single-node deployment | **Partially resolved** — SSH, feature flags, and key URLs centralized |
| Machine-specific file paths | ~45 | High — blocks any other machine | **Largely resolved** — shell scripts use `paths.env`, DB keys exist for Python; ~10 Python files still need wiring |
| Database credentials (hardcoded "yourpassword") | 13 files | Medium — env var exists but fallbacks are everywhere | Open |
| Model names (qwen3, llava-phi-3, etc.) | ~25 | Medium — blocks model-agnostic deployment | Open |
| Identity names (Iris, Victor, Captain) | ~20 | Medium — blocks other identities | Open |
| Systemd service names | ~15 | Low — only matters for service management | Open |
| Feature assumptions (unconditional imports) | ~5 | Low — causes import errors if subsystem missing | **Partially resolved** — UI controls now gated by capability flags |

**Total hardcoded values: ~200+ (estimated ~15 resolved this pass)**

---

## Category 1: Node2 / Two-Node Architecture

Everything that assumes a second server exists at hostname "node2".

### SSH References (must become optional or configurable)

| File | Line | Value | Purpose | Status |
|------|------|-------|---------|--------|
| `core/gpu_manager.py` | 71 | `NODE2_SSH = "captain@node2"` | SSH connection constant | **RESOLVED** — now uses `_get_node2_ssh()` reading from `config.NODE2_SSH_USER` + `config.NODE2_HOST` |
| `app/api/routes_admin.py` | 476 | `ssh captain@node2 'sudo systemctl ...'` | Service control | **RESOLVED** — now builds SSH target from config |
| `app/api/routes_admin.py` | 699 | `ssh captain@node2 'echo ...'` | STT config write | **RESOLVED** — same |
| `app/api/routes_admin.py` | 1043 | `ssh captain@node2 'journalctl ...'` | Log retrieval | **RESOLVED** — same |
| `scripts/nightly_dream.sh` | 72-73 | `NODE2_HOST="node2"`, `NODE2_USER="captain"` | Dream script | **RESOLVED** — now queries `system_config` table with fallback defaults |

**Config keys added:** `NODE2_HOST` and `NODE2_SSH_USER` in `system_config` table (`remote_services` category), with fallback defaults in `config.py`.

### Service Health URLs (must become config-driven or optional)

| File | Line | Value | Service | Status |
|------|------|-------|---------|--------|
| `core/gpu_manager.py` | 43 | `http://node2:11435/health` | Vision | Reads from `config.VISION_OLLAMA_URL` — config-driven |
| `core/gpu_manager.py` | 50 | `http://node2:8000/` | FLOAT | Reads from `config.FLOAT_SERVER_URL` — config-driven |
| `core/gpu_manager.py` | 57 | `http://node2:11435/health` | Freud | Reads from `config.FREUD_URL` — config-driven |
| `core/gpu_manager.py` | 64 | `http://node2:8189/system_stats` | ComfyUI | Open — still hardcoded |

### Service URL Fallbacks (in code where config.X falls back to node2)

| File | Line | Config Key | Fallback |
|------|------|-----------|----------|
| `app/api/routes_stt.py` | 22, 30 | `STT_SERVER_URL` | `http://node2:8600` |
| `app/api/routes_video.py` | 190, 200 | `FLOAT_SERVER_URL` | `http://node2:8800` (BUG: wrong port) |
| `core/summary_generator.py` | 24 | `MISTRAL_URL` | `http://node2:11437/v1/chat/completions` |
| `core/emotional_state.py` | 35 | `MISTRAL_URL` | `http://localhost:11436/v1/chat/completions` |
| `services/paddleocr_service.py` | 21, 23 | `PADDLEOCR_SERVER_URL` | `http://node2:5200` |
| `services/florence2_service.py` | 35, 38 | `FLORENCE2_SERVER_URL` | `http://node2:5100` |
| `backend/memory/dreams/conversation_manager.py` | 25 | `FREUD_URL` | `http://node2:11435` |

### No Config Fallback (hardcoded directly)

| File | Line | Value | Purpose | Status |
|------|------|-------|---------|--------|
| `core/want_detector.py` | 31 | `http://node2:11437/v1/chat/completions` | Mistral URL — NO config lookup | Open |
| `mcp_servers/creative/creative_server.py` | 27 | `http://node2:8189` | ComfyUI URL — NO config lookup | Open |
| `mcp_servers/creative/creative_server.py` | 28 | `/home/captain/node2-mount/programs/ComfyUI/output` | NFS mount path | Open |
| `app/api/routes_ephemeral.py` | — | `http://node2:11437` | Mistral URL for ephemeral chat | **RESOLVED** — now derives from `config.MISTRAL_URL` |
| `mcp_servers/directions/processors/directions_maker.py` | — | `http://localhost:5200` | PaddleOCR URL | **RESOLVED** — now reads from `config.PADDLEOCR_SERVER_URL` with env var fallback |

### Admin UI (HTML/JS references to node2)

| File | Lines | Value | Status |
|------|-------|-------|--------|
| `static/admin.html` | 412-414 | `id="node2-refresh"`, `id="node2-services"` | Open — cosmetic |
| `static/admin.html` | 1199-1221 | JS references to `data.node2`, node2 rendering | Open — cosmetic |
| `static/admin.html` | 1753 | Confirmation dialog mentioning "node2" | Open — cosmetic |

### Main Chat UI (feature gating)

| File | Lines | Value | Status |
|------|-------|-------|--------|
| `static/js/main.js` | — | Voice/Mic/Video controls always active | **RESOLVED** — `loadCapabilities()` queries `/api/capabilities` on page load, disables controls when services unavailable |
| `static/css/main.css` | — | No disabled state styling | **RESOLVED** — `.disabled-feature` class with opacity + pointer-events |
| `app/main.py` | — | No capability endpoint | **RESOLVED** — `GET /api/capabilities` exposes `tts`, `stt`, `video`, `vision` flags via `is_node2_service_enabled()` |

### Database Config (SQL populates node2 URLs)

| File | Lines | Values |
|------|-------|--------|
| `database/sql/populate_system_config_complete.sql` | 46-56 | All `remote_services` category entries with `http://node2:*` |

---

## Category 2: Machine-Specific File Paths

**Status: Largely resolved.** Paths are centralized in two places:
- **Shell scripts:** `scripts/paths.env` (sourced by 7 scripts) — defines `IRIS_VENV`, `IRIS_PROJECT_ROOT`, `IRIS_LLAMA_SERVER`, model paths
- **Python code:** `database/sql/add_path_config.sql` — 15 entries in `system_config` table (`paths` and `node2_paths` categories)

### Python Virtual Environment

| File | Line | Path | Status |
|------|------|------|--------|
| `scripts/start.sh` | 75 | `/venv/iris-v3/bin/activate` | **RESOLVED** — sources `paths.env` `$IRIS_VENV` |
| `scripts/llama_server_start.sh` | 3 | `/venv/iris-v3/bin/activate` | **RESOLVED** — sources `paths.env` |
| `scripts/llama_freud_server_start.sh` | 4 | `/venv/iris-v3/bin/activate` | File deleted |
| `scripts/sglang_server_start.sh` | 3 | `/venv/iris-v3/bin/activate` | **RESOLVED** — sources `paths.env` |
| `scripts/llama_q6.sh` | 3 | `/venv/iris-v3/bin/activate` | **RESOLVED** — sources `paths.env` |
| `scripts/nightly_memory_creation.sh` | 18 | `/venv/iris-v3/bin/python` | **RESOLVED** — sources `paths.env` |
| `scripts/index_knowledge.sh` | 15 | `/venv/iris-v3/bin/python` | **RESOLVED** — sources `paths.env` |
| `scripts/nightly_dream.sh` | 19 | `/venv/iris-v3` | **RESOLVED** — sources `paths.env` |

### LLM Model Files

| File | Line | Path | Model | Status |
|------|------|------|-------|--------|
| `scripts/llama_server_start.sh` | 6 | `/localmodels/qwen/Qwen3-32B-Q4_K_M.gguf` | Main Qwen3 | **RESOLVED** — uses `$IRIS_MAIN_MODEL` from `paths.env` |
| `scripts/llama_q6.sh` | 6 | `/models/llm_models/qwen/...` | Alt Qwen3 | **RESOLVED** — uses `$IRIS_ALT_MODEL` from `paths.env` |
| `scripts/llama_freud_server_start.sh` | 9 | `/localmodels/gemma/...` | Freud | File deleted |
| `scripts/llama_small_server_start.sh` | 6-7 | `/models/vision/qwen/...` | Vision | File deleted |
| `app/api/routes_vision.py` | 268 | `/models/vision/llava-v1.6-mistral-7b.Q4_K_M.gguf` | Vision | Open — Python code, needs config lookup |

### llama.cpp Binary

| File | Line | Path | Status |
|------|------|------|--------|
| `scripts/llama_server_start.sh` | 5 | `/programs/llama.cpp/build/bin/llama-server` | **RESOLVED** — uses `$IRIS_LLAMA_SERVER` from `paths.env` |
| `scripts/sglang_server_start.sh` | 5 | `/programs/llama.cpp/build/bin/llama-server` | **RESOLVED** — uses `$IRIS_LLAMA_SERVER` |
| `scripts/llama_q6.sh` | 5 | `/programs/llama.cpp/build/bin/llama-server` | **RESOLVED** — uses `$IRIS_LLAMA_SERVER` |
| `scripts/llama_freud_server_start.sh` | 8 | `/programs/llama.cpp/build/bin/llama-server` | File deleted |

### Embedding Model

| File | Line | Path | Status |
|------|------|------|--------|
| `core/embeddings.py` | 63, 76 | `/home/captain/.cache/huggingface/hub` | Open — needs `config.HF_CACHE_DIR` lookup (DB key exists) |
| `backend/llama_engines/llm_engine.py` | 187 | `/models/.../all-mpnet-base-v2/` | Open — needs `config.EMBEDDING_MODEL_PATH` lookup (DB key exists) |
| `backend/llama_engines/small_llm_api.py` | 24 | `/models/.../all-mpnet-base-v2/` | Open — same |
| `backend/memory/backfill_topic_labels.py` | 35 | `/models/.../all-mpnet-base-v2/` | Open — same |

### Emotion/Valence Models

| File | Line | Paths | Status |
|------|------|-------|--------|
| `backend/memory/iris_memory_retrieval.py` | 52-54 | `/models/Memory-models/emotion_model_balanced`, `valence_model`, `arousal_model` | Open — needs config lookup (DB keys exist) |

### Other Machine-Specific Paths

| File | Line | Path | Purpose | Status |
|------|------|------|---------|--------|
| `app/api/routes_tts.py` | 560 | `/home/captain/bin/rhubarb` | Lip-sync tool | Open — needs `config.RHUBARB_PATH` lookup (DB key exists) |
| `app/api/routes_video.py` | 38-42 | `/iris-v3/assets/temp`, etc. | Video system dirs | Open — could derive from `config.PROJECT_ROOT` |
| `services/face_monitor.py` | 445 | `/iris-v3/ssl/cert.pem` | SSL cert | Open — needs `config.SSL_CERT_PATH` lookup (DB key exists) |
| `services/florence2_service.py` | 41 | `/models/vision/florence2` | Florence2 model | Open — needs `config.FLORENCE2_MODEL_PATH` lookup (DB key exists) |
| `mcp_servers/system/system_server.py` | 478, 607, 740 | `/iris-v3` | Project root | Open — needs `config.PROJECT_ROOT` lookup (DB key exists) |

**Note:** The database keys for all "Open" Python items above already exist in `add_path_config.sql`. The remaining work is wiring the Python code to read from `config.X` instead of hardcoding. The shell scripts are fully resolved via `paths.env`.

---

## Category 3: Database Credentials

`IRIS_DB_PASSWORD` env var is the intended method, but "yourpassword" appears as hardcoded fallback in 13 files:

| File | Line | Context |
|------|------|---------|
| `app/config.py` | 28 | Main config fallback |
| `app/api/routes_chat.py` | 290 | Subprocess environment |
| `scripts/start.sh` | 11-12 | Shell script |
| `scripts/iris/safe_query.sh` | 8 | Shell script |
| `scripts/iris/claude_safe_query.sh` | 8 | Shell script |
| `backend/llama_engines/llm_engine.py` | 37 | Engine config |
| `backend/llama_engines/small_llm_api.py` | 16 | Engine config |
| `backend/memory/test_model_for_topics.py` | 12 | Test file |
| `backend/memory/test_topic_vs_narrative.py` | 44 | Test file |
| `backend/memory/debug_embeddings.py` | 27 | Test file |
| `backend/memory/comprehensive_validation.py` | 22 | Test file |
| `backend/memory/backfill_topic_labels.py` | 37 | Test file |
| `backend/memory/generate_test_sessions.py` | 17 | Test file |

Database name `irisdb` and user `irisuser` hardcoded in 5+ files (config.py, llm_engine.py, small_llm_api.py, test files).

---

## Category 4: Model Names

Hardcoded model identifiers that assume specific models are installed.

| Model | Files | Count |
|-------|-------|-------|
| `qwen3:32b` / `qwen3-32b` | config.py, routes_admin.py, routes_ephemeral.py, conversation_manager.py, dream_moderator.py, dream_storage.py, iris-monitor.py | 10+ |
| `llava-phi-3` | gpu_manager.py, config.py, vision_service.py | 4 |
| `gemma-3-4b` / `gemma3:4b` | gpu_manager.py, config.py, dream scripts | 5 |
| `mistral-7b` | routes_admin.py | 1 |
| `qwen2.5:14b` | dream_storage.py, backfill_topic_labels.py | 3 |
| `all-mpnet-base-v2` | embeddings.py, llm_engine.py, small_llm_api.py, test files | 8 |

---

## Category 5: Identity Names

Hardcoded references to "Iris", "Victor", and "Captain" in code (not docs).

| Name | File | Line | Context |
|------|------|------|---------|
| Iris + Victor | `core/system_prompt.py` | 340 | Fallback prompt: "You are Iris...conversation with Victor" |
| Iris + Victor | `core/prompt_builder.py` | 193 | Fallback prompt (duplicate) |
| Victor | `core/summary_generator.py` | 28, 98, 100 | Third-person summary instructions |
| Iris + Victor | `backend/memory/new/memory_creation.py` | 122-123 | Memory creation instructions |
| Captain | `core/system_prompt.py` | 932-953, 1080-1085 | Dream consolidation templates |
| Victor | `mcp_servers/protocols/protocol_loader.py` | 196, 205 | Default user name |
| Victor | `tests/face_detect_reset.py` | 23, 31 | Test data |
| Iris | `static/index.html` | 6, 19, 96 | Page title, header, PiP label |
| Iris | `static/js/main.js` | 587 | "Iris is thinking..." placeholder |

---

## Category 6: Feature Assumptions

Code that imports or initializes subsystems unconditionally, which would crash if the subsystem isn't installed.

| File | Line | Import/Assumption | Risk | Status |
|------|------|-------------------|------|--------|
| `app/main.py` | 49 | `from services import face_monitor` | Crashes if face_recognition not installed | Open |
| `app/main.py` | 65 | `from services import face_monitor` (shutdown) | Same | Open |
| `core/system_prompt.py` | 20 | `from core.emotional_state import get_emotional_tracker` | Crashes if sentiment service deps missing | Open |
| `app/api/routes_chat.py` | 33 | `from core.emotional_state import ...` | Same | Open |
| `core/system_prompt.py` | 359-390 | Queries `episodic_dreams` table | Fails if table doesn't exist | Open |
| `core/system_prompt.py` | 417-447 | Queries `dream_truths` table | Fails if table doesn't exist | Open |

**New:** The frontend now gracefully handles disabled Node2 services via the `/api/capabilities` endpoint and `applyCapabilities()` in `main.js`. Controls are visually disabled with tooltips explaining why, rather than failing silently.

---

## Category 7: Systemd Service Names

| Service | Files Referenced |
|---------|-----------------|
| `iris-vision.service` | gpu_manager.py, routes_admin.py |
| `iris-float.service` | gpu_manager.py, routes_admin.py |
| `iris-freud.service` | gpu_manager.py, routes_admin.py |
| `iris-xtts.service` | routes_admin.py |
| `iris-stt.service` | routes_admin.py |
| `iris-sentiment.service` | routes_admin.py |
| `comfyui.service` | gpu_manager.py |
| `iris-main` | routes_admin.py |
| `iris-llama` | nightly_memory_creation.sh |

---

## Bugs Found During Audit

1. **Wrong FLOAT port** — `app/api/routes_video.py:190` defaults to `http://node2:8800` but FLOAT runs on port `8000` — **FIXED**
2. **Wrong GPU assignment** — `scripts/llama_freud_server_start.sh:6` uses `CUDA_VISIBLE_DEVICES=1` but Freud should be on GPU 0 — **FIXED** (script deleted)
3. **Stale sentiment URL** — `core/emotional_state.py:35` defaults to `http://localhost:11436` (old port) instead of `http://node2:11437` — **FIXED**

---

## Recommended Abstraction Priority

### Phase 1: Configuration Centralization (enables single-machine deployment)
1. Route ALL service URLs through `config.py` / `system_config` table — eliminate inline fallbacks
   - **Progress:** SSH targets centralized, most service URLs config-driven. Remaining: `want_detector.py` Mistral URL, `creative_server.py` ComfyUI URL + NFS path.
2. Route ALL file paths through config — model paths, binary paths, project root
   - **Progress:** Shell scripts fully resolved via `scripts/paths.env`. Database keys created for all paths in `add_path_config.sql`. Remaining: ~10 Python files need to read from `config.X` instead of hardcoding (DB keys already exist).
3. Make Node2 entirely optional — feature flags for TTS, STT, vision, video, sentiment
   - **DONE:** `NODE2_ENABLED` master flag + per-service flags (`TTS_ENABLED`, `STT_ENABLED`, `VIDEO_ENABLED`, `VISION_ENABLED`) in database. Backend returns 503 when disabled. Frontend queries `/api/capabilities` and disables UI controls (voice toggle, mic button, video button) with visual feedback.
4. Fix the 3 bugs found above
   - **DONE:** FLOAT port corrected, Freud script deleted, sentiment URL fixed.

### Phase 2: Identity Abstraction (enables other AI identities)
1. Move "Iris"/"Victor"/"Captain" to config/database — replace hardcoded names
2. Parameterize frontend (page title, thinking message, PiP label)
3. Parameterize summary generator and memory creation instructions
4. Create first-run setup for identity bootstrapping

### Phase 3: Hardware Abstraction (enables arbitrary hardware)
1. Auto-detect available GPUs and services
2. Make GPU manager topology configurable (not hardcoded to 2-node)
3. Parameterize systemd service names
4. Abstract SSH user/host for remote nodes
   - **DONE:** `NODE2_HOST` and `NODE2_SSH_USER` in `system_config` table. GPU manager, admin routes, and shell scripts all read from config/database with fallback defaults.

---

---

## Completed Work Log

### 2026-01-30: Node2 Centralization + UI Feature Gating

**SSH/hostname centralization** (5 sites resolved):
- `core/gpu_manager.py` — `_get_node2_ssh()` helper reads `config.NODE2_HOST` + `config.NODE2_SSH_USER`
- `app/api/routes_admin.py` — 3 SSH command sites now build target from config
- `scripts/nightly_dream.sh` — queries `system_config` table for `NODE2_HOST` and `NODE2_SSH_USER`

**URL centralization** (2 sites resolved):
- `app/api/routes_ephemeral.py` — Mistral URL derived from `config.MISTRAL_URL`
- `mcp_servers/directions/processors/directions_maker.py` — PaddleOCR URL from config with env var fallback

**Dynamic service discovery** (1 site resolved):
- `tools/iris-monitor.py` — queries `/api/admin/services/all` API on startup, falls back to hardcoded defaults

**UI feature gating** (new capability):
- `app/main.py` — new `GET /api/capabilities` endpoint exposes `tts`, `stt`, `video`, `vision` flags
- `static/js/main.js` — `loadCapabilities()` + `applyCapabilities()` disable controls when services unavailable
- `static/css/main.css` — `.disabled-feature` class for visual disabled state

**File path centralization** (prior work, now documented):
- `scripts/paths.env` — centralized shell path variables (`IRIS_VENV`, `IRIS_PROJECT_ROOT`, `IRIS_LLAMA_SERVER`, model paths), sourced by 7 scripts
- `database/sql/add_path_config.sql` — 15 path entries in `system_config` table covering all model paths, binary paths, cache dirs
- All shell scripts (`start.sh`, `llama_server_start.sh`, `llama_q6.sh`, `sglang_server_start.sh`, `nightly_*.sh`, `index_knowledge.sh`) now source `paths.env`
- Deleted scripts: `llama_freud_server_start.sh`, `llama_small_server_start.sh`

**Config infrastructure improvements**:
- `app/api/routes_admin.py` — config update now uses `reload_config()` + `inject_into_module()` for proper type conversion instead of raw `setattr()`
- `app/api/routes_admin.py` — mismatch comparison uses `str()` for type-safe comparison
- `database/sql/populate_system_config_complete.sql` — added `NODE2_HOST` and `NODE2_SSH_USER` entries

---

*This manifest is the roadmap for making Iris v3 deployable. Each item is a concrete, verifiable change.*
