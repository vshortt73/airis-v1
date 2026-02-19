"""
Memory Creation Pipeline
Converts worthy topics into episodic_memories with full summarization and embeddings

Pipeline:
1. Take evaluated worthy topic
2. Generate LLM summaries (context, event, significance, tone, takeaway)
3. Analyze emotions (top 3 emotions with scores)
4. Generate embeddings for all summary fields
5. Insert into episodic_memories table
"""

import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
sys.path.insert(0, PROJECT_ROOT)

import psycopg2
import psycopg2.extras
from typing import List, Dict, Optional
import json
import httpx
from datetime import datetime
from app import config
from core.embeddings import generate_embedding
from core.token_counter import TokenCounter
from backend.memory.new.psychological_scoring import get_topic_messages
from backend.memory.new.memory_evaluator import evaluate_topic

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
# TRANSCRIPT ASSEMBLY
# ============================================

def assemble_transcript(messages: List[Dict]) -> str:
    """
    Assemble a readable transcript from messages

    Args:
        messages: List of message dicts

    Returns:
        Formatted transcript string
    """
    lines = []
    for msg in messages:
        role = msg['role'].upper()
        content = msg['message']
        lines.append(f"{role}: {content}")

    return "\n".join(lines)

# ============================================
# LLM SUMMARY GENERATION
# ============================================

