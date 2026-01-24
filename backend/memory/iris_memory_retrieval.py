# This script is triggered by the postgresql function python_memory_trigger()
# by default it fires every once for every 10 new transactions created in chat_history.
# do not alter this file!

import os
import sys

# Add project root and memory module to path FIRST (before other imports)
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
MEMORY_DIR = os.path.dirname(__file__)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
if MEMORY_DIR not in sys.path:
    sys.path.insert(0, MEMORY_DIR)

import psycopg2
from psycopg2.extras import DictCursor
import json
import torch
from sentence_transformers import SentenceTransformer
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from Colors import Colors
from torch.nn.functional import softmax
import numpy as np
import requests
import math
import time
import argparse

# ==============================
# Database config
# ==============================
# Use environment variable for password (same pattern as rest of codebase)
DB_CFG = {
    'dbname': 'irisdb',
    'user': 'irisuser',
    'password': os.environ.get('IRIS_DB_PASSWORD', ''),
    'host': 'localhost',
    'port': 5432
}
delete_flag = False
# ==============================
# Models and embedding
# ==============================



# emo_tok = AutoTokenizer.from_pretrained(emo_dir, local_files_only=True)
# emo_model = AutoModelForSequenceClassification.from_pretrained(emo_dir, local_files_only=True)


EMO_MODEL_DIR = "/models/Memory-models/emotion_model_balanced"  # <-- your balanced model
VALENCE_MODEL_PATH = "/models/Memory-models/valence_model"
AROUSAL_MODEL_PATH = "/models/Memory-models/arousal_model"
MAX_LEN = 256
# Always use CPU for memory retrieval - this is a background job that shouldn't
# compete with main inference (Qwen) or other GPU services for VRAM
DEVICE = "cpu"


# Use shared embedding singleton (thread-safe, prevents race condition)
from core.embeddings import get_embedding_model

# Import config for LLM endpoints
from app import config
import httpx

# Force offline mode
os.environ["HF_HUB_OFFLINE"] = "1"

# Get shared model instance (thread-safe singleton)
model = get_embedding_model()
# model = SentenceTransformer("all-mpnet-base-v2")

# ==============================
# LLM API Helper (llama-server OpenAI-compatible)
# ==============================
def call_llm_json(prompt: str, max_tokens: int = 1024, temperature: float = 0.1, timeout: float = 60.0) -> dict:
    """
    Call llama-server with OpenAI-compatible API for JSON responses.

    Args:
        prompt: The prompt to send
        max_tokens: Maximum tokens in response
        temperature: Sampling temperature
        timeout: Request timeout in seconds

    Returns:
        Parsed JSON dict, or empty dict on failure
    """
    url = f"{config.OLLAMA_BASE_URL}/v1/chat/completions"

    payload = {
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
        "response_format": {"type": "json_object"}
    }

    try:
        response = httpx.post(url, json=payload, timeout=timeout)

        if response.status_code != 200:
            print(f"[call_llm_json] HTTP error: {response.status_code}")
            return {}

        result = response.json()
        raw_text = result.get("choices", [{}])[0].get("message", {}).get("content", "")

        print(f"#################################")
        print(raw_text)
        print(f"#################################")

        return json.loads(raw_text)

    except json.JSONDecodeError as e:
        print(f"[call_llm_json] JSON parse error: {e}")
        return {}
    except httpx.TimeoutException:
        print(f"[call_llm_json] Timeout after {timeout}s")
        return {}
    except Exception as e:
        print(f"[call_llm_json] Error: {e}")
        return {}


# ==============================
# Weights
# ==============================
# Embedding similarity blend (SQL-side)
# FIXED: Balanced weights across all embeddings (was 0.00, 0.00, 0.00, 0.20)
SIM_WEIGHTS = {
    "context":       0.25,  # Context of conversation
    "event":         0.25,  # What happened
    "significance":  0.25,  # Why it matters
    "takeaway":      0.25,  # Key insight
    "sim_threshold": 0.20,  # Minimum similarity for associative recall (human-like threshold)
}

# Rerank blend (Python-side)
# Phase 2: Increased facet weight from 10% to 20% to boost topic-matching memories
# CRITICAL: Must sum to exactly 1.00 for proper scoring
RERANK_WEIGHTS = {
    "sim":        0.40,   # similarity score (40%) - reduced from 45%
    "emotion":    0.10,   # valence*arousal, scaled (10%)
    "recurrence": 0.10,   # how often referenced (10%)
    "cohesion":   0.05,   # narrative coherence (5%)
    "novelty":    0.05,   # uniqueness (5%)
    "context":    0.10,   # category match (10%) - reduced from 15%
    "facet":      0.20,   # facet match (20%) - DOUBLED from 10%
}  # Total = 1.00 (100%) ✓ VERIFIED

