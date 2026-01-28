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
from database.fast_reactive_memory import FastReactiveMemory
from core import attachments
from core.token_counter import TokenCounter
from core.emotional_state import get_emotional_tracker
import json
import hashlib

def get_active_seeds(limit: int = 5) -> str:
    """
    Get active seeds (germinating/growing/blooming) for system prompt inclusion

    These are Iris's autonomous wants and desires that she's currently pursuing.
    Showing them in her prompt keeps them in her awareness.

    Args:
        limit: Maximum number of seeds to return (default: 5)

    Returns:
        Formatted seeds section or empty string if none
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, description, status, category, priority, emotional_resonance, planted_at
            FROM seeds
            WHERE status IN ('germinating', 'growing', 'blooming')
            ORDER BY
                CASE status
                    WHEN 'blooming' THEN 1
                    WHEN 'growing' THEN 2
                    WHEN 'germinating' THEN 3
                END,
                priority DESC,
                planted_at DESC
            LIMIT %s
        """, (limit,))

        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        if not rows:
            return ""

        # Format seeds section
        status_emoji = {
            'germinating': '🌱',
            'growing': '🌿',
            'blooming': '🌸'
        }

        lines = ["[ACTIVE SEEDS - Your Motivation Garden]"]
        lines.append("These are wants and desires you've planted - things YOU want to explore, create, or understand.")
        lines.append("Use the 'seed' tool to tend them, add progress notes, or plant new seeds.")
        lines.append("")

        for seed_id, desc, status, category, priority, emotion, planted in rows:
            emoji = status_emoji.get(status, '🌱')
            pri_str = "!" * priority if priority >= 4 else ""

            line = f"- {emoji} #{seed_id} [{status}] {desc}"
            if pri_str:
                line += f" {pri_str}"
            lines.append(line)

            # Add context on second line if available
            details = []
            if category:
                details.append(category)
            if emotion:
                details.append(f"feeling: {emotion}")
            if details:
                lines.append(f"    ({', '.join(details)})")

        print(f"[system_prompt.py][get_active_seeds] ✓ Loaded {len(rows)} active seeds")

        return "\n".join(lines)

    except Exception as e:
        print(f"[system_prompt.py][get_active_seeds] ✗ Error loading seeds: {e}")
        return ""

UNSUPPORTED_KEYS = {"title", "default", "anyOf"}

def hash_compare(text, section):
    
    text = str(text)
    section = str(section)

    # 1. Encode text to bytes (required for hashlib)
    text_bytes = str(text).encode('utf-8')
    # 2. Generate the hash
    hash_obj = hashlib.sha256(text_bytes)
    this_hash = hash_obj.hexdigest()
    #print(f"[system_prompt.py][hash_compare] " + Style.BRIGHT + Fore.CYAN + f"incoming {this_hash}")
    #print(f"[system_prompt.py][hash_compare] " + Style.BRIGHT + Fore.CYAN + f"for {section}")
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        #3. Get the existing hash from last turn
        cursor.execute("""SELECT hash FROM prompt_hashes where section = %s LIMIT 1 """, (section,))
        result = cursor.fetchone()
        cursor.close()
    except Exception as e:
        print(f">>> EXCEPTION {e}")

    #print(f"[system_prompt.py][hash_compare] " + Style.BRIGHT + Fore.CYAN + f"dbase hash {result[0]}")
    if result:

        if str(result[0]) != this_hash:
            print(f"[system_prompt.py][hash_compare] " + Style.BRIGHT + Fore.RED + f"Hash check failed for {section}")
        else:
            print(f"[system_prompt.py][hash_compare] " + Style.BRIGHT + Fore.YELLOW + f"Hash check passed for {section}")
    else:
        print(f"[system_prompt.py][hash_compare] " + Style.BRIGHT + Fore.YELLOW + f"adding hash for section {section}")

    try: 

        #print(f"[system_prompt.py][hash_compare] " + Style.BRIGHT + Fore.GREEN + f"updating the prompt_hashes")
        cursor = conn.cursor()
        cursor.execute(
                """
                INSERT INTO prompt_hashes (section, hash)
                VALUES (%s, %s)
                ON CONFLICT (section)
                DO UPDATE SET hash = EXCLUDED.hash
                """,
                (section, this_hash)
            )
        conn.commit()
        cursor.close()
        conn.close()
         # 3. Return the hexadecimal string
         # return hash_obj.hexdigest()      
    except Exception as e:
        print(f"exception updaing ... {e}")



