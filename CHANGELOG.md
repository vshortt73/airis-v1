# Changelog

All notable changes to Iris v3 are documented here.

Format: [Keep a Changelog](https://keepachangelog.com/). Versioning: `3.MINOR.PATCH`.

---

## [3.0.0] - 2026-02-18

Stable baseline. Declares the current state of Iris v3 as the versioned starting point.

### Added
- **Chat pipeline refactor** — Split monolithic routes_chat.py into 9 focused modules under `app/api/chat/` (connection, input, tools, TTS, video, observability, turn pipeline, system endpoints)
- **MCP smart tool selection** — Keyword triggers and tool groups reduce token overhead sent to LLM; native MCP tool discovery via `list_tools`; DB-driven server configs
- **New MCP servers** — Calendar (events CRUD + reminders), Meeting (recording + WhisperX transcription), Moltbook (social network integration)
- **MCP server enhancements** — News headlines RSS tool, distributed system health check, directions tool split, knowledge_save tool
- **Node2 feature flags** — Master `NODE2_ENABLED` switch + per-service flags gate all Node2-dependent functionality, enabling single-node deployment
- **Semantic memory consolidation** — Nightly pipeline clusters episodic memories by embedding similarity, distills via LLM into `semantic_memories` table
- **Memory retrieval v2** — Inline episodic retrieval (~200ms) with 3-factor scoring: topic similarity, emotional resonance, recency decay
- **Gap report system** — "While you were away" XML injected on first turn after 30min+ gap, reporting memory processing, dreams, and service health
- **Autonomous drive system** — Background daemon tracking 7 internal state variables with drift/decay/noise, persisted to PostgreSQL
- **Observability system** — Per-turn metrics, drift analysis, and dashboard
- **Repetition prevention** — LLM-powered structural detection via Mistral 7B + application-layer cross-turn echo gate
- **Version tracking** — `VERSION` file as single source of truth, exposed in `/api/health`, startup banner, admin console
- **Desktop tools** — GTK service monitor and drive state monitor

### Changed
- **Deployability hardening** — Replaced hardcoded paths and credentials across 34+ files with env vars, `config.py`, and shared `scripts/paths.env`
- **HTTPS dual-port** — SSL on port 8443 with HTTP 301 redirect from 8000
- **Prompt format** — XML-tagged system prompt sections, concise memory format, third-person summaries
- **Node2 resilience** — SSH retry with exponential backoff (3 attempts), circuit breaker (opens after 3 failures, 120s cooldown), state reconciliation on crash detection
- **Dream script hardened** — Trap-based cleanup guarantees vision restore on any exit, SSH timeout flags, 3-attempt retry on restore
- **Token counting** — Now counts `tool_calls`, `tool_call_id`, `tool_name` fields
- **Frontend** — Meeting recorder UI, HLS video pop-out with session handoff, new idle/thinking animation videos, admin panel enhancements

### Fixed
- Memory creation pipeline silent failure when LLM unavailable
- Structural analysis formatting for Mistral, message deduplication
- Repetitive motif loops via penalties, temperature adjustment, drive message cap
- Context overflow protection
