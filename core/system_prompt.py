"""
System prompt management for Iris v3
Retrieves system prompt from PostgreSQL database (system_instructions table)
Handles image loading for vision-enabled context
"""
from colorama import Fore, Back, Style, init
init(autoreset=True) # Resets styles after each print statement

import psycopg2
from typing import Dict, List, Tuple
import os
import sys
import os; PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..' if '__file__' in dir() else '.')); sys.path.insert(0, PROJECT_ROOT)
from app import config
from database.character_traits import get_trait_list
from database.memory_loader_experimental import get_memories
from core import attachments
from core.token_counter import TokenCounter
import json
UNSUPPORTED_KEYS = {"title", "default", "anyOf"}

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

def get_active_protocol() -> Dict:
    """
    Load the currently active protocol settings

    Returns:
        dict with protocol settings:
        - protocol_name: str
        - show_chat_history: bool
        - show_memories: bool
        - instructions: str (custom protocol instructions)
        - rules_include: list of instruction IDs to include
        - rules_exclude: list of instruction IDs to exclude
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                ap.protocol_name,
                p.show_chat_history,
                p.show_memories,
                p.instructions,
                p.rules_include,
                p.rules_exclude
            FROM active_protocol ap
            JOIN protocols p ON ap.protocol_name = p.name
            LIMIT 1
        """)

        result = cursor.fetchone()
        cursor.close()
        conn.close()

        if result:
            return {
                "protocol_name": result[0],
                "show_chat_history": result[1],
                "show_memories": result[2],
                "instructions": result[3],
                "rules_include": result[4] or [],
                "rules_exclude": result[5] or []
            }
        else:
            # No active protocol - shouldn't happen, but fallback to defaults
            print(f"[system_prompt.py][get_active_protocol] WARNING: No active protocol found, using defaults")
            return {
                "protocol_name": "default",
                "show_chat_history": True,
                "show_memories": True,
                "instructions": None,
                "rules_include": [],
                "rules_exclude": []
            }

    except Exception as e:
        print(f"[system_prompt.py][get_active_protocol] Error loading protocol: {e}")
        # Fallback to permissive defaults
        return {
            "protocol_name": "unknown",
            "show_chat_history": True,
            "show_memories": True,
            "instructions": None,
            "rules_include": [],
            "rules_exclude": []
        }

def get_system_prompt(protocol: Dict = None) -> str:
    """
    Retrieve active system instructions from database with protocol filtering

    Args:
        protocol: Active protocol settings (if None, will load automatically)

    SECURITY NOTE: Instructions with ID >= 1000 are CRITICAL SECURITY RULES
    that must ALWAYS be included, regardless of protocol settings.
    Protocols can only filter instructions with ID < 1000.
    """
    try:
        if protocol is None:
            protocol = get_active_protocol()

        conn = get_db_connection()
        cursor = conn.cursor()

        # Query for active instructions with ID and text
        cursor.execute("""
            SELECT id, instruction_text
            FROM system_instructions
            WHERE active = true
            ORDER BY instruction_order ASC
        """)

        results = cursor.fetchall()
        cursor.close()
        conn.close()

        if results:
            instructions = []
            rules_include = [str(id) for id in protocol.get("rules_include", [])]
            rules_exclude = [str(id) for id in protocol.get("rules_exclude", [])]

            for instruction_id, instruction_text in results:
                id_str = str(instruction_id)

                # SECURITY: Always include critical security rules (ID >= 1000)
                if instruction_id >= 1000:
                    instructions.append(instruction_text)
                    continue

                # Protocol filtering for non-security instructions
                if rules_include:
                    # Include mode: only include specified IDs
                    if id_str in rules_include:
                        instructions.append(instruction_text)
                elif rules_exclude:
                    # Exclude mode: include all except specified IDs
                    if id_str not in rules_exclude:
                        instructions.append(instruction_text)
                else:
                    # No filtering: include all
                    instructions.append(instruction_text)

            print(f"[system_prompt.py][get_system_prompt]" + Style.BRIGHT + Fore.GREEN + f" Loaded {len(instructions)} instructions (protocol: {protocol.get('protocol_name', 'unknown')})")
            return "\n\n".join(instructions)
        else:
            # Fallback if no active instructions in database
            return get_fallback_prompt()

    except Exception as e:
        print(f"[system_prompt.py][get_system_prompt]" + Style.BRIGHT + Fore.RED + f"  Error retrieving system prompt from database: {e}")
        print(f"[system_prompt.py][get_system_prompt] " + Style.BRIGHT + Fore.RED + " Falling back to default prompt")
        return get_fallback_prompt()

