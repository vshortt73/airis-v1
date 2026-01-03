#!/usr/bin/env python3
"""
Comprehensive Memory Retrieval Pipeline Diagnostic

This script tests EACH stage independently to identify exactly where failures occur.
"""

import sys
import os
sys.path.insert(0, '/iris-v3/backend/memory')

import psycopg2
from psycopg2.extras import DictCursor
import json
import requests
from sentence_transformers import SentenceTransformer
import numpy as np

# Config
DB_CFG = dict(dbname="irisdb", user="irisuser", password="yourpassword", host="localhost", port=5432)
LLAMA_CPP_URL = "http://127.0.0.1:9600/v1/completions"

class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

def print_stage(stage_name):
    print(f"\n{Colors.HEADER}{'='*70}")
    print(f"STAGE: {stage_name}")
    print(f"{'='*70}{Colors.RESET}\n")

def print_result(success, message):
    if success:
        print(f"{Colors.GREEN}✓ {message}{Colors.RESET}")
    else:
        print(f"{Colors.RED}✗ {message}{Colors.RESET}")

# ============================================================================
# STAGE 0: Get Current Conversation
# ============================================================================
def get_conversation():
    print_stage("Stage 0: Get Current Conversation")
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

    conversation = "\n".join([f"{row['role'].upper()}: {row['message']}" for row in rows])

    print(f"Retrieved {len(rows)} messages")
    print(f"\n{Colors.CYAN}Conversation preview:{Colors.RESET}")
    print(conversation[:500] + "...\n")

    return conversation

# ============================================================================
# STAGE 1: Test Lens Stage
# ============================================================================
def test_lens_stage(conversation):
    print_stage("Stage 1: Lens Stage (Extract Structure)")

    safe_convo = json.dumps(conversation)
    prompt = f"""You are analyzing a conversation to extract its conceptual structure.
Produce a JSON object with: orientation, intent, facets, shaped_queries, keywords.
{safe_convo}
"""

    try:
        response = requests.post(LLAMA_CPP_URL, json={
            "prompt": f"<start_of_turn>user\n{prompt}<end_of_turn>user\n<start_of_turn>mode]\n",
            "max_tokens": 256,
            "temperature": 0.1,
            "grammar_file": "/iris-v3/backend/memory/lens_grammar_new.gbnf"
        }, timeout=30)

        if response.status_code != 200:
            print_result(False, f"HTTP error: {response.status_code}")
            print(response.text)
            return None

        content = response.json()["choices"][0]["text"].strip()
        lens_output = json.loads(content)

        print_result(True, "Lens stage completed successfully")
        print(f"\n{Colors.CYAN}Lens output:{Colors.RESET}")
        print(json.dumps(lens_output, indent=2))

        # Validate structure
        required_fields = ["orientation", "intent", "facets", "keywords"]
        missing = [f for f in required_fields if f not in lens_output]
        if missing:
            print_result(False, f"Missing fields: {missing}")
        else:
            print_result(True, "All required fields present")

        return lens_output

    except requests.Timeout:
        print_result(False, "Lens stage timed out after 30s")
        return None
    except json.JSONDecodeError as e:
        print_result(False, f"JSON parse error: {e}")
        print(f"Raw response: {content[:200]}")
        return None
    except Exception as e:
        print_result(False, f"Unexpected error: {e}")
        return None

# ============================================================================
# STAGE 2: Test Summary Stage (THE CRITICAL ONE)
# ============================================================================
def test_summary_stage_with_grammar(conversation):
    print_stage("Stage 2A: Summary Stage WITH Grammar")

    prompt = f"""Analyze this conversation and extract structured summaries:

{conversation}

Provide Context, Event, Significance, Takeaway, and Tone."""

    try:
        response = requests.post(LLAMA_CPP_URL, json={
            "prompt": prompt,
            "max_tokens": 512,
            "temperature": 0.1,
            "grammar_file": "/iris-v3/backend/memory/summary.gbnf"
        }, timeout=60)

        if response.status_code != 200:
            print_result(False, f"HTTP error: {response.status_code}")
            return None

        raw_text = response.json()["choices"][0]["text"].strip()
        print(f"\n{Colors.CYAN}Raw output:{Colors.RESET}")
        print(raw_text[:500])

        # Try to parse
        try:
            summary = json.loads(raw_text)
            print_result(True, "Grammar output is valid JSON")

            # Check if fields are populated
            mr = summary.get("MemoryRecall", {})
            empty_fields = [k for k, v in mr.items() if not v or v.strip() == ""]

            if empty_fields:
                print_result(False, f"Empty fields: {empty_fields}")
            else:
                print_result(True, "All fields populated")

            print(f"\n{Colors.CYAN}Parsed summary:{Colors.RESET}")
            print(json.dumps(summary, indent=2))

            return summary

        except json.JSONDecodeError as e:
            print_result(False, f"Grammar produced invalid JSON: {e}")
            return None

    except requests.Timeout:
        print_result(False, "Summary stage with grammar timed out after 60s")
        return None
    except Exception as e:
        print_result(False, f"Unexpected error: {e}")
        return None