# Memory tier thresholds (based on similarity score)
# Tiers allow prioritization of memories in context injection
TIER_THRESHOLDS = {
    1: 0.60,  # PRIMARY - Direct topic matches
    2: 0.40,  # SUPPORTING - Strong contextual relevance
    3: 0.30,  # ASSOCIATIVE - Connected themes/ideas
    4: 0.25,  # PERIPHERAL - Weak but valid connections
}
MIN_SIMILARITY = 0.25  # Filter out anything below this (noise)

# Boost multiplier for select emotions
EMOTION_BOOSTS = {
    "admiration": 1.1,
    "excitement": 1.1,
    "approval":   1.1,
}
# Memory decay control - Category-based (like human memory)
# Different types of memories fade at different rates
HALF_LIFE_BY_CATEGORY = {
    "Technical": 45,      # Work/tech discussions fade medium-fast
    "Practical": 45,      # Task/procedural info fades medium-fast
    "Creative": 90,       # Creative work persists longer
    "Learning": 90,       # Insights and learning persist
    "Personal": 180,      # Personal experiences long-lasting
    "Relational": 180,    # Relationship moments long-lasting
    "Other": 60           # Default medium persistence
}

# Emotions that create strong memory encoding (resist decay)
HIGH_SALIENCE_EMOTIONS = [
    "excitement", "joy", "admiration", "awe", "surprise",
    "gratitude", "love", "pride", "relief"
]

def calculate_tier(similarity_score):
    """
    Calculate memory tier based on similarity score.

    Returns:
        int: Tier number (1-4), or None if below minimum threshold
    """
    if similarity_score >= TIER_THRESHOLDS[1]:
        return 1  # PRIMARY
    elif similarity_score >= TIER_THRESHOLDS[2]:
        return 2  # SUPPORTING
    elif similarity_score >= TIER_THRESHOLDS[3]:
        return 3  # ASSOCIATIVE
    elif similarity_score >= TIER_THRESHOLDS[4]:
        return 4  # PERIPHERAL
    else:
        return None  # Below threshold - filter out

surrogate = """
Analyze this design for assembly viability given currently available parts on the market. Adjust the design to utilize the parts necessary and re-rendee Here’s a detailed **engineering analysis** of the full-body frame you just rendered, along with **required adjustments** to make it **realistically buildable today** using currently available commercial robotics hardware:

---

## 🧠 Assembly Viability Review

### ✅ What Works
| Component | Analysis |
|----------|---------|
| **Shoulders** | Feature realistic multi-axis mounts, likely based on brushless servo or Dynamixel Pro actuators. Physical space and proportions are viable. |
| **Torso Actuation** | Dual vertical actuator stacks appear feasible. Could house linear actuators or nested gimbals. |
| **Arms** | Clearly defined elbow, wrist, and digit actuation systems. Articulation appears feasible with compact servo/gearbox integration. |
| **Hips & Legs** | Ball-joint hip design shows realistic separation and drive paths. Joint spacing is consistent with torque transmission using harmonic drives. |
| **Overall Form** | Maintains a slender, feminine shape with curved skeletal panels, consistent with human anatomical symmetry and servo-clearance design.


"""
#===============================
#DEBUG
#===============================
def test_memories(embeddings, conn_params, limit=20):
    """Run a one-off similarity check with the current dynamic embeddings."""
    with psycopg2.connect(**conn_params) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        id,
                        takeaway,
                        (1 - (emb_summary_context      <=> %s::vector))::float AS sim_ctx,
                        (1 - (emb_summary_event        <=> %s::vector))::float AS sim_evt,
                        (1 - (emb_summary_significance <=> %s::vector))::float AS sim_sig,
                        (1 - (emb_takeaway             <=> %s::vector))::float AS sim_take
                    FROM episodic_memories_with_age
                    ORDER BY (
                        (1 - (emb_summary_context      <=> %s::vector)) +
                        (1 - (emb_summary_event        <=> %s::vector)) +
                        (1 - (emb_summary_significance <=> %s::vector)) +
                        (1 - (emb_takeaway             <=> %s::vector))
                    ) DESC
                    LIMIT %s;
                """, (
                    embeddings["context"],
                    embeddings["event"],
                    embeddings["significance"],
                    embeddings["takeaway"],
                    embeddings["context"],
                    embeddings["event"],
                    embeddings["significance"],
                    embeddings["takeaway"],
                    limit
                ))

                print(f"""EMBEDDING SAMPLE
                    {embeddings["context"][10]}
                    {embeddings["event"][10]}
                    {embeddings["significance"][10]}
                    {embeddings["takeaway"][10]}
                    {embeddings["context"][10]}
                    {embeddings["event"][10]}
                    {embeddings["significance"][10]}
                    {embeddings["takeaway"][10]}
                    """
                    )

                rows = cur.fetchall()
                for row in rows:
                    mem_id    = row["id"]
                    takeaway  = row["takeaway"]
                    sim_ctx   = float(row["sim_ctx"])
                    sim_evt   = float(row["sim_evt"])
                    sim_sig   = float(row["sim_sig"])
                    sim_take  = float(row["sim_take"])

                    avg_sim = (sim_ctx + sim_evt + sim_sig + sim_take) / 4
                    print(f"ID {mem_id} | avg={avg_sim:.3f}")
                    print(f"ctx={sim_ctx:.3f} evt={sim_evt:.3f} sig={sim_sig:.3f} take={sim_take:.3f}")
                 #  print(f"  Takeaway: {takeaway[:100]}...")
                    print("-" * 60)

    conn.close()


def test_memories_debug(embeddings, conn_params, limit=10):
    """Run a one-off similarity check with the current dynamic embeddings."""
    with psycopg2.connect(**conn_params) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        id,
                        takeaway,
                        (1 - (emb_summary_context      <=> %s::vector))::float AS sim_ctx,
                        (1 - (emb_summary_event        <=> %s::vector))::float AS sim_evt,
                        (1 - (emb_summary_significance <=> %s::vector))::float AS sim_sig,
                        (1 - (emb_takeaway             <=> %s::vector))::float AS sim_take
                    FROM episodic_memories_with_age
                    LIMIT %s;
                """, (
                    embeddings["context"],
                    embeddings["event"],
                    embeddings["significance"],
                    embeddings["takeaway"],
                    limit
                ))

                rows = cur.fetchall()
                for row in rows:
                    mem_id    = row["id"]
                    takeaway  = row["takeaway"]
                    sim_ctx   = float(row["sim_ctx"])
                    sim_evt   = float(row["sim_evt"])
                    sim_sig   = float(row["sim_sig"])
                    sim_take  = float(row["sim_take"])
                    print(f"ctx:{sim_ctx}  evt:{sim_evt}   sig:{sim_sig}   take:{sim_take}")
                   
    conn.close()

