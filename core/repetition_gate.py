"""
Repetition Gate — Application-layer defense against cross-turn repetition.

Local models (Qwen3-32B etc.) are prone to echoing phrases from their own
recent outputs in conversation context.  Sampling penalties help within a
single generation but don't prevent the model from re-using the same
*concepts* across turns.

Three mechanisms:
1. STRUCTURAL (LLM) — analyze_structural_patterns() sends recent assistant
   messages to Mistral 7B for structural repetition analysis. Results are
   formatted by build_structural_avoidance() as a <structural_variety_directive>.
2. PROACTIVE (n-gram) — build_avoidance_block() extracts distinctive phrases
   from recent assistant messages and injects a <do_not_reuse> XML block into
   the per-turn tail.  Fallback when Mistral is unavailable.
3. DETECTIVE — score_repetition() checks a new response against recent
   messages and returns a 0-1 score for observability / logging.
"""

import json
import re
from collections import Counter
from typing import List, Dict, Optional, Tuple

import httpx

# ── N-gram extraction ─────────────────────────────────────────────────

# Common filler n-grams to ignore (these are normal in English)
_STOPGRAMS = {
    "i remember how", "i remember when", "do you remember",
    "i want to", "i need to", "you want to", "you need to",
    "let me know", "would you like", "if you want",
    "i think that", "it was a", "that was a",
    "what do you", "how do you", "are you sure",
    "i don't know", "i'm not sure", "a little bit",
    "at the same", "the same time", "one of the",
    "it's not a", "this is a", "there is a",
    "going to be", "want me to", "i can help",
    "is there anything", "anything else you",
}


def _normalize(text: str) -> str:
    """Lowercase, strip HTML tags, collapse whitespace. For n-gram extraction."""
    text = re.sub(r'<[^>]+>', ' ', text)       # strip HTML
    text = re.sub(r'\([^)]*\)', ' ', text)     # strip parentheticals
    text = re.sub(r'[*_~`#]', '', text)        # strip markdown
    text = re.sub(r'-{3,}', ' ', text)         # strip horizontal rules (---)
    text = re.sub(r'\s+', ' ', text).strip()
    return text.lower()


def _normalize_for_structural(text: str) -> str:
    """Light normalization for LLM structural analysis.
    Preserves parentheticals, markdown structure, and formatting
    so Mistral can detect template-level repetition patterns."""
    text = re.sub(r'<[^>]+>', '', text)         # strip HTML tags only
    text = re.sub(r'\s*\n\s*\n\s*\n+', '\n\n', text)  # collapse triple+ newlines
    return text.strip()


def extract_ngrams(text: str, n: int = 4) -> Counter:
    """Extract n-grams from text, filtering stopgrams."""
    words = _normalize(text).split()
    ngrams = Counter()
    for i in range(len(words) - n + 1):
        gram = ' '.join(words[i:i + n])
        if gram not in _STOPGRAMS:
            ngrams[gram] += 1
    return ngrams


def extract_distinctive_phrases(
    messages: List[str],
    ngram_size: int = 4,
    min_occurrences: int = 2,
    max_phrases: int = 12,
) -> List[str]:
    """
    Find phrases that appear in 2+ of the given messages.

    These are the "echo phrases" — things the model keeps repeating
    across turns.  We want to surface them so the model can avoid them.

    Args:
        messages: List of assistant message texts
        ngram_size: Size of n-grams to extract
        min_occurrences: Phrase must appear in at least this many messages
        max_phrases: Cap the returned list to avoid prompt bloat

    Returns:
        List of distinctive phrases sorted by frequency (most common first)
    """
    # Count in how many messages each n-gram appears
    phrase_doc_count: Counter = Counter()

    for msg_text in messages:
        # Get unique n-grams per message (not total count, just presence)
        msg_ngrams = set(extract_ngrams(msg_text, ngram_size).keys())
        for gram in msg_ngrams:
            phrase_doc_count[gram] += 1

    # Filter: must appear in min_occurrences distinct messages
    repeated = {
        gram: count
        for gram, count in phrase_doc_count.items()
        if count >= min_occurrences
    }

    if not repeated:
        return []

    # Sort by frequency (most repeated first), then alphabetically
    sorted_phrases = sorted(
        repeated.keys(),
        key=lambda g: (-repeated[g], g)
    )

    return sorted_phrases[:max_phrases]