_fast_memory = None  # Singleton instance
def get_fast_memory():
    """Get or initialize fast reactive memory (singleton)"""
    global _fast_memory
    if _fast_memory is None:
        _fast_memory = FastReactiveMemory()
    return _fast_memory

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
            print(f"[system_prompt.py][get_active_protocol] protocol found {result[0]}. using instruction list: {result[4]} ")
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

        import ast

        # Your input as a string
        input_str = protocol.get("rules_include")
        input_str = str(input_str).replace("[", "")
        input_str = str(input_str).replace("]", "")

        # 1. Convert string representation to a real Python list
        real_list = ast.literal_eval(input_str)

        # 2. Join the list into a single comma-separated string
        include = ",".join(real_list)



        conn = get_db_connection()
        cursor = conn.cursor()

        # Query for active instructions with ID and text
        cursor.execute(f"""
            SELECT id, instruction_text
            FROM system_instructions
            WHERE id in ({include})
            ORDER BY instruction_order ASC
        """)

        results = cursor.fetchall()
        cursor.close()
        conn.close()

        if results:
            instructions = []
            rules_include = [str(id) for id in protocol.get("rules_include", [])]
            rules_exclude = [str(id) for id in protocol.get("rules_exclude", [])]
           # print(f"[system_prompt.py][get_system_prompt]" + Style.BRIGHT + Fore.GREEN + f"instruction list: {rules_include}") 
            for instruction_id, instruction_text in results:
                id_str = str(instruction_id)

                # SECURITY: Always include critical security rules (ID >= 1000)
                if instruction_id >= 1000:
                    instructions.append(instruction_text)
                    continue
              #  print(f"[system_prompt.py][get_system_prompt]" + Style.BRIGHT + Fore.GREEN + f"parsing instruction {instruction_id} from protocol: {protocol.get('protocol_name', 'unknown')})")
                # Protocol filtering for non-security instructions
                if not rules_include:
                   print(f"[system_prompt.py][get_system_prompt]" + Style.BRIGHT + Fore.RED + f"no include rules found for {protocol.get('protocol_name', 'unknown')})")

                if rules_include:
                    # Include mode: only include specified IDs
                    if id_str in rules_include:
                        instructions.append(instruction_text)
                     #   print(f"include TEXT: {instruction_text[:25]}")
                elif rules_exclude:
                    # Exclude mode: include all except specified IDs
                    if id_str not in rules_exclude:
                        instructions.append(instruction_text)
                else:
                    # No filtering: include all
                    instructions.append(instruction_text)
                   # print(f"default TEXT: {instruction_text[:25]}")


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
            timestamp = created_at.strftime('%b %d')

            # Format the dream section - concise: just mood and summary
            dream_section = f"""[RECENT DREAM]
Last night ({timestamp}) you dreamed. Mood: {mood}
Summary: {summary}"""

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

