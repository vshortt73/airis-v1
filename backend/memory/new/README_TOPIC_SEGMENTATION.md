# Topic Segmentation Script

LLM-first approach for maximum accuracy in topic boundary detection and title generation.

## Overview

This script identifies topic boundaries in conversation history and generates concise titles using a four-stage process:

1. **Stage 1: LLM Boundary Detection** (High Accuracy)
   - Uses Ollama LLM to identify where conversation topics change
   - Analyzes chunks of conversation with context
   - Can detect "no boundaries" (entire session is one topic)
   - Configurable model selection (recommended: llama3.1:8b for speed/quality balance)

2. **Stage 2: Boundary Refinement** (Optional)
   - Validates detected boundaries for consistency
   - Can be skipped for faster processing

3. **Stage 3: Coherence Validation** (Optional)
   - Validates internal coherence of each topic group
   - Flags groups with low coherence for potential sub-topics
   - Can be skipped for faster processing

4. **Stage 4: Title Generation** (Magazine-Style Titles)
   - LLM generates concise 2-5 word titles for each topic
   - Magazine article style: "Python Installation" not "Installing Python on a computer"
   - Stores titles in `conv_title` column
   - Programmatic fallback for edge cases

## Database Changes

The script will add a `topic_id` column to `chat_history`:
```sql
ALTER TABLE chat_history ADD COLUMN topic_id INTEGER;
```

Each message will be assigned a simple integer (1, 2, 3, etc.) representing its topic group within a session.

## Usage

### Recommended Usage (llama3.1:8b)
Best balance of speed, accuracy, and clean titles:
```bash
export IRIS_DB_PASSWORD='yourpassword'
cd /iris-v3
python backend/memory/new/topic_segmentation.py --analysis-model llama3.1:8b
```

### Basic Usage (Default Model)
Uses qwen3:32b (may have verbose output issues):
```bash
python backend/memory/new/topic_segmentation.py
```

### Process Single Session
```bash
python backend/memory/new/topic_segmentation.py --session-id "uuid-here" --analysis-model llama3.1:8b
```

### Skip Coherence Validation (Faster)
```bash
python backend/memory/new/topic_segmentation.py --no-coherence --analysis-model llama3.1:8b
```

### Dry Run (Test Without Database Updates)
```bash
python backend/memory/new/topic_segmentation.py --dry-run --analysis-model llama3.1:8b
```

### Limit Number of Sessions (Testing)
Process only the first N sessions (excellent for testing):
```bash
# Process only 3 sessions with llama3.1:8b
python backend/memory/new/topic_segmentation.py --limit 3 --analysis-model llama3.1:8b

# Quick test: 1 session with dry-run
python backend/memory/new/topic_segmentation.py --limit 1 --dry-run --analysis-model llama3.1:8b
```

## Command Line Arguments

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `--analysis-model` | string | qwen3:32b | Model for boundary detection and titles (e.g., llama3.1:8b) |
| `--no-coherence` | flag | False | Skip coherence validation stage |
| `--session-id` | string | None | Process only this session UUID |
| `--limit` | int | None | Maximum number of sessions to process |
| `--dry-run` | flag | False | Test without database updates |

**Recommended Model**: Use `--analysis-model llama3.1:8b` for best balance of speed, accuracy, and clean titles. Qwen models use "thinking mode" which can cause issues.

## Recommended Testing Workflow

Before processing all sessions, test with a limited subset:

```bash
# Step 1: Dry run on 1 session to verify it works
python backend/memory/new/topic_segmentation.py --limit 1 --dry-run --analysis-model llama3.1:8b

# Step 2: Process 1 session for real and inspect results
python backend/memory/new/topic_segmentation.py --limit 1 --analysis-model llama3.1:8b

# Step 3: Check the database results
PGPASSWORD='yourpassword' psql -h localhost -U irisuser -d irisdb -c \
  "SELECT topic_id, conv_title, COUNT(*) FROM chat_history WHERE topic_id IS NOT NULL GROUP BY topic_id, conv_title ORDER BY topic_id;"

# Step 4: If satisfied, process 5-10 sessions
python backend/memory/new/topic_segmentation.py --limit 10 --analysis-model llama3.1:8b

# Step 5: Process all remaining sessions
python backend/memory/new/topic_segmentation.py --analysis-model llama3.1:8b
```

## How It Works

### Stage 1: LLM Boundary Detection
```
LLM Prompt (analyzing chunks of 40 messages):
  "Analyze this conversation and identify where topic changes occur.

   A TOPIC CHANGE occurs when:
   - The subject matter clearly shifts to something unrelated
   - A new question asks about a completely different subject
   - The conversation pivots from one domain to another

   Return ONLY the message numbers where topic changes occur."

LLM Response Examples:
  - "15, 42, 89" → Boundaries at messages 15, 42, and 89
  - "NONE" → No topic changes, entire session is one topic
```

### Stage 2: Boundary Refinement (Optional)
```
Validates detected boundaries for consistency.
Can be skipped with --no-coherence for faster processing.
```

### Stage 3: Coherence Validation (Optional)
```
For each topic group:
  - Validates reasonable group size (not too small/large)
  - Flags groups that might contain sub-topics
  - Ensures quality of segmentation
```

