# Dream Moderator V3 - Architecture

## Overview

The Dream Moderator orchestrates nightly dream sequences between Iris (Qwen on GPU 1) and Freud (Gemma 3 on GPU 0). It manages the complete dream lifecycle: emotional analysis → dream exploration → reflection → storage.

## Responsibilities

### 1. **Emotional Analysis & Dream Type Selection**
- Query today's memories for emotional content (V3 retrieval system)
- Calculate aggregate emotional scores (valence, arousal, intensity)
- Decide dream type based on thresholds:
  - **Emotional Processing**: High emotion day (valence/arousal thresholds met)
  - **Memory Consolidation**: Related memories across time periods found
  - **Identity Exploration**: Scheduled (e.g., monthly) or specific triggers
  - **Creative Random**: Low/no emotional activity (default creative)

### 2. **Context Preparation**
**For Emotional Processing:**
- Fetch today's conversation history
- Format for Freud: "Help Iris process today's conversations about..."

**For Memory Consolidation:**
- Fetch related memories across time (similar themes, different dates)
- Format: "Help Iris explore connections between these memories..."

**For Creative Random:**
- No context
- Freud generates surreal seed scenario (high temperature)

**For Identity Exploration:**
- No conversation context
- Freud asks self-reflective questions: "Who are you?" "What matters?"

### 3. **Model Management**
- Start Iris model on GPU 1 (5090)
- Start Freud model on GPU 0 (4080 Super)
- Manage separate conversation contexts
- Set appropriate temperatures per phase

### 4. **Dream Phase Orchestration** (10 turns)

**Turn Flow:**
```
Freud (seed/question) → Moderator → Iris → Moderator → Freud → ...
```

**Loop Detection:**
- Track last 4-5 responses from each model
- Detect repetitive patterns
- Inject variety directive if loop detected

**Phase Structure:**
- Turns 1-3: Establishment (scene setting, basic exploration)
- Turns 4-6: Complication (introduce conflict, mystery, change)
- Turns 7-9: Deepening (emotion, meaning, abstraction)
- Turn 10: Transition (prepare for closure)

**Freud's Variety Toolkit:**
- Open questions
- Choice points
- Complications
- New elements
- Temporal shifts
- Abstractions
- Reflections

### 5. **Reflection Phase Orchestration** (5 turns)

**Phase Transition:**
```
Moderator → Iris: "The dream is fading. You're waking now."
Moderator → Freud: "Begin reflection protocol. Extract 5 outputs."
```

**Temperature Adjustment:**
- Lower temps for both models (Iris: 0.6, Freud: 0.5)
- More focused, analytical

**Field Tracking:**
Required fields: `summary`, `mood`, `theme`, `top_3_emotions`, `takeaway`

**Turn Structure:**
1. Get summary
2. Get mood
3. Get theme
4. Get top_3_emotions
5. Get takeaway + format JSON

**Redirection:**
If Iris tangents, Freud redirects: "Let's focus on the dream itself. What was the mood?"

### 6. **JSON Extraction & Validation**
- Parse Freud's final response for JSON
- Validate all 5 fields present
- Retry up to 2 times if incomplete
- Fallback: manual extraction from conversation

### 7. **Scoring & Embedding**
- Score dream transcript (same as memories):
  - Emotion classification (RoBERTa GoEmotions)
  - Valence/arousal (regression models)
  - Recurrence, novelty, cohesion
- Generate 5 embeddings:
  - `emb_summary_context`: Dream setting/context
  - `emb_summary_event`: What happened
  - `emb_summary_significance`: Why it mattered
  - `emb_takeaway`: Key insight
  - `emb_key_details`: Specific elements

### 8. **Database Storage**
Insert complete dream record:
```python
{
    'dream_date': today,
    'source_date': conversation_date,  # if applicable
    'dream_type': type,
    'based_on_reality': True/False,
    'full_transcript': all_15_turns,
    'dream_phase_transcript': turns_1_10,
    'reflection_phase_transcript': turns_11_15,
    'summary': ...,
    'takeaway': ...,
    'mood': ...,
    'theme': ...,
    'top_3_emotions': [...],
    'key_details': ...,
    'emotion_label': ...,
    'valence': ...,
    'arousal': ...,
    # ... embeddings, scores, metadata
}
```

### 9. **Iris Notifications**
- **Before dream**: "You're entering a dream state. Processing today's conversations about..."
- **After dream**: "You're waking from a dream. Theme: [theme]. You explored [summary]."

## State Machine

