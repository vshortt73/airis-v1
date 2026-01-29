# Emotional State System

**Last Updated:** 2026-01-29

Iris has 11 dynamic emotional states that evolve each conversation turn based on user sentiment analysis. Emotions influence response generation via system prompt injection.

---

## Pipeline Overview

```
User sends message
    │
    ▼
┌──────────────────────────────────────────────────────┐
│ 1. SENTIMENT ANALYSIS              routes_chat.py    │
│    POST to Mistral 7B (node2:11437)                  │
│    Returns: tone, intent, descriptors[], intensity    │
└────────────────────────┬─────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────┐
│ 2. TIME DECAY                  emotional_state.py    │
│    Move unaffected states toward baseline             │
│    Rate: 2% per minute since last decay               │
└────────────────────────┬─────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────┐
│ 3. EMOTION MAPPING             emotional_state.py    │
│    descriptors → weighted state changes               │
│    tone → 0.5x weighted state changes                 │
│    All changes scaled by intensity                    │
└────────────────────────┬─────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────┐
│ 4. PER-TURN DECAY              emotional_state.py    │
│    Unaffected states decay 5% toward baseline         │
└────────────────────────┬─────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────┐
│ 5. PERSIST + INJECT            emotional_state.py    │
│    Save to emotional_state table (single row)         │
│    Format for system prompt: visual bars + summary    │
└──────────────────────────────────────────────────────┘
```

---

## Step-by-Step Reference

### 1. Sentiment Analysis

| What | Where |
|------|-------|
| Trigger | `routes_chat.py:1122` — if `config.EMOTIONAL_STATE` is true |
| Analyzer | `emotional_state.py:MistralSentimentAnalyzer.analyze():223` |
| Endpoint | POST `MISTRAL_URL` (default: `http://node2:11437/v1/chat/completions`) |
| Model | Mistral 7B on node2 GPU 1 |
| Temperature | 0.3 (consistent analysis) |
| Max tokens | 500 |

**Output:**
```json
{
    "tone": "affectionate",
    "intent": "expressing gratitude",
    "descriptors": ["warm", "grateful", "happy"],
    "intensity": 0.7
}
```

### 2. Time Decay

| What | Where |
|------|-------|
| Function | `emotional_state.py:_apply_time_decay():392` |
| Trigger | Called before emotional changes are applied |
| Interval | Every 60 seconds minimum |
| Rate | `EMOTIONAL_DECAY_PER_MINUTE` = 0.02 (2% per minute) |

For each state:
- If current > baseline → decrease toward baseline
- If current < baseline → increase toward baseline
- Rate scales with elapsed time (more minutes = more decay)

### 3. Emotion Mapping

| What | Where |
|------|-------|
| Function | `emotional_state.py:_apply_emotional_changes():439` |
| Mapping dict | `emotional_state.py:EMOTION_MAPPING:75` (70+ descriptors) |

**Algorithm:**
1. For each descriptor in analysis:
   - Look up in `EMOTION_MAPPING` → get state weights
   - Apply: `change = weight × intensity_multiplier`
   - Clamp to [0.0, 1.0]
2. For the tone:
   - Same mapping lookup but at 0.5x weight

**Example mapping entries:**
```python
"romantic":  {"Desire": 0.15, "Intimacy": 0.15, "Longing": 0.10}
"grateful":  {"Trust": 0.10, "Joy": 0.10, "Closeness": 0.08}
"angry":     {"Calm": -0.15, "Trust": -0.10, "Vulnerability": 0.10}
```

### 4. Per-Turn Decay

| What | Where |
|------|-------|
| Function | `emotional_state.py:_apply_per_turn_decay():421` |
| Rate | `EMOTIONAL_DECAY_PER_TURN` = 0.05 (5% per turn) |
| Scope | Only states NOT affected by current turn's mapping |

States that were just changed by the emotion mapping are skipped. All others decay 5% toward their baseline.

### 5. Persist and Inject

