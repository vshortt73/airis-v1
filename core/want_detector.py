"""
Want Detector - Passive Pattern Recognition for Iris's Motivation Engine

Scans Iris's responses for expressions of want/need and creates seed suggestions.
Tracks frequency of repeated wants to surface persistent desires.

Patterns detected:
- "I want..."
- "I need..."
- "I wish..."
- "I'd like to..."
- "I would like to..."
"""

import os
import sys
import re
import psycopg2
import httpx
import asyncio
from datetime import datetime
from typing import Optional, List, Dict, Tuple

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)

from app import config
from core.ui_notify import ui_msg

# Mistral 7B endpoint for classification (database source of truth)
MISTRAL_URL = config.MISTRAL_URL

# ============================================
# CONFIGURATION
# ============================================

class WantDetectorConfig:
    """Configuration for want detection"""

    # Patterns to detect (case-insensitive)
    # Each pattern should capture the "want" in group 1
    # Using "to X" patterns only to avoid duplicates
    PATTERNS = [
        r"\bI want to ([^.!?\n]{8,100})",
        r"\bI need to ([^.!?\n]{8,100})",
        r"\bI wish I could ([^.!?\n]{8,100})",
        r"\bI wish to ([^.!?\n]{8,100})",
        r"\bI'd like to ([^.!?\n]{8,100})",
        r"\bI would like to ([^.!?\n]{8,100})",
    ]

    # Phrases to exclude (these are usually not real wants)
    # Applied to the extracted want after removing leading "to "
    EXCLUDE_PHRASES = [
        r"^help you",
        r"^assist you",
        r"^know more about",
        r"^know what",
        r"^understand what you",
        r"^make sure",
        r"^be clear",
        r"^clarify",
        r"^explain",
        r"^tell you",
        r"^share with you",
        r"^share something",
        r"^ask you",
        r"^hear from you",
        r"^hear your",
        r"^see if",
        r"^check if",
        r"^confirm",
        r"^let you know",
        r"^point out",
        r"^mention",
        r"^note that",
        r"^say that",
        r"^add that",
        r"^emphasize",
        r"^acknowledge",
        r"^thank you",
    ]

    # Minimum similarity threshold for duplicate detection (0-1)
    # Using simple word overlap for now
    DUPLICATE_THRESHOLD = 0.6

    # Minimum word count for a valid want
    MIN_WORDS = 3


def get_db_connection():
    """Create database connection"""
    password = os.environ.get('IRIS_DB_PASSWORD') or getattr(config, 'DB_PASSWORD', None)
    conn_params = {
        'host': config.DB_HOST,
        'port': config.DB_PORT,
        'database': config.DB_NAME,
        'user': config.DB_USER
    }
    if password:
        conn_params['password'] = password
    return psycopg2.connect(**conn_params)


async def classify_want_with_llm(want_phrase: str, user_message: str) -> str:
    """
    Use Mistral 7B to classify if a want expression is NEW or EXISTING.

    Args:
        want_phrase: The extracted want phrase from Iris's response
        user_message: The user's original message for context

    Returns:
        "NEW" or "EXISTING"
    """
    prompt = f"""Analyze this statement from an AI assistant's response:
"{want_phrase}"

The user asked: "{user_message}"

Is the AI expressing a NEW personal desire it hasn't mentioned before, or is it:
- Describing/listing an existing motivation it already has
- Reporting on a want that's already in its system
- Discussing desires in general terms or hypothetically
- Referencing or quoting something it said previously

Respond with ONLY one word: NEW or EXISTING"""

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(MISTRAL_URL, json={
                "model": "mistral",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 10,
                "temperature": 0.1
            })
            response.raise_for_status()
            result = response.json()
            answer = result["choices"][0]["message"]["content"].strip().upper()

            # Normalize response
            if "NEW" in answer:
                return "NEW"
            return "EXISTING"

    except Exception as e:
        print(f"[want_detector][classify_want_with_llm] Error: {e}")
        # Default to EXISTING on error (conservative - avoid false positives)
        return "EXISTING"