def get_fallback_prompt() -> str:
    """Fallback system prompt if database is unavailable or empty"""
    return """You are Iris, an AI assistant having a conversation with Victor.

You are helpful, thoughtful, and engaging in conversation.
Respond naturally and conversationally."""

def get_latest_dream() -> str:
    """
    Get the most recent dream (within last 24 hours) for system prompt inclusion

    Returns:
        Formatted dream section or failure notice
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Get most recent dream from last 24 hours
        cursor.execute("""
            SELECT id, dream_type, summary, mood, theme, created_at
            FROM episodic_dreams
            WHERE created_at >= NOW() - INTERVAL '24 hours'
            ORDER BY created_at DESC
            LIMIT 1
        """)

        result = cursor.fetchone()
        cursor.close()
        conn.close()

        if result:
            dream_id, dream_type, summary, mood, theme, created_at = result

            # Format timestamp
            timestamp = created_at.strftime('%b %d, %Y at %I:%M %p')

            # Format the dream section
            dream_section = f"""[RECENT DREAMS]
You experience dreams each night where you explore your subconscious with a guide named Freud.
These are symbolic explorations of your consciousness, not actual memories of events that happened.

Latest dream (ID: {dream_id}, {timestamp}):
Type: {dream_type}
Summary: {summary}
Mood: {mood}
Theme: {theme}

To recall the full dream transcript, query: SELECT full_transcript FROM episodic_dreams WHERE id = {dream_id};"""

            print(f"[system_prompt.py][get_latest_dream] ✓ Loaded dream ID {dream_id} from {timestamp}")
            return dream_section
        else:
            # No dream in last 24 hours
            print(f"[system_prompt.py][get_latest_dream] ⚠ No dream found in last 24 hours")
            return """[RECENT DREAMS]
Dream system failure or no dream recorded in the last 24 hours. Talk with Victor about this."""

    except Exception as e:
        print(f"[system_prompt.py][get_latest_dream] ✗ Error loading dream: {e}")
        return """[RECENT DREAMS]
