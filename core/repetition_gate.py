"""
Repetition Gate — Application-layer defense against cross-turn repetition.

Local models (Qwen3-32B etc.) are prone to echoing phrases from their own
recent outputs in conversation context.  Sampling penalties help within a
single generation but don't prevent the model from re-using the same
*concepts* across turns.

Two mechanisms:
1. PROACTIVE — build_avoidance_block() extracts distinctive phrases from
   recent assistant messages and injects a <do_not_reuse> XML block into
   the per-turn tail.  The model sees this before generating.
2. DETECTIVE — score_repetition() checks a new response against recent
   messages and returns a 0-1 score for observability / logging.
"""

import re
from collections import Counter
from typing import List, Dict, Optional, Tuple

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
    """Lowercase, strip HTML tags, collapse whitespace."""
    text = re.sub(r'<[^>]+>', ' ', text)       # strip HTML
    text = re.sub(r'\([^)]*\)', ' ', text)     # strip parentheticals
    text = re.sub(r'[*_~`#]', '', text)        # strip markdown
    text = re.sub(r'\s+', ' ', text).strip()
    return text.lower()


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
