"""
Memory Worthiness Evaluator
Uses psychological scores + LLM judgment to determine if a topic should become a memory

Evaluation Process:
1. Calculate psychological scores (arousal, valence, novelty, coherence, cohesion, recurrence)
2. Present scores + topic content to LLM
3. LLM decides: WORTHY or NOT_WORTHY
4. If worthy, LLM provides: category, voice, primary_emotion, reasoning
"""

import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
sys.path.insert(0, PROJECT_ROOT)

import psycopg2
import psycopg2.extras
from typing import List, Dict, Optional, Tuple
import json
import httpx
from app import config
from backend.memory.new.psychological_scoring_transformers import score_topic, get_topic_messages

# ============================================
# DATABASE CONNECTION
# ============================================

def get_db_connection():
    """Get database connection with password from environment"""
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
# LLM EVALUATION
# ============================================

async def evaluate_memory_worthiness(
    session_id: str,
    topic_id: int,
    messages: List[Dict],
    scores: Dict[str, float],
    conv_title: str = None
) -> Dict:
    """
    Use LLM to evaluate if a topic is worthy of becoming a memory

    Args:
        session_id: Session UUID
        topic_id: Topic ID
        messages: List of messages in topic
        scores: Psychological scores dict
        conv_title: Optional existing conversation title

    Returns:
        Dict with evaluation results:
        {
            'worthy': bool,
            'category': str (if worthy),
            'voice': str (if worthy),
            'primary_emotion': str (if worthy),
            'reasoning': str,
            'confidence': float (0-1)
        }
    """
    print(f"\n[Evaluator] Evaluating topic {topic_id}")

    # Assemble transcript
    transcript = assemble_transcript(messages)

    # Truncate if too long (keep first and last parts)
    if len(transcript) > 3000:
        parts = transcript.split('\n')
        first_half = '\n'.join(parts[:15])
        last_half = '\n'.join(parts[-15:])
        transcript = f"{first_half}\n\n[... middle section truncated ...]\n\n{last_half}"

    # Build evaluation prompt
    prompt = f"""You are a memory formation expert. Your task is to determine if this conversation topic should be stored as a long-term episodic memory.

CONVERSATION TOPIC:
Title: {conv_title or 'Untitled'}
Messages: {scores['message_count']}
Tokens: {scores['token_count']}

PSYCHOLOGICAL SCORES (based on memory research):
- Arousal:    {scores['arousal']:.3f} [0-1, higher = more emotionally intense]
- Valence:    {scores['valence']:+.3f} [-1 to +1, negative to positive emotion]
- Novelty:    {scores['novelty']:.3f} [0-1, higher = more unique/novel content]
- Coherence:  {scores['coherence']:.3f} [0-1, higher = better semantic flow]
- Cohesion:   {scores['cohesion']:.3f} [0-1, higher = more connected narrative]
- Recurrence: {scores['recurrence']:.3f} [0-1, higher = relates to existing memories]

TRANSCRIPT:
{transcript}

EVALUATION CRITERIA:
A topic is WORTHY of becoming a memory if it meets ANY of these:
1. High significance: Important event, learning, or decision
2. Strong emotional content: Arousal > 0.5 OR |Valence| > 0.7
3. Novel information: Novelty > 0.6 AND Coherence > 0.4
4. Practical value: Contains useful information, instructions, or solutions
5. Relational value: Deepens understanding of user preferences, personality, or relationships

NOT worthy if:
- Pure greetings/acknowledgments with no content
- Very short exchanges (< 150 tokens) with low arousal/valence
- Incoherent fragments (Coherence < 0.3 AND Cohesion < 0.3)
- Purely transactional with no memorable content

YOU MUST respond in EXACTLY this format (no extra text before or after):

DECISION: [WORTHY or NOT_WORTHY]
CATEGORY: [Practical/Personal/Technical/Creative/Relational/Learning/Other]
VOICE: [neutral/practical/emotional/technical/creative]
PRIMARY_EMOTION: Choose the DOMINANT emotion from the conversation: joy, sadness, fear, anger, surprise, love, curiosity, frustration, satisfaction, excitement, neutral
CONFIDENCE: [number between 0.0 and 1.0]
REASONING: [2-3 sentence explanation]

IMPORTANT: Choose PRIMARY_EMOTION based on the actual emotional tone of the conversation, not a default. Technical problem-solving often has frustration or satisfaction. Creative work often has excitement or joy. Personal conversations often have love or sadness.

Now evaluate the topic above: /no_think"""

    try:
        # Use llama-server OpenAI-compatible API
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{config.OLLAMA_BASE_URL}/v1/chat/completions",
                json={
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "max_tokens": 400,
                    "temperature": 0.2
                }
            )

            if response.status_code == 200:
                result = response.json()
                answer = result.get("choices", [{}])[0].get("message", {}).get("content", "").strip()

                # Debug: print raw response
                print(f"\n[Debug] Raw LLM response from llama-server:")
                print(f"  Full text ({len(answer)} chars):")
                print(f"{answer}")
                print(f"  [End of response]\n")

                if answer:
                    evaluation = parse_evaluation(answer)
                else:
                    print(f"[Debug] Empty response from llama-server!")
                    evaluation = {
                        'worthy': False,
                        'reasoning': 'LLM returned empty response',
                        'confidence': 0.0
                    }
                evaluation['session_id'] = session_id
                evaluation['topic_id'] = topic_id
                print(f"updating session {session_id}")
                update_chat(str(session_id))
                

                # Print results
                print(f"[Evaluator] Decision: {evaluation['worthy']}")
                if evaluation['worthy']:
                    print(f"[Evaluator] Category: {evaluation.get('category', 'N/A')}")
                    print(f"[Evaluator] Voice: {evaluation.get('voice', 'N/A')}")
                    print(f"[Evaluator] Emotion: {evaluation.get('primary_emotion', 'N/A')}")
                print(f"[Evaluator] Confidence: {evaluation.get('confidence', 0.0):.2f}")
                print(f"[Evaluator] Reasoning: {evaluation.get('reasoning', 'N/A')}")

                return evaluation
            else:
                print(f"[Evaluator] ✗ Error: HTTP {response.status_code}")
                return {
                    'worthy': False,
                    'error': True,
                    'reasoning': f'LLM error: HTTP {response.status_code}',
                    'confidence': 0.0
                }

    except Exception as e:
        print(f"[Evaluator] ✗ Exception: {e}")
        return {
            'worthy': False,
            'error': True,
            'reasoning': f'Exception: {str(e)}',
            'confidence': 0.0
        }