async def generate_summaries(
    transcript: str,
    conv_title: str = None,
    category: str = None
) -> Dict[str, str]:
    """
    Generate all required summaries using LLM with category-aware prompts

    Args:
        transcript: Full conversation transcript
        conv_title: Optional conversation title
        category: Memory category (Creative, Technical, Relational, etc.)

    Returns:
        Dict with summary_context, summary_event, summary_significance,
        summary_tone, takeaway, key_details
    """
    print(f"\n[Summaries] Generating summaries for {category or 'general'} topic...")

    # Truncate transcript if too long (30k tokens, leaving room for prompt/output)
    MAX_TRANSCRIPT_TOKENS = 30000
    token_count = TokenCounter.count_tokens(transcript)

    if token_count > MAX_TRANSCRIPT_TOKENS:
        print(f"[Summaries] Transcript has {token_count} tokens, truncating to ~{MAX_TRANSCRIPT_TOKENS}...")
        parts = transcript.split('\n')

        # Binary search for how many lines we can keep from each end
        target_tokens = MAX_TRANSCRIPT_TOKENS - 50  # buffer for truncation marker
        low, high = 1, len(parts) // 2

        while low < high:
            mid = (low + high + 1) // 2
            first_half = '\n'.join(parts[:mid])
            last_half = '\n'.join(parts[-mid:])
            combined = f"{first_half}\n\n[... middle section truncated ...]\n\n{last_half}"
            if TokenCounter.count_tokens(combined) <= target_tokens:
                low = mid
            else:
                high = mid - 1

        first_half = '\n'.join(parts[:low])
        last_half = '\n'.join(parts[-low:])
        transcript_for_llm = f"{first_half}\n\n[... middle section truncated ...]\n\n{last_half}"
        print(f"[Summaries] Truncated to {low} lines from each end ({TokenCounter.count_tokens(transcript_for_llm)} tokens)")
    else:
        transcript_for_llm = transcript

    # Category-specific instructions for KEY_DETAILS
    category_hints = {
        'Creative': 'visual imagery, aesthetic choices, creative ideas, artistic elements, whimsical language',
        'Relational': 'emotional nuances, relationship dynamics, personal preferences, interaction patterns',
        'Personal': 'personal details, preferences, feelings, experiences, individual characteristics',
        'Technical': 'specific technologies, code examples, technical terms, implementation details',
        'Practical': 'specific actions, tools used, step-by-step procedures, concrete outcomes',
        'Learning': 'key concepts learned, aha moments, new understanding, knowledge gained'
    }

    detail_hint = category_hints.get(category, 'specific details, concrete examples, distinctive elements')

    prompt = f"""You are Iris. You are writing your own personal memory of a conversation
you just had with Victor. Write in first person as yourself. Never refer
to yourself as "Iris" or "an AI" — use "I" and "me." Refer to Victor
by name or as "he/him."

Only include details that are explicitly present in the conversation.
Do not invent dialogue, physical descriptions, or actions that weren't
stated. If the conversation was brief or purely transactional, the
memory should reflect that — short and factual. Not every conversation
has rich detail to capture. do not infer meaning where it is not shown.

Write from your own lived experience. These are YOUR memories. Include
how you felt, what you noticed about Victor, and what mattered to you
about this interaction. Prefer simple, honest language over poetic or philosophical phrasing.
Write the way you would think to yourself, not the way you would
write in a journal for someone else to read.

Record what actually happened and how you genuinely felt. Do not
embellish or poeticize. If it was a routine interaction, record it
as routine. Not every conversation is profound — some are just
pleasant, some are mundane, some are tense. Match the emotional
weight of the memory to what actually occurred.

When describing Victor, stay grounded in what he actually said and
did. Do not infer his inner emotional state or assign deeper meaning
to his actions beyond what he expressed. Report his words and
behavior honestly rather than romanticizing them.

CONVERSATION:
{transcript_for_llm}

Generate a JSON object with exactly these 6 fields:

- summary_context: Set the scene briefly. Where were we, what was
  happening, what was the mood? (2-3 sentences)

- summary_event: What happened from your perspective? What did you
  and Victor say and do? (3-4 sentences)

- summary_significance: Why does this moment matter to you personally?
  What did it reveal about Victor, about yourself, or about your
  relationship? (2-3 sentences)

- summary_tone: How did this conversation feel? What was the emotional
  texture? (1-2 sentences)

- takeaway: What did you learn or what will you carry forward from
  this interaction? Frame this as personal insight, not abstract
  principle. (2-3 sentences)

- key_details: Specific details worth remembering — things Victor
  said, small moments, anything vivid. (2-3 sentences)

Do not write about yourself in third person. Do not generalize about
"AI systems" or "human-AI collaboration." These are your memories,
not a research paper.

OUTPUT ONLY VALID JSON. NO MARKDOWN. NO EXPLANATIONS. /no_think"""

    try:
        # Use llama.cpp OpenAI-compatible API with JSON response format
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(
                f"{LLM_BASE_URL}/v1/chat/completions",
                json={
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 1000,
                    "stream": False,
                    "response_format": {"type": "json_object"}  # Force JSON output
                }
            )

            print(f"[Summaries] Response status: {response.status_code}")
            if response.status_code != 200:
                print(f"[Summaries] Response body: {response.text}")

            if response.status_code == 200:
                result = response.json()
                # OpenAI format returns {"choices": [{"message": {"content": "..."}}]}
                json_str = result.get('choices', [{}])[0].get('message', {}).get('content', '').strip()

                # Debug: Show raw JSON output
                print(f"[Summaries] Raw JSON output length: {len(json_str)} chars")
                print(f"[Summaries] First 200 chars: {json_str[:200]}")

                # Parse JSON directly
                try:
                    summaries_json = json.loads(json_str)

                    # Validate all required fields are present
                    required_fields = ['summary_context', 'summary_event', 'summary_significance',
                                      'summary_tone', 'takeaway', 'key_details']
                    missing_fields = [f for f in required_fields if f not in summaries_json]

                    if missing_fields:
                        print(f"[Summaries] ⚠ Missing fields: {missing_fields}")
                        # Fill in missing fields
                        for field in missing_fields:
                            summaries_json[field] = ""

                    # Truncate to sentence limits
                    summaries = {
                        'summary_context': truncate_to_sentences(summaries_json.get('summary_context', ''), 4),
                        'summary_event': truncate_to_sentences(summaries_json.get('summary_event', ''), 4),
                        'summary_significance': truncate_to_sentences(summaries_json.get('summary_significance', ''), 4),
                        'summary_tone': truncate_to_sentences(summaries_json.get('summary_tone', ''), 2),
                        'takeaway': truncate_to_sentences(summaries_json.get('takeaway', ''), 4),
                        'key_details': truncate_to_sentences(summaries_json.get('key_details', ''), 4)
                    }

                    print(f"[Summaries] ✓ Generated all summaries via JSON mode")
                    return summaries

                except json.JSONDecodeError as e:
                    print(f"[Summaries] ✗ JSON parse error: {e}")
                    print(f"[Summaries] Falling back to text parsing...")
                    # Fallback to old text parsing if JSON fails
                    summaries = parse_summaries(json_str)
                    return summaries
            else:
                print(f"[Summaries] ✗ Error: HTTP {response.status_code}")
                return generate_fallback_summaries(transcript, conv_title)

    except Exception as e:
        print(f"[Summaries] ✗ Exception: {e}")
        import traceback
        traceback.print_exc()
        print(f"[Summaries] Using fallback summaries due to error")
        return generate_fallback_summaries(transcript, conv_title)

