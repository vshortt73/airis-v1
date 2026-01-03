#!/usr/bin/env python3
"""
Iris Memory Retrieval v2 - Fixed Summary Generation

Key changes from original:
1. Improved summary prompt with explicit examples
2. Expanded grammar character set
3. Better fallback parsing
4. Temporal bridging in summaries
"""

# Copy entire original file first, then modify specific sections
import sys
sys.path.insert(0, '/iris-v3/backend/memory')

# Import original as base
with open('/iris-v3/backend/memory/iris_memory_retrieval.py', 'r') as f:
    original_code = f.read()

# Execute to get all functions
exec(original_code.replace('if __name__ == "__main__":', 'if False:'))

# Now override the broken function
def get_summaries_improved(conversation: str):
    """
    IMPROVED summary generation with explicit, example-driven prompt

    Key improvements:
    - Examples showing GOOD summaries (abstract, third-person)
    - Examples showing BAD summaries (literal, conversational)
    - Explicit temporal bridging guidance
    - Field-by-field instructions
    """

    prompt = f"""You are extracting structured summaries from a conversation between a user and an AI assistant named Iris.

CRITICAL INSTRUCTIONS:
1. Write in third-person perspective (NOT "I" or conversational)
2. Be ABSTRACT and CONCEPTUAL (not literal quotes)
3. Bridge temporal gaps (if discussing future, consider past context)
4. Each field should be 1-2 concise sentences
5. ALL fields must be filled (no empty strings)

EXAMPLE 1 - Planning Activity (like current conversation):

Conversation: "Let's go to Hawaii next month! What did we do last time we were there?"

GOOD OUTPUT:
{{
  "MemoryRecall": {{
    "Context": "Vacation planning and leveraging past travel experiences",
    "Event": "Discussion of upcoming trip with reflection on previous visit to same destination",
    "Significance": "Using experiential knowledge to inform future planning and decision-making",
    "Takeaway": "Past travel experiences shape expectations and preparations for future trips",
    "Tone": "excited"
  }}
}}

BAD OUTPUT (don't do this):
{{
  "MemoryRecall": {{
    "Context": "",
    "Event": "",
    "Significance": "",
    "Takeaway": "The user wants to go to Hawaii but I don't remember the last trip",
    "Tone": "confused"
  }}
}}

EXAMPLE 2 - Technical Discussion:

Conversation: "I'm getting an error with async/await in Python. Can you help debug this httpx issue?"

GOOD OUTPUT:
{{
  "MemoryRecall": {{
    "Context": "Python programming and asynchronous code troubleshooting",
    "Event": "Technical debugging session focused on async library compatibility",
    "Significance": "Resolving async/await issues improves application performance and code quality",
    "Takeaway": "Async-compatible libraries are essential for non-blocking Python applications",
    "Tone": "problem-solving"
  }}
}}

NOW ANALYZE THIS CONVERSATION:

{conversation}

REMEMBER:
- Context: What general topic/domain? (e.g., "Vacation planning" NOT "User scheduled cruise")
- Event: What's happening conceptually? (e.g., "Applying past experiences to future planning" NOT "User asks about last cruise")
- Significance: Why does this matter? (e.g., "Experiential learning improves outcomes" NOT "User wants help")
- Takeaway: Key insight? (e.g., "Past informs future" NOT "I don't have that information")
- Tone: One word emotional tone (excited, reflective, curious, etc.)

Return ONLY valid JSON in the MemoryRecall format:"""

    payload = {
        "prompt": prompt,
        "max_tokens": 600,  # Increased from 512
        "temperature": 0.1,
        "grammar_file": "/iris-v3/backend/memory/diagnostics/summary_fixed.gbnf"  # Uses expanded grammar
    }

    try:
        response = requests.post("http://127.0.0.1:9600/v1/completions", json=payload, timeout=90)

        if response.status_code != 200:
            print(f"[get_summaries_improved] HTTP error: {response.status_code}")
            return get_empty_summary()

        raw_text = response.json()["choices"][0]["text"].strip()

        # Try direct parse
        try:
            summary = json.loads(raw_text)

            # Validate all fields are populated
            mr = summary.get("MemoryRecall", {})
            required = ["Context", "Event", "Significance", "Takeaway", "Tone"]

            missing_or_empty = [f for f in required if not mr.get(f) or mr.get(f).strip() == ""]

            if missing_or_empty:
                print(f"[get_summaries_improved] Warning: Empty fields {missing_or_empty}, using fallback")
                return get_summary_with_fallback(raw_text, conversation)

            return summary

        except json.JSONDecodeError as e:
            print(f"[get_summaries_improved] JSON parse failed: {e}")
            return get_summary_with_fallback(raw_text, conversation)

    except requests.Timeout:
        print(f"[get_summaries_improved] Timeout after 90s")
        return get_empty_summary()
    except Exception as e:
        print(f"[get_summaries_improved] Error: {e}")
        return get_empty_summary()

def get_summary_with_fallback(raw_text: str, conversation: str):
    """
    Fallback: Extract what we can from malformed output, generate missing fields
    """
    import re

    fields = {}

    # Try regex extraction
    for field in ["Context", "Event", "Significance", "Takeaway", "Tone"]:
        match = re.search(f'"{field}":\s*"([^"]*)"', raw_text)
        if match and match.group(1).strip():
            fields[field] = match.group(1).strip()

    # Generate missing fields with simple heuristics
    if not fields.get("Context"):
        # Extract key nouns from conversation
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

# Replace the original function
get_summaries = get_summaries_improved

# Run if called directly
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--top_k", type=int, default=10)
    parser.add_argument("--insert", type=lambda x: x.lower() in ["true","1","yes"], default=True)
    parser.add_argument("--show", type=lambda x: x.lower() in ["true","1","yes"], default=True)
    parser.add_argument("--mode", choices=["replace","append"], default="replace")
    parser.add_argument("--prompt", type=lambda x: x.lower() in ["true","1","yes"], default=False)
    args = parser.parse_args()

    # Get conversation
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
        convo += f"{message}\\n"
    cur.close()
    conn.close()

    # Run retrieval
    class Embedder:
        def __init__(self):
            self.model = SentenceTransformer("/models/llm_models/huggingface/models/all-mpnet-base-v2/", local_files_only=True)
        def embed(self, text: str):
            return self.model.encode(text, normalize_embeddings=True).tolist()

    embedder = Embedder()
    injection = cognitive_recall(convo, embedder, DB_CFG, args.top_k, args.insert, args.show, args.mode, args.prompt)
