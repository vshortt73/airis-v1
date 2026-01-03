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

def _fetch_memory_data():
    """Shared function to fetch memory data from database"""
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""SELECT lm.*,
                               em.takeaway,
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
            print(f"[memory_loader.py] Loaded {len(mems)} memories from database")
            return mems
    except Exception as e:
        print(f"[memory_loader_experimental.py] Error fetching memories: {e}")
        return []

def _clean_field(text, prefixes_to_remove=None):
    """Clean and normalize field text"""
    if not text:
        return ""
    
    text = text.strip()
    
    if prefixes_to_remove:
        for prefix in prefixes_to_remove:
            if text.lower().startswith(prefix.lower()):
                text = text[len(prefix):].strip()
    
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
        temporal = _clean_field(row.get("temporal_description", ""))
        bias = _clean_field(row.get("emotion_bias", ""))
        
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
    
    header = "[LONG TERM MEMORIES]\nThese are structured memories from past conversations. Each memory block contains labeled fields describing what happened, when, and what you learned. Reference these memories naturally when they're relevant to the current conversation.\n\n"
    
    return header + block

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
        temporal = _clean_field(row.get("temporal_description", ""))
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
    
    header = "[LONG TERM MEMORIES]\nYou have memories from past conversations with Victor. These memories help you maintain continuity and understanding. Reference them naturally when relevant:\n\n"
    
    return header + "\n\n".join(memories)

# ============================================================================
# FORMAT C: XML HYBRID (Anthropic recommended)
# ============================================================================

def get_memories_xml() -> Optional[str]:
    """
    FORMAT C: XML structure with natural language content

    Pros: Structured (XML tags), natural content, metadata in attributes
    Cons: Slightly more verbose than pure conversational
    """
    mems = _fetch_memory_data()
    if not mems:
        return None

    # Sort memories by tier (Tier 1 first, most relevant)
    mems_sorted = sorted(mems, key=lambda x: x.get("tier", 3))

    memories = []

    for row in mems_sorted:
        # Extract and clean fields
        takeaway = _clean_field(row.get("takeaway", ""), ["[relational]", "adaptive"])
        event = _clean_field(row.get("summary_event", ""))
        temporal = _clean_field(row.get("temporal_description", ""))
        emotion = _clean_field(row.get("emotion_label", ""))
        category = _clean_field(row.get("category", ""))
        significance = _clean_field(row.get("summary_significance", ""))
        tier = row.get("tier", 3)  # Default to tier 3 if not set

        # Map tier to relevance level
        tier_label = {1: "primary", 2: "supporting", 3: "associative", 4: "peripheral"}.get(tier, "associative")

        # Build XML with natural language content
        attributes = []
        attributes.append(f'relevance="{tier_label}"')  # Add tier as relevance attribute
        if temporal:
            attributes.append(f'when="{temporal}"')
        if emotion:
            attributes.append(f'emotion="{emotion}"')
        if category:
            attributes.append(f'category="{category}"')

        attr_string = " ".join(attributes)

        # Build narrative content
        content_parts = []
        if event:
            content_parts.append(event)
        if takeaway:
            content_parts.append(f"Key insight: {takeaway}")
        if significance:
            content_parts.append(f"Why it matters: {significance}")

        content = " ".join(content_parts)

        if content:
            memories.append(f"<memory {attr_string}>\n{content}\n</memory>")

    header = """[LONG TERM MEMORIES]
You have episodic memories from past conversations. Each memory is tagged with:
- relevance: How directly it relates to current topics (primary > supporting > associative > peripheral)
- when: Temporal context (when this happened)
- emotion: Emotional context at the time
- category: Type of interaction

Memory priority:
- PRIMARY memories are directly relevant to current conversation topics
- SUPPORTING memories provide strong contextual relevance
- ASSOCIATIVE memories are thematically connected
- PERIPHERAL memories are weakly connected background context

When a memory is relevant to the current conversation:
- Prioritize PRIMARY and SUPPORTING memories in your responses
- Reference memories naturally ("I remember when we...")
- Use the insights to inform your response
- Connect past experiences to present context

Your memories (sorted by relevance):

"""

    return header + "\n\n".join(memories)

# ============================================================================
# MAIN FUNCTION - Switch between formats
# ============================================================================

def get_memories(format_type: str = "structured") -> Optional[str]:
    """
    Get memories in specified format
    
    Args:
        format_type: "structured", "conversational", or "xml"
    
    Returns:
        Formatted memory string
    """
    if format_type == "structured":
        return get_memories_structured()
    elif format_type == "conversational":
        return get_memories_conversational()
    elif format_type == "xml":
        return get_memories_xml()
    else:
        print(f"[memory_loader.py] Unknown format type: {format_type}, defaulting to structured")
        return get_memories_structured()

if __name__ == "__main__":
    print(get_memories())