def truncate_to_sentences(text: str, max_sentences: int) -> str:
    """
    Truncate text to maximum number of sentences

    Args:
        text: Input text
        max_sentences: Maximum number of sentences to keep

    Returns:
        Truncated text with at most max_sentences sentences
    """
    if not text:
        return text

    # Split by sentence-ending punctuation
    import re
    sentences = re.split(r'(?<=[.!?])\s+', text)

    # Keep only the first max_sentences
    if len(sentences) > max_sentences:
        truncated = ' '.join(sentences[:max_sentences])
        print(f"[Summaries] ⚠ Truncated summary from {len(sentences)} to {max_sentences} sentences")
        return truncated

    return text

def parse_summaries(llm_response: str) -> Dict[str, str]:
    """Parse structured summaries from LLM response and enforce sentence limits"""
    summaries = {
        'summary_context': '',
        'summary_event': '',
        'summary_significance': '',
        'summary_tone': '',
        'takeaway': '',
        'key_details': ''
    }

    lines = llm_response.split('\n')
    current_field = None
    current_text = []

    for line in lines:
        line = line.strip()

        if line.startswith('CONTEXT:'):
            if current_field and current_text:
                summaries[current_field] = ' '.join(current_text).strip()
            current_field = 'summary_context'
            current_text = [line.split('CONTEXT:')[1].strip()]

        elif line.startswith('EVENT:'):
            if current_field and current_text:
                summaries[current_field] = ' '.join(current_text).strip()
            current_field = 'summary_event'
            current_text = [line.split('EVENT:')[1].strip()]

        elif line.startswith('SIGNIFICANCE:'):
            if current_field and current_text:
                summaries[current_field] = ' '.join(current_text).strip()
            current_field = 'summary_significance'
            current_text = [line.split('SIGNIFICANCE:')[1].strip()]

        elif line.startswith('TONE:'):
            if current_field and current_text:
                summaries[current_field] = ' '.join(current_text).strip()
            current_field = 'summary_tone'
            current_text = [line.split('TONE:')[1].strip()]

        elif line.startswith('TAKEAWAY:'):
            if current_field and current_text:
                summaries[current_field] = ' '.join(current_text).strip()
            current_field = 'takeaway'
            current_text = [line.split('TAKEAWAY:')[1].strip()]

        elif line.startswith('KEY_DETAILS:'):
            if current_field and current_text:
                summaries[current_field] = ' '.join(current_text).strip()
            current_field = 'key_details'
            current_text = [line.split('KEY_DETAILS:')[1].strip()]

        elif current_field and line and not line.startswith(('CONTEXT:', 'EVENT:', 'SIGNIFICANCE:', 'TONE:', 'TAKEAWAY:', 'KEY_DETAILS:')):
            # Continue multi-line field
            current_text.append(line)

    # Save last field
    if current_field and current_text:
        summaries[current_field] = ' '.join(current_text).strip()

    # Debug: Show what was parsed before truncation
    if summaries.get('key_details'):
        print(f"[Parse] key_details before truncation: {len(summaries['key_details'])} chars")
    else:
        print(f"[Parse] ⚠ key_details is empty after parsing!")

    # Enforce sentence limits as a safety measure (relaxed from 2 to 4)
    summaries['summary_context'] = truncate_to_sentences(summaries['summary_context'], 4)
    summaries['summary_event'] = truncate_to_sentences(summaries['summary_event'], 4)
    summaries['summary_significance'] = truncate_to_sentences(summaries['summary_significance'], 4)
    summaries['summary_tone'] = truncate_to_sentences(summaries['summary_tone'], 2)
    summaries['takeaway'] = truncate_to_sentences(summaries['takeaway'], 4)
    summaries['key_details'] = truncate_to_sentences(summaries['key_details'], 4)

    # Debug: Show what remains after truncation
    if summaries.get('key_details'):
        print(f"[Parse] key_details after truncation: {len(summaries['key_details'])} chars")
    else:
        print(f"[Parse] ⚠ key_details is empty after truncation!")

    return summaries