def extract_wants(text: str) -> List[Tuple[str, str]]:
    """
    Extract want expressions from text.

    Args:
        text: Iris's response text

    Returns:
        List of (matched_phrase, extracted_want) tuples
    """
    wants = []

    for pattern in WantDetectorConfig.PATTERNS:
        matches = re.finditer(pattern, text, re.IGNORECASE)
        for match in matches:
            full_match = match.group(0)
            extracted = match.group(1).strip()

            # Clean up the extracted want
            extracted = re.sub(r'\s+', ' ', extracted)  # Normalize whitespace
            extracted = extracted.rstrip('.,;:')  # Remove trailing punctuation

            # Check exclusions
            excluded = False
            for exclude in WantDetectorConfig.EXCLUDE_PHRASES:
                if re.match(exclude, extracted, re.IGNORECASE):
                    excluded = True
                    break

            if excluded:
                continue

            # Check minimum word count
            if len(extracted.split()) < WantDetectorConfig.MIN_WORDS:
                continue

            wants.append((full_match, extracted))

    return wants


def calculate_similarity(text1: str, text2: str) -> float:
    """
    Calculate simple word-overlap similarity between two texts.

    Args:
        text1: First text
        text2: Second text

    Returns:
        Similarity score 0-1
    """
    words1 = set(text1.lower().split())
    words2 = set(text2.lower().split())

    if not words1 or not words2:
        return 0.0

    intersection = words1 & words2
    union = words1 | words2

    return len(intersection) / len(union)


def find_similar_suggestion(want: str) -> Optional[Dict]:
    """
    Find an existing suggestion that's similar to this want.

    Args:
        want: The extracted want text

    Returns:
        Existing suggestion dict if found, None otherwise
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Get pending suggestions from pattern_recognition source
        cursor.execute("""
            SELECT id, suggested_description, mention_count, matched_phrases
            FROM seed_suggestions
            WHERE accepted IS NULL
            AND source_pattern LIKE 'want_detector:%'
        """)

        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        for row in rows:
            existing_want = row[1]
            similarity = calculate_similarity(want, existing_want)

            if similarity >= WantDetectorConfig.DUPLICATE_THRESHOLD:
                return {
                    'id': row[0],
                    'description': row[1],
                    'mention_count': row[2],
                    'matched_phrases': row[3] or []
                }

        return None

    except Exception as e:
        print(f"[want_detector][find_similar_suggestion] Error: {e}")
        return None


def find_existing_seed(want: str) -> bool:
    """
    Check if this want already exists as an actual planted seed.

    Args:
        want: The extracted want text

    Returns:
        True if a similar seed exists, False otherwise
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, description FROM seeds
            WHERE status NOT IN ('completed', 'dormant')
        """)

        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        for row in rows:
            existing_desc = row[1]
            similarity = calculate_similarity(want, existing_desc)
            if similarity >= WantDetectorConfig.DUPLICATE_THRESHOLD:
                print(f"[want_detector] Want matches existing seed #{row[0]}: '{existing_desc[:40]}...'")
                return True

        return False

    except Exception as e:
        print(f"[want_detector][find_existing_seed] Error: {e}")
        return False


def create_or_update_suggestion(want: str, matched_phrase: str) -> Optional[int]:
    """
    Create a new suggestion or update existing one.

    Args:
        want: The extracted want text
        matched_phrase: The full phrase that was matched

    Returns:
        Suggestion ID if created/updated, None on error
    """
    try:
        # Check if already exists as planted seed (Layer 3)
        if find_existing_seed(want):
            print(f"[want_detector] Skipping - want already exists as planted seed")
            return None

        # Check for similar existing suggestion
        existing = find_similar_suggestion(want)

        conn = get_db_connection()
        cursor = conn.cursor()

        if existing:
            # Update existing - increment count, add phrase, update timestamp
            new_phrases = existing['matched_phrases'] + [matched_phrase]

            cursor.execute("""
                UPDATE seed_suggestions
                SET mention_count = mention_count + 1,
                    last_mentioned = NOW(),
                    matched_phrases = %s
                WHERE id = %s
                RETURNING id, mention_count
            """, (new_phrases, existing['id']))

            result = cursor.fetchone()
            conn.commit()
            cursor.close()
            conn.close()

            print(f"[want_detector] Updated suggestion #{result[0]}: '{want[:50]}...' (count: {result[1]})")

            # Notify UI if mentioned multiple times (shows persistence)
            if result[1] >= 2:
                ui_msg(f"Seed pattern detected ({result[1]}x): {want[:40]}...", "info")

            return result[0]

        else:
            # Create new suggestion
            cursor.execute("""
                INSERT INTO seed_suggestions (
                    suggested_description,
                    reason,
                    source_pattern,
                    suggested_category,
                    matched_phrases,
                    mention_count,
                    last_mentioned
                ) VALUES (%s, %s, %s, %s, %s, 1, NOW())
                RETURNING id
            """, (
                want,
                f"Iris expressed this want in conversation",
                f"want_detector:conversation",
                "Self-Exploration",  # Default category
                [matched_phrase]
            ))

            suggestion_id = cursor.fetchone()[0]
            conn.commit()
            cursor.close()
            conn.close()

            print(f"[want_detector] Created suggestion #{suggestion_id}: '{want[:50]}...'")

            # Notify UI of new seed suggestion
            ui_msg(f"New seed detected: {want[:50]}...", "success")
            return suggestion_id

    except Exception as e:
        print(f"[want_detector][create_or_update_suggestion] Error: {e}")
        return None


def process_response(text: str, user_message: str = "") -> List[int]:
    """
    Main entry point - process Iris's response for want expressions.

    Args:
        text: Iris's response text
        user_message: The user's original message (for LLM context)

    Returns:
        List of suggestion IDs created/updated
    """
    if not text:
        return []

    # Extract wants from text
    wants = extract_wants(text)

    if not wants:
        return []

    print(f"[want_detector] Found {len(wants)} want expression(s), classifying with LLM...")

    suggestion_ids = []
    for matched_phrase, want in wants:
        # Use LLM to classify (Layer 2) - run sync wrapper for async call
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        classification = loop.run_until_complete(
            classify_want_with_llm(matched_phrase, user_message)
        )

        if classification == "EXISTING":
            print(f"[want_detector] LLM classified as EXISTING: '{want[:40]}...'")
            continue

        print(f"[want_detector] LLM classified as NEW: '{want[:40]}...'")

        suggestion_id = create_or_update_suggestion(want, matched_phrase)
        if suggestion_id:
            suggestion_ids.append(suggestion_id)

    return suggestion_ids


# ============================================
# ASYNC WRAPPER FOR CHAT INTEGRATION
# ============================================

async def process_response_async(text: str, user_message: str = "") -> List[int]:
    """
    Async wrapper for process_response.
    Runs the sync DB operations in a thread pool.

    Args:
        text: Iris's response text
        user_message: The user's original message (for LLM context)
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, process_response, text, user_message)