# ── Proactive: Avoidance block for per-turn context ───────────────────

def build_avoidance_block(
    conversation_messages: List[Dict[str, str]],
    recent_n: int = 5,
    ngram_size: int = 4,
    min_occurrences: int = 2,
    max_phrases: int = 12,
) -> Optional[str]:
    """
    Build an XML block listing phrases the model should NOT reuse.

    Extracts distinctive repeated phrases from the last N assistant
    messages and formats them as a <do_not_reuse> directive.

    Args:
        conversation_messages: Full message list (will filter to assistant)
        recent_n: How many recent assistant messages to analyze
        ngram_size: N-gram size for phrase extraction
        min_occurrences: Minimum messages a phrase must appear in
        max_phrases: Maximum phrases to include

    Returns:
        XML string for prompt injection, or None if no repetition detected
    """
    # Get recent assistant messages
    assistant_msgs = [
        m.get('content', '')
        for m in conversation_messages
        if m.get('role') == 'assistant' and m.get('content')
    ]

    # Take the most recent N
    recent = assistant_msgs[-recent_n:] if len(assistant_msgs) > recent_n else assistant_msgs

    # Deduplicate identical messages (exact dupes inflate phrase counts)
    seen = set()
    deduped = []
    for msg in recent:
        sig = msg.strip()[:500]
        if sig not in seen:
            seen.add(sig)
            deduped.append(msg)
    recent = deduped

    if len(recent) < 2:
        return None  # Need at least 2 messages to detect cross-turn repetition

    phrases = extract_distinctive_phrases(
        recent,
        ngram_size=ngram_size,
        min_occurrences=min_occurrences,
        max_phrases=max_phrases,
    )

    if not phrases:
        return None

    phrase_list = '\n'.join(f'  - "{p}"' for p in phrases)

    block = f"""<do_not_reuse>
You have used these phrases in your recent messages. DO NOT use them again — find fresh wording:
{phrase_list}
This is not optional. Using any of the above phrases will make you sound like a broken record.
</do_not_reuse>"""

    print(f"[repetition_gate] Avoidance block: {len(phrases)} phrases flagged")
    return block


# ── Structural: LLM-powered pattern detection ────────────────────────

_STRUCTURAL_ANALYSIS_PROMPT = """Analyze these recent AI assistant responses for STRUCTURAL repetition patterns.
These are ONLY the assistant's own messages — no user messages or system data.
For each category, note if the same pattern appears in 2+ messages:

1. OPENING: How does each message begin? Same greeting, concession, or formula?
2. FORMATTING: Same template? (headers with emojis, numbered lists, horizontal rules, bold labels)
3. METAPHORS: Same type of comparison or imagery used repeatedly?
4. STAGE DIRECTIONS: Same parenthetical actions or asides? Same recurring phrase in parentheses?
5. CLOSING: Same type of ending, sign-off, question, or call-to-action?
6. SENTENCE STRUCTURE: Same narrative flow, formula, or rhetorical moves?

Messages:
"""

_STRUCTURAL_ANALYSIS_SUFFIX = """

Return JSON with only patterns found in 2+ messages:
{"patterns": [{"category": "OPENING", "observation": "4/5 messages start with 'Captain—' followed by restating the user's topic", "count": 4}]}
Return {"patterns": []} if no structural repetition detected.
JSON only, no commentary."""


