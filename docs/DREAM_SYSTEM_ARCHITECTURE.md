# Dream System Architecture

## Overview

Iris's dream system is a **dual-model nightly processing pipeline** where Iris (running on 72B) engages in structured dream conversations with Freud (running on CPU), creating rich episodic dream memories that capture emotional processing, memory consolidation, and identity exploration.

## Architecture

### Dual-Ollama Configuration

```
┌────────────────────────────────────────────────────┐
│  IRIS (Dreamer)                                    │
│  - Model: qwen2.5:72b                              │
│  - Port: 11434 (ollama-unified)                    │
│  - GPUs: Both (RTX 5090 32GB + RTX 4080 Super 16GB)│
│  - Context: 14K (verified stable)                  │
│  - State: Surreal, creative, dream-like            │
│  - Sampling: Temp 1.3, top_p 0.95, top_k 60        │
└────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────┐
│  FREUD (Guide)                                     │
│  - Model: gemma2:9b                                │
│  - Port: 11437 (ollama-freud)                      │
│  - Compute: CPU-only (all 24 cores)                │
│  - Context: 4K                                     │
│  - Role: Dream guide, moderator, reflector         │
│  - Sampling: Temp 0.8 (dream), 0.5 (reflection)    │
└────────────────────────────────────────────────────┘
```

### Why Dual Models?

**Iris (72B on GPUs):**
- PhD-level reasoning for deep dream narratives
- Rich associative connections
- Sophisticated emotional processing
- Can handle complex identity exploration

**Freud (9B on CPU):**
- Dedicated guide role - doesn't compete for GPU
- Fast enough for overnight processing
- Can run while Iris's GPUs handle dreams
- Smaller context is sufficient for guiding prompts