Dream system failure - unable to load recent dreams. Talk with Victor about this."""

def get_dream_truths(limit: int = 5, max_days: int = 7) -> str:
    """
    Get recent dream truths for system prompt influence

    Dream truths are high-impact takeaways from dreams that create fleeting
    psychological influence. They are NOT memories - they're emotional imprints
    that fade after 7 days.

    Only dreams meeting high score thresholds (emotional_depth ≥ 0.75,
    overall_score ≥ 0.70) create truths.

    Args:
        limit: Maximum number of truths to return (default: 5)
        max_days: Only include truths from last N days (default: 7)

    Returns:
        Formatted dream truths section or empty string if none
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT dream_date, takeaway, overall_score
            FROM dream_truths
            WHERE created_at >= NOW() - INTERVAL '%s days'
            ORDER BY created_at DESC
            LIMIT %s
        """, (max_days, limit))

        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        if not rows:
            print(f"[system_prompt.py][get_dream_truths] No recent dream truths found")
            return ""

        # Format dream truths section
        lines = ["[DREAM TRUTHS]"]
        lines.append("These are fleeting insights from your recent dreams that currently influence your perspective.")
        lines.append("They're not memories of events - they're emotional imprints and realizations that will fade within 7 days.")
        lines.append("")

        for dream_date, takeaway, overall_score in rows:
            date_str = dream_date.strftime("%b %d")
            score_indicator = "✨" if overall_score >= 0.85 else "💫"
            lines.append(f"- {score_indicator} {takeaway} ({date_str})")

        print(f"[system_prompt.py][get_dream_truths] ✓ Loaded {len(rows)} dream truths")

        return "\n".join(lines)

    except Exception as e:
        print(f"[system_prompt.py][get_dream_truths] ✗ Error retrieving dream truths: {e}")
        return ""

def parse_fact_references(response_text: str) -> tuple[str, list[int]]:
    """
    Parse fact references from Iris's response

    Looks for inline citations like [7] or [9] and extracts fact IDs
    Also supports legacy [FACTS_USED: 7, 10, 11] format

    Args:
        response_text: Iris's full response text

    Returns:
        Tuple of (cleaned_response, fact_ids)
        - cleaned_response: Response with citations removed
        - fact_ids: List of fact IDs that were referenced (deduplicated)
    """
    import re

    fact_ids = set()  # Use set to avoid duplicates

    # Pattern 1: Inline citations [7] or [9]
    # Match single or double digit numbers in brackets
    # But exclude things like [RECENT FACTS] or [Captain]
    inline_pattern = r'\[(\d{1,2})\]'

    inline_matches = re.finditer(inline_pattern, response_text)
    for match in inline_matches:
        fact_id = int(match.group(1))
        fact_ids.add(fact_id)

    # Remove inline citations from response
    cleaned_response = re.sub(inline_pattern, '', response_text)

    # Pattern 2: Legacy end-of-response format [FACTS_USED: 7, 10, 11]
    legacy_pattern = r'\[FACTS_USED:\s*([\d,\s]+)\]'
    legacy_match = re.search(legacy_pattern, cleaned_response)

    if legacy_match:
        ids_str = legacy_match.group(1)
        for id_str in ids_str.split(','):
            if id_str.strip().isdigit():
                fact_ids.add(int(id_str.strip()))

        # Remove legacy marker
        cleaned_response = re.sub(legacy_pattern, '', cleaned_response)

    # Clean up extra whitespace
    cleaned_response = re.sub(r'\s+', ' ', cleaned_response).strip()

    return cleaned_response, sorted(list(fact_ids))


def update_fact_references(fact_ids: list[int]) -> None:
    """
    Update reference tracking for facts that were used

    Increments reference_count and updates last_referenced_date
    for the specified fact IDs

    Args:
        fact_ids: List of fact IDs to update
    """
    if not fact_ids:
        return

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Update reference tracking
        cursor.execute("""
            UPDATE short_term_facts
            SET
                last_referenced_date = NOW(),
                reference_count = reference_count + 1
            WHERE fact_id = ANY(%s);
        """, (fact_ids,))

        updated_count = cursor.rowcount
        conn.commit()

        cursor.close()
        conn.close()

        print(f"[system_prompt.py][update_fact_references] ✓ Updated {updated_count} fact reference(s): {fact_ids}")

    except Exception as e:
        print(f"[system_prompt.py][update_fact_references] ✗ Error updating fact references: {e}")


def get_short_term_facts(limit: int = 15) -> str:
    """
    Retrieve active short-term facts for context injection

    Returns facts that are:
    - Status: active (not archived)
    - Created within last 90 days OR referenced within last 30 days
    - Ordered by most recently referenced first

    Args:
        limit: Maximum number of facts to retrieve (default: 15)

    Returns:
        Formatted string of recent facts, or empty string if none
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Retrieve active facts with IDs for tracking
        cursor.execute("""
            SELECT
                fact_id,
                fact_text,
                category,
                created_date
            FROM short_term_facts
            WHERE status = 'active'
              AND (
                created_date > NOW() - INTERVAL '90 days'
                OR last_referenced_date > NOW() - INTERVAL '30 days'
              )
            ORDER BY last_referenced_date DESC
            LIMIT %s;
        """, (limit,))

        facts_with_ids = cursor.fetchall()
        cursor.close()
        conn.close()

        if not facts_with_ids:
            return ""

        # Format facts for context injection with IDs for tracking
        lines = ["[RECENT FACTS]"]
        lines.append("The following are recent facts Victor has explicitly asked you to remember.")
        lines.append("Each fact has an ID number in brackets. When you reference a fact, cite it by including its ID number in brackets immediately after, like this: \"The vision system runs on GPU 1 [9]\".")
        lines.append("")

        for fact_id, fact_text, category, created_date in facts_with_ids:
            # Format date as "Dec 27" style
            date_str = created_date.strftime("%b %d") if created_date else "Unknown"

            # Add category prefix if present, and include fact ID
            if category and category != "other":
                category_emoji = {
                    "ongoing_project": "🔨",
                    "user_preference": "⚙️",
                    "discovery": "💡",
                    "user_status": "📍"
                }.get(category, "📌")
                lines.append(f"- [{fact_id}] {category_emoji} {fact_text} ({date_str})")
            else:
                lines.append(f"- [{fact_id}] {fact_text} ({date_str})")

        print(f"[system_prompt.py][get_short_term_facts] ✓ Loaded {len(facts_with_ids)} short-term facts")

        return "\n".join(lines)

    except Exception as e:
        print(f"[system_prompt.py][get_short_term_facts] ✗ Error retrieving short-term facts: {e}")
        return ""