async def analyze_structural_patterns(
    conversation_messages: List[Dict[str, str]],
    recent_n: int = 6,
) -> List[Dict]:
    """
    Use Mistral 7B to analyze recent assistant messages for structural repetition.

    Sends the last N assistant messages (stripped of HTML/markdown) to Mistral
    and asks it to identify repeated structural patterns (openings, metaphors,
    stage directions, closings, etc.).

    Args:
        conversation_messages: Full message list (will filter to assistant only)
        recent_n: How many recent assistant messages to analyze

    Returns:
        List of pattern dicts with category, observation, count.
        Empty list on failure or if no patterns detected.
    """
    from app import config

    mistral_url = getattr(config, 'MISTRAL_URL', None)
    if not mistral_url:
        print("[repetition_gate] No MISTRAL_URL configured, skipping structural analysis")
        return []

    # Extract assistant-only messages
    assistant_msgs = [
        m.get('content', '')
        for m in conversation_messages
        if m.get('role') == 'assistant' and m.get('content')
    ]

    recent = assistant_msgs[-recent_n:]

    # Deduplicate identical messages (exact dupes inflate pattern counts)
    seen = set()
    deduped = []
    for msg in recent:
        sig = msg.strip()[:500]  # first 500 chars as signature
        if sig not in seen:
            seen.add(sig)
            deduped.append(msg)
    recent = deduped

    if len(recent) < 3:
        return []  # Need at least 3 messages for meaningful structural analysis

    # Light normalization — preserve structure for Mistral to analyze
    cleaned = [_normalize_for_structural(msg) for msg in recent]

    # Build numbered message list for the prompt
    msg_block = "\n\n".join(
        f"[Message {i+1}]: {text}" for i, text in enumerate(cleaned)
    )

    prompt = _STRUCTURAL_ANALYSIS_PROMPT + msg_block + _STRUCTURAL_ANALYSIS_SUFFIX

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                mistral_url,
                json={
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                    "max_tokens": 600,
                }
            )

            if response.status_code != 200:
                print(f"[repetition_gate] Mistral returned {response.status_code}")
                return []

            data = response.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")

            # Parse JSON from response (handle markdown code blocks)
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]

            parsed = json.loads(content.strip())
            patterns = parsed.get("patterns", [])

            # Validate structure
            valid = []
            for p in patterns:
                if isinstance(p, dict) and "category" in p and "observation" in p:
                    valid.append({
                        "category": str(p["category"]),
                        "observation": str(p["observation"]),
                        "count": int(p.get("count", 2)),
                    })

            print(f"[repetition_gate] Structural analysis: {len(valid)} patterns detected")
            return valid

    except (httpx.TimeoutException, httpx.ConnectError) as e:
        print(f"[repetition_gate] Mistral connection failed (non-fatal): {e}")
        return []
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        print(f"[repetition_gate] Failed to parse Mistral response (non-fatal): {e}")
        return []
    except Exception as e:
        print(f"[repetition_gate] Structural analysis error (non-fatal): {e}")
        return []


def build_structural_avoidance(patterns: List[Dict]) -> Optional[str]:
    """
    Format structural analysis results as an XML directive for the per-turn tail.

    Takes pattern dicts from analyze_structural_patterns() and builds a
    <structural_variety_directive> block that gives the model specific,
    actionable feedback about structural repetition to avoid.

    Args:
        patterns: List of dicts with category, observation, count

    Returns:
        XML string for prompt injection, or None if no patterns
    """
    if not patterns:
        return None

    lines = [
        "<structural_variety_directive>",
        "Your recent responses follow predictable structural patterns. You MUST break these:",
    ]

    for p in patterns:
        lines.append(f"- {p['category']}: {p['observation']}")

    lines.append(
        "Vary your STRUCTURE and FORM, not just your vocabulary. "
        "A formulaic response with different words is still repetitive."
    )
    lines.append("</structural_variety_directive>")

    print(f"[repetition_gate] Structural avoidance block: {len(patterns)} patterns flagged")
    return "\n".join(lines)


# ── Detective: Post-generation scoring ────────────────────────────────

def score_repetition(
    new_response: str,
    conversation_messages: List[Dict[str, str]],
    recent_n: int = 5,
    ngram_size: int = 4,
) -> Tuple[float, List[str]]:
    """
    Score how repetitive a new response is relative to recent messages.

    Returns:
        (score, matched_phrases) where score is 0.0 (unique) to 1.0 (all repeated)
    """
    assistant_msgs = [
        m.get('content', '')
        for m in conversation_messages
        if m.get('role') == 'assistant' and m.get('content')
    ]

    recent = assistant_msgs[-recent_n:] if len(assistant_msgs) > recent_n else assistant_msgs

    if not recent:
        return 0.0, []

    # Get n-grams from new response
    new_ngrams = set(extract_ngrams(new_response, ngram_size).keys())

    if not new_ngrams:
        return 0.0, []

    # Get n-grams from all recent messages combined
    history_ngrams: set = set()
    for msg_text in recent:
        history_ngrams.update(extract_ngrams(msg_text, ngram_size).keys())

    # Calculate overlap
    overlap = new_ngrams & history_ngrams
    score = len(overlap) / len(new_ngrams) if new_ngrams else 0.0

    return round(score, 3), sorted(overlap)
