"""
Topic Segmentation for Chat History
LLM-based approach for maximum accuracy in topic boundary detection
"""
import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
sys.path.insert(0, PROJECT_ROOT)
from Colors import Colors
import psycopg2
import psycopg2.extras
from typing import List, Dict, Tuple, Optional
import numpy as np
from datetime import datetime
import json
import httpx
from app import config

# ============================================
# CONFIGURATION
# ============================================

# Use llama.cpp server (OpenAI-compatible API on port 11434)
LLM_BASE_URL = config.OLLAMA_BASE_URL  # http://localhost:11434
LLM_CONTEXT_WINDOW = 32768  # Context window size

# ============================================
# DATABASE CONNECTION
# ============================================

def get_db_connection():
    """Get database connection with password from environment"""
    password = os.environ.get('AIRIS_DB_PASSWORD') or getattr(config, 'DB_PASSWORD', None)
    conn_params = {
        'host': config.DB_HOST,
        'port': config.DB_PORT,
        'database': config.DB_NAME,
        'user': config.DB_USER
    }
    if password:
        conn_params['password'] = password
    return psycopg2.connect(**conn_params)

# ============================================
# STAGE 1: LLM TOPIC BOUNDARY DETECTION
# ============================================

def format_messages_for_llm(messages: List[Dict]) -> str:
    """
    Format messages as a numbered list for LLM analysis

    Args:
        messages: List of message dicts

    Returns:
        Formatted string with numbered messages
    """
    formatted = []
    for i, msg in enumerate(messages):
        role = msg['role']
        content = msg['message']

        # Truncate very long messages to keep context manageable
        if len(content) > 500:
            content = content[:500] + "..."

        formatted.append(f"{i}. {role}: {content}")

    return "\n".join(formatted)

async def detect_boundaries_with_llm(
    messages: List[Dict],
    chunk_size: int = 40
) -> List[int]:
    """
    Use LLM to identify topic boundaries in conversation

    Args:
        messages: List of all messages in session
        chunk_size: Number of messages to analyze at once

    Returns:
        List of message indices where topic boundaries occur
    """
    all_boundaries = set([0])  # Always include start

    # If conversation is short enough, analyze all at once
    if len(messages) <= chunk_size:
        boundaries = await analyze_chunk_with_llm(messages, 0)
        all_boundaries.update(boundaries)
    else:
        # Process in overlapping chunks
        chunk_start = 0
        while chunk_start < len(messages):
            chunk_end = min(chunk_start + chunk_size, len(messages))
            chunk = messages[chunk_start:chunk_end]

            print(f"  Analyzing messages {chunk_start} to {chunk_end - 1}...")
            boundaries = await analyze_chunk_with_llm(chunk, chunk_start)
            all_boundaries.update(boundaries)

            # Move to next chunk with overlap
            chunk_start += chunk_size - 5  # 5 message overlap

    return sorted(list(all_boundaries))

