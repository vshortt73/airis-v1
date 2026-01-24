# Iris v3 Database Schema

## Overview

Iris uses PostgreSQL with the pgvector extension for vector similarity search. Database: `irisdb`, User: `irisuser`.

---

## Core Tables

### chat_history
Stores all conversation messages.

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL PK | Message ID |
| role | VARCHAR | "user", "assistant", "tool" |
| message | TEXT | Message content |
| c_timestamp | TIMESTAMP | Message time |
| session_id | UUID | Session reference |
| tool_calls | JSONB | Tool call specs |
| tool_name | VARCHAR | Tool that was called |
| attachments | JSONB | Attachment metadata |
| emb_message | vector(768) | Message embedding |
| summary | TEXT | Generated summary |
| sender | VARCHAR | Sender identifier |

**View:** `chat_history_readable` - excludes embedding column

---

### chat_sessions
Session metadata for analytics.

| Column | Type | Description |
|--------|------|-------------|
| session_id | UUID PK | Session identifier |
| start_time | TIMESTAMP | Session start |
| end_time | TIMESTAMP | Session end |
| message_count | INTEGER | Message count |
| summary | TEXT | Session summary |

**Note:** Sessions are analytics-only. Memory loads across ALL sessions.

---

### episodic_memories
Long-term semantic memories with multi-facet embeddings.

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL PK | Memory ID |
| session_id | VARCHAR | Source session |
| transcript | TEXT | Full conversation |
| summary_context | TEXT | Setting/context |
| summary_event | TEXT | What happened |
| summary_significance | TEXT | Why it matters |
| takeaway | TEXT | Key insight |
| key_details | TEXT | Visual/emotional details |
| emotion_label | VARCHAR | Primary emotion |
| emotion_top3 | JSONB | Top 3 emotions |
| valence | FLOAT | Sentiment (-1 to 1) |
| arousal | FLOAT | Intensity (0 to 1) |
| emb_summary_context | vector(768) | Context embedding |
| emb_summary_event | vector(768) | Event embedding |
| emb_summary_significance | vector(768) | Significance embedding |
| emb_takeaway | vector(768) | Takeaway embedding |
| emb_key_details | vector(768) | Details embedding |

**View:** `episodic_memories_readable` - excludes embeddings

---

### episodic_dreams
Dream sequences from Iris + Freud dialogue.

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL PK | Dream ID |
| dream_date | DATE | Night of dream |
| dream_type | VARCHAR | Type (emotional_processing, creative_random, etc.) |
| full_transcript | TEXT | All 15 turns |
| summary | TEXT | 2-3 sentence summary |
| takeaway | TEXT | Key insight |
| mood | VARCHAR | Emotional atmosphere |
| theme | VARCHAR | Central concept |
| emotion_label | VARCHAR | Primary emotion |
| valence | FLOAT | Sentiment |
| arousal | FLOAT | Intensity |
| emb_full_dream | vector(768) | Full dream embedding |

---

### short_term_facts
Middle-tier memory for flagged facts.

| Column | Type | Description |
|--------|------|-------------|
| fact_id | SERIAL PK | Fact ID |
| fact_text | TEXT | The fact |
| category | VARCHAR | Category |
| status | VARCHAR | "active" or "archived" |
| reference_count | INTEGER | Times retrieved |

**Categories:** ongoing_project, user_preference, discovery, user_status, other

---

## Protocol System

### protocols
Personality mode definitions.

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL PK | Protocol ID |
| name | VARCHAR UNIQUE | Protocol name |
| description | TEXT | Description |
| system_instructions | JSONB | Instruction IDs |
| traits_override | JSONB | Trait adjustments |
| enabled | BOOLEAN | Can be activated |

### active_protocol
Currently active protocol (singleton).

| Column | Type | Description |
|--------|------|-------------|
| protocol_id | INTEGER FK | Active protocol |
| activated_at | TIMESTAMP | Activation time |
| expires_at | TIMESTAMP | Auto-deactivate time |
| passphrase_hash | TEXT | bcrypt hash if protected |

### fulltraits
Dynamic personality traits.

| Column | Type | Description |
|--------|------|-------------|
| trait_id | SERIAL PK | Trait ID |
| trait_name | VARCHAR | Name (e.g., "Warmth") |
| trait_value | INTEGER | Value (1-10) |
| description | TEXT | What it means |

---

## Tool System

### mcp_tools
Tool definitions for MCP.

| Column | Type | Description |
|--------|------|-------------|
| tool_id | SERIAL PK | Tool ID |
| tool_name | VARCHAR UNIQUE | Function name |
| description | TEXT | What it does |
| input_schema | JSONB | JSON Schema for params |
| enabled | BOOLEAN | Is active |
| icon | VARCHAR | Emoji icon |
| server_type | VARCHAR | MCP server name |

