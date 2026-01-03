# This script is triggered by the postgresql function python_memory_trigger()
# by default it fires every once for every 10 new transactions created in chat_history.
# do not alter this file!



import psycopg2
from psycopg2.extras import DictCursor
import json
import torch
from llama_cpp import Llama, LlamaGrammar
from sentence_transformers import SentenceTransformer
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from Colors import Colors
from torch.nn.functional import softmax
import numpy as np
import requests
import math
import time
import argparse
from sentence_transformers import SentenceTransformer
import os

# ==============================
# Database config
# ==============================
DB_CFG = dict(dbname="irisdb", user="irisuser", password="yourpassword", host="localhost", port=5432)
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
DEVICE = "cuda:0" if torch.cuda.is_available() else "cpu"


import os
from sentence_transformers import SentenceTransformer
# Force offline mode
os.environ["HF_HUB_OFFLINE"] = "1"

# Load from local folder
model = SentenceTransformer("/models/llm_models/huggingface/models/all-mpnet-base-v2/", local_files_only=True)

# model = SentenceTransformer("all-mpnet-base-v2")


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
# FIXED: Normalized to sum to 1.00 (was 1.15)
RERANK_WEIGHTS = {
    "sim":        0.45,   # similarity score (45%)
    "emotion":    0.10,   # valence*arousal, scaled (10%)
    "recurrence": 0.10,   # how often referenced (10%)
    "cohesion":   0.05,   # narrative coherence (5%)
    "novelty":    0.05,   # uniqueness (5%)
    "context":    0.15,   # category match (15%)
    "facet":      0.10,   # facet match (10%)
}  # Total = 1.00 (100%)

# Boost multiplier for select emotions
EMOTION_BOOSTS = {
    "admiration": 1.1,
    "excitement": 1.1,
    "approval":   1.1,
}
# Memory decay control
HALF_LIFE_DAYS = 30
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


def test_memories_debug(embeddings, conn_params, limit=20):
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
# Lens stage
# ==============================
def run_lens_stage(convo: str):
    safe_convo = json.dumps(convo)
    prompt = f"""
    You are analyzing a conversation to extract its conceptual structure.  
    Produce a JSON object with: orientation, intent, facets, shaped_queries, keywords.
    {safe_convo}
        """

    payload = {
        "prompt": f"<start_of_turn>user\n{prompt}<end_of_turn>user\n<start_of_turn>mode]\n",
        "max_tokens": 256,
        "temperature": 0.1,
        "grammar_file": "/iris-v3/backend/memory/lens_grammar_new.gbnf"
    }

    response = requests.post("http://127.0.0.1:9600/v1/completions", json=payload)
    if response.status_code != 200:
        print("❌ API error:", response.text)
        return None

    try:
        content = response.json()["choices"][0]["text"].strip()
        return json.loads(content)
    except Exception as e:
        print("❌ Failed to parse lens response:", e, response.text)
        return None