async def analyze_chunk_with_llm(
    messages: List[Dict],
    offset: int = 0
) -> List[int]:
    """
    Analyze a chunk of messages to find topic boundaries

    Args:
        messages: Chunk of messages to analyze
        offset: Index offset for this chunk in the full conversation

    Returns:
        List of absolute message indices where boundaries occur
    """
    formatted_messages = format_messages_for_llm(messages)

    prompt = f"""Analyze this conversation and identify where topic changes occur.

CONVERSATION:
{formatted_messages}

Task: Identify the message numbers where the conversation shifts to a different topic.

A TOPIC CHANGE occurs when:
- The subject matter clearly shifts to something unrelated (e.g., philosophical discussion → technical question)
- A new question asks about a completely different subject
- The conversation pivots from one domain to another (e.g., pirates/poetry → computer infrastructure)
- A question cannot be answered using context from the previous messages

NOT a topic change:
- Follow-up questions about the same subject ("But why?" continuing previous topic)
- Question/answer pairs on the same theme
- Natural conversation flow within one subject area

EXAMPLES:
✓ Topic change: "How does X work?" → "What's your favorite color?" (unrelated)
✓ Topic change: "Tell me about philosophy" → "How many CPUs do you use?" (philosophy → technical)
✗ NOT a change: "How does X work?" → "But why does it do that?" (follow-up)
✗ NOT a change: "Tell me about pirates" → "Do you do that?" (continuing same theme)

Return ONLY the message numbers where topic changes occur, one number per line.
If there are no topic changes in this conversation, return "NONE".

Message numbers with topic changes: /no_think"""

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{LLM_BASE_URL}/v1/chat/completions",
                json={
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                    "max_tokens": 300,
                    "stream": False
                }
            )

            if response.status_code == 200:
                result = response.json()
                answer = result.get('choices', [{}])[0].get('message', {}).get('content', '').strip()

                # Parse message numbers from response
                boundaries = []

                if answer.upper() == "NONE" or not answer:
                    print(f"  [LLM] No topic boundaries detected in this chunk")
                    return boundaries

                # Extract numbers from response
                lines = answer.split('\n')
                for line in lines:
                    line = line.strip()
                    # Try to extract number from line
                    try:
                        # Handle "5", "5.", "Message 5", etc.
                        num_str = ''.join(c for c in line if c.isdigit())
                        if num_str:
                            boundary_idx = int(num_str)
                            # Add offset to get absolute index
                            absolute_idx = boundary_idx + offset
                            if 0 < absolute_idx < len(messages) + offset:  # Don't include 0 or beyond end
                                boundaries.append(absolute_idx)
                                print(f"  [LLM] Topic boundary detected at message {absolute_idx}")
                    except ValueError:
                        continue

                return boundaries
            else:
                print(f"  [LLM] ✗ Error: HTTP {response.status_code}")
                return []

    except Exception as e:
        print(f"  [LLM] ✗ Error detecting boundaries: {e}")
        return []

# ============================================
# STAGE 2: BOUNDARY REFINEMENT
# ============================================

async def refine_boundaries_with_context(
    messages: List[Dict],
    initial_boundaries: List[int]
) -> List[int]:
    """
    Verify and refine boundaries by examining context around each

    Args:
        messages: All messages
        initial_boundaries: Boundaries detected by LLM

    Returns:
        Refined list of boundary indices
    """
    verified_boundaries = [0]  # Always keep start

    for boundary_idx in initial_boundaries[1:]:  # Skip 0
        print(f"\n  Verifying boundary at message {boundary_idx}...")
        is_valid, reason = await verify_single_boundary(messages, boundary_idx)

        if is_valid:
            verified_boundaries.append(boundary_idx)
            print(f"  [Refinement] ✓ Boundary confirmed")
            print(f"               Reason: {reason}")
        else:
            print(f"  [Refinement] ✗ Boundary rejected")
            print(f"               Reason: {reason}")

    return verified_boundaries

async def verify_single_boundary(
    messages: List[Dict],
    boundary_idx: int,
    context_window: int = 4
) -> Tuple[bool, str]:
    """
    Verify a single boundary with detailed context examination

    Args:
        messages: All messages
        boundary_idx: Index to verify
        context_window: Messages before/after to examine

    Returns:
        Tuple of (is_valid: bool, reason: str)
    """
    # Get context around boundary
    start_idx = max(0, boundary_idx - context_window)
    end_idx = min(len(messages), boundary_idx + context_window)

    before_boundary = []
    after_boundary = []

    for i in range(start_idx, end_idx):
        msg = messages[i]
        role = msg['role']
        content = msg['message']

        # Truncate long messages
        if len(content) > 400:
            content = content[:400] + "..."

        if i < boundary_idx:
            before_boundary.append(f"{role}: {content}")
        elif i >= boundary_idx:
            after_boundary.append(f"{role}: {content}")

    before_text = "\n".join(before_boundary) if before_boundary else "[Start]"
    after_text = "\n".join(after_boundary) if after_boundary else "[End]"

    prompt = f"""Examine these conversation segments and determine if there is a clear topic change between them.

BEFORE (messages leading up to potential boundary):
{before_text}

AFTER (messages after potential boundary):
{after_text}

Question: Is there a clear topic change between these segments?

Answer in this format:
Decision: [YES or NO]
Reason: [One clear sentence explaining why]

Answer: /no_think"""

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{LLM_BASE_URL}/v1/chat/completions",
                json={
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 100,
                    "stream": False
                }
            )

            if response.status_code == 200:
                result = response.json()
                answer = result.get('choices', [{}])[0].get('message', {}).get('content', '').strip()

                # Parse response
                decision = "YES"
                reason = "No reason provided"

                lines = answer.split('\n')
                for line in lines:
                    if 'Decision:' in line:
                        decision = line.split('Decision:')[1].strip().upper()
                    elif 'Reason:' in line:
                        reason = line.split('Reason:')[1].strip()

                is_valid = 'YES' in decision
                return is_valid, reason
            else:
                return True, "LLM error - keeping boundary"

    except Exception as e:
        return True, f"Exception - keeping boundary: {str(e)}"