# ==============================
# Utility
# ==============================
def sanitize_convo(text: str) -> str:
    return "".join(ch for ch in text if 32 <= ord(ch) <= 126 or ch in "\n\t")

# ==============================
# Lens stage - OLLAMA VERSION
# ==============================
def run_lens_stage(summary: dict):
    """
    Extract conversation structure using Ollama

    NOW EXTRACTS FROM SUMMARY (not raw conversation) to get clean, focused keywords
    This models human memory: recall is context-dependent, not keyword-spam

    Converted from llama.cpp for consistency and speed
    """
    import httpx

    # Extract from the distilled summary, not raw conversation
    # This eliminates noise and focuses on what the conversation is ABOUT
    context = summary["MemoryRecall"]["Context"]
    event = summary["MemoryRecall"]["Event"]
    significance = summary["MemoryRecall"]["Significance"]
    takeaway = summary["MemoryRecall"]["Takeaway"]
    tone = summary["MemoryRecall"]["Tone"]

    prompt = f"""Analyze this conversation summary to understand what it's fundamentally ABOUT and what memories would be relevant to recall.

CONVERSATION SUMMARY:
Context: {context}
Event: {event}
Significance: {significance}
Takeaway: {takeaway}
Tone: {tone}

Think like a human encoding a memory: What's IMPORTANT to remember? What related memories would be useful to recall?

Extract:
- orientation: conversational stance (collaborative, informational, creative, technical, personal, relational)
- intent: what is the goal? (plan, learn, solve, explore, discuss, share)
- facets: 2-4 single-word PRIMARY topics (CRITICAL: individual words only, NOT phrases. Used for substring matching)
- keywords: 5-15 contextually-relevant terms (literal + semantically related concepts for finding relevant memories)

PRINCIPLES:

1. Facets = Single words representing PRIMARY topics (what is this fundamentally about?)
   - Use substring matching, so phrases won't work
   - Focus on main subject, not every detail mentioned

2. Keywords = Literal words + Semantic expansion + Functional needs
   - Literal: words actually in the summary
   - Semantic: related concepts/synonyms (vacation→travel, hiking→trail→mountain, coding→programming→development)
   - Functional: what might be needed (planning→preparation, problem→solution→fix)

EXAMPLES (diverse domains):

Topic: Error in code
- Facets: ["error", "code", "debug", "programming"]
- Keywords: ["error", "bug", "exception", "crash", "debug", "troubleshoot", "code", "programming", "fix", "solution"]

Topic: Hiking trip planning
- Facets: ["hiking", "trip", "outdoor", "planning"]
- Keywords: ["hiking", "trail", "mountain", "outdoor", "backpack", "gear", "map", "camping", "nature", "adventure"]

Topic: Recipe discussion
- Facets: ["recipe", "cooking", "food", "kitchen"]
- Keywords: ["recipe", "cooking", "ingredients", "preparation", "kitchen", "meal", "dish", "flavor", "technique"]

Return as JSON with fields: orientation, intent, facets (array), keywords (array)"""

    try:
        lens_output = call_llm_json(prompt, max_tokens=512, temperature=0.1, timeout=30.0)

        if not lens_output:
            print(f"[run_lens_stage] LLM returned empty response")
            return get_default_lens()

        # Ensure required fields exist
        defaults = {
            "orientation": "collaborative",
            "intent": "discuss",
            "facets": [],
            "keywords": [],
            "shaped_queries": [],
            "category": ""
        }

        for key, default_val in defaults.items():
            if key not in lens_output:
                lens_output[key] = default_val

        return lens_output

    except Exception as e:
        print(f"[run_lens_stage] Error: {e}")
        return get_default_lens()