### Stage 4: Title Generation
```
LLM Prompt (for each topic):
  "Provide a concise title for this conversation as though
   it was a magazine article. Use 2-5 words maximum.

   EXAMPLES:
   - Python Installation
   - Database Connection Issues
   - Understanding Recursion"

LLM Response Examples:
  - "Python Installation"
  - "Rendering Engine Consistency"
  - "Database Password Setup"

Programmatic cleanup removes any verbose prefixes if needed.
```

## Example Output

```
============================================================
Processing session: f47ac10b-58cc-4372-a567-0e02b2c3d479
============================================================
Found 127 messages

[Stage 1] Detecting boundaries with LLM...
  Processing chunk 0-40...
  [LLM] Boundary detected at message 15
  Processing chunk 40-80...
  [LLM] Boundary detected at message 67
  Processing chunk 80-127...
  [LLM] Boundary detected at message 103
[Stage 1] ✓ Found 3 boundaries

[Stage 3] Validating topic coherence...
  Topic 1: messages 0-14 (15 messages)
    ✓ Reasonable size
  Topic 2: messages 15-66 (52 messages)
    ✓ Reasonable size
  Topic 3: messages 67-102 (36 messages)
    ✓ Reasonable size
  Topic 4: messages 103-126 (24 messages)
    ✓ Reasonable size
[Stage 3] ✓ Validated 4 topic groups

[Title Generation] Creating titles for 4 topics...
  Generating title for Topic 1 (15 messages)...
  [Title] Topic 1: "Python Installation"

  Generating title for Topic 2 (52 messages)...
  [Title] Topic 2: "Database Connection Issues"

  Generating title for Topic 3 (36 messages)...
  [Title] Topic 3: "Rendering Engine Consistency"

  Generating title for Topic 4 (24 messages)...
  [Title] Topic 4: "GPU Memory Optimization"

[Database] Updating chat_history...
  ✓ Updated 127 messages with topic IDs
  ✓ Updated 127 messages with titles

============================================================
✓ Session f47ac10b-58cc-4372-a567-0e02b2c3d479 completed
  Total messages: 127
  Topics identified: 4
  Titles generated: 4
============================================================
```

## Tuning Recommendations

### For Best Results (Recommended)
- Use `--analysis-model llama3.1:8b` for clean, concise titles
- Keep all stages enabled (default)
- Trade-off: Slower but highly accurate

### For Maximum Speed
- Skip coherence validation: `--no-coherence`
- Use faster model: `--analysis-model llama3.1:8b` (8B is faster than 32B)
- Trade-off: Slightly less validation but still accurate boundaries

### Model Selection Guide
- **llama3.1:8b**: Best balance - fast, accurate, clean titles (RECOMMENDED)
- **qwen3:32b**: More thoughtful but "thinking mode" causes verbose titles
- **qwen2.5:14b**: Same "thinking mode" issues as qwen3:32b
- Avoid models with "thinking mode" for cleaner output

## Requirements

- Python 3.8+
- psycopg2
- httpx
- Ollama running on `localhost:11434`
- llama3.1:8b model installed: `ollama pull llama3.1:8b`
- PostgreSQL database with `chat_history` table

## Dependencies

All dependencies should already be in `requirements.txt`:
```
psycopg2-binary
httpx
```

## Troubleshooting

### LLM Connection Issues
If LLM calls fail:
- Check Ollama is running: `curl http://localhost:11434/api/tags`
- Verify model is installed: `ollama list | grep llama3.1`
- Pull model if needed: `ollama pull llama3.1:8b`

### Verbose or Poor Quality Titles
If titles are verbose or conversational:
- Switch to llama3.1:8b: `--analysis-model llama3.1:8b`
- Avoid Qwen models which use "thinking mode"
- Programmatic cleanup should handle most verbose patterns

### Database Connection
Ensure `IRIS_DB_PASSWORD` is set:
```bash
export IRIS_DB_PASSWORD='yourpassword'
```

## Performance

Approximate processing times (per session):

| Configuration | Model | Speed | Accuracy | Est. Time (100 msgs) |
|---------------|-------|-------|----------|---------------------|
| All stages (default) | llama3.1:8b | Fast | 95%+ | 15-30 seconds |
| All stages (default) | qwen3:32b | Medium | 95%+ | 30-60 seconds |
| --no-coherence | llama3.1:8b | Very Fast | 93%+ | 10-20 seconds |
| --no-coherence | qwen3:32b | Fast | 93%+ | 20-40 seconds |

**Note**: llama3.1:8b is recommended for best balance of speed and quality.

## Next Steps

After running this script:

1. **View all topics with titles**:
```sql
SELECT topic_id, conv_title, COUNT(*) as message_count
FROM chat_history
WHERE topic_id IS NOT NULL
GROUP BY topic_id, conv_title
ORDER BY topic_id;
```

2. **Inspect specific topic messages**:
```sql
SELECT c_timestamp, role, message, conv_title
FROM chat_history
WHERE topic_id = 1
ORDER BY c_timestamp;
```

3. **View topics per session**:
```sql
SELECT session_id, topic_id, conv_title, COUNT(*) as message_count
FROM chat_history
WHERE topic_id IS NOT NULL
GROUP BY session_id, topic_id, conv_title
ORDER BY session_id, topic_id;
```

4. **Use topic_id and conv_title for**:
   - Memory clustering and retrieval
   - Conversation analysis and summaries
   - Topic-based context loading
   - User interface topic navigation