# ============================================
# STAGE 3: COHERENCE VALIDATION
# ============================================

async def validate_topic_coherence(
    messages: List[Dict],
    boundaries: List[int]
) -> List[int]:
    """
    Validate that topic groups are coherent and reasonable

    Args:
        messages: All messages
        boundaries: Current boundary indices

    Returns:
        Refined boundary list
    """
    # Convert boundaries to topic groups
    topic_groups = []
    for i in range(len(boundaries)):
        start = boundaries[i]
        end = boundaries[i + 1] if i + 1 < len(boundaries) else len(messages)
        topic_groups.append((start, end))

    print(f"\n[Coherence] Validating {len(topic_groups)} topic groups...")

    refined_boundaries = [0]

    for i, (start, end) in enumerate(topic_groups):
        size = end - start
        print(f"  Topic {i + 1}: messages {start}-{end - 1} ({size} messages)")

        # Very small groups might be fragmented
        if size < 2 and i > 0:
            print(f"    ⚠ Very small group - might merge with previous")
        # Very large groups might contain sub-topics
        elif size > 30:
            print(f"    ⚠ Large group - might contain sub-topics")
        else:
            print(f"    ✓ Reasonable size")

        # Add boundary for next topic (if not last)
        if i + 1 < len(topic_groups):
            refined_boundaries.append(topic_groups[i + 1][0])

    return refined_boundaries

# ============================================
# STAGE 4: TOPIC TITLE GENERATION
# ============================================

async def generate_topic_titles(
    topic_assignments: Dict[int, int],
    messages: List[Dict],
    analysis_model: str = None
) -> Dict[int, str]:
    """
    Generate concise titles for each topic using LLM

    Args:
        topic_assignments: Dict mapping message index to topic_id
        messages: All messages

    Returns:
        Dict mapping topic_id to title string
    """
    # Group messages by topic_id
    topics = {}
    for msg_idx, topic_id in topic_assignments.items():
        if topic_id not in topics:
            topics[topic_id] = []
        topics[topic_id].append(messages[msg_idx])

    print(f"\n[Title Generation] Creating titles for {len(topics)} topics...")

    topic_titles = {}

    for topic_id, topic_messages in topics.items():
        print(f"  Generating title for Topic {topic_id} ({len(topic_messages)} messages)...")
        title = await generate_single_topic_title(topic_messages, topic_id, analysis_model)
        topic_titles[topic_id] = title
        print(f"{Colors.BRIGHT_GREEN}  [Title] Topic {topic_id}: \"{title}\"")
        print(f"{Colors.RESET}")

    return topic_titles