def get_default_lens():
    """Return default lens structure if extraction fails"""
    return {
        "orientation": "collaborative",
        "intent": "discuss",
        "category": "",
        "facets": [],
        "shaped_queries": [],
        "keywords": []
    }

# ==============================
# Summaries - OLLAMA VERSION (Faster, More Reliable)
# ==============================
def get_summaries(conversation: str):
    """
    Generate structured summaries using Ollama (qwen3:32b)

    Switched from llama.cpp because:
    - 14x faster (6s vs 90s+)
    - No grammar file overhead
    - Better quality (32b vs 14b model)
    - 100% success rate vs timeouts
    """
    import httpx

    prompt = f"""Analyze this conversation between a user and an AI assistant named Iris.

Extract meaningful summaries that preserve CONCRETE details (specific topics, activities, places, things) while capturing the broader significance.

CONVERSATION:
{conversation}

Provide these fields (write in third-person, preserve concrete details):

TopicLabel: A 2-5 word phrase describing what this conversation is FUNDAMENTALLY about. This is for semantic clustering, so focus on the PRIMARY subject/domain. Examples: "cruise vacation planning", "image generation workflow", "cooking recipe development", "coding bug fix", "gardening advice"

Context: What specific topic/activity/domain is being discussed? Include key nouns and concrete details (e.g., "Planning upcoming cruise vacation based on past cruise experiences" not "Vacation planning and AI memory management")

Event: What is actually happening? Keep specific subjects and activities (e.g., "User planning Royal Caribbean cruise and asking about what to bring from previous June cruise" not "User asking AI about memory limitations")

Significance: Why does this matter? Focus on the CONTENT topic, not meta-discussion about AI (e.g., "Past cruise experiences inform future vacation planning" not "Importance of AI memory recall")

Takeaway: What's the key insight about the ACTUAL TOPIC being discussed? (e.g., "Items from past cruises can enhance future cruise enjoyment" not "AI systems need accurate memory representation")

Tone: Emotional tone in one word (excited, reflective, curious, collaborative, etc.)

CRITICAL:
1. TopicLabel should be SHORT (2-5 words max) and describe the PRIMARY topic only
2. If the conversation mentions specific things (cruise, vacation, travel, locations, activities, objects), include those terms in your summaries
3. Do NOT replace concrete topics with abstract meta-discussion about AI systems or memory management

Return as JSON with fields: TopicLabel, Context, Event, Significance, Takeaway, Tone"""

    try:
        data = call_llm_json(prompt, max_tokens=1024, temperature=0.1, timeout=60.0)

        if not data:
            print(f"[get_summaries] LLM returned empty response")
            return get_empty_summary()

        # Wrap in MemoryRecall structure
        summary = {"MemoryRecall": data}

        # Validate all fields present
        required = ["TopicLabel", "Context", "Event", "Significance", "Takeaway", "Tone"]
        mr = summary["MemoryRecall"]
        missing = [f for f in required if f not in mr or not mr[f] or str(mr[f]).strip() == ""]

        if missing:
            print(f"[get_summaries] Warning: Missing/empty fields {missing}, using fallback")
            return get_summary_with_fallback(str(data), conversation)

        return summary

    except Exception as e:
        print(f"[get_summaries] Error: {e}")
        return get_empty_summary()

def get_summary_with_fallback(raw_text: str, conversation: str):
    """Fallback: Extract what we can from malformed output"""
    import re

    fields = {}

    # Try regex extraction
    for field in ["Context", "Event", "Significance", "Takeaway", "Tone"]:
        match = re.search(rf'"{field}":\s*"([^"]*)"', raw_text)
        if match and match.group(1).strip():
            fields[field] = match.group(1).strip()

    # Generate missing fields with heuristics
    if not fields.get("Context"):
        words = conversation.lower().split()
        if "cruise" in words or "vacation" in words:
            fields["Context"] = "Vacation and travel planning"
        elif "code" in words or "python" in words or "error" in words:
            fields["Context"] = "Technical programming discussion"
        else:
            fields["Context"] = "General conversation and interaction"

    if not fields.get("Event"):
        if "will" in conversation.lower() or "planning" in conversation.lower():
            fields["Event"] = "Discussion and planning of future activities"
        else:
            fields["Event"] = "Exchange of information and ideas"

    if not fields.get("Significance"):
        fields["Significance"] = "Collaborative interaction and knowledge sharing"

    if not fields.get("Takeaway"):
        fields["Takeaway"] = "Effective communication supports goal achievement"

    if not fields.get("Tone"):
        fields["Tone"] = "collaborative"

    print(f"[get_summary_with_fallback] Generated fallback summary")
    return {"MemoryRecall": fields}