### system_instructions
Dynamic system prompt components.

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL PK | Instruction ID |
| instruction_key | VARCHAR UNIQUE | Identifier |
| instruction_text | TEXT | Content |
| instruction_order | INTEGER | Sort order |
| active | BOOLEAN | Include in prompt |

---

## Knowledge Base (RAG)

### knowledge_documents
Indexed document metadata.

| Column | Type | Description |
|--------|------|-------------|
| doc_id | BIGSERIAL PK | Document ID |
| file_path | TEXT UNIQUE | File path |
| file_type | VARCHAR | Extension |
| doc_category | VARCHAR | Category |
| chunk_count | INTEGER | Number of chunks |
| total_tokens | INTEGER | Total tokens |

### knowledge_chunks
Document chunks with dual-facet embeddings.

| Column | Type | Description |
|--------|------|-------------|
| chunk_id | BIGSERIAL PK | Chunk ID |
| doc_id | BIGINT FK | Document reference |
| chunk_text | TEXT | Content |
| chunk_type | VARCHAR | Type (text, code, etc.) |
| emb_content | vector(768) | Content embedding (60%) |
| emb_context | vector(768) | Context embedding (40%) |

---

## Face Recognition

### face_persons
Known people registry.

| Column | Type | Description |
|--------|------|-------------|
| person_id | SERIAL PK | Person ID |
| name | TEXT UNIQUE | Identifier |
| display_name | TEXT | Display name |
| relationship | TEXT | Relationship type |
| tags | TEXT[] | Tags |

### face_embeddings
Face vectors for recognition.

| Column | Type | Description |
|--------|------|-------------|
| embedding_id | SERIAL PK | Embedding ID |
| person_id | INTEGER FK | Person reference |
| embedding | vector(512) | ArcFace vector |
| is_primary | BOOLEAN | Best embedding |

### face_presence_state
Current presence tracking.

| Column | Type | Description |
|--------|------|-------------|
| person_id | INTEGER FK | Person |
| camera_id | INTEGER FK | Camera |
| is_present | BOOLEAN | Currently present |
| entered_at | TIMESTAMP | Entry time |

---

## Configuration

### system_config
Runtime configuration (source of truth).

| Column | Type | Description |
|--------|------|-------------|
| config_id | SERIAL PK | Config ID |
| category | VARCHAR | Category |
| key | VARCHAR UNIQUE | Config key |
| value | TEXT | Value |
| value_type | VARCHAR | Type (int, float, bool, string) |
| description | TEXT | Description |

**Categories:**
- `llm` - Ollama settings
- `server` - Host, port
- `remote_services` - Node2 URLs
- `identity` - Names
- `session` - Timeouts
- `tokens` - Budgets
- `features` - Feature flags
- `emotional` - Decay rates
- `vision` - Vision settings
- `face` - Face recognition
- `knowledge` - RAG settings

### emotional_state
Current emotional state (singleton).

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Always 1 |
| state_data | JSONB | All emotional values |
| updated_at | TIMESTAMP | Last update |

---

## Motivation Engine

### seeds
Iris's autonomous wants and desires.

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL PK | Seed ID |
| description | TEXT | What Iris wants |
| category | VARCHAR | Category |
| tags | TEXT[] | Tags |
| status | VARCHAR | Status |
| priority | SMALLINT | Priority (1-5) |
| planted_at | TIMESTAMP | Creation time |

**Categories:** Creative, Technical, Self-Exploration, Experience, Pattern

**Statuses:** germinating, growing, blooming, completed, dormant

---

## Key Design Patterns

### Multi-Facet Embeddings
- Episodic memories: 5 embeddings
- Dreams: 6 embeddings
- Knowledge chunks: 2 embeddings (content + context)
- All use 768-dimensional vectors (all-mpnet-base-v2)
- Face embeddings: 512-dimensional (ArcFace)

### HNSW Indexes
Vector similarity uses HNSW indexes:
```sql
CREATE INDEX ON episodic_memories
USING hnsw (emb_takeaway vector_cosine_ops)
WITH (m = 16, ef_construction = 64);
```

### Views
Most tables have `_readable` views excluding embedding columns for easier queries.

---

## Connection

```python
import psycopg2

conn = psycopg2.connect(
    host='localhost',
    port=5432,
    database='irisdb',
    user='irisuser',
    password=os.environ['IRIS_DB_PASSWORD']
)
```

---

*Last updated: 2026-01-24*