# ==============================
# Summaries
# ==============================
def get_summaries(prompt):
    payload = {
        "prompt": prompt,
        "max_tokens": 512,
        "temperature": 0.1,
        "grammar_file": "/iris-v3/backend/memory/diagnostics/summary_fixed.gbnf"
    }
    response = requests.post("http://127.0.0.1:9600/v1/completions", json=payload)
    raw_text = response.json()["choices"][0]["text"].strip()

    # Try direct parsing first
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError as e:
        print(f"[get_summaries] JSON parse failed: {str(e)[:100]}")
        print(f"[get_summaries] Raw text (first 200 chars): {raw_text[:200]}")

        # Try to find JSON object boundaries
        # Look for the outermost { }
        start_idx = raw_text.find('{')
        if start_idx == -1:
            print("[get_summaries] No opening brace found, returning empty dict")
            return {"MemoryRecall": {"Takeaway": "", "Context": "", "Event": "", "Significance": "", "Tone": ""}}

        # Find matching closing brace
        brace_count = 0
        end_idx = -1
        for i in range(start_idx, len(raw_text)):
            if raw_text[i] == '{':
                brace_count += 1
            elif raw_text[i] == '}':
                brace_count -= 1
                if brace_count == 0:
                    end_idx = i + 1
                    break

        if end_idx == -1:
            # No matching brace found, take everything and add closing brace
            cleaned = raw_text[start_idx:] + "}"
        else:
            cleaned = raw_text[start_idx:end_idx]

        # Try parsing cleaned version
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e2:
            print(f"[get_summaries] Cleaned parse also failed: {str(e2)[:100]}")
            print(f"[get_summaries] Cleaned text: {cleaned[:200]}")
            # Return empty structure to avoid crashing
            return {"MemoryRecall": {"Takeaway": "", "Context": "", "Event": "", "Significance": "", "Tone": ""}}

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
    half_life_days=HALF_LIFE_DAYS
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
                    (
                        {SIM_WEIGHTS["context"]}      * (1 - (emb_summary_context      <=> %s::vector)) +
                        {SIM_WEIGHTS["event"]}        * (1 - (emb_summary_event        <=> %s::vector)) +
                        {SIM_WEIGHTS["significance"]} * (1 - (emb_summary_significance <=> %s::vector)) +
                        {SIM_WEIGHTS["takeaway"]}     * (1 - (emb_takeaway             <=> %s::vector))
                    ) AS sim_score
                FROM episodic_memories_with_age
                WHERE summary_context IS NOT NULL AND summary_context <> ''
                  AND summary_event IS NOT NULL AND summary_event <> ''
                  AND summary_significance IS NOT NULL AND summary_significance <> ''
                  AND takeaway IS NOT NULL AND takeaway <> ''
                ORDER BY sim_score DESC
                LIMIT %s;
            """, (
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

        # Emotional salience
        # FIXED: Use abs(valence) to avoid negative weights for negative emotions
        emo_weight = abs(c["valence"] or 0.0) * (c["arousal"] or 0.0)
        boost = EMOTION_BOOSTS.get(c.get("emotion_label"), 1.0)
        emo_weight *= boost

        # Recurrence / novelty / cohesion
        recurrence = c.get("recurrence") or 0.0
        novelty    = c.get("novelty")    or 0.0
        cohesion   = c.get("cohesion")   or 0.0

        # Contextual alignment
        context_boost = 0.0
        if orientation and orientation.lower() in (c.get("category") or "").lower():
            context_boost += RERANK_WEIGHTS["context"]
        if facets:
            for f in facets:
                if f.lower() in (c.get("summary_context") or "").lower():
                    context_boost += RERANK_WEIGHTS["facet"]

        # Age decay (half-life)
        age_days = float(c.get("age_days") or 0)
        decay = math.exp(-math.log(2) * (age_days / half_life_days))

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
        rank = (f"{row.get('sim_score', 0):.3f}")
        block_lines.append(
            f"[Memory Score {row.get('sim_score', 0):.3f} | "
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
            post_live_mem(mem_id, rank)
            if show: print(f"insert successfull {insert}")
        else:
            if show: ("no insert performed")
    return "\n".join(block_lines)



def post_live_mem(mem_id, rank):
    global delete_flag

    conn = psycopg2.connect(**DB_CFG)
    cursor = conn.cursor()
    if delete_flag == True:
        delete_flag = False
        cursor.execute("""TRUNCATE TABLE live_memories""")
        conn.commit()
    cursor.execute("""INSERT INTO live_memories (memory_id, rank) VALUES (%s, %s)""", (mem_id, rank))  # Note the comma
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


    if show: print(f"{Colors.BRIGHT_YELLOW}running lens...")
    lens = run_lens_stage(convo)
    if not lens or "keywords" not in lens:
        return {"error": "Lens stage failed", "lens_output": lens}
    if show: print(f"{lens}{Colors.RESET}")

    if show: print(f"{Colors.BRIGHT_GREEN}running emotion scoring...")
    emo_results, valence, arousal, top_emotion, top3_json = run_emotion_stage(convo)
    if show: print(f"valence={valence}, arousal={arousal}, emotion={top_emotion}{Colors.RESET}")

    if show: print(f"{Colors.BRIGHT_CYAN}getting summaries...")
    summary = get_summaries(convo)
    if show: print(f"{summary}{Colors.RESET}")

   
    def normalize(vec):
        arr = np.array(vec, dtype=np.float32)
        norm = np.linalg.norm(arr)
        if norm == 0:
            return arr
        return arr / norm

    try:
        vectors = model.encode([
            summary["MemoryRecall"]["Context"],
            summary["MemoryRecall"]["Event"],
            summary["MemoryRecall"]["Significance"],
            summary["MemoryRecall"]["Takeaway"]
        ])
    except Exception as e:
        print(f"error trying to vectorize: {e} for id")

    emb_context, emb_event, emb_significance, emb_takeaway = [
        normalize(v).tolist() for v in vectors
    ]

    
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
        half_life_days=HALF_LIFE_DAYS
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
            LIMIT 15
        ) sub
        ORDER BY id ASC
    """)
    rows = cur.fetchall()
    for role, message in rows:
        convo += f"{message}\n"
    cur.close()

    class Embedder:
        def __init__(self, model_name="all-mpnet-base-v2"):
            self.model = SentenceTransformer(model_name)
        def embed(self, text: str):
            return self.model.encode(text, normalize_embeddings=True).tolist()

    embedder = Embedder("all-mpnet-base-v2")
    injection = cognitive_recall(convo, embedder, DB_CFG, args.top_k, args.insert, args.show, args.mode, args.prompt)
    #print(injection)
