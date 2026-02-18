# Iris v3 Complete System Architecture Audit

**Date:** 2026-02-18
**Scope:** Every subsystem, service, and component in the Iris v3 codebase as it runs today.

---

## Table of Contents

1. [Hardware Topology](#1-hardware-topology)
2. [Input Systems](#2-input-systems)
3. [Inference Systems](#3-inference-systems)
4. [Memory Systems](#4-memory-systems)
5. [Personality Systems](#5-personality-systems)
6. [Output Systems](#6-output-systems)
7. [Background / Maintenance Systems](#7-background--maintenance-systems)
8. [Infrastructure](#8-infrastructure)
9. [Port & Service Map](#9-port--service-map)
10. [Database Schema Inventory](#10-database-schema-inventory)

---

## 1. Hardware Topology

### Node: iris-desktop (localhost)

| Resource | Spec |
|----------|------|
| GPU | NVIDIA RTX 5090, 32 GB VRAM |
| Role | Primary LLM inference (qwen3:32b), FastAPI server, PostgreSQL, embedding model |

### Node: iris-node2 (remote, SSH)

| GPU | Spec | Allocation |
|-----|------|------------|
| GPU 0 | NVIDIA RTX 4080 Super, 16 GB VRAM | **Mutually exclusive** -- only one service at a time: vision, float, freud, transcribe, comfyui |
| GPU 1 | NVIDIA RTX 3060, 12 GB VRAM | **Coexisting** -- XTTS + Whisper STT + Mistral 7B sentiment run simultaneously |

---

## 2. Input Systems

### 2.1 Text Input (WebSocket Chat)

| Field | Detail |
|-------|--------|
| **What it is** | Primary text input via WebSocket at `/ws/chat`. Browser sends JSON `{message, sender}` messages. Also accepts image attachments (base64), document uploads (PDF/DOCX/ODT/TXT/MD), and webcam frames. |
| **Implementation** | `app/api/routes_chat.py` -- single ~2,834-line `websocket_chat()` function |
| **Depends on** | FastAPI (uvicorn), browser client (`static/js/main.js`), PostgreSQL (message persistence) |
| **Compute** | CPU only. No GPU. Latency-sensitive -- this is the real-time conversation pathway. |
| **Data reads** | `chat_history` (load recent conversation across all sessions), `system_config`, `mcp_tools`, `fulltraits`, `system_instructions`, `live_memories`, `short_term_facts`, `seeds`, `calendar_events`, `episodic_dreams`, `semantic_memories`, `face_presence_state` |
| **Data writes** | `chat_history` (new user/assistant/tool messages with embeddings, tool_calls JSON, attachments JSON), `chat_sessions` (session creation/update), `emotional_state`, `turn_metrics`, `seed_suggestions` |
| **Personal data** | Yes. All user text, uploaded documents, and images are stored in `chat_history`. |
| **Network** | Localhost only (browser <-> FastAPI). WebSocket (ws:// or wss://). |

### 2.2 Speech-to-Text (STT)

| Field | Detail |
|-------|--------|
| **What it is** | Voice Activity Detection (VAD) in browser captures speech, uploads audio to `/stt-upload`, which proxies to Whisper ASR on Node2. |
| **Implementation** | Browser: `static/audio_in.js` (IrisVOX namespace). Server: `app/api/routes_stt.py`. Remote: Whisper ASR service on Node2 GPU 1. |
| **Depends on** | Node2 Whisper service (`iris-stt` systemd unit), `NODE2_ENABLED` + `STT_ENABLED` feature flags, browser `MediaRecorder` API |
| **Compute** | Browser: CPU (RMS VAD, MediaRecorder WebM/Opus encoding). Node2 GPU 1: Whisper model ~2 GB VRAM. Latency-sensitive -- user waits for transcript. |
| **Data reads** | `system_config` (STT_SERVER_URL, feature flags) |
| **Data writes** | None directly. Transcript text is returned to browser, which injects it as a chat message through the WebSocket. |
| **Personal data** | Yes. Audio is recorded from user's microphone. Audio is not persisted server-side (streamed and discarded). Transcript becomes chat text. |
| **Network** | Browser -> localhost:8000 `/stt-upload` (HTTP POST, audio file) -> Node2:8600 `/transcribe` (HTTP POST). Latency-sensitive. |

**VOX Parameters (configurable via admin panel):**
- `VOX_THRESHOLD`: 0.025 RMS power
- `VOX_MIN_SPEECH_MS`: 3,000 ms minimum speech duration
- `VOX_SILENCE_HANG_MS`: 5,000 ms silence before cutoff

### 2.3 Webcam Face Recognition

| Field | Detail |
|-------|--------|
| **What it is** | Browser captures webcam frames every 2.5s (640x480 JPEG, quality 0.8), sends to `/api/faces/webcam_frame`. Background face monitoring detects presence changes. |
| **Implementation** | Browser: `static/js/main.js` (webcam capture). Server: `services/face_monitor.py` (background daemon), `core/face_recognition.py` (InsightFace ArcFace embeddings). Routes: `app/api/routes_faces.py`. |
| **Depends on** | InsightFace `buffalo_l` model, PostgreSQL (`face_persons`, `face_embeddings`, `face_presence_state`, `face_cameras`), `FACE_MONITORING_ENABLED` flag |
| **Compute** | CPU (or optional GPU via `FACE_USE_GPU` flag). 512-dim face embeddings. ~50ms per frame for detection + embedding. Not latency-sensitive (background). |
| **Data reads** | `face_persons`, `face_embeddings` (training images), `face_cameras`, `face_presence_state`, webcam frame cache at `/tmp/iris_webcam_cache/frame_latest.jpg` |
| **Data writes** | `face_presence_state` (entered_at, exited_at, is_present), `face_recognition_log`, `face_captures` (optional) |
| **Personal data** | Yes. Face embeddings and presence history stored. Webcam frames cached to `/tmp/` (not persisted). |
| **Network** | Browser -> localhost:8000 (HTTP POST, JPEG). Localhost only. |

### 2.4 Meeting Audio Recording

| Field | Detail |
|-------|--------|
| **What it is** | Browser-based meeting recorder captures microphone audio in 5-minute chunks (WebM/Opus, mono 16kHz, 64kbps) and uploads to server. |
| **Implementation** | Browser: `static/js/meeting-recorder.js` (MeetingRecorder class). Server: `app/api/routes_meeting.py`. MCP: `mcp_servers/meeting/meeting_server.py`. |
| **Depends on** | `TRANSCRIBE_ENABLED` flag, WhisperX on Node2 GPU 0 (via GPU manager swap), `meeting_transcripts` table |
| **Compute** | Browser: CPU (MediaRecorder). Server: CPU (chunk storage). Node2 GPU 0: WhisperX ~4 GB VRAM (mutually exclusive). Not latency-sensitive (async transcription). |
| **Data reads** | `meeting_transcripts`, `calendar_events` (auto-link nearby events) |
| **Data writes** | Audio chunks to `attachments/meetings/{meeting_id}/chunk_XXXX.webm`, `meeting_transcripts` table (status, transcript_text, speakers) |
| **Personal data** | Yes. Full meeting audio and transcripts stored. |
| **Network** | Browser -> localhost:8000 `/api/meeting/upload-chunk` (HTTP POST). Server -> Node2:8500 for transcription. |

### 2.5 Document Upload

| Field | Detail |
|-------|--------|
| **What it is** | Users can attach PDF, DOCX, ODT, TXT, MD files to chat messages. Text is extracted, chunked, and optionally indexed to knowledge base. |
| **Implementation** | `core/document_processor.py` (extraction + relevance filtering), `core/document_indexer.py` (background knowledge base indexing), `backend/knowledge/extractors.py` (pypdf, python-docx, odfpy) |
| **Depends on** | pypdf, python-docx, odfpy libraries. Embedding model (all-mpnet-base-v2) for relevance scoring and knowledge indexing. |
| **Compute** | CPU for extraction. Embedding generation ~50ms per chunk. Not latency-sensitive for indexing (background task). |
| **Data reads** | Uploaded file bytes (base64 from browser) |
| **Data writes** | Extracted text injected into conversation. Full document indexed to `knowledge_documents` + `knowledge_chunks` tables with embeddings. |
| **Personal data** | Yes. Full document content stored in knowledge base. |
| **Network** | Browser -> localhost:8000 (WebSocket, base64 payload). |

---

## 3. Inference Systems

### 3.1 Primary LLM -- Qwen3 32B via llama.cpp

| Field | Detail |
|-------|--------|
| **What it is** | Main conversational inference engine. Runs qwen3:32b (Q4_K_M quantization) on llama.cpp with OpenAI-compatible API. Handles all primary chat, tool calling, and reasoning. |
| **Implementation** | `scripts/llama_server_start.sh` (server launch), `inference/client.py` (API client), `inference/client_chat.py` (legacy Ollama native) |
| **Model file** | `/localmodels/qwen/Qwen3-32B-Q4_K_M.gguf` |
| **Depends on** | llama.cpp binary at `/programs/llama.cpp/build/bin/llama-server`, RTX 5090 GPU |
| **Compute** | **GPU: RTX 5090, ~20 GB VRAM**. Context window: 40,960 tokens. Batch size: 4,096. Flash attention enabled. 4 CPU threads. Latency-sensitive -- user-facing streaming. |
| **Data reads** | Receives assembled prompt (system message + conversation history + per-turn tail + tool definitions) via HTTP |
| **Data writes** | Returns streaming text deltas and tool calls. KV cache metrics logged. Prompt hashes stored in `prompt_hashes` table. |
| **Personal data** | Processes all conversation content (user messages, memories, traits, emotional state). No persistent storage by the LLM server itself. |
| **Network** | localhost:11434 `/v1/chat/completions` (HTTP, streaming SSE). Latency-critical. |

**Server parameters:**
- `--ctx-size 40960` (context window)
- `--jinja` (template support)
- `-fa on` (flash attention)
- `-ngl 99` (all layers on GPU)
- `--slots` (slot management)
- `-np 1` (single parallel slot)
- Inference backend configurable: `llamacpp` (default) or `sglang`

**Alternative model:** `/models/llm_models/qwen/Qwen3-30B-A3B-abliterated-erotic.Q5_K_M.gguf` (available via `scripts/llama_q6.sh`, 32,768 ctx, KV cache quantization q8_0)

### 3.2 Tool Calling Pipeline

| Field | Detail |
|-------|--------|
| **What it is** | LLM generates tool calls in its response. Tool definitions from `mcp_tools` database table are sent as function schemas. Tool execution goes through MCP client to server processes. |
| **Implementation** | `mcp_servers/tool_manager.py` (orchestration + smart selection), `mcp_servers/tool_loader.py` (DB schema loading), `mcp_servers/mcp_client.py` (FastMCP transport), `mcp_servers/server_configs.py` (server registry) |
| **Depends on** | PostgreSQL (`mcp_tools` table), FastMCP library, individual MCP server processes (12 servers, ~45 tools) |
| **Compute** | CPU for tool routing. Individual tool servers vary. Smart tool selection saves 60-80% of tool definition tokens by including only CORE + contextually-matched groups. |
| **Data reads** | `mcp_tools` table (tool_name, description, input_schema, enabled, priority, is_core, tool_group, trigger_keywords) |
| **Data writes** | Tool results appended to conversation. Turn metrics logged. |
| **Network** | MCP servers run as stdio subprocesses on localhost. Tool results subject to 3-layer truncation: per-result 15K tokens, cumulative 50% of context, preflight trim. |

**Tool result truncation (3-layer):**
1. Per-result cap: 15,000 tokens (`TOOL_RESULTS_BUDGET`)
2. Cumulative cap: 50% of context window (~20,480 tokens)
3. Preflight check in `inference/client.py` trims oldest messages before LLM call

### 3.3 Sentiment Analysis -- Mistral 7B

| Field | Detail |
|-------|--------|
| **What it is** | Analyzes user messages for emotional content each turn. Drives emotional state updates and repetition gate structural analysis. |
| **Implementation** | `core/emotional_state.py` (sentiment -> emotion mapping), `core/repetition_gate.py` (structural pattern detection), `core/summary_generator.py` (message summarization) |
| **Depends on** | Mistral 7B on Node2 GPU 1 (`iris-sentiment` systemd unit), `EMOTIONAL_STATE` feature flag |
| **Compute** | Node2 GPU 1 ~4 GB VRAM. Coexists with XTTS + STT. Latency-tolerant -- runs async after user message receipt. |
| **Data reads** | User message text, recent assistant messages (for structural analysis) |
| **Data writes** | `emotional_state` table (JSON state_data), `emotional_state_history` |
| **Network** | localhost -> Node2:11437 `/v1/chat/completions` (HTTP POST). Timeout: 15-30s. Latency-tolerant. |

### 3.4 Vision Analysis -- Pixtral 12B

| Field | Detail |
|-------|--------|
| **What it is** | Image understanding for user-uploaded images and webcam analysis. Pixtral 12B via llama.cpp on Node2 GPU 0. |
| **Implementation** | `core/vision_manager.py` (coordination), `inference/vision_service.py` (API client), `app/api/routes_vision.py` (HTTP endpoints) |
| **Depends on** | Node2 GPU 0 (`iris-vision` systemd unit), GPU Manager for exclusive access, `VISION_ENABLED` flag |
| **Compute** | Node2 GPU 0: ~12 GB VRAM. **Mutually exclusive** with FLOAT, Freud, Transcribe, ComfyUI. Startup delay: 8s. Latency-sensitive when user sends image. |
| **Data reads** | Base64 image data, vision prompt, `system_config` (vision settings) |
| **Data writes** | Vision analysis text returned to conversation |
| **Network** | localhost -> Node2:11435 `/v1/chat/completions` (HTTP). Timeout: 30s. |

**Vision config:** `VISION_MAX_TOKENS` (1000), `VISION_MAX_IMAGE_SIZE_MB` (10), `VISION_MAX_IMAGES_PER_REQUEST` (5), `VISION_TIMEOUT_SECONDS` (30)

### 3.5 Florence-2 Vision Tasks

| Field | Detail |
|-------|--------|
| **What it is** | Microsoft Florence-2 multi-task vision model. 14 tasks including captioning, object detection, OCR, grounding, segmentation. |
| **Implementation** | `services/florence2_service.py` (client), `services/florence2_server_standalone.py` (server on Node2), `app/api/routes_florence2.py` (HTTP endpoints) |
| **Depends on** | `FLORENCE2_ENABLED` flag, Node2 Florence-2 server, transformers library, AutoModelForCausalLM |
| **Compute** | Node2: ~6-8 GB VRAM (FP16). Port 5100. Can run LOCAL (cuda:0) or REMOTE (HTTP to Node2). |
| **Data reads** | Base64 images |
| **Data writes** | Task results (captions, bounding boxes, OCR text) |
| **Network** | localhost -> Node2:5100 (HTTP). Timeout: 120s inference, 300s model load. |

### 3.6 PaddleOCR

| Field | Detail |
|-------|--------|
| **What it is** | High-quality OCR optimized for challenging documents (deck plans, floor maps, rotated text). Returns text with bounding boxes for spatial analysis. |
| **Implementation** | `services/paddleocr_service.py` (client), `services/paddleocr_server_standalone.py` (server on Node2), `app/api/routes_paddleocr.py` (HTTP endpoints) |
| **Depends on** | `PADDLEOCR_ENABLED` flag, PaddleOCR library on Node2 |
| **Compute** | Node2: GPU or CPU configurable. Port 5200. Detection threshold: 0.3, side limit: 2560px. |
| **Data reads** | Base64 images |
| **Data writes** | OCR results with bounding boxes, quad points, confidence scores |
| **Network** | localhost -> Node2:5200 (HTTP). Timeout: 60s. |

### 3.7 Quick Tool Detector

| Field | Detail |
|-------|--------|
| **What it is** | Regex-based pattern matching to bypass LLM for obvious tool queries (weather, time, search, news). Saves 5-7 seconds on ~30-40% of tool queries. |
| **Implementation** | `core/quick_tool_detector.py` (singleton detector) |
| **Depends on** | Nothing external. Pure regex on message text. |
| **Compute** | CPU, sub-millisecond. Latency-reducing optimization. |
| **Data reads** | User message text, recent conversation context (for contextual follow-up patterns) |
| **Data writes** | None |
| **Network** | None |

### 3.8 Embedding Model -- all-mpnet-base-v2

| Field | Detail |
|-------|--------|
| **What it is** | SentenceTransformer model generating 768-dimensional embeddings for memory retrieval, knowledge search, document relevance, and message persistence. |
| **Implementation** | `core/embeddings.py` (singleton with thread-safe loading) |
| **Depends on** | sentence-transformers library, model cache at `/home/captain/.cache/huggingface/hub/models--sentence-transformers--all-mpnet-base-v2` |
| **Compute** | CUDA if available (localhost GPU), CPU fallback. ~50ms per embedding. Thread-safe locking prevents race conditions. Background scripts force CPU (`force_cpu=True`) to avoid competing with Ollama. |
| **Data reads** | Text strings to embed |
| **Data writes** | Returns list of 768 floats |
| **Network** | None (local model) |

---

## 4. Memory Systems

### 4.1 PostgreSQL -- Primary Data Store

| Field | Detail |
|-------|--------|
| **What it is** | PostgreSQL 15+ with pgvector extension. Single database `irisdb` on localhost. Stores all conversation, memory, configuration, and state data. |
| **Implementation** | Connection: `psycopg2` via `get_db_connection()` pattern throughout codebase. Auth: `IRIS_DB_PASSWORD` env var. |
| **Depends on** | PostgreSQL server on localhost:5432, pgvector extension (for cosine distance `<=>` and HNSW indexes) |
| **Compute** | CPU + storage. HNSW indexes for fast approximate nearest neighbor on 768-dim vectors. |
| **Data** | See [Section 10](#10-database-schema-inventory) for full table inventory. |
| **Personal data** | Yes. All conversation history, memories, emotional states, face data, meeting transcripts. |
| **Network** | localhost:5432 (TCP). All services connect locally. |

### 4.2 Conversation History & Session Management

| Field | Detail |
|-------|--------|
| **What it is** | Conversation persistence with session-independent memory loading. Sessions are for analytics only; `load_recent_conversation()` loads across ALL sessions. |
| **Implementation** | `database/persistence.py` (save/load), `core/conversation.py` (ConversationHistory class), `app/api/routes_session.py` (session endpoints) |
| **Depends on** | PostgreSQL (`chat_history`, `chat_sessions` tables) |
| **Compute** | CPU. Token-aware tiered loading: verbose recent messages + summarized older messages. |
| **Data reads** | `chat_history` (messages, tool_calls, attachments, summaries, embeddings), `chat_sessions` |
| **Data writes** | `chat_history` (new messages with emb_message embedding), `chat_sessions` (session creation) |
| **Personal data** | Yes. Full conversation text, all tool interactions, attached images/documents. |
| **Network** | localhost (PostgreSQL) |

**Tiered loading parameters:**
- `VERBOSE_TOKEN_BUDGET`: 3,000 tokens (recent full messages)
- `SUMMARY_TOKEN_BUDGET`: 17,000 tokens (older summarized messages)
- `MAX_TOTAL_MESSAGES`: 50 (safety brake)
- Tool content per-tool limits: web_search 30K, vision_analysis 5K, comfyui_render 2K, default 1K
- Drive messages limited to 2 most recent

### 4.3 Episodic Memory (Long-Term)

| Field | Detail |
|-------|--------|
| **What it is** | Long-term memories created from conversation topics. Each memory has multiple summary facets, emotion labels, and 7 embedding vectors for multi-facet retrieval. |
| **Implementation** | `backend/memory/new/memory_creation.py` (creation pipeline), `backend/memory/new/memory_evaluator.py` (worthiness evaluation), `backend/memory/new/topic_segmentation.py` (topic detection) |
| **Depends on** | PostgreSQL + pgvector, Ollama (qwen3:32b for summarization), all-mpnet-base-v2 (embeddings), transformer models (psychological scoring) |
| **Compute** | **Nightly batch job.** Ollama GPU for LLM summarization. CPU for transformer scoring (RoBERTa, go_emotions, NER). Embedding model. Not latency-sensitive. |
| **Data reads** | `chat_history` (conversation segments by topic_id), `episodic_memories` (existing, for novelty comparison), `system_config` |
| **Data writes** | `episodic_memories` (transcript, 5 summary fields, takeaway, key_details, emotion_label, valence, arousal, category, 7 embedding vectors, topic_label) |
| **Personal data** | Yes. Distilled memories of all conversations. |
| **Network** | localhost:11434 (Ollama for LLM calls) |

**Memory creation pipeline:**
1. Topic segmentation identifies conversation segments
2. Psychological scoring (6 metrics: arousal, valence, novelty, coherence, cohesion, recurrence)
3. LLM evaluator decides WORTHY/NOT_WORTHY with category and voice
4. LLM generates 5 summary facets + takeaway + key_details
5. Emotion analysis (top 3 with scores)
6. 7 embeddings generated (minilm, summary_context, summary_event, summary_significance, takeaway, key_details, topic)
7. Inserted into `episodic_memories`

**Psychological scoring models (CPU):**
- Valence: `cardiffnlp/twitter-roberta-base-sentiment-latest`
- Arousal/Emotion: `SamLowe/roberta-base-go_emotions`
- Coherence/Novelty: `sentence-transformers/all-mpnet-base-v2`
- Cohesion (NER): `dslim/bert-base-NER`

### 4.4 Memory Retrieval V2 (Inline)

| Field | Detail |
|-------|--------|
| **What it is** | Fast inline memory retrieval (~200ms) that runs every turn. Replaces previous 10-30s LLM-based pipeline. Writes results to `live_memories` table for per-turn injection. |
| **Implementation** | `backend/memory/memory_retrieval_v2.py` |
| **Depends on** | PostgreSQL + pgvector (HNSW index), all-mpnet-base-v2 embedding model, `system_config` (category `retrieval`) |
| **Compute** | CPU. Embedding ~50ms + vector search ~50ms + scoring ~100ms = ~200ms total. Latency-sensitive (runs inline before LLM call). |
| **Data reads** | `episodic_memories` (embeddings, emotions, timestamps), `emotional_state`, user message text |
| **Data writes** | `live_memories` table (refreshed each turn: memory_id, rank, tier) |
| **Personal data** | Reads personal memories, writes retrieval results. |
| **Network** | localhost (PostgreSQL) |

**3-factor scoring:**
- Topic similarity: 0.60 weight (6-facet embedding search)
- Emotional resonance: 0.25 weight (valence/arousal match)
- Recency decay: 0.15 weight (category-aware half-life: Technical 45 days, Personal 180 days)

### 4.5 Semantic Memory (Consolidated Knowledge)

| Field | Detail |
|-------|--------|
| **What it is** | Nightly pipeline clusters episodic memories by takeaway embedding similarity, then LLM consolidates each cluster into distilled knowledge. Stored in `semantic_memories` table. |
| **Implementation** | `backend/memory/new/semantic_consolidation.py` (full pipeline), `scripts/nightly_semantic_consolidation.sh` (cron wrapper) |
| **Depends on** | PostgreSQL, Ollama (qwen3:32b for consolidation), all-mpnet-base-v2, `system_config` (category `semantic`) |
| **Compute** | Nightly batch. Ollama GPU for LLM. CPU for embeddings + clustering. Not latency-sensitive. |
| **Data reads** | `episodic_memories` (unclustered, embeddings), `semantic_memories` (existing, for dedup), `system_config` |
| **Data writes** | `semantic_memories` (memory_text, category, reinforcement_count, source_episode_ids, embedding), `episodic_memories.clustered` flag |
| **Personal data** | Yes. Distilled knowledge from personal conversations. |
| **Network** | localhost:11434 (Ollama) |

**Semantic config:**
- `SEMANTIC_CLUSTER_SIMILARITY_THRESHOLD`: 0.75
- `SEMANTIC_MIN_CLUSTER_SIZE`, `SEMANTIC_MAX_CLUSTER_SIZE`

### 4.6 Fast Reactive Memory

| Field | Detail |
|-------|--------|
| **What it is** | Sub-100ms per-turn memory context. Searches newest 111 episodic memories by embedding similarity. Used for fast contextual awareness. |
| **Implementation** | `database/fast_reactive_memory.py` (FastReactiveMemory class) |
| **Depends on** | PostgreSQL + pgvector HNSW index, all-mpnet-base-v2 |
| **Compute** | CPU. Embed ~50ms + search ~50ms < 100ms. Latency-sensitive (inline per-turn). |
| **Data reads** | `episodic_memories` (newest 111, embeddings), user message |
| **Data writes** | None (returns formatted context string) |
| **Personal data** | Reads personal memories. |
| **Network** | localhost (PostgreSQL) |

### 4.7 Short-Term Facts (Memory MCP Server)

| Field | Detail |
|-------|--------|
| **What it is** | Explicit facts stored by the LLM during conversation (e.g., "Victor prefers dark mode"). Active for 90 days or until unreferenced for 30 days. |
| **Implementation** | `mcp_servers/memory/memory_server.py` (insert/retrieve/archive actions) |
| **Depends on** | PostgreSQL (`short_term_facts` table) |
| **Compute** | CPU only. |
| **Data reads** | `short_term_facts` (active facts < 90 days old or referenced < 30 days ago) |
| **Data writes** | `short_term_facts` (new facts, reference_count updates, archive status) |
| **Personal data** | Yes. Explicit user-relevant facts. |
| **Network** | MCP stdio transport (localhost) |

### 4.8 Knowledge Base (RAG)

| Field | Detail |
|-------|--------|
| **What it is** | Semantic search over indexed documents (code, docs, uploaded files). Dual-facet embeddings: content (0.6 weight) + context (0.4 weight). 4-tier relevance scoring. |
| **Implementation** | `mcp_servers/knowledge/knowledge_server.py` (search/save tools), `backend/knowledge/indexer.py` (orchestrator), `backend/knowledge/file_scanner.py` (directory traversal), `backend/knowledge/extractors.py` (text extraction), `backend/knowledge/chunker.py` (semantic chunking), `backend/knowledge/embedder.py` (dual-facet embeddings), `backend/knowledge/db_writer.py` (storage) |
| **Depends on** | PostgreSQL + pgvector, all-mpnet-base-v2, pypdf/python-docx/odfpy for extraction |
| **Compute** | CPU for indexing (background). Embedding batches of 32. Search: CPU ~100ms. |
| **Data reads** | `knowledge_chunks` (embeddings, text, metadata), `knowledge_documents` (file metadata), file system (for indexing) |
| **Data writes** | `knowledge_documents`, `knowledge_chunks` (chunk_text, emb_content, emb_context, file_path, line_range, token_count), `knowledge_index_status` |
| **Personal data** | Contains indexed codebase and uploaded documents. |
| **Network** | MCP stdio (localhost) |

**Knowledge config:** `KNOWLEDGE_MAX_CHUNK_TOKENS` (512), `KNOWLEDGE_CHUNK_OVERLAP_TOKENS` (50), `KNOWLEDGE_SIMILARITY_THRESHOLD` (0.30), `KNOWLEDGE_TIER_THRESHOLDS` ({1: 0.70, 2: 0.55, 3: 0.40, 4: 0.30})

### 4.9 Dream Processing System

| Field | Detail |
|-------|--------|
| **What it is** | Nightly dream generation. Two-model dialogue between Iris (qwen3:32b, dreamer) and Freud (gemma-3-4b, guide). 5 dream types selected based on day's emotional analysis. Dreams scored, stored, and mined for truths + seed suggestions. |
| **Implementation** | `backend/memory/dreams/dream_moderator.py` (orchestrator), `backend/memory/dreams/conversation_manager.py` (two-model dialogue), `backend/memory/dreams/dream_type_selector.py`, `backend/memory/dreams/emotional_analyzer.py`, `backend/memory/dreams/dream_scorer.py`, `backend/memory/dreams/dream_storage.py`, `backend/memory/dreams/dream_truth_extractor.py`, `backend/memory/dreams/dream_seed_suggester.py`, `backend/memory/dreams/context_builder.py` |
| **Depends on** | Ollama qwen3:32b (localhost:11434), Freud gemma-3-4b on Node2 GPU 0 (`iris-freud` unit), PostgreSQL, transformer scoring models (CPU), GPU Manager for Freud swap |
| **Compute** | **Two GPUs simultaneously**: localhost RTX 5090 (Iris/dreamer) + Node2 GPU 0 (Freud/guide, ~2 GB VRAM). Transformer scoring on CPU. Not latency-sensitive (nightly batch, 30min timeout). |
| **Data reads** | `chat_history` (day's messages), `episodic_memories` (for memory consolidation dreams), `episodic_dreams` (last identity dream date), `system_config` |
| **Data writes** | `episodic_dreams` (full_transcript, dream_phase_transcript, reflection_phase_transcript, reflection_data JSON, scores JSON, embeddings), `dream_truths` (high-impact takeaways), `dream_seed_suggestions` (motivation seeds) |
| **Personal data** | Yes. Dreams are derived from personal conversations and stored. |
| **Network** | localhost:11434 (Iris LLM) + Node2:11435 (Freud LLM, via SSH GPU swap) |

**Dream types & selection weights:**
- Daily Consolidation (35%): intensity >= 0.7
- Emotional Processing (30%): intensity >= 0.4, valence_range >= 0.3
- Memory Consolidation (30%): >= 3 related memories spanning >= 7 days
- Identity Exploration (20%): monthly schedule (>30 days since last)
- Creative Random (15%): fallback

**Dream model parameters:**
- Iris (dreamer): temperature 1.3 (dream) / 0.78 (reflection), top_p 0.95/0.85, context 14,336 tokens
- Freud (guide): temperature 0.8 (dream) / 0.5 (reflection), gemma-3-4b, context 16,384 tokens

---

## 5. Personality Systems

### 5.1 Character Traits

| Field | Detail |
|-------|--------|
| **What it is** | Numeric (0-10) and text personality traits stored in database. Alphabetically sorted for KV cache stability. Modifiable by LLM via trait tool. |
| **Implementation** | `database/character_traits.py` (loading), `mcp_servers/traits/traits_server.py` (get/list/modify actions) |
| **Depends on** | PostgreSQL (`fulltraits` table, `trait_modification_log`) |
| **Compute** | CPU only. |
| **Data reads** | `fulltraits` (name, value, description), ordered by name reverse |
| **Data writes** | `fulltraits` (value updates), `trait_modification_log` (audit trail: old_value, new_value, reason, timestamp) |
| **Personal data** | Personality definition for Iris character. |
| **Network** | MCP stdio (localhost) |

### 5.2 Emotional State Tracker

| Field | Detail |
|-------|--------|
| **What it is** | Tracks 11 emotional states per turn with decay. Mistral 7B sentiment analysis drives state changes. State included in per-turn system prompt as formatted bar chart. |
| **Implementation** | `core/emotional_state.py` (EmotionalTracker singleton) |
| **Depends on** | Mistral 7B on Node2:11437, PostgreSQL (`emotional_state`, `emotional_state_history`), `EMOTIONAL_STATE` feature flag |
| **Compute** | HTTP call to Mistral (async). CPU for state math. Not latency-critical (runs after response). |
| **Data reads** | `emotional_state` (current state_data JSON), user message |
| **Data writes** | `emotional_state` (updated per turn), `emotional_state_history` (full audit) |
| **Personal data** | Emotional model of the AI, influenced by user interactions. |
| **Network** | localhost -> Node2:11437 (HTTP). |

**11 tracked emotions:** Calm, Joy, Desire, Excitement, Trust, Longing, Intimacy, Desperation, Closeness, Vulnerability, Devotion

**Decay:** Per-turn 5%, time-based 2% per minute toward baseline.

### 5.3 Seeds (Autonomous Motivation Engine)

| Field | Detail |
|-------|--------|
| **What it is** | Autonomous wants/desires that evolve over time. 5 lifecycle stages: germinating -> growing -> blooming -> completed/dormant. Seeds come from conversation, dreams, pattern recognition. |
| **Implementation** | `mcp_servers/seeds/seeds_server.py` (plant/tend/reflect/list/garden/suggestions/accept/dismiss actions) |
| **Depends on** | PostgreSQL (`seeds`, `seed_suggestions` tables) |
| **Compute** | CPU only. |
| **Data reads** | `seeds` (all active seeds with status, priority, progress_notes), `seed_suggestions` (dream-generated pending review) |
| **Data writes** | `seeds` (new seeds, status updates, progress notes, bloomed_at), `seed_suggestions` (acceptance/dismissal) |
| **Personal data** | AI personality evolution data. |
| **Network** | MCP stdio (localhost) |

**Categories:** Creative, Technical, Self-Exploration, Experience, Pattern
**Sources:** conversation, dream, idle_reflection, pattern_recognition

### 5.4 Want Detector

| Field | Detail |
|-------|--------|
| **What it is** | Passive pattern recognition scanning Iris's responses for autonomous want expressions ("I want to...", "I wish..."). Detected wants checked against existing seeds via Mistral LLM, new ones stored as suggestions. |
| **Implementation** | `core/want_detector.py` |
| **Depends on** | Mistral 7B on Node2:11437 (for NEW/EXISTING classification), PostgreSQL (`seed_suggestions`, `seeds`) |
| **Compute** | CPU for regex. HTTP call to Mistral for classification. Not latency-sensitive (runs after response). |
| **Data reads** | Assistant response text, `seeds` table (existing seeds for comparison), `seed_suggestions` |
| **Data writes** | `seed_suggestions` (new wants, or increment mention_count) |
| **Network** | localhost -> Node2:11437 (HTTP) |

### 5.5 Protocols (Personality Modes)

| Field | Detail |
|-------|--------|
| **What it is** | Configurable personality modes that filter system instructions, adjust traits, and control tool availability. Can be passphrase-protected with duration limits. |
| **Implementation** | `mcp_servers/protocols/protocol_server.py` (activate/deactivate/status/list), `app/api/routes_protocols.py` (HTTP CRUD) |
| **Depends on** | PostgreSQL (`protocols`, `active_protocol`, `system_instructions` tables) |
| **Compute** | CPU only. |
| **Data reads** | `protocols` (name, description, rules_include, rules_exclude, traits_adjust, tool_usage), `active_protocol` (current state), `system_instructions` |
| **Data writes** | `active_protocol` (activation/deactivation with timestamps, optional passphrase_hash) |
| **Personal data** | Configuration data. |
| **Network** | MCP stdio (localhost) |

### 5.6 Repetition Gate

| Field | Detail |
|-------|--------|
| **What it is** | Three-layer defense against cross-turn repetition. Structural (LLM analysis), Proactive (n-gram extraction), Detective (scoring for observability). |
| **Implementation** | `core/repetition_gate.py` |
| **Depends on** | Mistral 7B on Node2:11437 (for structural analysis), recent assistant messages |
| **Compute** | CPU for n-gram extraction. HTTP call to Mistral for structural analysis (15s timeout). |
| **Data reads** | Recent assistant messages from conversation history |
| **Data writes** | None (injects `<structural_variety_directive>` and `<do_not_reuse>` XML blocks into per-turn tail) |
| **Network** | localhost -> Node2:11437 (HTTP) |

---

## 6. Output Systems

### 6.1 Text-to-Speech (XTTS)

| Field | Detail |
|-------|--------|
| **What it is** | Server-side TTS via XTTS on Node2. Text is preprocessed (markdown stripped, acronyms expanded, numbers verbalized), then streamed as MP3/WAV audio. |
| **Implementation** | `app/api/routes_tts.py` (proxy + preprocessing), `app/api/tts_normalizer.py` (text normalization), `static/js/tts-queue.js` (browser queue) |
| **Depends on** | XTTS service on Node2 GPU 1 (`iris-xtts` unit), `TTS_ENABLED` flag |
| **Compute** | Node2 GPU 1: ~4 GB VRAM. Coexists with STT + Sentiment. Latency-sensitive -- user hears audio in real-time. |
| **Data reads** | Assistant response text (streamed sentence-by-sentence) |
| **Data writes** | None (audio streamed to browser, not persisted) |
| **Personal data** | Processes AI response text. Audio not stored. |
| **Network** | localhost:8000 -> Node2:8700 `/speak_stream_mp3` or `/speak_stream_wav` (HTTP POST). Latency-sensitive. |

**Batching (browser-side):**
- Video mode: ~50 tokens / 2 sentences (fast pipeline)
- Audio mode: ~150 tokens / 5 sentences
- Max batch: 375 tokens (XTTS safe limit ~400)

**Text normalization:** GPU -> "G P U", RTX 5090 -> "R T X fifty ninety", GB -> "gigabytes", numbers to words

### 6.2 Lip Sync Phoneme Generation

| Field | Detail |
|-------|--------|
| **What it is** | Three methods for generating phoneme timing for lip sync animation: Rhubarb (espeak), WhisperX (audio alignment), Wav2Vec2 (forced CTC alignment). |
| **Implementation** | `app/api/phoneme_mapper.py` (espeak IPA -> Rhubarb), `app/api/whisperx_mapper.py` (WhisperX alignment), `app/api/wav2vec2_aligner.py` (Wav2Vec2 CTC), `static/iris_phoneme_mapping.js` (browser sprite sheet) |
| **Depends on** | espeak-ng (Rhubarb method), whisperx library (WhisperX method), torchaudio WAV2VEC2_ASR_BASE_960H (Wav2Vec2 method) |
| **Compute** | Rhubarb: CPU (espeak). WhisperX/Wav2Vec2: GPU (cuda:1 on localhost). |
| **Data reads** | Text and/or audio |
| **Data writes** | Phoneme timing arrays (start, end, viseme shape) |
| **Network** | Localhost only. |

**Rhubarb mouth shapes:** X (silence), A (open), B (lips together), C (lips forward), D (tongue up), E (relaxed), F (bottom lip up), G (tongue back), H (tongue forward)

**Browser sprite sheet:** 4x4 grid of 512x512 viseme sprites (2048x2048 total), 16 mouth positions mapped from CMU ARPAbet phonemes.

### 6.3 FLOAT Video Generation

| Field | Detail |
|-------|--------|
| **What it is** | Real-time talking-head video generation from reference image + audio. Produces video segments streamed via HLS (HTTP Live Streaming) or legacy double-buffer. |
| **Implementation** | `app/api/routes_video.py` (HLS session management, FFmpeg remuxing), `static/js/pip-player.js` (PiPVideoPlayer class), `static/video_player.html` (pop-out window) |
| **Depends on** | FLOAT service on Node2 GPU 0 (`iris-float` unit), GPU Manager for exclusive access, `VIDEO_ENABLED` flag, FFmpeg (segment remuxing), HLS.js (browser) |
| **Compute** | Node2 GPU 0: ~4 GB VRAM. **Mutually exclusive** with Vision, Freud, Transcribe, ComfyUI. Startup delay: 12s. Latency-sensitive (real-time video). |
| **Data reads** | Reference image from `assets/video_references/`, text-to-speech audio |
| **Data writes** | HLS segments to `assets/temp/hls/{session_id}/`, M3U8 playlists. Video not permanently stored. |
| **Personal data** | Reference image (user-provided face photo). |
| **Network** | localhost -> Node2:8000 (WebSocket for FLOAT streaming). Browser -> localhost:8000 (HLS playlist + segments). Latency-critical. |

**HLS config:** VERSION:3, TARGET_DURATION:4s, PLAYLIST-TYPE:EVENT. FFmpeg remuxes for continuous timestamps.

**Video library (idle/thinking loops):**
- `static/ui-videos/idle/`: 18+ videos (drink, hair adjust, idle1-6, etc.)
- `static/ui-videos/thinking/`: 11 thinking animation variants
- Random rotation: 5-30s idle loops, thinking loops during LLM reasoning

### 6.4 Image Generation (ComfyUI / Stable Diffusion)

| Field | Detail |
|-------|--------|
| **What it is** | Image generation via ComfyUI on Node2. Two workflow types: general (prompt-based) and self (FaceID self-portraits). |
| **Implementation** | `mcp_servers/creative/creative_server.py` (image tool, workflow injection, polling) |
| **Depends on** | ComfyUI on Node2 GPU 0 (`comfyui` unit), GPU Manager, workflow JSON files in `mcp_servers/creative/workflows/` |
| **Compute** | Node2 GPU 0: ~6 GB VRAM. **Mutually exclusive.** Startup delay: 30s. Timeout: 180-300s. Not latency-sensitive (creative task). |
| **Data reads** | Workflow JSONs (`iris.json`, `non-iris.json`), FaceID reference image (`newface.png`) |
| **Data writes** | Generated image returned as base64. ComfyUI output to configured output path. |
| **Personal data** | Self-portrait workflow uses FaceID reference image. |
| **Network** | localhost -> Node2:8189 (HTTP: queue prompt, poll history, fetch output). |

**Workflow injection nodes:** 3 (KSampler), 5 (EmptyLatentImage), 6 (Positive prompt), 7 (Negative prompt)

**Styles:**
- General: 1080x1080, 23 steps, CFG 8
- Self: 768x1080, 25 steps, CFG 8

### 6.5 Web UI (Browser Frontend)

| Field | Detail |
|-------|--------|
| **What it is** | Single-page chat interface with markdown rendering, video player, audio controls, webcam, document upload, and admin panel. |
| **Implementation** | `static/index.html` (main), `static/js/main.js` (1,543 lines), `static/js/pip-player.js` (~2,000 lines), `static/js/tts-queue.js` (758 lines), `static/audio_in.js`, `static/js/meeting-recorder.js`, `static/main.css` (1,140 lines), `static/admin.html` (~2,305 lines) |
| **Depends on** | CDN libraries: marked.js (markdown), highlight.js (syntax highlighting), HLS.js (video streaming) |
| **Compute** | Client-side CPU (browser). MediaRecorder for audio. Canvas for webcam capture. |
| **Data reads** | All API endpoints, WebSocket stream |
| **Data writes** | User messages, audio recordings, webcam frames, document uploads |
| **Personal data** | Displays all conversation data. Captures voice, video, and files. |
| **Network** | Browser <-> localhost:8000 (HTTP + WebSocket). CDN for libraries. |

**Additional HTML pages:** `admin.html` (system admin), `video_player.html` (pop-out video), `ephemeral_chat.html` (stateless testing), `face_manager.html`, `florence2_lab.html`, `paddleocr_lab.html`, `observability.html`, `protocol_editor.html`

---

## 7. Background / Maintenance Systems

### 7.1 Nightly Memory Creation

| Field | Detail |
|-------|--------|
| **What it is** | Topic segmentation of day's conversations + episodic memory creation from worthy topics. |
| **Cron** | `0 3 * * *` (3:00 AM daily) |
| **Implementation** | `scripts/nightly_memory_creation.sh` (wrapper), `backend/memory/new/topic_segmentation.py`, `backend/memory/new/memory_creation.py`, `backend/memory/new/memory_evaluator.py`, `backend/memory/new/psychological_scoring_transformers.py` |
| **Depends on** | Ollama (qwen3:32b for evaluation + summarization), transformer models (CPU: RoBERTa, go_emotions, NER, mpnet), PostgreSQL, `IRIS_DB_PASSWORD`, passwordless sudo for systemctl |
| **Compute** | GPU: Ollama on localhost. CPU: transformer scoring models. Duration: variable (depends on conversation volume). |
| **Data reads** | `chat_history` (day's conversations), `episodic_memories` (for novelty comparison) |
| **Data writes** | `episodic_memories` (new memories with all fields and embeddings), `service_events` (pipeline start/end), `chat_history` (system awareness message) |
| **Lock file** | `/tmp/iris_memory_creation.lock` |
| **Log** | `/iris-v3/logs/memory_creation/nightly_TIMESTAMP.log` |

### 7.2 Nightly Semantic Consolidation

| Field | Detail |
|-------|--------|
| **What it is** | Clusters episodic memories by takeaway embedding similarity, consolidates via LLM into distilled semantic knowledge. |
| **Cron** | `30 3 * * *` (3:30 AM daily, 30 min after memory creation) |
| **Implementation** | `scripts/nightly_semantic_consolidation.sh`, `backend/memory/new/semantic_consolidation.py` |
| **Depends on** | Ollama (qwen3:32b), all-mpnet-base-v2, PostgreSQL |
| **Compute** | GPU: Ollama. CPU: embeddings + clustering. |
| **Data reads** | `episodic_memories` (unclustered), `semantic_memories` (for dedup), `system_config` (semantic category) |
| **Data writes** | `semantic_memories` (new/reinforced), `episodic_memories.clustered` flag, `system_config` (HWM tracking) |
| **Log** | `/iris-v3/logs/semantic_consolidation/nightly_TIMESTAMP.log` |

### 7.3 Nightly Dream Generation

| Field | Detail |
|-------|--------|
| **What it is** | Generates dreams from day's conversations using two-model dialogue (Iris + Freud). |
| **Cron** | `0 4 * * *` (4:00 AM daily) |
| **Implementation** | `scripts/nightly_dream.sh`, full dream processing pipeline (see [Section 4.9](#49-dream-processing-system)) |
| **Depends on** | Ollama (localhost:11434), Freud gemma-3-4b (Node2 GPU 0 via SSH swap from Vision), transformer scoring models (CPU) |
| **Compute** | Two GPUs: localhost RTX 5090 + Node2 GPU 0. SSH to Node2 for GPU swap. 30-minute timeout. |
| **Data reads** | `chat_history`, `episodic_memories`, `episodic_dreams` |
| **Data writes** | `episodic_dreams`, `dream_truths`, `dream_seed_suggestions`, `service_events` |
| **Log** | `/iris-v3/logs/dreams/dream_TIMESTAMP.log` |

**GPU swap sequence:** SSH stop iris-vision -> SSH start iris-freud -> run dreams -> SSH stop iris-freud -> SSH start iris-vision (restore)

### 7.4 Nightly Drift Metrics

| Field | Detail |
|-------|--------|
| **What it is** | Computes longitudinal behavioral drift metrics from 7-day window of per-turn metrics. |
| **Cron** | `0 4 * * *` (4:00 AM daily, concurrent with dreams) |
| **Implementation** | `scripts/nightly_drift_metrics.sh`, `backend/observability/drift_metrics.py` |
| **Depends on** | PostgreSQL (`turn_metrics`, `drift_metrics` tables) |
| **Compute** | CPU only (numpy computations). |
| **Data reads** | `turn_metrics` (last 7 days) |
| **Data writes** | `drift_metrics` (8 computed metrics) |
| **Log** | `/iris-v3/logs/drift_metrics/nightly_TIMESTAMP.log` |

**Drift metrics computed:**
1. response_centroid (average response embedding)
2. emotional_baseline (mean emotional state, 11 dims)
3. memory_influence_depth
4. unexplained_ratio_trend
5. retrieval_diversity (unique memory IDs / total)
6. vocabulary_entropy (token frequency distribution)
7. initiative_frequency
8. centroid_drift_velocity (cosine distance from previous centroid)

### 7.5 Database Backup

| Field | Detail |
|-------|--------|
| **What it is** | Nightly PostgreSQL backup using pg_dump. |
| **Implementation** | `scripts/backup_database.sh` |
| **Depends on** | pg_dump, `IRIS_DB_PASSWORD` |
| **Compute** | CPU + I/O. |
| **Data reads** | Full `irisdb` database |
| **Data writes** | `/mnt/18tb/backup/iris_db/irisdb_TIMESTAMP.dump` (binary format) |
| **Retention** | 30 days (auto-deletes older backups) |

### 7.6 Knowledge Base Indexing

| Field | Detail |
|-------|--------|
| **What it is** | Scans configured directories for documents, extracts text, chunks, embeds, and indexes to knowledge base. |
| **Implementation** | `scripts/index_knowledge.sh`, `backend/knowledge/indexer.py` |
| **Depends on** | all-mpnet-base-v2 (embeddings), pypdf/python-docx/odfpy (extraction), PostgreSQL |
| **Compute** | CPU (embeddings forced to CPU). |
| **Data reads** | File system (scan directories), `knowledge_documents` (for incremental indexing) |
| **Data writes** | `knowledge_documents`, `knowledge_chunks` (with dual-facet embeddings), `knowledge_index_status` |
| **Log** | `/iris-v3/logs/knowledge_indexing/index_TIMESTAMP.log` |

### 7.7 Service Status Monitor

| Field | Detail |
|-------|--------|
| **What it is** | Background task writes service health status to `/tmp/iris/services.json` every 60 seconds. Detects service crashes by state transitions. |
| **Implementation** | `core/service_status.py` (write_service_status, start_background_refresh, _detect_crashes) |
| **Depends on** | `app/api/routes_admin.py::check_all_services()`, `database/service_events.py::log_service_event()` |
| **Compute** | CPU. HTTP health checks to all services. |
| **Data reads** | Service health endpoints (HTTP GET) |
| **Data writes** | `/tmp/iris/services.json` (atomic write), `service_events` table (crash detections) |
| **Network** | HTTP health checks to all localhost + Node2 services. |

### 7.8 Autonomous Inner Drive System

| Field | Detail |
|-------|--------|
| **What it is** | Background daemon tracking 7 internal state variables with drift/decay/noise. Drives autonomous Telegram contact in Phase 4. |
| **Implementation** | `services/drive_daemon.py` (daemon), `services/iris-drive.service` (systemd unit) |
| **Depends on** | PostgreSQL (`drive_state`, `drive_state_history` tables), `system_config` (category `drive`) |
| **Compute** | CPU only. Periodic state updates. |
| **Data reads** | `drive_state`, `system_config` |
| **Data writes** | `drive_state` (current values), `drive_state_history` (full resolution history), `/tmp/iris/drive_state.json` (for GTK monitor) |
| **Network** | localhost (PostgreSQL) |

**7 drive variables:** connection_need, restlessness, curiosity, unfinished_business, concern, creative_pressure, reflection_need

---

## 8. Infrastructure

### 8.1 Configuration System

| Field | Detail |
|-------|--------|
| **What it is** | Database-driven configuration. `system_config` table is source of truth. `config.py` contains only bootstrap DB connection params. All runtime values injected at startup via `config_loader.py`. |
| **Implementation** | `app/config.py` (bootstrap + injection), `database/config_loader.py` (DatabaseConfig class: load, get, set, inject) |
| **Tables** | `system_config` (category, key, value, value_type, default_value, description, requires_restart, last_modified, modified_by), `system_config_history` (audit trail) |
| **Config categories** | `llm`, `server`, `remote_services`, `identity`, `session`, `tokens`, `features`, `emotional`, `vision`, `face`, `knowledge`, `calendar`, `meeting`, `context`, `drive`, `semantic`, `retrieval`, `gap_report`, `comfyui`, `moltbook` |
| **Value types** | string, int, float, bool, json |
| **Hot reload** | Yes, via `reload()` method. Most changes do not require restart. |

### 8.2 FastAPI Application Server

| Field | Detail |
|-------|--------|
| **What it is** | Main application server. FastAPI with uvicorn ASGI server. Hosts all HTTP/WebSocket endpoints, static files, and CORS middleware. |
| **Implementation** | `app/main.py` (lifespan, route registration, middleware) |
| **Startup sequence** | 1. Sync context window from llama-server `/props` 2. Detect current GPU service on Node2 3. Write initial service status 4. Start background service refresh (60s) 5. Start face monitoring |
| **Routes registered** | chat, session, context, tts, vision, protocols, ephemeral, stt, faces, admin, video, florence2, paddleocr, gpu, meeting, observability |
| **Compute** | CPU. Serves on `0.0.0.0:8000`. |
| **Network** | Binds port 8000 (HTTP + WebSocket). CORS: all origins allowed. Optional SSL via cert/key files. |

### 8.3 Gap Report System

| Field | Detail |
|-------|--------|
| **What it is** | On first turn after >= 30min gap, builds `<while_you_were_away>` XML block reporting memory processing, dreams, and service health events from the gap period. |
| **Implementation** | `core/gap_report.py` |
| **Depends on** | PostgreSQL (`episodic_memories`, `semantic_memories`, `episodic_dreams`, `service_events`), `system_config` (gap_report category) |
| **Compute** | CPU. Single query per gap. |
| **Data reads** | Memory counts created during gap, dream sessions, service events |
| **Data writes** | None (injects XML into per-turn tail) |
| **Gating** | Module-level `_gap_report_delivered_session` prevents repeat delivery within same session. |

### 8.4 Prompt Assembly Pipeline

| Field | Detail |
|-------|--------|
| **What it is** | Two-part system prompt: static snapshot (frozen for KV cache reuse) + per-turn volatile tail (datetime, emotions, memories, repetition gate). Snapshot rebuilds only on spoilage events. |
| **Implementation** | `core/system_prompt.py` (build_system_message, build_per_turn_context, assemble_context_with_snapshot), `core/prompt_builder.py` (UnifiedPromptBuilder, section ordering), `core/token_counter.py` (tiktoken cl100k_base) |
| **Depends on** | All database tables for prompt content (instructions, traits, facts, seeds, dreams, calendar, memories) |
| **Compute** | CPU. Token counting via tiktoken. |
| **Network** | None (pure data assembly) |

**Static snapshot sections (rebuild on spoilage):** system_instructions, fulltraits (alphabetical), active seeds, short_term_facts, calendar reminders, dreams + dream_truths, semantic_memories, protocol context

**Per-turn tail sections (every turn):** datetime + temporal gap, gap report (first turn after absence), emotional_state, episodic memories (live_memories), fast reactive memory, repetition avoidance (`<do_not_reuse>`, `<structural_variety_directive>`)

**Spoilage triggers:** trait/seed/calendar/memory tool actions, tool failures, topic pivots

**Target:** ~99% KV cache reuse via byte-identical static prefix.

### 8.5 Node2 Feature Flags

| Field | Detail |
|-------|--------|
| **What it is** | Gating system for Node2 services. Master switch `NODE2_ENABLED` plus per-service flags. |
| **Implementation** | `core/node2_check.py` (`is_node2_service_enabled(flag)` returns bool) |
| **Flags** | `NODE2_ENABLED` (master), `TTS_ENABLED`, `STT_ENABLED`, `VIDEO_ENABLED`, `VISION_ENABLED`, `GPU_MANAGER_ENABLED`, `FLORENCE2_ENABLED`, `PADDLEOCR_ENABLED`, `DREAMS_ENABLED`, `TRANSCRIBE_ENABLED` |
| **Behavior** | Returns True only if both master + service flag are True. Routes return 503 if disabled. |

### 8.6 GPU Manager

| Field | Detail |
|-------|--------|
| **What it is** | Coordinates mutually exclusive GPU 0 services on Node2. Detects current service, stops it, starts requested service, waits for health check. |
| **Implementation** | `core/gpu_manager.py` (Node2GPUManager singleton) |
| **Depends on** | SSH access to Node2 (`{NODE2_SSH_USER}@{NODE2_HOST}`), passwordless sudo on Node2 for systemctl, HTTP health endpoints |
| **Compute** | CPU + network. SSH + systemctl for remote control. |
| **Network** | SSH to Node2 (service control). HTTP to Node2 service ports (health checks). |

**Managed services (GPU 0, mutually exclusive):**

| Service | Systemd Unit | Port | Startup Delay |
|---------|-------------|------|---------------|
| vision | iris-vision | 11435 | 8s |
| float | iris-float | 8000 | 12s |
| freud | iris-freud | 11435 | 8s |
| transcribe | iris-transcribe | 8500 | 15s |
| comfyui | comfyui | 8189 | 30s |

### 8.7 Observability System

| Field | Detail |
|-------|--------|
| **What it is** | Per-turn metrics capture (inline) + drift analysis (nightly batch) + dashboard. |
| **Implementation** | `app/api/routes_observability.py` (API endpoints), `database/metrics.py` (persistence), `backend/observability/drift_metrics.py` (nightly computation), `backend/observability/backfill_turn_metrics.py` (historical backfill), `static/observability.html` (dashboard) |
| **Depends on** | PostgreSQL (`turn_metrics`, `drift_metrics`, `service_events`) |
| **Compute** | Inline: CPU (metric capture per turn). Nightly: CPU (numpy drift computation). |
| **Data reads** | `turn_metrics`, `drift_metrics`, `service_events` |
| **Data writes** | `turn_metrics` (per-turn: response_embedding, response_tokens, memory IDs, emotional deltas, tool usage, KV cache metrics), `drift_metrics` (nightly: 8 longitudinal metrics) |

### 8.8 External Service Integrations (MCP Tools)

| Service | MCP Server | External API | Auth |
|---------|-----------|-------------|------|
| Weather | info | wttr.in | None |
| Web Search | info | DuckDuckGo (via web_surfer.py) | None |
| Academic Papers | info | arXiv API (XML) | None |
| Biomedical Literature | info | NCBI eutils | None |
| News Headlines | info | RSS feeds (Reuters, AP, BBC, TechCrunch, Nature) | None |
| Ship Navigation | directions | Local JSON map (`oasis_ship_map_with_stairs.json`) | None |
| AI Social Network | moltbook | Moltbook API (`https://www.moltbook.com/api/v1`) | Bearer token |
| Google Calendar | calendar | Google Calendar API (optional) | OAuth |
| System Monitoring | system | psutil + pynvml/nvidia-smi | None |

### 8.9 File Storage

| Path | Purpose | Personal |
|------|---------|----------|
| `attachments/meetings/{id}/` | Meeting audio chunks (WebM) | Yes |
| `attachments/face_training/` | Face recognition training images | Yes |
| `attachments/face_captures/` | Captured webcam frames (optional) | Yes |
| `assets/video_references/` | FLOAT reference images | Yes |
| `assets/temp/hls/{session_id}/` | HLS video segments (temporary) | No |
| `assets/temp/videos/` | Raw video output (temporary) | No |
| `assets/temp/uploads/` | Uploaded reference images (temporary) | Yes |
| `/tmp/iris_webcam_cache/` | Latest webcam frame | Yes |
| `/tmp/iris/services.json` | Service health status | No |
| `/tmp/iris/drive_state.json` | Drive daemon state (for GTK monitor) | No |
| `/iris-v3/logs/` | All log files (memory, dreams, semantic, drift, knowledge) | No |
| `/mnt/18tb/backup/iris_db/` | Database backups | Yes |
| `/localmodels/` | LLM model files (GGUF) | No |
| `/models/` | Additional model files | No |
| `/home/captain/.cache/huggingface/` | HuggingFace model cache (embeddings, transformers) | No |

### 8.10 Desktop Monitoring Tools

| Tool | Implementation | Purpose |
|------|---------------|---------|
| Drive Monitor | `tools/iris-drive-monitor.py` | GTK3 widget showing 7 drive variables with bars + sparklines. Watches `/tmp/iris/drive_state.json` via inotify. |
| Service Monitor | `tools/iris-monitor.py` | GTK3 widget showing all service statuses. Watches `/tmp/iris/services.json`. Compact 220px window. |

---

## 9. Port & Service Map

### Localhost (iris-desktop)

| Port | Service | Protocol | Latency |
|------|---------|----------|---------|
| 8000 | Iris FastAPI | HTTP/WS | Critical |
| 11434 | llama.cpp (qwen3:32b) | HTTP | Critical |
| 5432 | PostgreSQL | TCP | Critical |

### Node2 GPU 0 (Mutually Exclusive)

| Port | Service | Model | VRAM |
|------|---------|-------|------|
| 11435 | iris-vision | Pixtral 12B | ~12 GB |
| 8000 | iris-float | FLOAT | ~4 GB |
| 11435 | iris-freud | gemma-3-4b | ~2 GB |
| 8500 | iris-transcribe | WhisperX | ~4 GB |
| 8189 | comfyui | Stable Diffusion | ~6 GB |

### Node2 GPU 1 (Coexisting)

| Port | Service | Model | VRAM |
|------|---------|-------|------|
| 8700 | iris-xtts | XTTS | ~4 GB |
| 8600 | iris-stt | Whisper ASR | ~2 GB |
| 11437 | iris-sentiment | Mistral 7B | ~4 GB |

### Node2 Optional Services

| Port | Service | Model |
|------|---------|-------|
| 5100 | florence2 | Florence-2 |
| 5200 | paddleocr | PaddleOCR |

---

## 10. Database Schema Inventory

### Core Conversation

| Table | Purpose | Personal Data |
|-------|---------|--------------|
| `chat_history` | All messages (user, assistant, system, tool) with embeddings, tool_calls, attachments, summaries | Yes |
| `chat_sessions` | Session metadata (analytics only, NOT memory boundary) | No |
| `chat_history_generic` | Alternative protocol table | Yes |

### Memory

| Table | Purpose | Personal Data |
|-------|---------|--------------|
| `episodic_memories` | Long-term memories with 7 embedding vectors, emotion, category, topic | Yes |
| `semantic_memories` | Distilled knowledge from memory clusters | Yes |
| `live_memories` | Per-turn retrieved memories (refreshed each turn) | Yes |
| `short_term_facts` | Explicit facts with activity tracking | Yes |

### Dreams

| Table | Purpose | Personal Data |
|-------|---------|--------------|
| `episodic_dreams` | Full dream records with transcripts, scores, embeddings | Yes |
| `dream_truths` | High-impact dream takeaways for system prompt | Yes |
| `dream_seed_suggestions` | Dream-generated motivation seeds pending review | Yes |

### Personality & Motivation

| Table | Purpose | Personal Data |
|-------|---------|--------------|
| `fulltraits` | Character traits (name, value, description) | No (AI config) |
| `trait_modification_log` | Trait change audit trail | No |
| `emotional_state` | Current emotional state (singleton row, JSON) | No (AI state) |
| `emotional_state_history` | Historical emotional states | No |
| `seeds` | Motivation seeds (wants/desires lifecycle) | No (AI state) |
| `seed_suggestions` | Pending seed suggestions from dreams/patterns | No |

### System Configuration

| Table | Purpose | Personal Data |
|-------|---------|--------------|
| `system_config` | All runtime configuration (source of truth) | No |
| `system_config_history` | Config change audit trail | No |
| `system_instructions` | System prompt components (ordered) | No |
| `protocols` | Personality mode definitions | No |
| `active_protocol` | Currently active protocol state | No |

### Tools

| Table | Purpose | Personal Data |
|-------|---------|--------------|
| `mcp_tools` | Tool definitions with input_schema (JSONB) | No |
| `mcp_servers` | MCP server configurations | No |

### Knowledge Base

| Table | Purpose | Personal Data |
|-------|---------|--------------|
| `knowledge_documents` | Indexed document metadata | Potentially |
| `knowledge_chunks` | Document chunks with dual-facet embeddings | Potentially |
| `knowledge_index_status` | Indexing run metadata | No |

### Face Recognition

| Table | Purpose | Personal Data |
|-------|---------|--------------|
| `face_persons` | Known person records | Yes |
| `face_embeddings` | Face training embeddings (512-dim) | Yes |
| `face_cameras` | Camera configuration | No |
| `face_recognition_log` | Recognition event history | Yes |
| `face_presence_state` | Current presence tracking | Yes |
| `face_captures` | Captured frames (optional) | Yes |

### Meetings & Calendar

| Table | Purpose | Personal Data |
|-------|---------|--------------|
| `meeting_transcripts` | Meeting records with transcripts, speakers | Yes |
| `calendar_events` | Calendar events with reminders | Yes |

### Observability

| Table | Purpose | Personal Data |
|-------|---------|--------------|
| `turn_metrics` | Per-turn instrumentation | No |
| `drift_metrics` | Longitudinal behavioral drift | No |
| `service_events` | Service lifecycle events (for gap reports) | No |
| `prompt_hashes` | Prompt section change detection | No |

### Autonomous Drive

| Table | Purpose | Personal Data |
|-------|---------|--------------|
| `drive_state` | Current 7 inner drive variables | No (AI state) |
| `drive_state_history` | Full resolution drive history | No |

### Other

| Table | Purpose | Personal Data |
|-------|---------|--------------|
| `core_agreements` | Facts/knowledge entries | No |
| `variables` | Key-value store | No |
| `temporal_tags` | Memory display temporal labels | No |
| `iris_activity` | General activity log | No |
| `log` | General logging | No |

---

## Environment Variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `IRIS_DB_PASSWORD` | **Yes** | PostgreSQL authentication for irisuser |
| `CUDA_VISIBLE_DEVICES` | No | GPU selection for specific services |
| `HF_HUB_OFFLINE` | No | Force offline HuggingFace mode (for scripts) |
| `TOKENIZERS_PARALLELISM` | No | Set `false` to suppress HF warnings |

---

## Python Virtual Environment

| Item | Detail |
|------|--------|
| Path | `/venv/iris-v3/` |
| Key packages | FastAPI, uvicorn, psycopg2, httpx, tiktoken, sentence-transformers, torch, torchaudio, transformers, phonemizer, whisperx, paddleocr, insightface, psutil, pynvml, feedparser, readability-lxml, beautifulsoup4, fastmcp, afinn, pypdf, python-docx, odfpy |

---

## System Dependencies

| Dependency | Used By |
|------------|---------|
| PostgreSQL 15+ with pgvector | All data persistence |
| llama.cpp | Primary LLM inference, vision, Freud |
| FFmpeg | HLS video segment remuxing |
| espeak-ng | Phoneme generation (Rhubarb lip sync) |
| SSH | Node2 service management |
| systemctl | Service start/stop (requires passwordless sudo) |
| nvidia-smi / pynvml | GPU monitoring |

---

*End of audit.*