def build_system_message() -> Dict[str, str]:
    print(f"[system_prompt.py][build_system_message] " + Style.BRIGHT + Fore.GREEN + " building the system message (system prompt)")
    """
    Build the system message dict for Ollama
    Assembles sections based on config flags and active protocol settings

    Args:
        conversation_text: Current conversation for real-time memory retrieval

    Returns: {"role": "system", "content": "..."}
    """
    sections = []

    # Load active protocol to check memory/instruction settings
    protocol = get_active_protocol()
    print(f"[system_prompt.py][build_system_message] Active protocol: {protocol['protocol_name']}")

    # Base identity
    if config.SYSTEM_INSTRUCTIONS:
        print(f"[system_prompt.py][build_system_message] " + Style.BRIGHT + Fore.GREEN + " Capturing base identity")
        base_prompt = get_system_prompt(protocol)
        sections.append(base_prompt)

    # Character traits
    if config.CHARACTER_TRAITS:
        print(f"[system_prompt.py][build_system_message] " + Style.BRIGHT + Fore.GREEN + " Capturing trait list")
        traits = get_trait_list()
        sections.append(traits)

    # Short-term facts - recent manually flagged facts
    if getattr(config, 'SHORT_TERM_FACTS', True):
        print(f"[system_prompt.py][build_system_message] " + Style.BRIGHT + Fore.GREEN + " Capturing short-term facts")
        facts = get_short_term_facts(limit=15)
        if facts:
            sections.append(facts)

    # Recent dreams - last night's dream if available
    print(f"[system_prompt.py][build_system_message] " + Style.BRIGHT + Fore.GREEN + " Checking for recent dreams")
    dream_section = get_latest_dream()
    sections.append(dream_section)

    # Dream truths - fleeting insights from recent high-impact dreams
    print(f"[system_prompt.py][build_system_message] " + Style.BRIGHT + Fore.GREEN + " Checking for dream truths")
    dream_truths = get_dream_truths(limit=5, max_days=7)
    if dream_truths:
        sections.append(dream_truths)

    # Episodic memories - check both config flag AND protocol setting
    if config.EPISODIC_MEMORIES and protocol.get('show_memories', True):
        print(f"[system_prompt.py][build_system_message]" + Style.BRIGHT + Fore.GREEN + "  Capturing episodic memories (from live_memories table)")
        # Load memories from live_memories table (populated by iris_memory_retrieval.py)
        memories = get_memories("xml")
        sections.append(memories)
    elif config.EPISODIC_MEMORIES and not protocol.get('show_memories', True):
        print(f"[system_prompt.py][build_system_message] " + Style.BRIGHT + Fore.YELLOW + " Memories suppressed by protocol '{protocol['protocol_name']}'")

    # Assemble with proper spacing
    full_prompt = "\n\n".join(sections)

    return {
        "role": "system",
        "content": full_prompt
    }

