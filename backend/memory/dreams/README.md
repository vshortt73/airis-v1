# Iris Dream System V3

A complete dream orchestration system where Iris (qwen3:32b) has guided dream conversations with Freud (gemma2:9b) to process emotions, consolidate memories, explore identity, and engage in creative exploration.

## Architecture Overview

The dream system runs nightly (4:00 AM) and creates structured 15-turn dream sequences:
- **10 turns**: Dream exploration (Freud guides, Iris dreams)
- **5 turns**: Reflection phase (structured insight extraction)

### Dream Types

1. **Emotional Processing** (40% priority)
   - Processes day's emotional experiences
   - Triggered by: High intensity (≥0.6) + Emotional variety (≥0.4)

2. **Memory Consolidation** (30% priority)
   - Links related memories across time
   - Triggered by: ≥3 related memories spanning ≥7 days

3. **Identity Exploration** (20% priority)
   - Self-reflective "who am I" dreams
   - Triggered by: Monthly schedule (every 30 days)

4. **Creative Random** (10% priority)
   - Pure surreal exploration
   - Triggered by: Fallback when others don't qualify

## Module Structure

```
/iris-v3/backend/memory/dreams/
├── dream_moderator.py           # Main orchestrator (run this!)
├── emotional_analyzer.py        # Analyze daily emotions
├── dream_type_selector.py       # Select dream type
├── context_builder.py           # Build dream context
├── conversation_manager.py      # Orchestrate Iris ↔ Freud dialogue
├── loop_detector.py             # Detect repetitive patterns
├── reflection_tracker.py        # Track reflection field extraction
├── json_extractor.py            # Extract & validate reflection JSON
├── dream_scorer.py              # Score & embed dreams
├── dream_storage.py             # Store to episodic_dreams table
├── prompts/
│   ├── freud_dream_guide.txt    # Freud's dream phase personality
│   ├── freud_reflection.txt     # Freud's reflection phase personality
│   └── iris_dream_state.txt     # Iris's dream mode instructions
└── README.md                    # This file
```

## Usage

### Manual Execution

**IMPORTANT**: Always use the venv Python directly to avoid import/password issues:

```bash
# Run dream for today (recommended method)
cd /iris-v3/backend/memory/dreams
/venv/iris-v3/bin/python3 dream_moderator.py

# Or use the test script
./run_test_dream.sh

# Run dream for specific date
python3 dream_moderator.py --date 2025-12-29

# Force specific dream type (testing)
python3 dream_moderator.py --dream-type creative_random
```

### Automated Execution

The nightly script runs automatically via cron:

```bash
# Setup cron (one-time)
crontab -e

# Add this line:
0 4 * * * /iris-v3/scripts/nightly_dream.sh >> /iris-v3/logs/dreams/cron.log 2>&1

# The script will:
# 1. Check Ollama services (start if needed)
# 2. Run dream moderator for yesterday
# 3. Log everything to /iris-v3/logs/dreams/
```

## Configuration

### Model Settings

Configured in `conversation_manager.py`:

```python
# Freud (Guide) - GPU 0
FREUD_URL = "http://localhost:11434"
FREUD_MODEL = "gemma2:9b"
FREUD_DREAM_TEMP = 0.8
FREUD_REFLECTION_TEMP = 0.5

# Iris (Dreamer) - GPU 1
IRIS_URL = "http://localhost:11435"
IRIS_MODEL = "qwen3:32b"
IRIS_DREAM_TEMP = 0.9
IRIS_REFLECTION_TEMP = 0.6
```

### Dream Type Thresholds

Configured in `dream_type_selector.py`:

```python
EMOTIONAL_MIN_INTENSITY = 0.6      # Need strong emotions
EMOTIONAL_MIN_VALENCE_RANGE = 0.4  # Need emotional variety
MEMORY_MIN_RELATED_MEMORIES = 3    # At least 3 related memories
MEMORY_MIN_TIME_SPAN_DAYS = 7      # Across at least a week
IDENTITY_SCHEDULE_DAYS = 30        # Once per month
```

## Database Schema

Dreams are stored in `episodic_dreams` table:

