#!/usr/bin/env python3
"""
Compare Summary Generation: llama.cpp vs Ollama

This will test both approaches with the same conversation
and show which produces better results.
"""

import sys
sys.path.insert(0, '/iris-v3/backend/memory')

import psycopg2
from psycopg2.extras import DictCursor
import json
import requests
import httpx
from sentence_transformers import SentenceTransformer
import numpy as np
import time

DB_CFG = dict(dbname="irisdb", user="irisuser", password="yourpassword", host="localhost", port=5432)

class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

def get_conversation():
    """Get current conversation"""
    conn = psycopg2.connect(**DB_CFG)
    cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("""
        SELECT role, message FROM (
            SELECT id, role, message
            FROM chat_history
            ORDER BY c_timestamp DESC
            LIMIT 10
        ) sub
        ORDER BY id ASC
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    return "\n".join([f"{row['role'].upper()}: {row['message']}" for row in rows])

def test_llama_cpp_improved(conversation):
    """Test llama.cpp with IMPROVED prompt"""

    print(f"{Colors.HEADER}{'='*70}")
    print("TEST 1: llama.cpp with IMPROVED PROMPT")
    print(f"{'='*70}{Colors.RESET}\n")

    prompt = f"""You are extracting structured summaries from a conversation between a user and an AI assistant named Iris.

CRITICAL INSTRUCTIONS:
1. Write in third-person perspective (NOT "I" or conversational)
2. Be ABSTRACT and CONCEPTUAL (not literal quotes)
3. Bridge temporal gaps (if discussing future, consider past context)
4. Each field should be 1-2 concise sentences
5. ALL fields must be filled (no empty strings)

EXAMPLE - Planning Activity:
Conversation: "Let's go to Hawaii! What did we do last time?"
Good Output:
{{
  "MemoryRecall": {{
    "Context": "Vacation planning and leveraging past travel experiences",
    "Event": "Discussion of upcoming trip with reflection on previous visit to same destination",
    "Significance": "Using experiential knowledge to inform future planning and decision-making",
    "Takeaway": "Past travel experiences shape expectations and preparations for future trips",
    "Tone": "excited"
  }}
}}

NOW ANALYZE THIS CONVERSATION:
{conversation}

Return ONLY valid JSON:"""

    start = time.time()

    try:
        response = requests.post("http://127.0.0.1:9600/v1/completions", json={
            "prompt": prompt,
            "max_tokens": 600,
            "temperature": 0.1,
            "grammar_file": "/iris-v3/backend/memory/diagnostics/summary_fixed.gbnf"
        }, timeout=90)

        elapsed = time.time() - start

        if response.status_code != 200:
            print(f"{Colors.RED}✗ HTTP Error: {response.status_code}{Colors.RESET}")
            return None, elapsed

        raw_text = response.json()["choices"][0]["text"].strip()

        print(f"{Colors.CYAN}Raw output:{Colors.RESET}")
        print(raw_text[:500])
        print()

        try:
            summary = json.loads(raw_text)
            mr = summary.get("MemoryRecall", {})

            # Check field population
            empty = [k for k, v in mr.items() if not v or v.strip() == ""]

            print(f"{Colors.GREEN}✓ Valid JSON{Colors.RESET}")
            print(f"Time: {elapsed:.2f}s")

            if empty:
                print(f"{Colors.YELLOW}⚠ Empty fields: {empty}{Colors.RESET}")
            else:
                print(f"{Colors.GREEN}✓ All fields populated{Colors.RESET}")

            # Print summary
            print(f"\n{Colors.BOLD}Summary:{Colors.RESET}")
            for field, value in mr.items():
                status = "✓" if value and value.strip() else "✗"
                color = Colors.GREEN if value and value.strip() else Colors.RED
                print(f"{color}{status} {field}: {value}{Colors.RESET}")

            return summary, elapsed

        except json.JSONDecodeError as e:
            print(f"{Colors.RED}✗ Invalid JSON: {e}{Colors.RESET}")
            return None, elapsed

    except requests.Timeout:
        print(f"{Colors.RED}✗ Timeout after 90s{Colors.RESET}")
        return None, 90
    except Exception as e:
        print(f"{Colors.RED}✗ Error: {e}{Colors.RESET}")
        return None, time.time() - start

def test_ollama(conversation):
    """Test Ollama with JSON mode"""

    print(f"\n{Colors.HEADER}{'='*70}")
    print("TEST 2: Ollama with JSON MODE")
    print(f"{'='*70}{Colors.RESET}\n")

    prompt = f"""Analyze this conversation between a user and an AI assistant named Iris.

Extract ABSTRACT, CONCEPTUAL summaries (not literal quotes).

CONVERSATION:
{conversation}

Provide these fields (write in third-person, be conceptual):

Context: What is the general topic/domain being discussed? (e.g., "Vacation planning" not "User scheduled a cruise")

Event: What is happening conceptually? (e.g., "Reflecting on past experiences to inform future planning" not "User asks about last cruise")

Significance: Why does this conversation matter? (e.g., "Experiential learning improves decision-making" not "User wants help")

Takeaway: What's the key insight? (e.g., "Past experiences inform future planning" not "I don't remember the last cruise")

Tone: Emotional tone in one word (excited, reflective, curious, collaborative, etc.)

Return as JSON with fields: Context, Event, Significance, Takeaway, Tone"""

    start = time.time()

    try:
        response = httpx.post(
            "http://localhost:11434/api/generate",
            json={
                "model": "qwen3:32b",
                "prompt": prompt,
                "stream": False,
                "format": "json",  # Ollama's JSON mode
                "options": {
                    "temperature": 0.1,
                    "num_ctx": 8192
                }
            },
            timeout=90.0
        )

        elapsed = time.time() - start

        if response.status_code != 200:
            print(f"{Colors.RED}✗ HTTP Error: {response.status_code}{Colors.RESET}")
            return None, elapsed

        result = response.json()
        raw_text = result["response"]

        print(f"{Colors.CYAN}Raw output:{Colors.RESET}")
        print(raw_text[:500])
        print()

        try:
            # Ollama returns flat JSON, need to wrap it
            data = json.loads(raw_text)

            # Wrap in MemoryRecall structure
            summary = {"MemoryRecall": data}

            mr = summary["MemoryRecall"]

            # Check field population
            required = ["Context", "Event", "Significance", "Takeaway", "Tone"]
            empty = [f for f in required if f not in mr or not mr[f] or mr[f].strip() == ""]

            print(f"{Colors.GREEN}✓ Valid JSON{Colors.RESET}")
            print(f"Time: {elapsed:.2f}s")

            if empty:
                print(f"{Colors.YELLOW}⚠ Empty/missing fields: {empty}{Colors.RESET}")
            else:
                print(f"{Colors.GREEN}✓ All fields populated{Colors.RESET}")

            # Print summary
            print(f"\n{Colors.BOLD}Summary:{Colors.RESET}")
            for field in required:
                value = mr.get(field, "")
                status = "✓" if value and value.strip() else "✗"
                color = Colors.GREEN if value and value.strip() else Colors.RED
                print(f"{color}{status} {field}: {value}{Colors.RESET}")

            return summary, elapsed

        except json.JSONDecodeError as e:
            print(f"{Colors.RED}✗ Invalid JSON: {e}{Colors.RESET}")
            return None, elapsed

    except httpx.TimeoutException:
        print(f"{Colors.RED}✗ Timeout after 90s{Colors.RESET}")
        return None, 90
    except Exception as e:
        print(f"{Colors.RED}✗ Error: {e}{Colors.RESET}")
        return None, time.time() - start

def evaluate_summary(summary, name):
    """Evaluate summary quality"""

    print(f"\n{Colors.CYAN}Evaluating {name}:{Colors.RESET}")

    if not summary:
        print(f"{Colors.RED}✗ No summary to evaluate{Colors.RESET}")
        return 0

    mr = summary.get("MemoryRecall", {})

    score = 0
    max_score = 5

    # 1. All fields populated?
    required = ["Context", "Event", "Significance", "Takeaway", "Tone"]
    populated = sum(1 for f in required if mr.get(f) and mr.get(f).strip())

    if populated == len(required):
        score += 1
        print(f"{Colors.GREEN}✓ All fields populated (1 point){Colors.RESET}")
    else:
        print(f"{Colors.RED}✗ Missing {len(required) - populated} fields (0 points){Colors.RESET}")

    # 2. Abstract vs literal?
    literal_phrases = ["I don't", "The user", "asks about", "wants to", "is not recorded"]
    is_literal = any(phrase in mr.get("Takeaway", "") for phrase in literal_phrases)

    if not is_literal:
        score += 1
        print(f"{Colors.GREEN}✓ Abstract (not literal) (1 point){Colors.RESET}")
    else:
        print(f"{Colors.RED}✗ Too literal/conversational (0 points){Colors.RESET}")

    # 3. Reasonable length?
    avg_length = np.mean([len(mr.get(f, "")) for f in required[:4]])  # Exclude Tone

    if 30 <= avg_length <= 200:
        score += 1
        print(f"{Colors.GREEN}✓ Good length (avg {avg_length:.0f} chars) (1 point){Colors.RESET}")
    else:
        print(f"{Colors.YELLOW}⚠ Length issue (avg {avg_length:.0f} chars) (0.5 points){Colors.RESET}")
        score += 0.5

    # 4. Third-person perspective?
    first_person = any(word in str(mr).lower() for word in [" i ", " my ", " me ", "i'm"])

    if not first_person:
        score += 1
        print(f"{Colors.GREEN}✓ Third-person perspective (1 point){Colors.RESET}")
    else:
        print(f"{Colors.RED}✗ Uses first-person (0 points){Colors.RESET}")

    # 5. Temporal bridging (if applicable)?
    mentions_future = "plan" in str(mr).lower() or "upcoming" in str(mr).lower()
    mentions_past = "past" in str(mr).lower() or "previous" in str(mr).lower() or "experience" in str(mr).lower()

    if mentions_future and mentions_past:
        score += 1
        print(f"{Colors.GREEN}✓ Bridges past and future (1 point){Colors.RESET}")
    elif mentions_future or mentions_past:
        print(f"{Colors.YELLOW}⚠ Partial temporal context (0.5 points){Colors.RESET}")
        score += 0.5
    else:
        print(f"{Colors.YELLOW}⚠ No temporal bridging (0 points){Colors.RESET}")

    print(f"\n{Colors.BOLD}Score: {score}/{max_score} ({score/max_score*100:.0f}%){Colors.RESET}")

    return score

def main():
    print(f"{Colors.BOLD}{Colors.HEADER}")
    print("="*70)
    print("SUMMARY GENERATION COMPARISON TEST")
    print("="*70)
    print(f"{Colors.RESET}\n")

    # Get conversation
    print("Getting current conversation...")
    conversation = get_conversation()
    print(f"\n{Colors.CYAN}Conversation (first 300 chars):{Colors.RESET}")
    print(conversation[:300] + "...\n")

    # Test both approaches
    summary1, time1 = test_llama_cpp_improved(conversation)
    summary2, time2 = test_ollama(conversation)

    # Evaluate both
    print(f"\n{Colors.BOLD}{Colors.HEADER}")
    print("="*70)
    print("EVALUATION & COMPARISON")
    print("="*70)
    print(f"{Colors.RESET}")

    score1 = evaluate_summary(summary1, "llama.cpp (improved)")
    score2 = evaluate_summary(summary2, "Ollama")

    # Final comparison
    print(f"\n{Colors.BOLD}{Colors.HEADER}")
    print("="*70)
    print("WINNER")
    print("="*70)
    print(f"{Colors.RESET}\n")

    print(f"llama.cpp: {score1}/5 ({score1/5*100:.0f}%) in {time1:.2f}s")
    print(f"Ollama:    {score2}/5 ({score2/5*100:.0f}%) in {time2:.2f}s")
    print()

    if score1 > score2:
        print(f"{Colors.GREEN}✓ llama.cpp wins on quality{Colors.RESET}")
        winner = "llama.cpp"
    elif score2 > score1:
        print(f"{Colors.GREEN}✓ Ollama wins on quality{Colors.RESET}")
        winner = "Ollama"
    else:
        print(f"{Colors.YELLOW}⚠ Tie on quality{Colors.RESET}")
        winner = "Ollama" if time2 < time1 else "llama.cpp"
        print(f"{Colors.GREEN}✓ {winner} wins on speed{Colors.RESET}")

    print(f"\n{Colors.BOLD}RECOMMENDATION: Use {winner} for summary generation{Colors.RESET}")

if __name__ == "__main__":
    main()