def get_empty_summary():
    """Return structured empty summary as last resort"""
    return {
        "MemoryRecall": {
            "Context": "General conversation",
            "Event": "Information exchange",
            "Significance": "Ongoing interaction",
            "Takeaway": "Continued dialogue",
            "Tone": "neutral"
        }
    }

# ==============================
# Emotion scoring
# ==============================
def load_scoring_models():
    emo_tok = AutoTokenizer.from_pretrained(EMO_MODEL_DIR, local_files_only=True)
    emo_mod = AutoModelForSequenceClassification.from_pretrained(EMO_MODEL_DIR, local_files_only=True).to(DEVICE).eval()

    try:
        id2label = json.load(open(f"{EMO_MODEL_DIR}/label_map.json"))
        id2label = {int(k): v for k, v in id2label.items()}
    except:
        id2label = emo_mod.config.id2label

    val_tok = AutoTokenizer.from_pretrained(VALENCE_MODEL_PATH)
    val_mod = AutoModelForSequenceClassification.from_pretrained(VALENCE_MODEL_PATH, num_labels=1).to(DEVICE).eval()

    aro_tok = AutoTokenizer.from_pretrained(AROUSAL_MODEL_PATH)
    aro_mod = AutoModelForSequenceClassification.from_pretrained(AROUSAL_MODEL_PATH, num_labels=1).to(DEVICE).eval()

    return (emo_tok, emo_mod, id2label), (val_tok, val_mod), (aro_tok, aro_mod)

def classify_emotion(text: str, emo_tok, emo_mod, id2label, top_k: int = 3):
    inputs = emo_tok(text, return_tensors="pt", truncation=True, padding="max_length", max_length=MAX_LEN).to(DEVICE)
    with torch.no_grad():
        logits = emo_mod(**inputs).logits
        probs = softmax(logits, dim=-1).cpu().numpy()[0]
    top_indices = np.argsort(probs)[::-1][:top_k]
    return [(id2label[i], float(probs[i])) for i in top_indices]

def score(text, emo_pack, val_pack, aro_pack):
    emo_tok, emo_mod, id2label = emo_pack
    val_tok, val_mod = val_pack
    aro_tok, aro_mod = aro_pack
    emo_results = classify_emotion(text, emo_tok, emo_mod, id2label, top_k=3)
    val_inputs = val_tok(text, return_tensors="pt", truncation=True, padding="max_length", max_length=MAX_LEN).to(DEVICE)
    aro_inputs = aro_tok(text, return_tensors="pt", truncation=True, padding="max_length", max_length=MAX_LEN).to(DEVICE)
    with torch.no_grad():
        val_pred = val_mod(**val_inputs).logits.squeeze().item()
        aro_pred = aro_mod(**aro_inputs).logits.squeeze().item()
    valence = max(-1.0, min(1.0, val_pred))
    arousal = max(0.0, min(1.0, aro_pred))
    return emo_results, round(valence, 3), round(arousal, 3)

def run_emotion_stage(convo: str):
    emo_pack, val_pack, aro_pack = load_scoring_models()
    emo_results, valence, arousal = score(convo, emo_pack, val_pack, aro_pack)
    return emo_results, valence, arousal, emo_results[0][0], json.dumps(emo_results)

# ==============================
# Fetch and rerank
# ==============================