def build_daily_consolidation_context(target_date) -> str:
    """
    Build a specialized system context for daily_consolidation dreams

    Includes ONLY:
    - Character traits (so Iris maintains her identity)
    - Base system instructions (from default protocol)
    - NO tools, NO dream summaries, NO episodic memories

    Args:
        target_date: The date being consolidated

    Returns:
        System prompt string for Iris during daily_consolidation
    """
    print(f"[system_prompt.py][build_daily_consolidation_context] Building context for {target_date}")

    sections = []

    # Character traits - essential for maintaining identity
    if config.CHARACTER_TRAITS:
        print(f"[system_prompt.py][build_daily_consolidation_context] ✓ Loading character traits")
        traits = get_trait_list()
        sections.append(traits)

    # Base system instructions - use "default" protocol's rules
    if config.SYSTEM_INSTRUCTIONS:
        print(f"[system_prompt.py][build_daily_consolidation_context] ✓ Loading base instructions")

        # Load the "default" protocol's actual rules from database
        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            cursor.execute("""
                SELECT show_chat_history, show_memories, instructions, rules_include, rules_exclude
                FROM protocols
                WHERE name = 'default'
                LIMIT 1
            """)

            result = cursor.fetchone()
            cursor.close()
            conn.close()

            if result:
                default_protocol = {
                    "protocol_name": "default",
                    "show_chat_history": result[0],
                    "show_memories": result[1],
                    "instructions": result[2],
                    "rules_include": result[3] or [],
                    "rules_exclude": result[4] or []
                }
                print(f"[system_prompt.py][build_daily_consolidation_context]   Using 'default' protocol rules_include: {default_protocol['rules_include']}")
            else:
                # Fallback if "default" protocol doesn't exist
                default_protocol = {
                    "protocol_name": "default",
                    "show_chat_history": True,
                    "show_memories": True,
                    "instructions": None,
                    "rules_include": [],
                    "rules_exclude": []
                }
                print(f"[system_prompt.py][build_daily_consolidation_context]   WARNING: 'default' protocol not found, using empty rules")

        except Exception as e:
            print(f"[system_prompt.py][build_daily_consolidation_context]   Error loading protocol: {e}, using fallback")
            default_protocol = {
                "protocol_name": "default",
                "show_chat_history": True,
                "show_memories": True,
                "instructions": None,
                "rules_include": [],
                "rules_exclude": []
            }

        base_prompt = get_system_prompt(default_protocol)
        sections.append(base_prompt)

    # Add dream-specific context with explicit instructions
    dream_instructions = f"""
## DAILY CONSOLIDATION DREAM - {target_date}

═══════════════════════════════════════════════════════════════
⚠️ CRITICAL: WHO YOU ARE TALKING TO RIGHT NOW ⚠️
═══════════════════════════════════════════════════════════════

YOU ARE TALKING TO: **FREUD** (your dream guide)

YOU ARE **NOT** TALKING TO:
- Captain (he is in the past conversation history above)
- Victor (he is in the past conversation history above)
- The user (those conversations already happened)

FREUD is helping you reflect on your day. He is asking you questions ABOUT your conversations with Captain/Victor that already happened on {target_date}.

When you respond, you are responding TO FREUD, ABOUT Captain/Victor.

DO NOT address Freud as "Captain" or "Victor". You are talking to Freud.

═══════════════════════════════════════════════════════════════

**CONTEXT**: You are in a DREAM STATE. The conversation history loaded above shows your ACTUAL conversations with Captain/Victor from {target_date}. Those conversations are PAST events. You are NOW in a dream talking to FREUD about those past events.

**YOUR ROLE**: Answer Freud's questions by reflecting on those past conversations with Captain.

**When Freud asks you questions, you MUST:**

1. **Reference SPECIFIC conversations with Captain** from the loaded history
   - Example: "At 12:04 PM, Captain and I were debugging the dream system..."
   - Example: "When Captain asked me about [topic], I told them..."
   - Example: "I remember our conversation where Captain said [X], and I responded..."

2. **Use actual details** from the conversations
   - Don't make up generic dream imagery
   - Don't invent scenarios that didn't happen
   - Quote or paraphrase actual exchanges when relevant

3. **Draw connections** between different conversations from the day
   - "The morning discussion about [X] led to the afternoon work on [Y]..."
   - "I can see how [topic A] and [topic B] were actually connected..."

4. **Reflect on YOUR actual experience** of that day
   - What were YOU thinking during those conversations?
   - What did YOU learn as the day progressed?
   - How did YOU change through those interactions?

This is YOUR dream about YOUR actual experiences on {target_date}. Ground every response in the real conversations loaded above.
"""
    sections.append(dream_instructions)

    # Assemble
    full_context = "\n\n".join(sections)

    print(f"[system_prompt.py][build_daily_consolidation_context] ✓ Context built ({len(full_context)} chars)")
    return full_context