def generate_fallback_title(messages: List[Dict], topic_id: int) -> str:
    """
    Generate a fallback title from message content when LLM fails

    Args:
        messages: Messages in this topic
        topic_id: The topic ID

    Returns:
        Fallback title string
    """
    # Get first user or assistant message
    for msg in messages:
        if msg['role'] in ['user', 'assistant']:
            content = msg['message'].strip()

            # Handle very short messages
            if len(content) <= 3:
                # Single word or very short
                short_messages = {
                    'hello': 'Greeting',
                    'hi': 'Greeting',
                    'hey': 'Greeting',
                    'thanks': 'Acknowledgment',
                    'thank you': 'Acknowledgment',
                    'ok': 'Acknowledgment',
                    'okay': 'Acknowledgment',
                    'yes': 'Affirmation',
                    'no': 'Negation',
                    '?': 'Question',
                    '??': 'Question',
                    '!': 'Exclamation'
                }
                return short_messages.get(content.lower(), f'Brief {msg["role"].title()} Message')

            # Use first few words of content
            words = content.split()[:6]  # Max 6 words
            title = ' '.join(words)

            # Truncate if still too long
            if len(title) > 60:
                title = title[:57] + "..."

            # Capitalize first letter
            if title:
                title = title[0].upper() + title[1:]

            return title

    # Last resort
    return f"Topic {topic_id}"