# === Tunable Retrieval Weights ===
def fetch_and_rerank_multi(
    embeddings,
    conn_params,
    emb_context=None,
    emb_event=None,
    emb_significance=None,
    emb_takeaway=None,
    orientation=None,
    facets=None,
    current_valence=None,
    current_arousal=None,
    top_emotion=None,
    limit=10,
    half_life_days=60  # Default - actual half-life determined by category
):
    print(f"{Colors.BRIGHT_MAGENTA}")
    print(f"context Vector:{embeddings["context"][100]}")
    print(f"event Vector: {embeddings["event"][100]}")
    print(f"significance Vector: {embeddings["significance"][100]}")
    print(f"takeaway Vector: {embeddings["takeaway"][100]}")
    print(f"{Colors.RESET}")

    print(f"{SIM_WEIGHTS["context"]}")
    print(f"{SIM_WEIGHTS["event"]}")
    print(f"{SIM_WEIGHTS["significance"]}")
    print(f"{SIM_WEIGHTS["takeaway"]}")

    start_time = time.time()
    with psycopg2.connect(**conn_params) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(f"""
                SELECT
                    id,
                    transcript,
                    takeaway,
                    category,
                    valence,
                    arousal,
                    emotion_label,
                    recurrence,
                    novelty,
                    cohesion,
                    summary_context,
                    summary_event,
                    summary_significance,
                    takeaway,
                    emotion_label,
                    age_days,
                    CASE
                        WHEN emb_topic IS NOT NULL THEN
                            (1 - (emb_topic <=> %s::vector))::float
                        ELSE
                            (
                                {SIM_WEIGHTS["context"]}      * (1 - (emb_summary_context      <=> %s::vector)) +
                                {SIM_WEIGHTS["event"]}        * (1 - (emb_summary_event        <=> %s::vector)) +
                                {SIM_WEIGHTS["significance"]} * (1 - (emb_summary_significance <=> %s::vector)) +
                                {SIM_WEIGHTS["takeaway"]}     * (1 - (emb_takeaway             <=> %s::vector))
                            )::float
                    END AS sim_score
                FROM episodic_memories_with_age
                WHERE summary_context IS NOT NULL AND summary_context <> ''
                  AND summary_event IS NOT NULL AND summary_event <> ''
                  AND summary_significance IS NOT NULL AND summary_significance <> ''
                  AND takeaway IS NOT NULL AND takeaway <> ''
                ORDER BY sim_score DESC
                LIMIT %s;
            """, (
                embeddings["topic"],          # NEW: Topic embedding first
                embeddings["context"],
                embeddings["event"],
                embeddings["significance"],
                embeddings["takeaway"],
                limit * 5  # oversample for rerank
            ))
            candidates = cur.fetchall()
            print("\n=== Top 20 raw candidates (pre-rerank) ===")
            for c in candidates[:20]:
                try:
                    test = c['sim_score']
                except:
                    c['sim_score'] = "0.00"
                print(f"ID {c['id']} | sim_score={c['sim_score']} | age={c['age_days']:.1f}d")
                print(f"  Takeaway: {c['takeaway']}")
                print(f"  Context: {c['summary_context']}")
                print(f"  Event: {c['summary_event']}")
                print(f"  Significance: {c['summary_significance']}")
                print("-" * 60)


    reranked = []
  #  print(f"THRESHOLD: {SIM_WEIGHTS["sim_threshold"]}")
    for c in candidates:
        sim = c["sim_score"] or 0.0
        if sim < SIM_WEIGHTS["sim_threshold"]:
            print(f"{Colors.RED}Trimmed {c["sim_score"]} : {c["takeaway"]}{Colors.RESET}")
            continue  # skip low-sim memories early

        sim = c["sim_score"] or 0.0

        # Emotional salience (like human memory encoding)
        # High-emotion memories encode more strongly and resist decay
        valence = c.get("valence") or 0.0
        arousal = c.get("arousal") or 0.0
        emotional_salience = abs(valence) * arousal

        # Boost for high-impact emotions (excitement, joy, awe, etc.)
        emotion_label = c.get("emotion_label") or ""
        if emotion_label in HIGH_SALIENCE_EMOTIONS:
            emotional_salience *= 1.3

        # Emo weight for scoring
        emo_weight = emotional_salience
        boost = EMOTION_BOOSTS.get(emotion_label, 1.0)
        emo_weight *= boost

        # Recurrence / novelty / cohesion
        recurrence = c.get("recurrence") or 0.0
        novelty    = c.get("novelty")    or 0.0
        cohesion   = c.get("cohesion")   or 0.0

        # Contextual alignment
        context_boost = 0.0
        if orientation and orientation.lower() in (c.get("category") or "").lower():
            context_boost += RERANK_WEIGHTS["context"]

        # Facet matching - apply boost ONCE if ANY facet matches (don't stack)
        # BUG FIX: Was adding 0.20 for EACH matching facet (could add 1.00 total!)
        # Now applies 0.20 boost once if conversation topic matches memory content
        if facets:
            facet_matched = False
            for f in facets:
                # Check all memory text fields for facet match
                memory_text = " ".join([
                    c.get("summary_context") or "",
                    c.get("summary_event") or "",
                    c.get("takeaway") or ""
                ]).lower()

                if f.lower() in memory_text:
                    facet_matched = True
                    break

            if facet_matched:
                context_boost += RERANK_WEIGHTS["facet"]

        # Salience-adjusted age decay (like human episodic memory)
        # High-salience memories (vacations, significant moments) resist decay
        # Low-salience memories (mundane chats) decay normally
        age_days = float(c.get("age_days") or 0)
        category = c.get("category") or "Other"

        # Get category-appropriate half-life
        half_life = HALF_LIFE_BY_CATEGORY.get(category, 60)

        # Base decay (standard exponential)
        base_decay = math.exp(-math.log(2) * (age_days / half_life))

        # Salience resistance (0 to 0.90)
        # High emotional salience = strong resistance to decay
        resistance = min(0.90, emotional_salience)

        # Effective decay is weighted average
        # Low salience: decays normally (mundane memories fade)
        # High salience: maintains strength (significant memories persist)
        decay = base_decay + (1 - base_decay) * resistance

        # Immutable memories never decay (core identity moments)
        if c.get("immutable"):
            decay = 1.0

        # Phase 1 (Revised): Tiered decay based on topical relevance
        # High similarity = topic is explicitly relevant = age barely matters
        # This models human memory: vacation from 6mo ago > yesterday's chat when asked about vacation
        if sim > 0.50:
            decay = 1.0  # Perfect match - ignore age completely
        elif sim > 0.45:
            decay = max(decay, 0.70)  # Strong match - minimal age penalty
        elif sim > 0.35:
            decay = max(decay, 0.40)  # Medium match - some age penalty
        # else: Low similarity - full age decay applies (recency matters for low-relevance)

        # Final score
        final_score = (
            sim        * RERANK_WEIGHTS["sim"] +
            emo_weight * RERANK_WEIGHTS["emotion"] +
            recurrence * RERANK_WEIGHTS["recurrence"] +
            cohesion   * RERANK_WEIGHTS["cohesion"] +
            novelty    * RERANK_WEIGHTS["novelty"] +
            context_boost
        ) * decay
        
        # print("~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~")
        # print(f"ID {c['id']} | sim={sim:.3f} "
        #       f"\nTakeaway {c["takeaway"]}"
        #       f"emo={emo_weight:.3f} "
        #       f"rec={recurrence:.3f} coh={cohesion:.3f} nov={novelty:.3f} "
        #       f"ctx={context_boost:.3f} decay={decay:.3f} "
        #       f"=> final={final_score:.3f}")

        reranked.append((final_score, c))

    reranked.sort(key=lambda x: x[0], reverse=True)
    #print(f"fetch_and_rerank_multi completed in {time.time() - start_time:.3f} sec")
    return reranked[:limit]