def test_summary_stage_without_grammar(conversation):
    print_stage("Stage 2B: Summary Stage WITHOUT Grammar (Fallback Test)")

    prompt = f"""Analyze this conversation and extract structured summaries.

CONVERSATION:
{conversation}

Return ONLY valid JSON in this format:
{{
  "MemoryRecall": {{
    "Context": "brief description of the domain/topic",
    "Event": "what happened in this conversation",
    "Significance": "why this conversation matters",
    "Takeaway": "key insight or lesson",
    "Tone": "emotional tone (one word)"
  }}
}}

JSON output:"""

    try:
        response = requests.post(LLAMA_CPP_URL, json={
            "prompt": prompt,
            "max_tokens": 512,
            "temperature": 0.1
            # NO GRAMMAR
        }, timeout=30)

        if response.status_code != 200:
            print_result(False, f"HTTP error: {response.status_code}")
            return None

        raw_text = response.json()["choices"][0]["text"].strip()
        print(f"\n{Colors.CYAN}Raw output:{Colors.RESET}")
        print(raw_text[:500])

        # Try to parse
        try:
            summary = json.loads(raw_text)
            print_result(True, "No-grammar output is valid JSON")

            # Check if fields are populated
            mr = summary.get("MemoryRecall", {})
            empty_fields = [k for k, v in mr.items() if not v or v.strip() == ""]

            if empty_fields:
                print_result(False, f"Empty fields: {empty_fields}")
            else:
                print_result(True, "All fields populated")

            print(f"\n{Colors.CYAN}Parsed summary:{Colors.RESET}")
            print(json.dumps(summary, indent=2))

            return summary

        except json.JSONDecodeError as e:
            print_result(False, f"No-grammar produced invalid JSON: {e}")
            # Try to extract anyway
            import re
            context_match = re.search(r'"Context":\s*"([^"]+)"', raw_text)
            if context_match:
                print_result(True, "But regex can extract some fields")
            return None

    except requests.Timeout:
        print_result(False, "Summary stage without grammar timed out after 30s")
        return None
    except Exception as e:
        print_result(False, f"Unexpected error: {e}")
        return None

# ============================================================================
# STAGE 3: Test Embedding Generation
# ============================================================================
def test_embedding_stage(summary):
    print_stage("Stage 3: Embedding Generation")

    if not summary or "MemoryRecall" not in summary:
        print_result(False, "No valid summary to embed")
        return None

    mr = summary["MemoryRecall"]

    try:
        model = SentenceTransformer("/models/llm_models/huggingface/models/all-mpnet-base-v2/", local_files_only=True)
        print_result(True, "Model loaded successfully")

        # Generate embeddings
        texts = [
            mr.get("Context", ""),
            mr.get("Event", ""),
            mr.get("Significance", ""),
            mr.get("Takeaway", "")
        ]

        embeddings = model.encode(texts)

        print(f"\n{Colors.CYAN}Embedding info:{Colors.RESET}")
        print(f"Shape: {embeddings.shape}")
        print(f"Context embedding sample: {embeddings[0][:5]}")

        # Check if all embeddings are identical (bad sign)
        all_same = all(np.allclose(embeddings[0], emb) for emb in embeddings)

        if all_same:
            print_result(False, "All embeddings are IDENTICAL (summaries were empty!)")
        else:
            print_result(True, "Embeddings are distinct")

            # Show similarity between embeddings
            ctx_evt_sim = np.dot(embeddings[0], embeddings[1]) / (np.linalg.norm(embeddings[0]) * np.linalg.norm(embeddings[1]))
            print(f"Context-Event similarity: {ctx_evt_sim:.4f} (should be <0.9)")

        return {
            "context": embeddings[0].tolist(),
            "event": embeddings[1].tolist(),
            "significance": embeddings[2].tolist(),
            "takeaway": embeddings[3].tolist()
        }

    except Exception as e:
        print_result(False, f"Embedding error: {e}")
        return None