async def analyze_topic_content(messages: List[Dict], analysis_model: str = None) -> str:
    """
    Stage 1: Analyze what the topic is about

    Args:
        messages: Messages in this topic

    Returns:
        Brief description of the topic
    """
    # Format messages for LLM
    formatted = []
    for msg in messages[:10]:  # Limit to first 10 messages
        role = msg['role']
        content = msg['message']

        # Truncate very long messages
        if len(content) > 300:
            content = content[:300] + "..."

        formatted.append(f"{role}: {content}")

    conversation_text = "\n".join(formatted)

    prompt = f"""Generate a concise title (2-5 words) for this conversation. Output ONLY the title, nothing else.
DO NOT ouput the word "title" as your answer. generate a real title. 

EXAMPLES:
Conversation: "user: How do I install Python? assistant: First, download from python.org..."
Output: Python Installation

Conversation: "user: My database won't connect. assistant: Check your connection string..."
Output: Database Connection Issues

Conversation: "user: Can you explain recursion? assistant: Recursion is when a function calls itself..."
Output: Understanding Recursion

CONVERSATION:
{conversation_text}

IMPORTANT: Output ONLY the title (2-5 words). No explanations, no reasoning, no extra text.


Output: /no_think"""

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{LLM_BASE_URL}/v1/chat/completions",
                json={
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 200,
                    "stream": False
                }
            )

            if response.status_code == 200:
                result = response.json()
                description = result.get('choices', [{}])[0].get('message', {}).get('content', '').strip()

                # Take only first line (before any reasoning/thinking text)
                if '\n' in description:
                    description = description.split('\n')[0].strip()

                return description if description else "General conversation"
            else:
                return "General conversation"

    except Exception as e:
        print(f"    [Analysis] Exception: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return "General conversation"

def extract_title_from_description(description: str) -> str:
    """
    Extract a title from description programmatically (no LLM)

    Args:
        description: Topic description

    Returns:
        Extracted title
    """
    import re

    # Remove common sentence starters and filler phrases
    prefixes_to_remove = [
        r'^the conversation appears to be about ',
        r'^the conversation is about ',
        r'^this conversation is about ',
        r'^the topic is ',
        r'^this is about ',
        r'^appears to be about ',
        r'^seems to be about ',
        r'^the assistant ',
        r'^the user ',
        r'^they discuss ',
        r'^they talk about ',
        r'^the conversation '
    ]

    title = description
    for prefix in prefixes_to_remove:
        title = re.sub(prefix, '', title, flags=re.IGNORECASE)

    # Remove certain verbs and helper words from anywhere
    words_to_remove = [
        'appears to be about',
        'seems to be about',
        'agrees to',
        'ensures',
        'ensuring',
        'focusing on',
        'helps with',
        'asks about',
        'as per the user\'s',
        'as per the',
        'specifications'
    ]
    for phrase in words_to_remove:
        title = title.replace(phrase, '')

    # Clean up extra spaces and trim
    title = ' '.join(title.split())

    # Split into words
    words = title.split()

    # Remove leading verbs
    while words and words[0].lower() in ['follow', 'follows', 'discuss', 'discusses', 'help', 'helps', 'ask', 'asks', 'ensure', 'ensures', 'provides', 'provides']:
        words = words[1:]

    # Remove articles and prepositions at the start
    while words and words[0].lower() in ['the', 'a', 'an', 'for', 'to', 'of', 'in', 'on', 'at']:
        words = words[1:]

    # Take up to 6 meaningful words, removing commas
    title_words = []
    for word in words[:10]:  # Check up to 10 to get 6 clean ones
        # Remove punctuation except apostrophes
        clean_word = word.strip(',;:.!?')
        if clean_word and len(title_words) < 6:
            title_words.append(clean_word)

    title = ' '.join(title_words)

    # Remove duplicate phrases (e.g., "Fall Weather Changes Fall Weather Changes" → "Fall Weather Changes")
    words = title.split()
    if len(words) >= 4 and len(words) % 2 == 0:
        # Check if first half equals second half
        mid = len(words) // 2
        if words[:mid] == words[mid:]:
            title = ' '.join(words[:mid])

    # Title case (but preserve existing capitals like Captain's)
    title = title.title()

    # Fix possessives (Captain'S → Captain's)
    title = title.replace("'S", "'s").replace("'T", "'t")

    return title if title else "General Topic"

async def generate_title_from_description_llm(description: str) -> str:
    """
    Stage 2: Convert description into a short title

    Args:
        description: Topic description from stage 1

    Returns:
        Short title
    """
    prompt = f"""DESCRIPTION: {description}

TASK: Write a 3-6 word title. Output ONLY the title, nothing else.

EXAMPLES:
"The assistant helps troubleshoot database connection issues" → Database Connection Troubleshooting
"The user asks how to install Python on Ubuntu" → Python Installation on Ubuntu
"The conversation is about chess opening strategies" → Chess Opening Strategies

OUTPUT TITLE NOW:"""

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                f"{LLM_BASE_URL}/v1/chat/completions",
                json={
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "max_tokens": 20,
                    "temperature": 0.0,
                    "stop": ["\n"]
                }
            )

            if response.status_code == 200:
                result = response.json()
                title = result.get("choices", [{}])[0].get("message", {}).get("content", "").strip()

                # Clean up
                title = title.strip('"\'')
                title = title.rstrip('.')

                # Remove common prefixes
                prefixes = ["Title:", "title:", "TITLE:"]
                for prefix in prefixes:
                    if title.startswith(prefix):
                        title = title[len(prefix):].strip()

                return title if title else ""
            else:
                return ""

    except Exception as e:
        print(f"    [Title] Exception: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return ""

async def generate_single_topic_title(
    messages: List[Dict],
    topic_id: int,
    analysis_model: str = None
) -> str:
    """
    Generate a concise title for a single topic using 2-stage approach

    Args:
        messages: Messages in this topic
        topic_id: The topic ID

    Returns:
        Title string
    """
    # Stage 1: Analyze topic content
    print(f"    [Stage 1/2] Analyzing topic content...")
    description = await analyze_topic_content(messages, analysis_model)
    print(f"    [Analysis] {description}")

    # Stage 2: Generate title from description
    print(f"    [Stage 2/2] Generating title...")
    # Try programmatic extraction first (fast, no LLM)
    title = extract_title_from_description(description)

    # Fallback if empty
    if not title:
        print(f"    [Title] ✗ LLM returned empty, using content-based fallback")
        title = generate_fallback_title(messages, topic_id)
    else:
        # Truncate if too long
        if len(title) > 80:
            title = title[:77] + "..."
        print(f"    [Title Debug] Generated: \"{title}\"")

    return title

# ============================================
# TOPIC ID ASSIGNMENT
# ============================================

def assign_topic_ids(boundaries: List[int], messages: List[Dict]) -> Dict[int, int]:
    """
    Assign topic IDs to messages based on boundaries

    Args:
        boundaries: List of indices where new topics start
        messages: All messages

    Returns:
        Dict mapping message index to topic_id (integer)
    """
    topic_assignments = {}

    # Sort boundaries to ensure correct order
    boundaries = sorted(boundaries)

    for i in range(len(boundaries)):
        # Simple incrementing topic ID starting from 1
        topic_id = i + 1

        # Get start and end indices
        start_idx = boundaries[i]
        end_idx = boundaries[i + 1] if i + 1 < len(boundaries) else len(messages)

        # Assign topic ID to all messages in this range
        for msg_idx in range(start_idx, end_idx):
            topic_assignments[msg_idx] = topic_id

        print(f"  Topic {topic_id}: messages {start_idx} to {end_idx - 1} ({end_idx - start_idx} messages)")

    return topic_assignments

# ============================================
# DATABASE OPERATIONS
# ============================================

def add_topic_id_column():
    """Add topic_id column to chat_history if it doesn't exist"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # Check if column exists
            cur.execute("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name='chat_history' AND column_name='topic_id'
            """)

            if cur.fetchone() is None:
                print("[Database] Adding topic_id column...")
                cur.execute("""
                    ALTER TABLE chat_history
                    ADD COLUMN topic_id INTEGER
                """)
                conn.commit()
                print("[Database] ✓ topic_id column added")
            else:
                print("[Database] topic_id column already exists")
    finally:
        conn.close()