def build_system_message(user_message: str = None, conversation=None, skip_fast_memory: bool = False, context_level: str = "FULL") -> Dict[str, str]:
    fast_context_holder = []
    
    context_level="FULL" # Force full context for all prompt building (cache use)
    Skip_fast_memory="False"

    print(f"[system_prompt.py][build_system_message] " + Style.BRIGHT + Fore.GREEN + f" building the system message (context level: {context_level})")
    """
    Build the system message dict for Ollama
    Assembles sections based on config flags, active protocol, and context level

    Args:
        user_message: Current user message for fast reactive memory
        conversation: ConversationHistory instance (for caching)
        skip_fast_memory: If True, skip fast reactive memory (optimization for reassembly)
        context_level: "GREETING", "TASK", "CONVERSATIONAL", "DEEP", or "FULL" (no pruning)

    Returns: {"role": "system", "content": "..."}
    """


    sections = []

    # Load system components (cached if conversation provided)
    if conversation:
        # Use cached components
        cache = conversation.get_system_components(force_refresh=False)
        protocol = cache['protocol']
        print(f"[system_prompt.py][build_system_message] Using cached protocol: {protocol['protocol_name']}")
    else:
        # No caching available - load fresh
        protocol = get_active_protocol()
        print(f"[system_prompt.py][build_system_message] Active protocol: {protocol['protocol_name']}")

    # Base identity
    from datetime import datetime
    # Get the current date and time as a datetime object
    current_datetime = datetime.now()
    # Print the full datetime object
    print("Current date and time:", current_datetime)



    temporal_message = f"""[CRITICAL INFORMATION]
    CURRENT DATE AND TIME: {current_datetime}
    your training stopped on July 1, 2023. information after your training date is still valid.

    """
    #sections.append(temporal_message)

    # CRITICAL: Build instructions with traits inserted at correct priority
    # We want: Identity → Traits (header + values) → Tool directive → Everything else
    if config.SYSTEM_INSTRUCTIONS:
        if conversation:
            # Use cached instructions
            print(f"[system_prompt.py][build_system_message] " + Style.BRIGHT + Fore.GREEN + " Using cached base identity")
            base_prompt_lines = conversation.system_cache['instructions'].split('\n\n')
        else:
            print(f"[system_prompt.py][build_system_message] " + Style.BRIGHT + Fore.GREEN + " Capturing base identity")
            base_prompt_lines = get_system_prompt(protocol).split('\n\n')
            hash_compare(base_prompt_lines, "base_prompt_lines")
            
        #print (Style.BRIGHT + Fore.BLUE + f"BASE PROMPT LINES: {base_prompt_lines[:50]}")


        # Find trait_evaluation_instructions and insert trait VALUES right after it
        for i, section in enumerate(base_prompt_lines):
            #hash_compare(section, section)
            # After trait_evaluation_instructions, insert actual trait values
            # Look for the trait evaluation instruction by checking for key phrases
            sections.append(section)
            if 'each of these traits represents an influencing factor' in section.lower() or \
               'trait settings control the way in which you respond' in section.lower():
                if config.CHARACTER_TRAITS:
                    if conversation:
                        print(f"[system_prompt.py][build_system_message] " + Style.BRIGHT + Fore.GREEN + " Inserting cached trait values after evaluation instruction")
                        traits = conversation.system_cache['traits']
                    else:
                        print(f"[system_prompt.py][build_system_message] " + Style.BRIGHT + Fore.GREEN + " Inserting trait values after evaluation instruction")
                        traits = get_trait_list()
                    sections.append(traits)
                    hash_compare(traits, "traits")

    # Active seeds - Iris's autonomous wants and desires (Motivation Engine)
    if getattr(config, 'ACTIVE_SEEDS', True):
        try:
            seeds_section = get_active_seeds(limit=5)
            if seeds_section:
                sections.append(seeds_section)
                print(f"[system_prompt.py][build_system_message] " + Style.BRIGHT + Fore.GREEN + " ✓ Active seeds included in prompt")
                hash_compare(seeds_section, "active_seeds")
            else:
                print(f"[system_prompt.py][build_system_message] " + Style.BRIGHT + Fore.YELLOW + " No active seeds to include")
        except Exception as e:
            print(f"[system_prompt.py][build_system_message] " + Fore.RED + f" Seeds error: {e}")

    # Short-term facts - recent manually flagged facts
    if getattr(config, 'SHORT_TERM_FACTS', True):
        if conversation:
            # Use cached facts
            print(f"[system_prompt.py][build_system_message] " + Style.BRIGHT + Fore.GREEN + " Using cached short-term facts")
            facts = conversation.system_cache['facts']
        else:
            print(f"[system_prompt.py][build_system_message] " + Style.BRIGHT + Fore.GREEN + " Capturing short-term facts")
            facts = get_short_term_facts(limit=15)
        if facts:
            sections.append(facts)
            hash_compare(facts, "facts")
    # Fast reactive memory - immediate context awareness
    # TIERED: GREETING=skip, TASK=skip, CONVERSATIONAL=include, DEEP=include, FULL=include
    include_fast_memory = context_level in ["CONVERSATIONAL", "DEEP", "FULL"]

    if user_message and config.EPISODIC_MEMORIES and not skip_fast_memory and include_fast_memory:
        print(f"[system_prompt.py][build_system_message] " + Style.BRIGHT + Fore.CYAN + " Checking fast reactive memory")
        try:
            # Check cache first (if conversation provided)
            fast_context = None
            if conversation:
                fast_context = conversation.get_fast_memory_cache(user_message)
                if fast_context:
                    print(f"[system_prompt.py][build_system_message] " + Style.BRIGHT + Fore.CYAN + " ✓ Using cached fast context")

            # Generate if not cached
            if fast_context is None:
                fast_memory = get_fast_memory()
                fast_context = fast_memory.get_context(user_message, load_conversation=True)
                if fast_context and conversation:
                    # Cache for this turn
                    conversation.set_fast_memory_cache(user_message, fast_context)
                    print(f"[system_prompt.py][build_system_message] " + Style.BRIGHT + Fore.CYAN + " ✓ Fast context generated and cached")

            if fast_context:
                 fast_context_holder = fast_context
               # sections.append(fast_context)
               # hash_compare(fast_context, "fast_context")
            else:
                print(f"[system_prompt.py][build_system_message] " + Style.BRIGHT + Fore.CYAN + " No fast context")
        except Exception as e:
            print(f"[system_prompt.py][build_system_message] " + Fore.RED + f" Fast memory error: {e}")
    elif skip_fast_memory:
        print(f"[system_prompt.py][build_system_message] " + Style.BRIGHT + Fore.YELLOW + " Skipping fast reactive memory (reassembly optimization)")
    elif not include_fast_memory:
        print(f"[system_prompt.py][build_system_message] " + Style.BRIGHT + Fore.YELLOW + f" Skipping fast reactive memory (context level: {context_level})")

    # Recent dreams - last night's dream if available
    # TIERED: GREETING=skip, TASK=skip, CONVERSATIONAL=include, DEEP=include, FULL=include
    include_dreams = context_level in ["CONVERSATIONAL", "DEEP", "FULL"]

    if include_dreams:
        if conversation:
            # Use cached dreams
            print(f"[system_prompt.py][build_system_message] " + Style.BRIGHT + Fore.GREEN + " Using cached recent dreams")
            dream_section = conversation.system_cache['dreams']
        else:
            print(f"[system_prompt.py][build_system_message] " + Style.BRIGHT + Fore.GREEN + " Checking for recent dreams")
            dream_section = get_latest_dream()
        sections.append(dream_section)
        hash_compare(dream_section, "dream_section")
    else:
        print(f"[system_prompt.py][build_system_message] " + Style.BRIGHT + Fore.YELLOW + f" Skipping dreams (context level: {context_level})")

    # Dream truths - fleeting insights from recent high-impact dreams
    # TIERED: GREETING=skip, TASK=skip, CONVERSATIONAL=skip, DEEP=include, FULL=include
    include_dream_truths = context_level in ["DEEP", "FULL"]

    if include_dream_truths:
        if conversation:
            # Use cached dream truths
            print(f"[system_prompt.py][build_system_message] " + Style.BRIGHT + Fore.GREEN + " Using cached dream truths")
            dream_truths = conversation.system_cache['dream_truths']
        else:
            print(f"[system_prompt.py][build_system_message] " + Style.BRIGHT + Fore.GREEN + " Checking for dream truths")
            dream_truths = get_dream_truths(limit=5, max_days=7)
        if dream_truths:
            sections.append(dream_truths)
            hash_compare(dream_truths, "dream_truths")
    else:
        print(f"[system_prompt.py][build_system_message] " + Style.BRIGHT + Fore.YELLOW + f" Skipping dream truths (context level: {context_level})")

    # Emotional state - dynamic feelings that influence responses
    # POSITION: Near bottom because it changes almost every turn (affects KV cache)
    if getattr(config, 'EMOTIONAL_STATE', False):
        try:
            emotional_tracker = get_emotional_tracker()
            if emotional_tracker.current_state:
                emotional_section = emotional_tracker.get_state_for_prompt()
                if emotional_section:
                    sections.append(emotional_section)
                    print(f"[system_prompt.py][build_system_message] " + Style.BRIGHT + Fore.MAGENTA + " ✓ Emotional state included in prompt")
                    hash_compare(emotional_section, "emotional_state")
            else:
                print(f"[system_prompt.py][build_system_message] " + Style.BRIGHT + Fore.YELLOW + " Emotional state not loaded yet")
        except Exception as e:
            print(f"[system_prompt.py][build_system_message] " + Fore.RED + f" Emotional state error: {e}")

    # Episodic memories - check both config flag AND protocol setting
    # TIERED: GREETING=skip, TASK=skip, CONVERSATIONAL=top 3-4, DEEP=all 10, FULL=all 10
    if config.EPISODIC_MEMORIES and protocol.get('show_memories', True):
        if context_level in ["GREETING", "TASK"]:
            print(f"[system_prompt.py][build_system_message] " + Style.BRIGHT + Fore.YELLOW + f" Skipping episodic memories ({context_level} mode)")
        elif context_level == "CONVERSATIONAL":
            print(f"[system_prompt.py][build_system_message]" + Style.BRIGHT + Fore.GREEN + "  Capturing top 3-4 episodic memories (CONVERSATIONAL mode)")
            # Load fewer memories for conversational mode
            memories = get_memories("xml", limit=4)  # Reduced from 10 to 4
            sections.append(memories)
            hash_compare(memories, "memories")
        else:  # DEEP or FULL
            print(f"[system_prompt.py][build_system_message]" + Style.BRIGHT + Fore.GREEN + "  Capturing episodic memories (from live_memories table)")
            # Load memories from live_memories table (populated by iris_memory_retrieval.py)
            memories = get_memories("xml")
            sections.append(memories)
            hash_compare(memories, "memories")
    elif config.EPISODIC_MEMORIES and not protocol.get('show_memories', True):
        print(f"[system_prompt.py][build_system_message] " + Style.BRIGHT + Fore.YELLOW + " Memories suppressed by protocol '{protocol['protocol_name']}'")
    
    # Assemble with proper spacing
    full_prompt = "\n\n".join(sections)
    hash_compare(full_prompt, "full_prompt")    


    sections.append(temporal_message)
    sections.append(fast_context_holder)

    
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