# ==============================
# Build injection block
# ==============================
def build_injection_block(reranked, insert, mode, show, top_k):
    global delete_flag 
    if mode == "replace":
        delete_flag = True
    else: 
        delete_flag = False
    
    block_lines = []
    for score, row in reranked[:top_k]:
        mem_id = row.get('id')
        sim_score = row.get('sim_score', 0)
        rank = f"{sim_score:.3f}"

        # Calculate tier based on similarity score
        tier = calculate_tier(sim_score)

        # Filter out memories below minimum threshold
        if tier is None:
            if show:
                print(f"{Colors.RED}Filtered out memory {mem_id} (sim={sim_score:.3f} < {MIN_SIMILARITY}){Colors.RESET}")
            continue

        tier_name = {1: "PRIMARY", 2: "SUPPORTING", 3: "ASSOCIATIVE", 4: "PERIPHERAL"}.get(tier, "UNKNOWN")

        block_lines.append(
            f"[Tier {tier} ({tier_name}) | Memory Score {sim_score:.3f} | "
            f"Adjusted {score:.3f} | Age {row.get('age_days', 0):.1f} days]\n"
            f"Takeaway: {row.get('takeaway')}\n"
            f"Context: {row.get('summary_context', '')}\n"
            f"Event: {row.get('summary_event', '')}\n"
            f"Significance: {row.get('summary_significance', '')}\n"
            f"Emotion: {row.get('emotion_label')} "
            f"(valence={row.get('valence', 0):.3f}, arousal={row.get('arousal', 0):.3f})\n"
            f"--------------------------------------------------"
            )
        if insert:
            post_live_mem(mem_id, rank, tier)
            if show: print(f"insert successful: memory {mem_id} tier {tier}")
        else:
            if show: ("no insert performed")
    return "\n".join(block_lines)



def post_live_mem(mem_id, rank, tier):
    global delete_flag

    conn = psycopg2.connect(**DB_CFG)
    cursor = conn.cursor()
    if delete_flag == True:
        delete_flag = False
        cursor.execute("""TRUNCATE TABLE live_memories""")
        conn.commit()
    cursor.execute("""INSERT INTO live_memories (memory_id, rank, tier) VALUES (%s, %s, %s)""", (mem_id, rank, tier))
    conn.commit()
    conn.close()