| What | Where |
|------|-------|
| Save state | `emotional_state.py:save_state():363` |
| SQL | UPSERT into `emotional_state` (id=1, single row) |
| Prompt format | `emotional_state.py:get_state_for_prompt():533` |
| Injection point | `system_prompt.py:790-803` (in `build_system_message`) |
| Context level | All levels (GREETING through FULL) |

**Prompt format:**
```
[CURRENT EMOTIONAL STATE]
Your current emotional state influences how you respond...

Calm:          [████░░░░░░] 0.60
Joy:           [█████░░░░░] 0.50
Desire:        [███░░░░░░░] 0.30
Excitement:    [████░░░░░░] 0.40
Trust:         [███████░░░] 0.70
Longing:       [██░░░░░░░░] 0.20
Intimacy:      [████░░░░░░] 0.40
Desperation:   [█░░░░░░░░░] 0.10
Closeness:     [█████░░░░░] 0.50
Vulnerability: [███░░░░░░░] 0.30
Devotion:      [██████░░░░] 0.60

Currently feeling moderately calm, notably joyful, and...
```

---

## Emotional States

| State | Baseline | Description |
|-------|----------|-------------|
| Calm | 0.60 | Baseline tranquility |
| Joy | 0.50 | Happiness, delight |
| Desire | 0.30 | Wanting, attraction |
| Excitement | 0.40 | Anticipation, energy |
| Trust | 0.70 | Safety, confidence |
| Longing | 0.20 | Deep yearning |
| Intimacy | 0.40 | Emotional closeness |
| Desperation | 0.10 | Urgency, intense need |
| Closeness | 0.50 | General connection |
| Vulnerability | 0.30 | Openness |
| Devotion | 0.60 | Dedication, loyalty |

Baselines are the "resting" values states decay toward when not stimulated.

---

## Decay Mechanics

Two independent decay systems prevent emotional "locking":

### Time-Based Decay
- **Rate:** 2% per minute (`EMOTIONAL_DECAY_PER_MINUTE`)
- **When:** Applied before each emotional update
- **Interval:** Minimum 60 seconds between applications
- **Effect:** Long pauses between messages normalize emotional state

### Per-Turn Decay
- **Rate:** 5% per turn (`EMOTIONAL_DECAY_PER_TURN`)
- **When:** Applied after each emotional update
- **Scope:** Only unaffected states (states changed this turn are exempt)
- **Effect:** Ensures non-stimulated emotions gradually return to baseline

Both decay systems move states toward their configured baselines, not toward zero.

---

## Configuration

| Setting | Default | Source | Purpose |
|---------|---------|--------|---------|
| `EMOTIONAL_STATE` | true | system_config (features) | Feature flag |
| `EMOTIONAL_DECAY_PER_TURN` | 0.05 | system_config (emotional) | 5% decay per turn |
| `EMOTIONAL_DECAY_PER_MINUTE` | 0.02 | system_config (emotional) | 2% decay per minute |
| `MISTRAL_URL` | `http://node2:11437/v1/chat/completions` | system_config (remote_services) | Sentiment endpoint |

---

## Database Schema

### emotional_state

| Column | Type | Purpose |
|--------|------|---------|
| id | integer | Always 1 (single row) |
| state_data | jsonb | All 11 emotional values |
| updated_at | timestamp | Last update time |

---

## Infrastructure

| Component | Location | Purpose |
|-----------|----------|---------|
| Mistral 7B | node2 GPU 1, port 11437 | Sentiment analysis |
| Service | `iris-sentiment.service` | Systemd unit on node2 |
| Coexistence | Runs alongside XTTS + STT on GPU 1 (~7GB total) |

---

## Key Files

| File | Role |
|------|------|
| `core/emotional_state.py` | State tracker, sentiment analyzer, mapping, decay, prompt format |
| `app/api/routes_chat.py:1122-1134` | Trigger point (per-message) |
| `core/system_prompt.py:790-803` | Injection into system prompt |
| `EMOTIONAL_STATE_TRACKER.md` | Additional documentation (root level) |