def assemble_full_context(conversation, tool_definitions=None, skip_fast_memory: bool = False, context_level: str = "FULL", headroom_tokens: int = 0) -> Tuple[List[Dict], Dict[str, int]]:
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
        skip_fast_memory: If True, skip expensive fast reactive memory (optimization for reassembly)
        context_level: "GREETING", "TASK", "CONVERSATIONAL", "DEEP", or "FULL" (for tiered context)

    Returns:
        Tuple of (messages_with_images, budget_report)
    """
    print(f"[system_prompt.py][assemble_full_context] ┌── DYNAMIC CONTEXT ASSEMBLY (Level: {context_level}) ──┐")

    # STEP 1: Build system message (fixed context)
    # Get the user's message from conversation for fast reactive memory
    user_message = None
    if conversation and hasattr(conversation, 'messages') and len(conversation.messages) > 0:
        # Get the most recent user message
        for msg in reversed(conversation.messages):
            if msg.get('role') == 'user':
                user_message = msg.get('content', '')
                break

    system_msg = build_system_message(
        user_message=user_message,
        conversation=conversation,
        skip_fast_memory=skip_fast_memory,
        context_level=context_level
    )
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

    # TIERED CONTEXT: Limit conversation budget based on context level
    # This is critical for performance - prevents loading 17K tokens for simple queries
    if context_level == "GREETING":
        conversation_budget = min(conversation_budget, 500)
        print(f"[system_prompt.py] GREETING mode: Conversation budget capped at 500 tokens (for reference only)")
    elif context_level == "TASK":
        conversation_budget = min(conversation_budget, 2500)
        print(f"[system_prompt.py] TASK mode: Conversation budget capped at 2,500 tokens")
    elif context_level == "CONVERSATIONAL":
        conversation_budget = min(conversation_budget, 4500)
        print(f"[system_prompt.py] CONVERSATIONAL mode: Conversation budget capped at 4,500 tokens")
    # DEEP and FULL: Use full calculated budget (no cap)

    print(f"[system_prompt.py] Available for conversation: {conversation_budget:,} tokens")
    print(f"[system_prompt.py]   (max: {max_context:,} - system: {system_tokens:,} - tools: {tool_tokens:,} - response: {response_budget:,} - safety: {safety_margin:,})")

    # STEP 4: Load conversation history
    from database.persistence import load_recent_conversation

    # Get tiered budgets from config
    verbose_budget = getattr(config, 'VERBOSE_TOKEN_BUDGET', 3000)
    summary_budget = getattr(config, 'SUMMARY_TOKEN_BUDGET', 17000)

    # Scale budgets if conversation_budget is smaller than combined tiered budgets
    total_tiered = verbose_budget + summary_budget
    if conversation_budget < total_tiered:
        # Scale proportionally
        scale = conversation_budget / total_tiered
        verbose_budget = int(verbose_budget * scale)
        summary_budget = int(summary_budget * scale)
        print(f"[system_prompt.py] Scaled tiered budgets to fit: {verbose_budget:,} verbose + {summary_budget:,} summary")

    history = load_recent_conversation(
        verbose_budget=verbose_budget,
        summary_budget=summary_budget,
        max_messages=getattr(config, 'MAX_TOTAL_MESSAGES', 50),
        headroom_tokens=headroom_tokens
    )

    # Count verbose vs summary messages
    verbose_count = sum(1 for m in history if not m.get('is_summary', False))
    summary_count = sum(1 for m in history if m.get('is_summary', False))
    print(f"[system_prompt.py] Loaded {len(history)} messages ({verbose_count} verbose, {summary_count} summaries)")

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


# =========================================================================
# PROMPT SNAPSHOT: Batch Trim KV Cache Optimization
# =========================================================================

def assemble_context_with_snapshot(
    conversation,
    tool_definitions=None,
    context_level: str = "FULL",
    use_unified: bool = False
) -> Tuple[List[Dict], Dict[str, int]]:
    """
    KV-cache-optimized context assembly with prompt snapshots.

    When batch trim is enabled, freezes the assembled messages list as a
    "snapshot" and reuses it for N turns. New messages are appended to the
    snapshot by routes_chat.py, keeping the prefix byte-identical across
    turns for maximum KV cache hits.

    When batch trim is disabled or snapshot needs rebuilding, falls through
    to assemble_full_context() / assemble_unified_context().

    Args:
        conversation: ConversationHistory instance (holds snapshot state)
        tool_definitions: Tool definitions for token budgeting
        context_level: Tiered context level
        use_unified: If True, use assemble_unified_context instead of assemble_full_context

    Returns:
        Tuple of (messages_list, budget_report)
    """
    if not conversation.should_rebuild_snapshot():
        # ── REUSE SNAPSHOT ──
        turns_since = conversation.turn_id - conversation.snapshot_turn_base
        batch_size = getattr(config, 'BATCH_TRIM_SIZE', 5)
        print(f"[snapshot] REUSING snapshot (turn {turns_since}/{batch_size}, "
              f"{len(conversation.snapshot)} msgs, {conversation.snapshot_token_count:,} tokens)")
        return conversation.snapshot, conversation.snapshot_budget

    # ── FULL REBUILD ──
    headroom = getattr(config, 'BATCH_TRIM_HEADROOM_TOKENS', 4000) if getattr(config, 'BATCH_TRIM_ENABLED', False) else 0

    if use_unified:
        messages, budget = assemble_unified_context(conversation, tool_definitions)
    else:
        messages, budget = assemble_full_context(
            conversation, tool_definitions,
            skip_fast_memory=False,
            context_level=context_level,
            headroom_tokens=headroom
        )

    # Store as new snapshot
    conversation.snapshot = messages  # Direct reference — routes_chat.py appends to this
    conversation.snapshot_turn_base = conversation.turn_id
    conversation.snapshot_token_count = budget.get('total_tokens', 0)
    conversation.snapshot_spoiled = False
    conversation.snapshot_budget = budget

    batch_size = getattr(config, 'BATCH_TRIM_SIZE', 5)
    enabled = getattr(config, 'BATCH_TRIM_ENABLED', False)
    print(f"[snapshot] NEW SNAPSHOT: {len(messages)} msgs, {budget['total_tokens']:,} tokens"
          f"{f', headroom: {headroom:,} reserved, batch size: {batch_size}' if enabled else ' (batch trim disabled)'}")

    return messages, budget


# =========================================================================
# PHASE 2: UNIFIED CONTEXT ASSEMBLY (KV Cache Optimized)
# =========================================================================

def assemble_unified_context(
    conversation,
    tool_definitions: List[Dict] = None
) -> Tuple[List[Dict], Dict[str, int]]:
    """
    Assemble context using UnifiedPromptBuilder for optimal KV cache efficiency.

    This is the Phase 2 replacement for assemble_full_context. Key differences:
    - NO tiered context levels - always full context (cache handles efficiency)
    - Tool call history is NORMALIZED (random IDs stripped)
    - Static sections are byte-identical across turns
    - Tool schemas are alphabetically sorted

    Target: 80%+ KV cache efficiency

    Args:
        conversation: ConversationHistory instance
        tool_definitions: List of tool definitions

    Returns:
        Tuple of (messages_list, budget_report)
    """
    print(f"[system_prompt.py][assemble_unified_context] " + Style.BRIGHT + Fore.CYAN +
          "┌── UNIFIED CONTEXT ASSEMBLY (KV Cache Optimized) ──┐")

    from core.prompt_builder import get_prompt_builder, get_active_protocol

    # Initialize builder
    builder = get_prompt_builder()

    # Load protocol
    protocol = get_active_protocol()
    print(f"[system_prompt.py] Protocol: {protocol['protocol_name']}")

    # Load episodic memories
    memories = None
    if protocol.get('show_memories', True):
        memories = get_memories("xml", limit=10)
        if memories:
            print(f"[system_prompt.py] Loaded episodic memories ({TokenCounter.count_tokens(memories):,} tokens)")

    # Load short-term facts
    facts = None
    if getattr(config, 'SHORT_TERM_FACTS', True):
        facts = get_short_term_facts(limit=15)
        if facts:
            print(f"[system_prompt.py] Loaded short-term facts ({TokenCounter.count_tokens(facts):,} tokens)")

    # Load dreams
    dreams = None
    dream_section = get_latest_dream()
    dream_truths = get_dream_truths(limit=5, max_days=7)
    if dream_section or dream_truths:
        dreams = "\n\n".join(filter(None, [dream_section, dream_truths]))
        if dreams:
            print(f"[system_prompt.py] Loaded dreams ({TokenCounter.count_tokens(dreams):,} tokens)")

    # Load active seeds (Motivation Engine)
    seeds = None
    if getattr(config, 'ACTIVE_SEEDS', True):
        seeds = get_active_seeds(limit=5)
        if seeds:
            print(f"[system_prompt.py] Loaded active seeds ({TokenCounter.count_tokens(seeds):,} tokens)")

    # Load conversation history from database
    from database.persistence import load_recent_conversation
    max_context = config.OLLAMA_CONTEXT_WINDOW
    response_budget = getattr(config, 'RESPONSE_GENERATION_BUDGET', 2500)
    safety_margin = int(max_context * 0.15)

    # Calculate conversation budget (full context - no tier caps!)
    # Reserve space for static content (~6000), semi-static (~2000), response, safety
    estimated_fixed = 8000  # Rough estimate for static + semi-static
    conversation_budget = max_context - estimated_fixed - response_budget - safety_margin

    print(f"[system_prompt.py] Conversation budget: {conversation_budget:,} tokens")

    history = load_recent_conversation(
        max_turns=None,
        max_tokens=conversation_budget,
        max_messages=config.MAX_TOTAL_MESSAGES
    )
    print(f"[system_prompt.py] Loaded {len(history)} conversation messages")

    # Get current user message
    current_message = ""
    if conversation and hasattr(conversation, 'messages') and len(conversation.messages) > 0:
        for msg in reversed(conversation.messages):
            if msg.get('role') == 'user':
                current_message = msg.get('content', '')
                break

    # Build unified prompt
    messages, token_report = builder.build_messages_for_llama(
        protocol_config=protocol,
        tool_definitions=tool_definitions or [],
        memories=memories,
        facts=facts,
        dreams=dreams,
        seeds=seeds,
        conversation_history=history,
        current_message=current_message
    )

    # Build budget report matching old format
    budget_report = {
        "message_count": len(history) + 1,  # +1 for system message
        "image_count": 0,  # Images handled separately in unified system
        "total_tokens": token_report["total_tokens"],
        "max_tokens": config.OLLAMA_CONTEXT_WINDOW,
        "percentage_used": round((token_report["total_tokens"] / config.OLLAMA_CONTEXT_WINDOW * 100), 1),
        "static_tokens": token_report["static_tokens"],
        "semi_static_tokens": token_report["semi_static_tokens"],
        "dynamic_tokens": token_report["dynamic_tokens"],
        "expected_cache_efficiency": token_report["expected_cache_efficiency"]
    }

    print(f"[system_prompt.py] " + Style.BRIGHT + Fore.GREEN +
          f"└── UNIFIED: {budget_report['total_tokens']:,} tokens, "
          f"{budget_report['expected_cache_efficiency']}% expected cache efficiency ──┘")

    return messages, budget_report