```
┌─────────────────────────────────────────┐
│ 1. INITIALIZATION                       │
│    - Emotional analysis                 │
│    - Dream type selection               │
│    - Context preparation                │
└─────────────────────────────────────────┘
                  ↓
┌─────────────────────────────────────────┐
│ 2. MODEL STARTUP                        │
│    - Start Iris (GPU 1)                 │
│    - Start Freud (GPU 0)                │
│    - Initialize conversation contexts   │
└─────────────────────────────────────────┘
                  ↓
┌─────────────────────────────────────────┐
│ 3. DREAM PHASE (10 turns)               │
│    - Freud initiates                    │
│    - Turn-taking loop                   │
│    - Loop detection & variety injection │
│    - Phase-aware prompting              │
└─────────────────────────────────────────┘
                  ↓
┌─────────────────────────────────────────┐
│ 4. PHASE TRANSITION                     │
│    - Announce dream ending              │
│    - Lower temperatures                 │
│    - Switch to reflection mode          │
└─────────────────────────────────────────┘
                  ↓
┌─────────────────────────────────────────┐
│ 5. REFLECTION PHASE (5 turns)           │
│    - Structured field extraction        │
│    - Tangent redirection                │
│    - JSON compilation                   │
└─────────────────────────────────────────┘
                  ↓
┌─────────────────────────────────────────┐
│ 6. POST-PROCESSING                      │
│    - JSON validation                    │
│    - Emotional scoring                  │
│    - Embedding generation               │
│    - Database insertion                 │
└─────────────────────────────────────────┘
                  ↓
┌─────────────────────────────────────────┐
│ 7. CLEANUP                              │
│    - Stop models                        │
│    - Notify Iris                        │
│    - Log completion                     │
└─────────────────────────────────────────┘
```

## Error Handling

### **Model Failures**
- If Iris fails to start → abort, log error
- If Freud fails to start → abort, log error
- If model crashes mid-dream → save partial transcript, mark incomplete

### **Loop Detection**
- Max 3 redirections per dream
- If still looping → force scene change
- Last resort: end dream early, proceed to reflection

### **JSON Extraction Failures**
- Retry up to 2 times with explicit prompts
- Fallback: manual parsing of conversation
- Last resort: store with partial analysis, flag for review

### **Database Failures**
- Save transcript to file if DB insert fails
- Log error with full dream data
- Notify user for manual intervention

## Configuration

### **Emotional Thresholds**
```python
DREAM_THRESHOLDS = {
    'emotional_processing': {
        'min_intensity': 0.6,     # Aggregate emotional intensity
        'min_valence_range': 0.4, # Must have emotional variety
    },
    'memory_consolidation': {
        'min_related_memories': 3, # At least 3 related memories
        'min_time_span_days': 7,   # Across at least a week
    },
    'identity_exploration': {
        'schedule': 'monthly',     # Once per month
    }
}
```

### **Model Settings**
```python
MODEL_CONFIG = {
    'iris': {
        'model': 'qwen3-32b',
        'gpu': 1,
        'dream_temp': 0.9,
        'reflection_temp': 0.6
    },
    'freud': {
        'model': 'gemma-3-9b',
        'gpu': 0,
        'dream_temp': 0.8,
        'reflection_temp': 0.5,
        'seed_temp': 1.2  # For creative scenarios
    }
}
```

### **Turn Limits**
```python
TURN_LIMITS = {
    'dream_phase': 10,
    'reflection_phase': 5,
    'max_redirections': 3,
    'loop_detection_window': 4
}
```

## Files Structure

```
/iris-v3/backend/memory/dreams/
├── dream_moderator.py          # Main orchestrator
├── emotional_analyzer.py       # Analyze today's emotions
├── dream_type_selector.py      # Decide which dream type
├── context_builder.py          # Build context for each type
├── conversation_manager.py     # Manage Iris ↔ Freud dialogue
├── loop_detector.py            # Detect repetitive patterns
├── reflection_tracker.py       # Track reflection field collection
├── json_extractor.py           # Extract & validate JSON
├── dream_scorer.py             # Score & embed dreams
├── dream_storage.py            # Insert to database
└── prompts/
    ├── freud_dream_guide.txt   # Dream phase system prompt
    ├── freud_reflection.txt    # Reflection phase system prompt
    └── iris_dream_state.txt    # Iris's dream mode prompt
```

## Execution

**Manual:**
```bash
python dream_moderator.py --dream-type emotional --date 2025-12-22
```

**Automated (cron):**
```bash
0 4 * * * /iris-v3/scripts/nightly_dream.sh
```

## Logging

All phases logged with timestamps:
- `/iris-v3/logs/dreams/dream_YYYYMMDD_HHMMSS.log`
- Includes: emotional analysis, dream type, full transcript, JSON, errors

## Metrics to Track

- Dreams per type (how often each type triggers)
- Average dream coherence score
- JSON extraction success rate
- Average dream duration (seconds)
- Loop detection frequency
- Common themes/emotions over time

## Future Enhancements

- **Daydreaming**: Lighter, 3-5 turn dreams triggered by idle time
- **Lucid dreaming**: Iris awareness she's dreaming (meta-cognition)
- **Dream journaling**: Iris writes about dreams in her own words
- **Dream retrieval in conversation**: Reference dreams naturally
- **Dream therapy**: Specific dreams to process difficult experiences