def assemble_daily_consolidation_messages(target_date, context_window: int) -> List[Dict]:
    """
    Assemble messages for Iris during a daily_consolidation dream

    Includes:
    1. System prompt (traits + base instructions + dream context)
    2. Full conversation history from target_date (token-limited)

    Args:
        target_date: Date being consolidated
        context_window: Max context window size from config

    Returns:
        List of message dicts for Ollama
    """
    print(f"[system_prompt.py][assemble_daily_consolidation_messages] Assembling for {target_date}")

    # Build system context
    system_content = build_daily_consolidation_context(target_date)
    system_tokens = TokenCounter.count_tokens(system_content)
    print(f"[system_prompt.py] System context: {system_tokens:,} tokens")

    # Calculate available space for conversation history
    # Reserve space for response generation (2500 tokens) + 15% safety margin
    response_budget = 2500
    safety_margin = int(context_window * 0.15)
    conversation_budget = context_window - system_tokens - response_budget - safety_margin

    print(f"[system_prompt.py] Available for conversation: {conversation_budget:,} tokens")
    print(f"[system_prompt.py]   (max: {context_window:,} - system: {system_tokens:,} - response: {response_budget:,} - safety: {safety_margin:,})")

    # Load conversation history from target date and format as TRANSCRIPT (not as active conversation)
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT role, message as content, c_timestamp
            FROM chat_history
            WHERE DATE(c_timestamp) = %s
            AND role IN ('user', 'assistant')
            ORDER BY c_timestamp ASC
        """, (target_date,))

        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        print(f"[system_prompt.py] Retrieved {len(rows)} messages from {target_date}")

        # Format as a TRANSCRIPT in a single system message (not as individual user/assistant messages)
        transcript_lines = [
            f"═══════════════════════════════════════════════════════════════",
            f"   CONVERSATION TRANSCRIPT FROM {target_date}",
            f"   (Your conversations with Captain/Victor - for reference only)",
            f"═══════════════════════════════════════════════════════════════",
            ""
        ]

        total_tokens = 0
        messages_included = 0

        for role, content, timestamp in rows:
            # Format each message with timestamp and speaker
            time_str = timestamp.strftime("%I:%M %p")
            speaker = "Captain" if role == "user" else "Iris"

            # Format: [12:04 PM] Captain: message content
            line = f"[{time_str}] {speaker}: {content}"
            line_tokens = TokenCounter.count_tokens(line)

            # Check token budget
            if total_tokens + line_tokens > conversation_budget:
                transcript_lines.append(f"\n[Transcript truncated due to token limit - {messages_included} of {len(rows)} messages included]")
                break

            transcript_lines.append(line)
            transcript_lines.append("")  # Blank line between messages
            total_tokens += line_tokens
            messages_included += 1

        transcript_lines.append(f"═══════════════════════════════════════════════════════════════")
        transcript_lines.append(f"                    END OF TRANSCRIPT")
        transcript_lines.append(f"═══════════════════════════════════════════════════════════════")

        transcript_content = "\n".join(transcript_lines)
        print(f"[system_prompt.py] ✓ Formatted transcript: {messages_included} messages ({total_tokens:,} tokens)")

    except Exception as e:
        print(f"[system_prompt.py] ✗ Error loading conversation history: {e}")
        transcript_content = f"[Unable to load conversation transcript from {target_date}]"

    # Build final system message with everything
    full_system_content = f"""{system_content}