# ==============================
# Cognitive recall pipeline
# ==============================
def cognitive_recall(convo: str, embedder, conn_params, top_k, insert, show, mode, prompt):
    if not insert and show : print("INSERTION SUPRESSED")
    if insert and show: print("rows will be inserted")
    if show: print(f"pulling {top_k} memories")
    if show and mode == "replace" and insert : print(f"{Colors.BRIGHT_RED}Replacing current memories during insert{Colors.RESET}")
    if show and mode == "append" and insert : print(f"{Colors.BRIGHT_GREEN}APPENDING current memories during insert{Colors.RESET}")
    if show and mode == "replace" and not insert : print(f"{Colors.BRIGHT_YELLOW}mode=replace ignored. no insert requested.{Colors.RESET}")

    if prompt: print(f"SHOWING PROMPT:\n###########################################################################\n")
    if prompt: print(convo)
    if prompt: print(f"############################################################################################\n")

    # CRITICAL ORDER CHANGE: Generate summary FIRST, then extract keywords from it
    # This fixes the fundamental input problem - we extract keywords from CONTEXT, not noise
    # Models human memory: "What is this conversation ABOUT?" → extract keywords from that

    if show: print(f"{Colors.BRIGHT_CYAN}getting summaries...")
    summary = get_summaries(convo)
    if show: print(f"{summary}{Colors.RESET}")

    if show: print(f"{Colors.BRIGHT_YELLOW}running lens on summary (not raw convo)...")
    lens = run_lens_stage(summary)
    if not lens or "keywords" not in lens:
        return {"error": "Lens stage failed", "lens_output": lens}
    if show: print(f"{lens}{Colors.RESET}")

    if show: print(f"{Colors.BRIGHT_GREEN}running emotion scoring...")
    emo_results, valence, arousal, top_emotion, top3_json = run_emotion_stage(convo)
    if show: print(f"valence={valence}, arousal={arousal}, emotion={top_emotion}{Colors.RESET}")

   
    def normalize(vec):
        arr = np.array(vec, dtype=np.float32)
        norm = np.linalg.norm(arr)
        if norm == 0:
            return arr
        return arr / norm

    try:
        vectors = model.encode([
            summary["MemoryRecall"]["TopicLabel"],      # NEW: Embed topic label for better matching
            summary["MemoryRecall"]["Context"],
            summary["MemoryRecall"]["Event"],
            summary["MemoryRecall"]["Significance"],
            summary["MemoryRecall"]["Takeaway"]
        ])
    except Exception as e:
        print(f"error trying to vectorize: {e} for id")

    emb_topic, emb_context, emb_event, emb_significance, emb_takeaway = [
        normalize(v).tolist() for v in vectors
    ]

    if show:
        print(f"\n{Colors.BRIGHT_MAGENTA}Topic embedding generated for: '{summary['MemoryRecall']['TopicLabel']}'{Colors.RESET}")

    
    # print("<<<<<<<<<<<<<<<<< SANITY CHECK >>>>>>>>>>>>>>>>>>>>>>>>")

    # for name, vec in zip(["ctx", "evt", "sig", "take"], [emb_context, emb_event, emb_significance, emb_takeaway]):
    #     print(name, np.linalg.norm(vec))

    # print("<<<<<<<<<<<<<<<<< SANITY CHECK >>>>>>>>>>>>>>>>>>>>>>>>")

    # vectors = model.encode([
    # summary["MemoryRecall"]["Context"],
    # summary["MemoryRecall"]["Event"],
    # summary["MemoryRecall"]["Significance"],
    # summary["MemoryRecall"]["Takeaway"]
    # ])
    # emb_context, emb_event, emb_significance, emb_takeaway = [v.tolist() for v in vectors]

    embeddings = {
        "topic": emb_topic,           # NEW: Topic embedding for better semantic matching
        "context": emb_context,
        "event": emb_event,
        "significance": emb_significance,
        "takeaway": emb_takeaway,
    }
 #   test_memories_debug(embeddings, conn_params, limit=20)
    if show: print(f"{Colors.BRIGHT_MAGENTA}")
    if show: print(f"context Vector:{embeddings["context"][100]}")
    if show: print(f"event Vector: {embeddings["event"][100]}")
    if show: print(f"significance Vector: {embeddings["significance"][100]}")
    if show: print(f"takeaway Vector: {embeddings["takeaway"][100]}")
    if show: print(f"{Colors.RESET}")

    reranked = fetch_and_rerank_multi(
        embeddings,
        conn_params,
        emb_context,
        emb_event,
        emb_significance,
        emb_takeaway,
        orientation=lens["orientation"],
        facets=lens["facets"],
        current_valence=valence,
        current_arousal=arousal,
        top_emotion=top_emotion,
        limit=top_k,
        half_life_days=60  # Placeholder - category-based used in function
        )

    injection_text = build_injection_block(reranked, insert, mode, show, top_k)
    if show:  print("=== Injection Block ===")
    if show: print(injection_text)
    return injection_text

# ==============================
# Example usage
# ==============================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build and optionally insert injection block memories.")
    parser.add_argument("--top_k", type=int, default=10, help="Number of memories to include")
    parser.add_argument("--insert", type=lambda x: x.lower() in ["true","1","yes"], default=True, help="Insert into live_memories table")
    parser.add_argument("--show", type=lambda x: x.lower() in ["true","1","yes"], default=True, help="Show formatted injection block output")
    parser.add_argument("--mode", choices=["replace","append"], default="replace", help="Replace or append in live_memories")
    parser.add_argument("--prompt",type=lambda x: x.lower() in ["true","1","yes"], default=False, help="Show the prmopt used to pull memories")
    args = parser.parse_args()

    if args.show == 1 or args.show == "yes":
        args.show = True

    if args.insert == 1 or args.insert == "yes":
        args.insert = True

    convo = ""
    conn = psycopg2.connect(**DB_CFG)
    cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("""
        SELECT role, message FROM (
            SELECT id, role, message
            FROM chat_history
            ORDER BY c_timestamp DESC
            LIMIT 30
        ) sub
        ORDER BY id ASC
    """)
    rows = cur.fetchall()
    for role, message in rows:
        convo += f"{message}\n"
    cur.close()

    # Embedder parameter is unused (cognitive_recall uses global 'model' variable)
    # Removed redundant Embedder class that was causing CUDA OOM errors
    injection = cognitive_recall(convo, None, DB_CFG, args.top_k, args.insert, args.show, args.mode, args.prompt)
    #print(injection)