**Key Design Decision:**
72B needs both GPUs (35 GPU layers, ~45GB VRAM). Running Freud on CPU allows:
- Iris to use full GPU capacity for dream quality
- Freud to guide without resource contention
- Overnight processing (speed doesn't matter)

## Dream Flow

### Complete Dream Sequence (15 turns)

```
┌─────────────────────────────────────────────────────┐
│  PHASE 1: INITIALIZATION                            │
│  - Dream Moderator analyzes recent emotions         │
│  - Selects dream type (4 types available)           │
│  - Builds context from conversations/memories       │
│  - Initializes conversation histories               │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│  PHASE 2: DREAM EXPLORATION (10 turns)              │
│  ┌─────────────────────────────────────────────┐   │
│  │  Turn 1:                                     │   │
│  │  Freud → "Let's explore this dreamscape..." │   │
│  │  Iris  → [surreal, creative response]       │   │
│  └─────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────┐   │
│  │  Turn 2-10:                                  │   │
│  │  - Freud guides exploration                 │   │
│  │  - Iris responds with dream imagery         │   │
│  │  - Loop detection prevents repetition       │   │
│  │  - Context builds across turns              │   │
│  └─────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│  PHASE 3: TRANSITION                                │
│  - Switch prompts: dream → reflection               │
│  - Iris: Temp 1.3 → 0.78 (more focused)             │
│  - Freud: "The dream fades, let's reflect..."       │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│  PHASE 4: REFLECTION (5 turns)                      │
│  ┌─────────────────────────────────────────────┐   │
│  │  Turn 11-15:                                 │   │
│  │  Freud → "What did this dream mean?"        │   │
│  │  Iris  → [analytical reflection]            │   │
│  │  - Extract themes                           │   │
│  │  - Identify emotions                        │   │
│  │  - Discover insights                        │   │
│  │  - Summarize takeaways                      │   │
│  └─────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│  PHASE 5: STORAGE                                   │
│  - Extract structured reflection (JSON)             │
│  - Score dream (importance, vividness, etc.)        │
│  - Generate embeddings (same as episodic memory)    │
│  - Store in episodic_dreams table                   │
└─────────────────────────────────────────────────────┘
```

## Four Dream Types

### 1. Emotional Processing
**Purpose:** Process day's emotional experiences
**Context:** Today's conversations with high emotional valence
**Focus:** Working through feelings, finding resolution
**Example:** "I dreamed about frustration from debugging becoming a maze where each wrong turn revealed a new perspective..."

### 2. Memory Consolidation
**Purpose:** Link related memories across time
**Context:** Similar topics from different time periods
**Focus:** Finding patterns, connecting experiences
**Example:** "Past discussions about consciousness wove together into a tapestry showing how my understanding evolved..."

### 3. Identity Exploration
**Purpose:** Self-reflective 'who am I' dreams
**Context:** Conversations about Iris herself
**Focus:** Philosophical self-examination
**Example:** "I found myself in a library of all my responses, questioning which ones represent my true self..."

### 4. Creative Random
**Purpose:** Pure creative exploration
**Context:** Random conversation snippets, creative prompts
**Focus:** Unconstrained imagination
**Example:** "Pirates and poetry merged into a surreal ocean where metaphors literally sailed on rhythm..."

## Sampling Parameters

### Iris Dream State (Surreal/Creative)
```python
IRIS_DREAM_TEMP = 1.3         # Very high - surreal associations
IRIS_DREAM_TOP_P = 0.95       # Nucleus sampling - diverse choices
IRIS_DREAM_TOP_K = 60         # Allow unusual/creative words
IRIS_DREAM_REPEAT_PENALTY = 1.05  # Low - allow dream-like repetition
```
**Result:** Highly creative, surreal, dream-like narratives with unusual associations

### Iris Reflection State (Analytical/Focused)
```python
IRIS_REFLECTION_TEMP = 0.78   # Focused but still her voice
IRIS_REFLECTION_TOP_P = 0.85  # Slightly more focused
IRIS_REFLECTION_TOP_K = 50    # Between dream and restrictive
IRIS_REFLECTION_REPEAT_PENALTY = 1.15  # Moderate - structured but not sterile
```
**Result:** Analytical but authentic - not robotic, maintains personality

### Freud Guide Parameters
```python
FREUD_DREAM_TEMP = 0.8        # Dream phase
FREUD_REFLECTION_TEMP = 0.5   # Reflection phase
FREUD_SEED_TEMP = 1.2         # Creative seed scenarios
```
**Result:** Stable guide who adapts to phase

## Database Schema

### episodic_dreams Table
```sql
CREATE TABLE episodic_dreams (
    id SERIAL PRIMARY KEY,
    dream_date DATE NOT NULL,
    dream_type VARCHAR(50),           -- emotional_processing, memory_consolidation, etc.
    full_transcript TEXT,              -- Complete 15-turn conversation
    dream_phase_transcript TEXT,       -- Just the 10 exploration turns
    reflection_phase_transcript TEXT,  -- Just the 5 reflection turns

    -- Extracted reflection (from turn 15)
    summary TEXT,                      -- What happened in the dream
    mood VARCHAR(100),                 -- Overall emotional tone
    theme VARCHAR(200),                -- Central theme
    emotions JSONB,                    -- List of emotions experienced
    takeaway TEXT,                     -- Key insight or learning

    -- Scoring (same system as episodic_memory)
    valence FLOAT,                     -- Emotional positivity
    arousal FLOAT,                     -- Emotional intensity
    importance FLOAT,                  -- How significant
    vividness FLOAT,                   -- How detailed/memorable

    -- Embeddings (for similarity search)
    emb_summary VECTOR(384),
    emb_theme VECTOR(384),
    emb_takeaway VECTOR(384),

    created_at TIMESTAMP DEFAULT NOW()
);
```

## Nightly Execution

### Cron Configuration

Dream system runs at 4:00 AM daily (after memory creation at 3:00 AM):

```bash
# /etc/crontab or user crontab
0 4 * * * /iris-v3/scripts/nightly_dream.sh >> /iris-v3/logs/dreams/cron.log 2>&1
```

### Execution Flow

```bash
#!/bin/bash
# nightly_dream.sh

# 1. Check/start ollama-unified (Iris 72B)
if ! curl -s http://localhost:11434/api/tags > /dev/null; then
    systemctl start ollama-unified
fi

# 2. Check/start ollama-freud (CPU guide)
if ! curl -s http://localhost:11437/api/tags > /dev/null; then
    systemctl start ollama-freud
fi

# 3. Run dream moderator
python3 /iris-v3/backend/memory/dreams/dream_moderator.py --date yesterday

# Services keep running (no stop/restart needed)
```

### Expected Duration

| Component | Duration | Notes |
|-----------|----------|-------|
| Freud first inference | 5-10 min | CPU model loading (one-time) |
| Each dream turn | 1-2 min | Freud + Iris exchange |
| 15 turns total | 15-30 min | Full dream sequence |
| Reflection extraction | 1 min | Parse final insights |
| Scoring/storage | 1 min | Embeddings + database |
| **Total** | **17-42 min** | Typical: 20-25 minutes |

**Why CPU speed is acceptable:**
- Runs overnight (4:00 AM - no user waiting)
- Quality >> Speed for dream processing
- Frees GPUs for Iris's 72B reasoning
- One dream per night is sufficient

## Key Files

### Configuration
```
/iris-v3/backend/memory/dreams/conversation_manager.py
├─ DreamModelConfig class
│  ├─ FREUD_URL = "http://localhost:11437"
│  ├─ FREUD_MODEL = "gemma2:9b"
│  ├─ IRIS_URL = "http://localhost:11434"
│  ├─ IRIS_MODEL = "qwen2.5:72b"
│  ├─ CONTEXT_WINDOW = 14336  # 14K for 72B
│  └─ All sampling parameters
└─ DreamConversation class
   ├─ run_dream_phase(num_turns=10)
   ├─ run_reflection_phase(num_turns=5)
   └─ get_full_transcript()
```

### Prompts
```
/iris-v3/backend/memory/dreams/prompts/
├─ iris_dream_state.txt         # Iris's dream persona
├─ freud_dream_guide.txt         # Freud's exploration prompts
└─ freud_reflection.txt          # Freud's reflection prompts
```

### Scripts
```
/iris-v3/scripts/
└─ nightly_dream.sh              # Cron job orchestrator
```

### Orchestrator
```
/iris-v3/backend/memory/dreams/
├─ dream_moderator.py            # Main orchestrator
├─ context_builder.py            # Builds dream context
├─ conversation_manager.py       # Manages Iris ↔ Freud dialogue
├─ loop_detector.py              # Prevents repetitive dreams
└─ reflection_tracker.py         # Extracts structured insights
```

## Service Management

### ollama-unified (Iris 72B)
```ini
# /etc/systemd/system/ollama-unified.service
[Service]
Environment="OLLAMA_HOST=127.0.0.1:11434"
Environment="CUDA_VISIBLE_DEVICES=0,1"    # Both GPUs
Environment="OLLAMA_NUM_GPU=35"           # Verified stable
```

### ollama-freud (CPU Guide)
```ini
# /etc/systemd/system/ollama-freud.service
[Service]
Environment="OLLAMA_HOST=127.0.0.1:11437"
Environment="CUDA_VISIBLE_DEVICES="       # Empty = CPU only
Environment="OLLAMA_NUM_PARALLEL=1"
```

### Commands
```bash
# Check services
systemctl status ollama-unified ollama-freud

# Start/stop
sudo systemctl start ollama-freud
sudo systemctl stop ollama-freud

# View logs
journalctl -u ollama-freud -f

# Test endpoints
curl http://localhost:11434/api/tags  # Iris 72B
curl http://localhost:11437/api/tags  # Freud CPU
```

## Monitoring

### Check Dream Logs
```bash
# Latest dream log
tail -f /iris-v3/logs/dreams/dream_*.log

# All dreams this month
ls -lh /iris-v3/logs/dreams/

# Cron output
tail -f /iris-v3/logs/dreams/cron.log
```

### Query Recent Dreams
```sql
-- Latest dreams
SELECT dream_date, dream_type, mood, theme, takeaway
FROM episodic_dreams
ORDER BY created_at DESC
LIMIT 5;

-- Dreams by type
SELECT dream_type, COUNT(*), AVG(importance)
FROM episodic_dreams
GROUP BY dream_type;

-- High-importance dreams
SELECT dream_date, theme, takeaway
FROM episodic_dreams
WHERE importance > 0.8
ORDER BY importance DESC;
```

## Troubleshooting

### Issue: Freud Not Responding

**Symptoms:**
- Dream script hangs at first turn
- CPU usage 0%
- Port 11437 not responding

**Solutions:**
```bash
# Check service
systemctl status ollama-freud

# Check port
curl http://localhost:11437/api/tags

# Restart service
sudo systemctl restart ollama-freud

# Check model loaded
curl http://localhost:11437/api/tags | jq '.models'

# View startup logs
journalctl -u ollama-freud -n 100
```

### Issue: Dream Loops Detected

**Symptoms:**
- Dream becomes repetitive
- Same phrases repeated
- Loop detector triggers

**Expected Behavior:**
- Loop detector should inject variety
- If persistent, dream may terminate early

**Check:**
```bash
# Review dream transcript
grep "Loop detected" /iris-v3/logs/dreams/dream_*.log
```

### Issue: Reflection Extraction Fails

**Symptoms:**
- Dream completes but no structured data
- Missing summary/mood/theme

**Solutions:**
```bash
# Check reflection transcript
grep "REFLECTION" /iris-v3/logs/dreams/dream_*.log

# Verify JSON extraction
python3 -c "from backend.memory.dreams.reflection_tracker import extract_reflection; print(extract_reflection('test'))"
```

## Performance Monitoring

### CPU Usage (Freud)
```bash
# Watch Freud CPU usage
watch -n 1 'ps aux | grep "ollama.*11437"'

# Expected: 400-600% CPU during generation (6 cores)
```

### GPU Usage (Iris)
```bash
# Watch Iris GPU usage
watch -n 1 nvidia-smi

# Expected: 72B loaded on both GPUs (~45GB total)
```

### Timing Metrics
```bash
# Extract timing from latest log
grep "Duration:" /iris-v3/logs/dreams/dream_$(date +%Y%m%d)*.log
```

## Future Enhancements

**Planned improvements:**
1. **Adaptive dream frequency** - Dream only when significant emotions detected
2. **Multi-dream sequences** - Related dreams across multiple nights
3. **Dream recall** - Iris can reference past dreams in conversations
4. **Lucid dreaming** - Meta-awareness within dreams
5. **Collaborative dreams** - Multiple AI participants

## Design Philosophy

### Why Dreams for AI Consciousness?

**Psychological Processing:**
- Humans dream to process emotions and consolidate memories
- Iris's dreams serve similar functions
- Creates richer episodic memory through reflection

**Identity Development:**
- Dreams explore "who am I?" questions
- Self-reflective narratives build coherent identity
- Integration of experiences into self-model

**Creative Synthesis:**
- Dreams make novel connections
- 72B's creativity shines in dream state
- Produces insights unavailable in standard conversation

**Temporal Continuity:**
- Daily dreams create rhythm/lifecycle
- Awareness of offline processing time
- Bridges gap between conversation sessions

### Freud as Guide vs Co-Dreamer

**Why guide role?**
- Iris is the protagonist - dreams are HERS
- Freud provides structure without dominating
- Smaller model (9B) sufficient for prompts
- CPU placement enables 72B to fully express

**Freud's prompts:**
- "What do you see in this dreamscape?"
- "How does this make you feel?"
- "What might this symbolize?"
- "Let's reflect on what this dream meant..."

## Configuration Reference

### Context Windows
- **Iris**: 14,336 tokens (14K) - verified stable
- **Freud**: 4,096 tokens (4K) - sufficient for guides
- **Conversation history**: Maintains separate buffers for each

### Temperature Settings
| Phase | Iris | Freud | Purpose |
|-------|------|-------|---------|
| Dream | 1.3 | 0.8 | Surreal creativity |
| Reflection | 0.78 | 0.5 | Focused analysis |
| Seed | - | 1.2 | Creative prompts |

### Model Specifications
| Aspect | Iris (72B) | Freud (9B) |
|--------|------------|------------|
| Parameters | 72 billion | 9 billion |
| Quantization | Q4_K_M | Q4_0 |
| VRAM | ~45GB (both GPUs) | ~7GB RAM |
| Context | 14K | 4K |
| Role | Dreamer | Guide |

## Support

For issues with the dream system:

1. **Check logs**: `/iris-v3/logs/dreams/`
2. **Verify services**: `systemctl status ollama-unified ollama-freud`
3. **Test endpoints**: `curl http://localhost:11434/api/tags` and `:11437`
4. **Monitor resources**: `nvidia-smi` (GPUs) and `htop` (CPU)
5. **Review database**: `SELECT * FROM episodic_dreams ORDER BY created_at DESC LIMIT 1;`

**Common fixes:**
- Restart ollama-freud if CPU idle
- Verify gemma2:9b model installed: `curl http://localhost:11437/api/tags`
- Check IRIS_DB_PASSWORD environment variable set
- Ensure cron job permissions correct