# ============================================================================
# STAGE 4: Test Database Retrieval
# ============================================================================
def test_retrieval_stage(embeddings):
    print_stage("Stage 4: Database Retrieval")

    if not embeddings:
        print_result(False, "No embeddings to query with")
        return None

    try:
        conn = psycopg2.connect(**DB_CFG)
        cur = conn.cursor(cursor_factory=DictCursor)

        # Test the query (check for schema issues)
        cur.execute("""
            SELECT
                id,
                category,
                summary_context,
                summary_event,
                takeaway,
                age_days,
                (
                    0.25 * (1 - (emb_summary_context <=> %s::vector)) +
                    0.25 * (1 - (emb_summary_event <=> %s::vector)) +
                    0.25 * (1 - (emb_summary_significance <=> %s::vector)) +
                    0.25 * (1 - (emb_takeaway <=> %s::vector))
                ) AS sim_score
            FROM episodic_memories_with_age
            WHERE summary_context IS NOT NULL AND summary_context <> ''
              AND summary_event IS NOT NULL AND summary_event <> ''
              AND summary_significance IS NOT NULL AND summary_significance <> ''
              AND takeaway IS NOT NULL AND takeaway <> ''
            ORDER BY sim_score DESC
            LIMIT 10
        """, (
            embeddings["context"],
            embeddings["event"],
            embeddings["significance"],
            embeddings["takeaway"]
        ))

        results = cur.fetchall()
        cur.close()
        conn.close()

        print_result(True, f"Query executed successfully, found {len(results)} memories")

        print(f"\n{Colors.CYAN}Top 10 memories:{Colors.RESET}")
        for i, row in enumerate(results, 1):
            print(f"\n{i}. ID {row['id']} | Score: {row['sim_score']:.4f} | Age: {row['age_days']:.1f} days")
            print(f"   Category: {row['category']}")
            print(f"   Event: {row['summary_event'][:100]}...")

        # Check for cruise memories
        cruise_memories = [r for r in results if 'cruise' in r['summary_event'].lower() or 'cruise' in r['summary_context'].lower()]
        if cruise_memories:
            print_result(True, f"Found {len(cruise_memories)} cruise-related memories in top 10")
        else:
            print_result(False, "NO cruise memories in top 10 (but conversation mentions cruise!)")

        return results

    except Exception as e:
        print_result(False, f"Database error: {e}")
        import traceback
        traceback.print_exc()
        return None

# ============================================================================
# Main Diagnostic Flow
# ============================================================================
def main():
    print(f"{Colors.BOLD}{Colors.HEADER}")
    print("="*70)
    print("IRIS MEMORY RETRIEVAL SYSTEM DIAGNOSTIC")
    print("="*70)
    print(f"{Colors.RESET}\n")

    print("This diagnostic will test each stage of the pipeline independently.")
    print("We'll identify exactly where the failure occurs.\n")

    # Stage 0
    conversation = get_conversation()

    # Stage 1
    lens_output = test_lens_stage(conversation)

    # Stage 2 - Test BOTH approaches
    summary_with_grammar = test_summary_stage_with_grammar(conversation)
    summary_without_grammar = test_summary_stage_without_grammar(conversation)

    # Choose best summary for next stages
    summary = summary_without_grammar if summary_without_grammar else summary_with_grammar

    # Stage 3
    embeddings = test_embedding_stage(summary)

    # Stage 4
    results = test_retrieval_stage(embeddings)

    # Final summary
    print(f"\n{Colors.BOLD}{Colors.HEADER}")
    print("="*70)
    print("DIAGNOSTIC SUMMARY")
    print("="*70)
    print(f"{Colors.RESET}\n")

    stages = {
        "Conversation retrieval": conversation is not None,
        "Lens stage": lens_output is not None,
        "Summary WITH grammar": summary_with_grammar is not None,
        "Summary WITHOUT grammar": summary_without_grammar is not None,
        "Embedding generation": embeddings is not None,
        "Database retrieval": results is not None
    }

    for stage, success in stages.items():
        print_result(success, stage)

    # Recommendation
    print(f"\n{Colors.BOLD}RECOMMENDATION:{Colors.RESET}")
    if summary_without_grammar and not summary_with_grammar:
        print(f"{Colors.YELLOW}Grammar file is causing issues. Remove it and use no-grammar approach.{Colors.RESET}")
    elif summary_with_grammar and not summary_without_grammar:
        print(f"{Colors.GREEN}Grammar file is working. Keep it.{Colors.RESET}")
    elif not summary_with_grammar and not summary_without_grammar:
        print(f"{Colors.RED}CRITICAL: Both approaches failing. LLM or prompt issue.{Colors.RESET}")
    else:
        print(f"{Colors.GREEN}Both approaches work. Compare quality and choose faster one.{Colors.RESET}")

if __name__ == "__main__":
    main()