def parse_evaluation(llm_response: str) -> Dict:
    """
    Parse structured evaluation from LLM response

    Args:
        llm_response: Raw LLM text response

    Returns:
        Dict with parsed fields
    """
    evaluation = {
        'worthy': False,
        'category': None,
        'voice': None,
        'primary_emotion': None,
        'confidence': 0.5,
        'reasoning': ''
    }

   

    # Clean up the response - remove common prefixes
    response = llm_response.strip()

    # Remove common intro phrases
    intro_phrases = [
        "Based on the provided information, I will evaluate",
        "Based on the evaluation criteria",
        "Here is my evaluation:",
        "My evaluation:",
        "Evaluation:"
    ]
    for phrase in intro_phrases:
        if response.startswith(phrase):
            # Find where the structured format starts
            if 'DECISION:' in response:
                response = response[response.index('DECISION:'):]
            break

    lines = response.split('\n')
    reasoning_lines = []
    capture_reasoning = False

    for i, line in enumerate(lines):
        line = line.strip()

        if line.startswith('DECISION:'):
            decision = line.split('DECISION:')[1].strip().upper()
            evaluation['worthy'] = 'WORTHY' in decision and 'NOT' not in decision
            capture_reasoning = False

        elif line.startswith('CATEGORY:'):
            category = line.split('CATEGORY:')[1].strip()
            # Clean up brackets and extra chars
            category = category.strip('[]')
            evaluation['category'] = category if category and category not in ['N/A', ''] else None
            capture_reasoning = False

        elif line.startswith('VOICE:'):
            voice = line.split('VOICE:')[1].strip()
            voice = voice.strip('[]')
            evaluation['voice'] = voice if voice and voice not in ['N/A', ''] else None
            capture_reasoning = False

        elif line.startswith('PRIMARY_EMOTION:'):
            emotion = line.split('PRIMARY_EMOTION:')[1].strip()
            emotion = emotion.strip('[]')
            evaluation['primary_emotion'] = emotion if emotion and emotion not in ['N/A', ''] else None
            capture_reasoning = False

        elif line.startswith('CONFIDENCE:'):
            try:
                conf_str = line.split('CONFIDENCE:')[1].strip()
                # Extract number from string (handles "0.8" or "0.8/1.0" or "[0.8]" etc)
                conf_str = conf_str.strip('[]')
                conf_num = float(conf_str.split()[0])
                evaluation['confidence'] = max(0.0, min(1.0, conf_num))
            except Exception as e:
                print(f"  [Parse] Warning: Could not parse confidence from '{conf_str}': {e}")
                evaluation['confidence'] = 0.5
            capture_reasoning = False

        elif line.startswith('REASONING:'):
            reasoning_text = line.split('REASONING:')[1].strip()
            # Clean up brackets
            reasoning_text = reasoning_text.strip('[]')
            if reasoning_text:
                reasoning_lines.append(reasoning_text)
            capture_reasoning = True

        elif capture_reasoning and line and not line.startswith('DECISION:'):
            # Continue capturing multi-line reasoning
            reasoning_lines.append(line)

    # Join reasoning lines
    if reasoning_lines:
        evaluation['reasoning'] = ' '.join(reasoning_lines)[:500]

    return evaluation

