"""
Character triat engine for Iris v3
Handles handles all aspects of character trait and their management.
"""

import psycopg2
from psycopg2.extras import DictCursor
from typing import List, Dict, Optional
from datetime import datetime
import uuid
import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)
from app import config
from core.token_counter import TokenCounter

def get_db_connection():
    """Create database connection"""
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

def _fetch_memory_data():
    """Shared function to fetch memory data from database"""
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""SELECT lm.*,
                               em.takeaway,
                               em.key_details,
                               em.summary_context,
                               em.summary_significance,
                               em.summary_tone,
                               em.summary_event,
                               em.emotion_label,
                               em.voice,
                               em.category
                               FROM live_memories lm
                                JOIN public.episodic_memories_with_age em on lm.memory_id = em.id
                        """)
            mems = cur.fetchall()
            print(f"[memory_loader_experimental.py] Loaded {len(mems)} memories from database")
            return mems
    except Exception as e:
        print(f"[memory_loader_experimental.py] >>>>>  Error fetching memories: {e}")
        return []

FORMULAIC_PREFIXES = [
    "I learned that ",
    "I realized that ",
    "I know that ",
    "I have learned that ",
    "I understand that ",
    "I noticed that ",
    "I saw that ",
    "I recognized that ",
    "I carry forward the insight that ",
    "I carry forward the sense that ",
]

def _clean_field(text, prefixes_to_remove=None):
    """Clean and normalize field text, stripping formulaic LLM prefixes"""
    if not text:
        return ""

    text = text.strip()

    if prefixes_to_remove:
        for prefix in prefixes_to_remove:
            if text.lower().startswith(prefix.lower()):
                text = text[len(prefix):].strip()

    # Strip formulaic "I learned that..." prefixes from LLM output
    for prefix in FORMULAIC_PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix):]
            # Capitalize first letter after stripping
            if text and text[0].islower():
                text = text[0].upper() + text[1:]
            break

    return text

# ============================================================================
# FORMAT A: STRUCTURED BLOCKS (Current format)
# ============================================================================

def get_memories_structured() -> Optional[str]:
    """
    FORMAT A: Structured block format with clear field labels
    
    Pros: Very structured, machine-readable, clear fields
    Cons: Not conversational, verbose, LLM must "parse"
    """
    mems = _fetch_memory_data()
    if not mems:
        return None
    
    block = ""
    for row in mems:
        # Clean fields
        takeaway = _clean_field(row.get("takeaway", ""), ["[relational]", "adaptive"])
        summary = row.get("summary_context", "")
        if summary and (summary.lower().startswith("20") or len(summary.split()) < 2):
            summary = ""
        
        significance = _clean_field(row.get("summary_significance", ""))
        tone = _clean_field(row.get("summary_tone", ""))
        event = _clean_field(row.get("summary_event", ""))
        voice = _clean_field(row.get("voice", ""))
        category = _clean_field(row.get("category", ""))
        emotion = _clean_field(row.get("emotion_label", ""))
        #temporal = _clean_field(row.get("temporal_description", ""))
        temporal = "recent"
        #bias = _clean_field(row.get("emotion_bias", ""))
        bias = "neutral"

        # Build block
        block += "-------------------------------------------------------\n"
        if voice or category:
            block += f"          Voice: {voice} | Category: {category}\n"
        if temporal:
            block += f"Temporal Anchor: {temporal} | bias: {bias}\n"
        if emotion:
            block += f"         Emotion: {emotion}\n"
        if takeaway:
            block += f"        Takeaway: {takeaway}\n"
        if summary:
            block += f"         Summary: {summary}\n"
        if significance:
            block += f"    Significance: {significance}\n"
        if tone:
            block += f"            Tone: {tone}\n"
        if event:
            block += f"           Event: {event}\n"
    
    return "<your_memories>\n" + block + "</your_memories>"

# ============================================================================
# FORMAT B: CONVERSATIONAL NARRATIVE
# ============================================================================

def get_memories_conversational() -> Optional[str]:
    """
    FORMAT B: Pure conversational format - memories as natural language
    
    Pros: Natural language, token-efficient, easy to reference
    Cons: Less structured, harder to extract specific fields
    """
    mems = _fetch_memory_data()
    if not mems:
        return None
    
    memories = []
    
    for row in mems:
        # Extract and clean fields
        takeaway = _clean_field(row.get("takeaway", ""), ["[relational]", "adaptive"])
        event = _clean_field(row.get("summary_event", ""))
        #temporal = _clean_field(row.get("temporal_description", ""))
        temporal = "recent"
        emotion = _clean_field(row.get("emotion_label", ""))
        category = _clean_field(row.get("category", ""))
        
        # Build narrative
        narrative_parts = []
        
        # Temporal context
        if temporal:
            narrative_parts.append(f"{temporal.capitalize()}")
        
        # Event description
        if event:
            narrative_parts.append(f"you and Victor {event.lower() if event else 'had an interaction'}")
        
        # Emotional context
        if emotion and emotion.lower() != "neutral":
            narrative_parts.append(f"You felt {emotion.lower()}")
        
        # Category if relevant
        if category and category.lower() != "general":
            narrative_parts.append(f"This was a {category.lower()} conversation")
        
        # Key takeaway
        if takeaway:
            narrative_parts.append(f"The key insight: {takeaway}")
        
        if narrative_parts:
            memory_text = ". ".join(narrative_parts) + "."
            memories.append(memory_text)
    
    return "<your_memories>\n" + "\n\n".join(memories) + "\n</your_memories>"

# ============================================================================
# FORMAT C: XML HYBRID (Anthropic recommended)
# ============================================================================

def get_memories_xml(limit: int = 10) -> Optional[str]:
    """
    FORMAT C: XML structure with concise, actionable content

    Leads with takeaway (the actionable insight), adds significance
    only when it adds new information. Drops tier 4 (peripheral)
    memories entirely — they're too weakly related to be useful.

    Args:
        limit: Maximum number of memories to return (default 10)
    """
    mems = _fetch_memory_data()
    if not mems:
        return None

    # Sort memories by tier (Tier 1 first, most relevant)
    mems_sorted = sorted(mems, key=lambda x: x.get("tier", 3))

    memories = []

    for row in mems_sorted:
        tier = row.get("tier", 3)

        # Drop tier 4 (peripheral) — too weakly related to be useful
        if tier >= 4:
            continue

        key_details = _clean_field(row.get("key_details", ""))
        takeaway = _clean_field(row.get("takeaway", ""), ["[relational]", "adaptive"])
        if not key_details and not takeaway:
            continue

        category = _clean_field(row.get("category", ""))

        # Map tier to relevance level
        tier_label = {1: "primary", 2: "supporting", 3: "associative"}.get(tier, "associative")

        # Build attributes
        attributes = [f'relevance="{tier_label}"']
        if category:
            attributes.append(f'category="{category}"')
        attr_string = " ".join(attributes)

        # key_details has specific facts (names, quotes, details)
        # takeaway is generic reflection — use only as fallback
        content = key_details if key_details else takeaway

        memories.append(f"<memory {attr_string}>{content}</memory>")

        if len(memories) >= limit:
            break

    if not memories:
        return None

    return "<your_memories>\n" + "\n".join(memories) + "\n</your_memories>"

# ============================================================================
# MAIN FUNCTION - Switch between formats
# ============================================================================

def get_memories(format_type: str = "structured", limit: int = 10) -> Optional[str]:
    """
    Get memories in specified format

    Args:
        format_type: "structured", "conversational", or "xml"
        limit: Maximum number of memories to return (default 10)

    Returns:
        Formatted memory string
    """
    if format_type == "structured":
        return get_memories_structured()
    elif format_type == "conversational":
        return get_memories_conversational()
    elif format_type == "xml":
        return get_memories_xml(limit)
    else:
        print(f"[memory_loader_experimental.py] Unknown format type: {format_type}, defaulting to structured")
        return get_memories_structured()

# ============================================================================
# SEMANTIC MEMORIES - Distilled knowledge from episodic memory clusters
# ============================================================================

def get_semantic_memories(limit: int = 10) -> Optional[str]:
    """
    Load active semantic memories ordered by reinforcement count.

    Returns XML block for system prompt injection:
    <your_knowledge>
    <insight category="Relational" confirmed="7">Memory text here.</insight>
    </your_knowledge>

    Args:
        limit: Maximum number of semantic memories to return

    Returns:
        Formatted XML string, or None if no semantic memories exist
    """
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT memory_text, category, reinforcement_count
                FROM semantic_memories
                WHERE active = TRUE
                ORDER BY reinforcement_count DESC, last_reinforced_at DESC
                LIMIT %s
            """, (limit,))
            rows = cur.fetchall()
        conn.close()

        if not rows:
            return None

        insights = []
        for row in rows:
            attrs = []
            if row.get('category'):
                attrs.append(f'category="{row["category"]}"')
            if row['reinforcement_count'] > 1:
                attrs.append(f'confirmed="{row["reinforcement_count"]}"')
            attr_str = " " + " ".join(attrs) if attrs else ""
            insights.append(f"<insight{attr_str}>{row['memory_text']}</insight>")

        print(f"[memory_loader_experimental.py] Loaded {len(rows)} semantic memories")
        return "<your_knowledge>\n" + "\n".join(insights) + "\n</your_knowledge>"

    except Exception as e:
        print(f"[memory_loader_experimental.py] Error loading semantic memories: {e}")
        return None


if __name__ == "__main__":
    print(get_memories())