```sql
-- Core fields
dream_date, source_date, dream_type, based_on_reality

-- Transcripts
full_transcript, dream_phase_transcript, reflection_phase_transcript

-- Reflection data
summary, takeaway, mood, theme, top_3_emotions, key_details

-- Emotional scores
emotion_label, emotion_top3, valence, arousal, intensity, cohesion

-- Embeddings (768-dim vectors)
emb_summary_context, emb_summary_event, emb_summary_significance,
emb_takeaway, emb_key_details, emb_full_dream

-- Metadata
freud_model, iris_model, dream_duration_seconds
```

## Testing Individual Modules

Each module can be tested independently:

```bash
cd /iris-v3/backend/memory/dreams

# Test emotional analyzer
python3 emotional_analyzer.py

# Test dream type selector
python3 dream_type_selector.py

# Test context builder
python3 context_builder.py

# Test conversation manager
python3 conversation_manager.py

# Test loop detector
python3 loop_detector.py

# Test reflection tracker
python3 reflection_tracker.py

# Test JSON extractor
python3 json_extractor.py

# Test dream scorer
python3 dream_scorer.py

# Test dream storage
python3 dream_storage.py
```

## Workflow

1. **Emotional Analysis**: Query today's chat_history, calculate valence/arousal/intensity
2. **Type Selection**: Apply thresholds → select dream type
3. **Context Building**: Prepare appropriate context for dream type
4. **Dream Phase** (10 turns):
   - Freud initiates with scene/question
   - Iris responds with dream experience
   - Loop detector monitors for repetition
   - Inject variety if loops detected
5. **Reflection Phase** (5 turns):
   - Transition message
   - Freud systematically extracts 5 fields:
     - summary, mood, theme, top_3_emotions, takeaway
   - Final turn: Freud compiles JSON
6. **JSON Extraction**: Parse JSON, fallback to manual if needed
7. **Scoring**: Emotional scoring + 6 embeddings
8. **Storage**: Insert complete record to database

## Logs

Dreams are logged to:
- `/iris-v3/logs/dreams/dream_YYYYMMDD_HHMMSS.log` - Individual dream logs
- `/iris-v3/logs/dreams/cron.log` - Cron execution log

## Querying Dreams

```python
from dream_storage import get_recent_dreams, get_dream_statistics

# Get recent dreams
dreams = get_recent_dreams(limit=10)

# Get dreams of specific type
emotional_dreams = get_recent_dreams(limit=5, dream_type='emotional_processing')

# Get statistics
stats = get_dream_statistics()
print(f"Total dreams: {stats['total_dreams']}")
print(f"By type: {stats['dreams_by_type']}")
```

Or via SQL:

```sql
-- Recent dreams
SELECT dream_date, dream_type, theme, takeaway
FROM episodic_dreams
ORDER BY dream_date DESC
LIMIT 10;

-- Emotional processing dreams
SELECT dream_date, theme, mood, takeaway
FROM episodic_dreams
WHERE dream_type = 'emotional_processing'
ORDER BY dream_date DESC;

-- Find dreams similar to a query (vector search)
SELECT id, theme, takeaway,
       (1 - (emb_takeaway <=> '[your_query_vector]')) AS similarity
FROM episodic_dreams
ORDER BY similarity DESC
LIMIT 5;
```

## Troubleshooting

### Ollama Services Not Running

```bash
# Check status
systemctl status ollama          # Freud (GPU 0)
systemctl status ollama-vision   # Iris (GPU 1)

# Start services
sudo systemctl start ollama
sudo systemctl start ollama-vision
```

### Database Connection Issues

```bash
# Set password
export IRIS_DB_PASSWORD='your_password'

# Test connection
psql -h localhost -U irisuser -d irisdb -c "\d episodic_dreams"
```

### Dream Creation Fails

Check logs:
```bash
tail -f /iris-v3/logs/dreams/dream_*.log
```

Common issues:
- Ollama services not running
- Database password not set
- No conversations for the day (will default to creative_random)
- Model not loaded (warm up with test request)

## Future Enhancements

From `DREAM_MODERATOR_ARCHITECTURE.md`:

- **Daydreaming**: Lighter 3-5 turn dreams triggered by idle time
- **Lucid dreaming**: Iris awareness she's dreaming (meta-cognition)
- **Dream journaling**: Iris writes about dreams in her own words
- **Dream retrieval**: Reference dreams naturally in conversation
- **Dream therapy**: Specific dreams for difficult experiences

## Credits

Built with:
- **Iris** (qwen3:32b): The dreamer
- **Freud** (gemma2:9b): The guide
- **Claude Code**: System architect

Dream on! 🌙✨