# ============================================
# MAIN EVALUATION PIPELINE
# ============================================

async def evaluate_topic(session_id: str, topic_id: int) -> Dict:
    """
    Complete evaluation pipeline for a topic

    Args:
        session_id: Session UUID
        topic_id: Topic ID

    Returns:
        Dict with scores and evaluation
    """
    print(f"\n{'='*60}")
    print(f"EVALUATING TOPIC: session={session_id}, topic_id={topic_id}")
    print(f"{'='*60}")

    # Get messages
    messages = get_topic_messages(session_id, topic_id)
    if not messages:
        print("[Evaluator] No messages found")
        return {'worthy': False, 'reasoning': 'No messages found'}

    # Get conversation title if exists
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

    # Calculate psychological scores
    print("\n[Step 1/2] Calculating psychological scores...")
    scores = score_topic(session_id, topic_id, messages)

    # Evaluate with LLM
    print("\n[Step 2/2] LLM evaluation...")
    evaluation = await evaluate_memory_worthiness(
        session_id, topic_id, messages, scores, conv_title
    )

    # Combine scores and evaluation
    result = {
        **scores,
        **evaluation
    }

    print(f"\n{'='*60}")
    if result['worthy']:
        print(f"✓ WORTHY - This topic should become a memory")
    else:
        print(f"✗ NOT WORTHY - This topic will not be stored")
    print(f"{'='*60}\n")

    return result

# ============================================
# BATCH PROCESSING
# ============================================

def get_topics_needing_evaluation(limit: int = None) -> List[Tuple[str, int]]:
    """
    Get topics that have been segmented but not yet evaluated

    Args:
        limit: Maximum number of topics to return

    Returns:
        List of (session_id, topic_id) tuples
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            query = """
                SELECT DISTINCT session_id, topic_id
                FROM chat_history
                WHERE topic_id IS NOT NULL
                AND topic_id != 0
                AND sessioned is false
                AND session_id NOT IN (select session_id from episodic_memories)  # prevents sessions from being analyzed more than once
                ORDER BY session_id, topic_id
            """
            if limit:
                query += f" LIMIT {limit}"

            cur.execute(query)
            return cur.fetchall()
    finally:
        conn.close()


# ============================================
# CHAT HISTORY MARKER
# ============================================
def update_chat(session_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            query = """
                UPDATE chat_history SET sessioned = true WHERE session_id = %s
            """
            cur.execute(query, (str(session_id),))  # Pass params as second argument
            conn.commit()  # commit() is on the connection, not cursor
        print("\n[eval] marking chat session as evaluated")
    except Exception as e:
        print(f">>>>>>>>>>>>>   chat history update failed. {e}")
    finally:
        conn.close()


# ============================================
# TESTING
# ============================================

async def test_evaluator():
    """Test the evaluation system on a sample topic"""
    print("="*60)
    print("MEMORY WORTHINESS EVALUATOR TEST")
    print("="*60)

    topics = get_topics_needing_evaluation(limit=1)
    if not topics:
        print("No topics found")
        return

    session_id, topic_id = topics[0]
    result = await evaluate_topic(session_id, topic_id)

    print("\n" + "="*60)
    print("FULL RESULT:")
    print(json.dumps(result, indent=2, default=str))
    print("="*60)

if __name__ == "__main__":
    import asyncio
    asyncio.run(test_evaluator())