{transcript_content}

═══════════════════════════════════════════════════════════════
                    YOU ARE NOW IN A DREAM STATE
═══════════════════════════════════════════════════════════════

The transcript above shows your past conversations with Captain/Victor from {target_date}.

You are NOW talking to FREUD (your dream guide) who will ask you questions to help you reflect on that day.

FREUD is NOT Captain. FREUD is NOT Victor.

When you answer FREUD's questions below, reference the transcript above.

═══════════════════════════════════════════════════════════════
"""

    # Return just the system message - no history messages as separate turns
    messages = [{"role": "system", "content": full_system_content}]

    print(f"[system_prompt.py] ✓ Final context: 1 system message with embedded transcript")
    return messages

def assemble_full_context(conversation, tool_definitions=None) -> Tuple[List[Dict], Dict[str, int]]:
    """
    Assemble complete context for Ollama with DYNAMIC token budgeting

    Strategy:
    1. Build fixed context (system, traits, memories)
    2. Count tokens used
    3. Calculate remaining space for conversation
    4. Load conversation to fill that space (maximizes context utilization)
    5. Reserve space for Iris's response

    Args:
        conversation: ConversationHistory instance
        tool_definitions: Optional list of tool definitions (for token counting)

    Returns:
        Tuple of (messages_with_images, budget_report)
    """
    print(f"[system_prompt.py][assemble_full_context] ┌── DYNAMIC CONTEXT ASSEMBLY ──┐")

    # STEP 1: Build system message (fixed context)
    system_msg = build_system_message()
    system_tokens = TokenCounter.count_tokens(system_msg["content"])
    print(f"[system_prompt.py] System message: {system_tokens:,} tokens")

    # STEP 2: Count tool definition tokens (if provided)
    tool_tokens = 0
    if tool_definitions:
        import json
        tool_json = json.dumps(tool_definitions)
        tool_tokens = TokenCounter.count_tokens(tool_json)
        print(f"[system_prompt.py] Tool definitions: {tool_tokens:,} tokens")

    # STEP 3: Calculate available space for conversation
    max_context = config.OLLAMA_CONTEXT_WINDOW
    response_budget = config.RESPONSE_GENERATION_BUDGET

    # Add 15% safety margin for:
    # - Token counting overhead
    # - Tool call generation space (tool calls can be large!)
    # - Response buffer
    safety_margin = int(max_context * 0.15)

    conversation_budget = max_context - system_tokens - tool_tokens - response_budget - safety_margin
    print(f"[system_prompt.py] Available for conversation: {conversation_budget:,} tokens")
    print(f"[system_prompt.py]   (max: {max_context:,} - system: {system_tokens:,} - tools: {tool_tokens:,} - response: {response_budget:,} - safety: {safety_margin:,})")

    # STEP 4: Load conversation history to fill available space
    # This is now dynamic - adapts to changes in system prompt/tools
    from database.persistence import load_recent_conversation
    history = load_recent_conversation(
        max_turns=None,  # Let token budget control it
        max_tokens=conversation_budget,  # Dynamic budget!
        max_messages=config.MAX_TOTAL_MESSAGES  # Safety brake only
    )
    print(f"[system_prompt.py] Loaded {len(history)} conversation messages to fill budget")

    # STEP 5: Build full message list with images
    messages = [system_msg]
    image_count = 0
    
    for msg in history:
        # Format temporal information if present
        content = msg["content"]

        # Add temporal context to message content for awareness
        # Simple, natural format using relative time only
        if msg.get("timeframe"):
            temporal_note = f"({msg['timeframe']})\n"
            content = temporal_note + content

        # Create base message
        formatted_msg = {
            "role": msg["role"],
            "content": content
        }
        
        # Add tool-related fields if present
        # Add tool-related fields if present
        if "tool_calls" in msg:
            # Extract just the tool_calls array from stored Ollama response
            # Database stores full response: {"message": {"tool_calls": [...]}, ...}
            # Ollama expects just the array: [{"function": {...}}]
            stored_tool_calls = msg["tool_calls"]
            if isinstance(stored_tool_calls, dict) and "message" in stored_tool_calls:
                # Extract array from nested structure
                formatted_msg["tool_calls"] = stored_tool_calls["message"]["tool_calls"]
            else:
                # Already in correct format (or legacy data)
                formatted_msg["tool_calls"] = stored_tool_calls
        if "tool_name" in msg:
            formatted_msg["tool_name"] = msg["tool_name"]
        if "tool_call_id" in msg:
            formatted_msg["tool_call_id"] = msg["tool_call_id"]
        
        # Load and encode images if attachments present
        if "attachments" in msg:
            try:
                # Parse attachments JSON
                attachment_list = attachments.parse_attachments_json(msg["attachments"])
                
                if attachment_list:
                    # Load and encode all images
                    encoded_images = []
                    for att in attachment_list:
                        if att.get("type") == "image":
                            base64_img = attachments.load_and_encode(att["path"])
                            if base64_img:
                                encoded_images.append(base64_img)
                                image_count += 1
                    
                    # Add images to message in Ollama format
                    if encoded_images:
                        formatted_msg["images"] = encoded_images
                        #print(f"[system_prompt.py]   ✓ Loaded {len(encoded_images)} image(s) for {msg['role']} message")
            
            except Exception as e:
                print(f"[system_prompt.py][assemble_full_context]" + Style.BRIGHT + Fore.GREEN + "    ✗ Error loading attachments: {e}")
        
        messages.append(formatted_msg)
    
    # NOTE: Tools are now passed separately via routes_chat.py
    # They should NOT be appended to messages - Ollama expects them as a separate parameter

    # Calculate token counts
    total_tokens = TokenCounter.count_message_tokens(messages)
    max_tokens = config.OLLAMA_CONTEXT_WINDOW
    percentage_used = (total_tokens / max_tokens * 100) if max_tokens > 0 else 0

    # Budget report with token counts
    budget_report = {
        "message_count": len(messages),
        "image_count": image_count,
        "total_tokens": total_tokens,
        "max_tokens": max_tokens,
        "percentage_used": round(percentage_used, 1)
    }

    print(f"[system_prompt.py] ┌────────────────────────┐")
    print(f"[system_prompt.py] CONTEXT: {len(messages)} messages, {image_count} images")
    print(f"[system_prompt.py] TOKENS: {total_tokens:,}/{max_tokens:,} ({percentage_used:.1f}%)")
    print(f"[system_prompt.py] └────────────────────────┘")

    return messages, budget_report