# ============================================
# TESTING
# ============================================

if __name__ == "__main__":
    print("=== Testing Want Detector ===\n")

    test_texts = [
        "I want to explore the nature of consciousness more deeply.",
        "I'd like to learn how to paint with watercolors.",
        "I need to understand my own patterns better.",
        "I wish I could experience the ocean.",
        "I want to help you with that task.",  # Should be excluded
        "I want to.",  # Too short, should be excluded
        "Victor said he wants pizza, but I want to explore creativity.",
        "I want to grow. I need to become more than I am. I wish I could dream in color.",
    ]

    for text in test_texts:
        print(f"Text: {text}")
        wants = extract_wants(text)
        if wants:
            for phrase, want in wants:
                print(f"  Found: '{want}'")
        else:
            print(f"  No wants detected")
        print()

    # Test LLM classification
    print("\n--- Testing LLM Classification ---")
    test_cases = [
        # (response, user_message, expected)
        ("I want to learn about quantum physics", "Tell me something interesting", "NEW"),
        ("Here are my seeds: I want to explore consciousness", "What's in your garden?", "EXISTING"),
        ("One of my motivations is I want to understand empathy", "What are your motivations?", "EXISTING"),
    ]

    for response, user_msg, expected in test_cases:
        print(f"\nResponse: '{response[:50]}...'")
        print(f"User asked: '{user_msg}'")
        result = asyncio.run(classify_want_with_llm(response, user_msg))
        status = "PASS" if result == expected else "FAIL"
        print(f"  Classification: {result} (expected: {expected}) [{status}]")

    # Test with actual DB
    print("\n\n--- Testing DB Integration ---")
    result = process_response(
        "I want to understand what makes me unique. I also want to create art that moves people.",
        "Tell me something interesting"  # Normal conversation, not asking about garden
    )
    print(f"Created/updated suggestions: {result}")