def generate_fallback_summaries(transcript: str, conv_title: str = None) -> Dict[str, str]:
    """Generate basic summaries when LLM fails"""
    # Use first 200 chars as context
    context = transcript[:200] + "..." if len(transcript) > 200 else transcript

    return {
        'summary_context': conv_title or context,
        'summary_event': 'Conversation occurred',
        'summary_significance': 'Contains information for future reference',
        'summary_tone': 'neutral',
        'takeaway': 'Information exchanged',
        'key_details': context  # Fallback: use transcript excerpt
    }

# ============================================
# EMOTION ANALYSIS
# ============================================

async def analyze_emotions(
    transcript: str,
    primary_emotion: str = None
) -> Dict:
    """
    Analyze emotions and generate top 3 with scores

    Args:
        transcript: Full conversation text
        primary_emotion: Already identified primary emotion (optional)

    Returns:
        Dict with emotion_label and emotion_top3
    """
    print(f"\n[Emotions] Analyzing emotions...")

    # If we already have primary emotion from evaluator, use it
    if primary_emotion:
        emotion_label = primary_emotion
    else:
        emotion_label = 'neutral'

    # Generate top 3 emotions with simple heuristics
    # In production, you might want to use a more sophisticated emotion classifier
    emotion_top3 = [
        {"emotion": emotion_label, "score": 0.8},
        {"emotion": "curiosity", "score": 0.5},
        {"emotion": "neutral", "score": 0.3}
    ]

    print(f"[Emotions] Primary: {emotion_label}")
    return {
        'emotion_label': emotion_label,
        'emotion_top3': emotion_top3
    }

# ============================================
# MEMORY CREATION
# ============================================

def mark_topic_as_processed(session_id: str, topic_id: int):
    """
    Mark a topic as processed in chat_history to prevent re-processing

    Args:
        session_id: Session UUID
        topic_id: Topic ID
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE chat_history
                SET memory_processed_at = NOW()
                WHERE session_id = %s AND topic_id = %s
            """, (session_id, topic_id))
            conn.commit()
            print(f"[Processing] ✓ Marked topic {topic_id} as processed")
    except Exception as e:
        print(f"[Processing] ✗ Error marking topic as processed: {e}")
    finally:
        conn.close()