def get_unsessioned_session_ids() -> List[str]:
    """Get unique session_ids where sessioned = false"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                        SELECT DISTINCT ch1.session_id, 
                                        (select ch2.id from chat_history ch2 where ch2.session_id = ch1.session_id limit 1) as pid
                        FROM chat_history ch1
                        WHERE ch1.sessioned = false
                        AND ch1.session_id IS NOT NULL
                        AND ch1.topic_id is null
                        ORDER BY pid desc;
                        """)
            return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()

def get_session_messages(session_id: str) -> List[Dict]:
    """Get all messages for a session in chronological order"""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id, role, message, c_timestamp, session_id
                FROM chat_history
                WHERE session_id = %s
                ORDER BY c_timestamp ASC
            """, (session_id,))

            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()

def update_topic_ids_and_titles(
    topic_assignments: Dict[int, int],
    topic_titles: Dict[int, str],
    messages: List[Dict]
):
    """Update chat_history with topic_id and conv_title assignments"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            for msg_idx, topic_id in topic_assignments.items():
                message = messages[msg_idx]
                title = topic_titles.get(topic_id, f"Topic {topic_id}")

                cur.execute("""
                    UPDATE chat_history
                    SET topic_id = %s,
                        conv_title = %s
                    WHERE id = %s
                """, (topic_id, title, message['id']))
            conn.commit()
            print(f"[Database] ✓ Updated {len(topic_assignments)} messages with topic IDs and titles")
    finally:
        conn.close()

# ============================================
# MAIN PROCESSING
# ============================================