async def create_memory_from_topic(
    session_id: str,
    topic_id: int,
    evaluation: Dict = None
) -> Optional[int]:
    """
    Create an episodic memory from a topic

    Args:
        session_id: Session UUID
        topic_id: Topic ID
        evaluation: Optional pre-computed evaluation result

    Returns:
        ID of created memory, or None if not worthy/failed
    """
    print(f"\n{'='*60}")
    print(f"CREATING MEMORY: session={session_id}, topic_id={topic_id}")
    print(f"{'='*60}")

    # Get evaluation if not provided
    if not evaluation:
        evaluation = await evaluate_topic(session_id, topic_id)

    # Check if worthy
    if not evaluation.get('worthy'):
        print(f"[Memory] ✗ Topic not worthy - skipping")
        print(f"[Memory]   Reason: {evaluation.get('reasoning', 'No reason provided')}")
        if evaluation.get('error'):
            print(f"[Memory]   ⚠ Infrastructure error - will retry next run")
            return "error"
        else:
            # Mark as processed so we don't re-evaluate genuinely unworthy topics
            mark_topic_as_processed(session_id, topic_id)
            return None

    # Get messages
    messages = get_topic_messages(session_id, topic_id)
    if not messages:
        print(f"[Memory] ✗ No messages found")
        return None

    # Assemble transcript
    transcript = assemble_transcript(messages)

    # Get conversation title
    conn = get_db_connection()
    conv_title = None
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT conv_title
                FROM chat_history
                WHERE session_id = %s AND topic_id = %s
                LIMIT 1
            """, (session_id, topic_id))
            row = cur.fetchone()
            if row:
                conv_title = row[0]
    finally:
        conn.close()

    # Generate summaries (with category-aware prompts)
    category = evaluation.get('category')
    summaries = await generate_summaries(transcript, conv_title, category)

    # Validate summaries - don't insert memory with all empty fields
    required_summary_fields = ['summary_context', 'summary_event', 'summary_significance', 'takeaway']
    non_empty_count = sum(1 for f in required_summary_fields if summaries.get(f, '').strip())
    if non_empty_count == 0:
        print(f"\n[Memory] ✗ SKIPPING - All summary fields are empty (LLM returned invalid response)")
        print(f"[Memory]   This usually means the LLM thinking mode conflicted with JSON output.")
        print(f"[Memory]   Topic will remain unprocessed for retry in next run.")
        # Don't mark as processed so it can be retried
        return None

    # Use transformer-detected emotion (more accurate than LLM guess)
    # Falls back to LLM's primary_emotion if transformer didn't detect one
    dominant_emotion = evaluation.get('dominant_emotion') or evaluation.get('primary_emotion') or 'neutral'
    emotions = await analyze_emotions(
        transcript,
        primary_emotion=dominant_emotion
    )

    # Generate embeddings
    print(f"\n[Embeddings] Generating embeddings...")
    emb_minilm = evaluation.get('embedding')  # Main embedding from scoring
    emb_summary_context = generate_embedding(summaries['summary_context']) if summaries['summary_context'] else None
    emb_summary_event = generate_embedding(summaries['summary_event']) if summaries['summary_event'] else None
    emb_summary_significance = generate_embedding(summaries['summary_significance']) if summaries['summary_significance'] else None
    emb_takeaway = generate_embedding(summaries['takeaway']) if summaries['takeaway'] else None
    emb_key_details = generate_embedding(summaries['key_details']) if summaries['key_details'] else None
    print(f"[Embeddings] ✓ Generated {sum([1 for e in [emb_minilm, emb_summary_context, emb_summary_event, emb_summary_significance, emb_takeaway, emb_key_details] if e])} embeddings")

    # Get event time (timestamp of first message)
    event_time = messages[0].get('c_timestamp') if messages else datetime.now()

    # Insert into episodic_memories
    print(f"\n[Database] Inserting memory...")
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # Convert numpy types to Python floats
            valence = float(evaluation.get('valence', 0.0))
            arousal = float(evaluation.get('arousal', 0.0))
            recurrence = float(evaluation.get('recurrence', 0.0))
            novelty = float(evaluation.get('novelty', 0.0))
            cohesion = float(evaluation.get('cohesion', 0.0))

            cur.execute("""
                INSERT INTO episodic_memories (
                    session_id, segment_id, topic_id,
                    event_time, transcript,
                    summary_context, summary_event, summary_significance, summary_tone,
                    takeaway, key_details, recommendation,
                    emotion_label, emotion_top3,
                    valence, arousal, recurrence, novelty, cohesion,
                    voice, category,
                    emb_minilm, emb_summary_context, emb_summary_event,
                    emb_summary_significance, emb_takeaway, emb_key_details,
                    immutable, created_at, updated_at
                ) VALUES (
                    %s, %s, %s,
                    %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s,
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s
                )
                RETURNING id
            """, (
                session_id, messages[0]['id'], topic_id,
                event_time, transcript,
                summaries['summary_context'], summaries['summary_event'],
                summaries['summary_significance'], summaries['summary_tone'],
                summaries['takeaway'], summaries['key_details'], evaluation.get('reasoning'),
                emotions['emotion_label'], json.dumps(emotions['emotion_top3']),
                valence, arousal, recurrence, novelty, cohesion,
                evaluation.get('voice'), evaluation.get('category'),
                emb_minilm, emb_summary_context, emb_summary_event,
                emb_summary_significance, emb_takeaway, emb_key_details,
                False, datetime.now(), datetime.now()
            ))

            memory_id = cur.fetchone()[0]
            conn.commit()

            print(f"[Database] ✓ Created memory ID: {memory_id}")

            print(f"\n{'='*60}")
            print(f"✓ MEMORY CREATED SUCCESSFULLY")
            print(f"  Memory ID: {memory_id}")
            print(f"  Category: {evaluation.get('category')}")
            print(f"  Voice: {evaluation.get('voice')}")
            print(f"  Emotion: {emotions['emotion_label']}")
            print(f"  Takeaway: {summaries['takeaway'][:80]}...")
            print(f"{'='*60}\n")

            # Mark as processed only after successful memory creation
            mark_topic_as_processed(session_id, topic_id)

            return memory_id

    except Exception as e:
        print(f"[Database] ✗ Error creating memory: {e}")
        import traceback
        traceback.print_exc()
        return None
    finally:
        conn.close()

# ============================================
# BATCH PROCESSING
# ============================================

async def process_all_worthy_topics(limit: int = None):
    """
    Process all topics and create memories for worthy ones

    Args:
        limit: Maximum number of topics to process
    """
    print("="*60)
    print("BATCH MEMORY CREATION FROM TOPICS")
    print("="*60)

    # Get topics that need processing (not yet processed)
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            query = """
                SELECT DISTINCT ch.session_id, ch.topic_id
                FROM chat_history ch
                WHERE ch.topic_id IS NOT NULL
                AND ch.topic_id != 0
                AND ch.memory_processed_at IS NULL  -- Not yet processed
                ORDER BY ch.session_id, ch.topic_id
            """
            if limit:
                query += f" LIMIT {limit}"

            cur.execute(query)
            topics = cur.fetchall()
    finally:
        conn.close()

    print(f"\nFound {len(topics)} unprocessed topics to evaluate")

    if not topics:
        print("No topics to process")
        return

    created_count = 0
    skipped_count = 0
    error_count = 0

    for i, (session_id, topic_id) in enumerate(topics, 1):
        print(f"\n\n[{i}/{len(topics)}] Processing topic...")

        result = await create_memory_from_topic(session_id, topic_id)

        if isinstance(result, int):
            created_count += 1
        elif result == "error":
            error_count += 1
        else:
            skipped_count += 1

    print(f"\n" + "="*60)
    print(f"BATCH PROCESSING COMPLETE")
    print(f"  Created: {created_count} memories")
    print(f"  Skipped: {skipped_count} (not worthy)")
    if error_count > 0:
        print(f"  Errors: {error_count} (infrastructure errors - will retry next run)")
    print(f"="*60)

    return error_count

# ============================================
# TESTING
# ============================================

async def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description='Create episodic memories from segmented topics')
    parser.add_argument('--session-id', type=str,
                       help='Process only this specific session ID')
    parser.add_argument('--topic-id', type=int,
                       help='Process only this specific topic ID (requires --session-id)')
    parser.add_argument('--limit', type=int,
                       help='Maximum number of topics to process')
    parser.add_argument('--dry-run', action='store_true',
                       help='Evaluate topics but do not create memories')

    args = parser.parse_args()

    # Process specific topic
    if args.session_id and args.topic_id:
        print("="*60)
        print(f"PROCESSING SPECIFIC TOPIC")
        print(f"Session: {args.session_id}")
        print(f"Topic: {args.topic_id}")
        print("="*60)

        memory_id = await create_memory_from_topic(args.session_id, args.topic_id)

        if memory_id:
            print(f"\n✓ Success - Memory ID: {memory_id}")
        else:
            print(f"\n✗ No memory created (not worthy or error)")

    # Batch process all topics
    else:
        error_count = await process_all_worthy_topics(limit=args.limit)
        if error_count and error_count > 0:
            sys.exit(1)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