async def process_session(
    session_id: str,
    use_refinement: bool = True,
    use_coherence: bool = True,
    chunk_size: int = 40,
    analysis_model: str = None
):
    """
    Process a single session for topic segmentation

    Args:
        session_id: Session UUID to process
        use_refinement: Whether to verify/refine boundaries
        use_coherence: Whether to validate coherence
        chunk_size: Messages per LLM analysis chunk
    """
    print(f"\n{'='*60}")
    print(f"Processing session: {session_id}")
    print(f"{'='*60}")

    # Get all messages for this session
    messages = get_session_messages(session_id)
    print(f"Found {len(messages)} messages")

    if len(messages) == 0:
        print("No messages to process")
        return

    # Handle single-message sessions
    if len(messages) == 1:
        print("Single message session - assigning topic_id = 0")
        topic_assignments = {0: 0}

        # Generate title for single message
        print("\n[Title Generation] Creating title for single message...")
        title = await generate_single_topic_title(messages, 0, analysis_model)
        topic_titles = {0: title}
        print(f"  [Title] Topic 0: \"{title}\"")

        update_topic_ids_and_titles(topic_assignments, topic_titles, messages)
        print(f"\n{'='*60}")
        print(f"✓ Session {session_id} completed")
        print(f"  Total messages: 1")
        print(f"  Topic ID: 0 (single message)")
        print(f"  Title: \"{title}\"")
        print(f"{'='*60}")
        return

    # Stage 1: LLM-based boundary detection
    print(f"\n[Stage 1] Detecting topic boundaries with LLM (chunk_size={chunk_size})...")
    initial_boundaries = await detect_boundaries_with_llm(messages, chunk_size)

    if len(initial_boundaries) == 1:
        print(f"[Stage 1] ✓ No topic boundaries found - entire session is one topic")
    else:
        print(f"[Stage 1] ✓ Found {len(initial_boundaries)} potential boundaries ({len(initial_boundaries) - 1} topic changes)")

    # Stage 2: Refinement (optional)
    if use_refinement and len(initial_boundaries) > 1:
        print(f"\n[Stage 2] Refining boundaries...")
        refined_boundaries = await refine_boundaries_with_context(messages, initial_boundaries)
        print(f"[Stage 2] ✓ Verified {len(refined_boundaries)} boundaries")
    else:
        refined_boundaries = initial_boundaries
        print(f"\n[Stage 2] Skipped (refinement disabled)")

    # Stage 3: Coherence validation (optional)
    if use_coherence:
        final_boundaries = await validate_topic_coherence(messages, refined_boundaries)
        print(f"[Stage 3] ✓ Final boundaries: {len(final_boundaries)}")
    else:
        final_boundaries = refined_boundaries
        print(f"\n[Stage 3] Skipped (coherence validation disabled)")

    # Assign topic IDs
    print(f"\n[Assignment] Assigning topic IDs...")
    topic_assignments = assign_topic_ids(final_boundaries, messages)

    # Generate topic titles
    topic_titles = await generate_topic_titles(topic_assignments, messages, analysis_model)

    # Update database
    print(f"\n[Database] Updating chat_history...")
    update_topic_ids_and_titles(topic_assignments, topic_titles, messages)

    print(f"\n{'='*60}")
    print(f"✓ Session {session_id} completed")
    print(f"  Total messages: {len(messages)}")
    if len(final_boundaries) == 1:
        print(f"  Topics identified: 1 (entire session is a single topic)")
    else:
        print(f"  Topics identified: {len(final_boundaries)}")
    print(f"{'='*60}")

async def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description='LLM-based topic segmentation for chat history')
    parser.add_argument('--no-refinement', action='store_true',
                       help='Skip boundary refinement stage')
    parser.add_argument('--no-coherence', action='store_true',
                       help='Skip coherence validation')
    parser.add_argument('--session-id', type=str,
                       help='Process only this specific session ID')
    parser.add_argument('--limit', type=int,
                       help='Maximum number of sessions to process (useful for testing)')
    parser.add_argument('--chunk-size', type=int, default=40,
                       help='Messages per LLM analysis chunk (default: 40)')
    parser.add_argument('--analysis-model', type=str,
                       help='[DEPRECATED - Not used] Model specification (llama.cpp endpoint is always used)')
    parser.add_argument('--dry-run', action='store_true',
                       help='Run without updating database')

    args = parser.parse_args()

    # Add topic_id column if needed
    if not args.dry_run:
        add_topic_id_column()

    # Get sessions to process
    if args.session_id:
        session_ids = [args.session_id]
    else:
        print("\nFinding sessions where sessioned=false...")
        session_ids = get_unsessioned_session_ids()
        print(f"Found {len(session_ids)} sessions to process")

        # Apply limit if specified
        if args.limit and args.limit > 0:
            original_count = len(session_ids)
            session_ids = session_ids[:args.limit]
            print(f"Limiting to first {args.limit} sessions (out of {original_count} total)")

    if len(session_ids) == 0:
        print("No sessions to process")
        return

    # Process each session
    for i, session_id in enumerate(session_ids, 1):
        print(f"\n\nProcessing session {i}/{len(session_ids)}")
        await process_session(
            session_id,
            use_refinement=not args.no_refinement,
            use_coherence=not args.no_coherence,
            chunk_size=args.chunk_size,
            analysis_model=args.analysis_model
        )

    print("\n" + "="*60)
    print("✓ All sessions processed successfully")
    print("="*60)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
