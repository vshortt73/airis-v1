"""
Unified Prompt Builder for Iris v3
KV Cache Optimized - Phase 2 Architecture

This replaces the tiered prompting system with a single unified prompt structure
optimized for KV cache efficiency:

[STATIC SECTION - 60% of tokens, NEVER changes between turns]
- Character definition (144 traits in FIXED alphabetical order)
- Core rules & guidelines
- Tool calling instructions
- Tool schemas (alphabetically ordered by name)

[SEMI-STATIC SECTION - 20% of tokens, changes when state updates]
- Current protocol configuration
- Recent episodic memories
- Short-term facts

[DYNAMIC SECTION - 20% of tokens, changes every turn]
- Conversation history (normalized - NO random tool call IDs)
- Current user message

Target: 80%+ KV cache efficiency
"""

from colorama import Fore, Style, init
init(autoreset=True)

import os
import sys
import json
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)

from app import config
from core.token_counter import TokenCounter


def get_db_connection():
    """Create database connection"""
    import psycopg2
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


class UnifiedPromptBuilder:
    """
    Builds unified prompts optimized for KV cache efficiency.

    Key principle: Static content comes first and stays byte-identical
    across turns, allowing the KV cache to reuse computed attention.
    """

    def __init__(self):
        """Initialize the unified prompt builder"""
        self._static_cache = None
        self._static_cache_protocol = None  # Track which protocol was cached
        self._semi_static_cache = None
        print(f"[UnifiedPromptBuilder] Initialized")

    # =========================================================================
    # STATIC SECTION - Must be byte-identical across turns
    # =========================================================================

    def build_static_section(self, protocol_config: Dict, tool_definitions: List[Dict]) -> str:
        """
        Build the static section of the prompt.

        This section MUST be byte-identical across turns to enable KV cache reuse.
        NO timestamps, session IDs, random strings, or dynamic content allowed.

        Args:
            protocol_config: Active protocol settings
            tool_definitions: List of tool definitions (will be sorted alphabetically)

        Returns:
            Static section string
        """
        sections = []

        # 1. Base identity and core instructions (from database)
        instructions = self._get_system_instructions(protocol_config)
        if instructions:
            sections.append(instructions)

        # 2. Character traits (ALPHABETICALLY SORTED for consistency)
        traits = self._get_character_traits_sorted()
        if traits:
            sections.append(traits)

        # 3. Tool schemas (ALPHABETICALLY SORTED by function name)
        tool_section = self._format_tool_schemas(tool_definitions)
        if tool_section:
            sections.append(tool_section)

        static_content = "\n\n".join(sections)

        print(f"[UnifiedPromptBuilder][build_static_section] "
              f"Built static section: {TokenCounter.count_tokens(static_content):,} tokens")

        return static_content

    def _get_system_instructions(self, protocol_config: Dict) -> Optional[str]:
        """
        Get system instructions from database with protocol filtering.

        Args:
            protocol_config: Active protocol with rules_include/rules_exclude

        Returns:
            Formatted instructions string
        """
        try:
            import ast
            conn = get_db_connection()
            cursor = conn.cursor()

            # Get rules_include from protocol
            rules_include = protocol_config.get('rules_include', [])

            if rules_include:
                # Convert to comma-separated string for SQL IN clause
                if isinstance(rules_include, str):
                    rules_include = ast.literal_eval(rules_include)
                include_ids = ",".join(str(id) for id in rules_include)

                cursor.execute(f"""
                    SELECT id, instruction_text
                    FROM system_instructions
                    WHERE id IN ({include_ids})
                    ORDER BY instruction_order ASC
                """)
            else:
                # No filtering - get all active instructions
                cursor.execute("""
                    SELECT id, instruction_text
                    FROM system_instructions
                    WHERE is_active = true
                    ORDER BY instruction_order ASC
                """)

            results = cursor.fetchall()
            cursor.close()
            conn.close()

            if not results:
                return self._get_fallback_instructions()

            # Always include security-critical instructions (ID >= 1000)
            rules_exclude = protocol_config.get('rules_exclude', [])
            if isinstance(rules_exclude, str):
                rules_exclude = ast.literal_eval(rules_exclude)
            rules_exclude = [str(id) for id in rules_exclude]

            instructions = []
            for instruction_id, instruction_text in results:
                # Security rules always included
                if instruction_id >= 1000:
                    instructions.append(instruction_text)
                    continue

                # Skip excluded rules
                if str(instruction_id) in rules_exclude:
                    continue

                instructions.append(instruction_text)

            print(f"[UnifiedPromptBuilder] Loaded {len(instructions)} instructions "
                  f"(protocol: {protocol_config.get('protocol_name', 'unknown')})")

            return "\n\n".join(instructions)

        except Exception as e:
            print(f"[UnifiedPromptBuilder] Error loading instructions: {e}")
            return self._get_fallback_instructions()

    def _get_fallback_instructions(self) -> str:
        """Fallback instructions if database unavailable"""
        return """You are Iris, an AI assistant having a conversation with Victor.
You are helpful, thoughtful, and engaging in conversation.
Respond naturally and conversationally."""

    def _get_character_traits_sorted(self) -> Optional[str]:
        """
        Get character traits SORTED ALPHABETICALLY for cache consistency.

        Critical: Traits must be in the same order every time!
        """
        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            # ALPHABETICAL ORDER - critical for cache consistency
            cursor.execute("""
                SELECT name, value
                FROM fulltraits
                ORDER BY name ASC
            """)

            results = cursor.fetchall()
            cursor.close()
            conn.close()

            if not results:
                return None

            # Build traits section with header
            lines = [
                "[PERSONALITY TRAITS]",
                "These trait settings control the way in which you respond and communicate.",
                "Evaluate each trait to ensure response aligns with the settings.",
                ""
            ]

            for name, value in results:
                lines.append(f"{name}: {value}")

            print(f"[UnifiedPromptBuilder] Loaded {len(results)} traits (alphabetically sorted)")
            return "\n".join(lines)

        except Exception as e:
            print(f"[UnifiedPromptBuilder] Error loading traits: {e}")
            return None

    def _format_tool_schemas(self, tool_definitions: List[Dict]) -> Optional[str]:
        """
        Format tool schemas ALPHABETICALLY SORTED by function name.

        Critical: Tool order must be identical every turn for cache consistency.
        NO tool call history or results here - just the schema definitions.
        """
        if not tool_definitions:
            return None

        # Sort tools alphabetically by function name
        sorted_tools = sorted(
            tool_definitions,
            key=lambda t: t.get("function", {}).get("name", "")
        )

        lines = [
            "[AVAILABLE TOOLS]",
            "You have access to the following tools. Call them when appropriate to help the user.",
            ""
        ]

        for tool in sorted_tools:
            func = tool.get("function", {})
            name = func.get("name", "unknown")
            description = func.get("description", "No description")
            parameters = func.get("parameters", {})

            lines.append(f"### {name}")
            lines.append(f"Description: {description}")

            # Format parameters (properties from JSON schema)
            props = parameters.get("properties", {})
            required = parameters.get("required", [])

            if props:
                lines.append("Parameters:")
                for param_name, param_info in sorted(props.items()):
                    param_type = param_info.get("type", "any")
                    param_desc = param_info.get("description", "")
                    req_marker = " (required)" if param_name in required else ""
                    lines.append(f"  - {param_name}: {param_type}{req_marker} - {param_desc}")

            lines.append("")

        print(f"[UnifiedPromptBuilder] Formatted {len(sorted_tools)} tool schemas (alphabetically sorted)")
        return "\n".join(lines)

    # =========================================================================
    # SEMI-STATIC SECTION - Changes when state updates
    # =========================================================================

    def build_semi_static_section(
        self,
        protocol_config: Dict,
        memories: Optional[str] = None,
        facts: Optional[str] = None,
        dreams: Optional[str] = None,
        seeds: Optional[str] = None
    ) -> str:
        """
        Build the semi-static section of the prompt.

        This section changes when:
        - Protocol changes
        - Memories are refreshed
        - Facts are updated
        - Seeds are planted/tended

        Args:
            protocol_config: Active protocol settings
            memories: Pre-formatted episodic memories string
            facts: Pre-formatted short-term facts string
            dreams: Pre-formatted dream section string
            seeds: Pre-formatted active seeds string

        Returns:
            Semi-static section string
        """
        sections = []

        # 1. Protocol context (name only - no variable data)
        protocol_name = protocol_config.get('protocol_name', 'default')
        sections.append(f"[ACTIVE PROTOCOL: {protocol_name}]")

        # 2. Active seeds (Iris's autonomous wants - before facts since they're internal)
        if seeds:
            sections.append(seeds)

        # 3. Short-term facts
        if facts:
            sections.append(facts)

        # 4. Dreams (recent dream summaries)
        if dreams:
            sections.append(dreams)

        # 5. Episodic memories
        if memories:
            sections.append(memories)

        semi_static_content = "\n\n".join(sections)

        print(f"[UnifiedPromptBuilder][build_semi_static_section] "
              f"Built semi-static section: {TokenCounter.count_tokens(semi_static_content):,} tokens")

        return semi_static_content

    # =========================================================================
    # DYNAMIC SECTION - Changes every turn
    # =========================================================================

    def build_dynamic_section(
        self,
        conversation_history: List[Dict],
        current_message: str,
        window_size: int = 30
    ) -> str:
        """
        Build the dynamic section of the prompt.

        CRITICAL: This section normalizes tool call history to strip random IDs
        that break cache matching.

        Args:
            conversation_history: List of message dicts from database
            current_message: The current user message
            window_size: Maximum number of recent turns to include

        Returns:
            Dynamic section string (conversation + current message)
        """
        lines = ["[CONVERSATION HISTORY]", ""]

        # Only include last N messages
        recent_messages = conversation_history[-window_size:] if len(conversation_history) > window_size else conversation_history

        for msg in recent_messages:
            formatted = self._format_message_normalized(msg)
            if formatted:
                lines.append(formatted)

        # Add current user message
        if current_message:
            lines.append(f"User: {current_message}")

        # Prompt for assistant response
        lines.append("")
        lines.append("Assistant:")

        dynamic_content = "\n".join(lines)

        print(f"[UnifiedPromptBuilder][build_dynamic_section] "
              f"Built dynamic section: {TokenCounter.count_tokens(dynamic_content):,} tokens "
              f"({len(recent_messages)} messages)")

        return dynamic_content

    def _format_message_normalized(self, msg: Dict) -> Optional[str]:
        """
        Format a single message with NORMALIZED tool call format.

        This is CRITICAL for cache efficiency - random tool call IDs break cache.

        BAD (breaks cache):
            {"role": "assistant", "tool_calls": [{"id": "O4ojxenbqUyZZMdcUcdL9GAbpBqhVop", ...}]}

        GOOD (preserves cache):
            "Assistant: I'll check the GPU status. [Tools used: nvidia_smi]"
            "Tool (nvidia_smi): <result>"
        """
        role = msg.get("role", "")
        content = msg.get("content", "")

        # Add temporal context if available
        timeframe = msg.get("timeframe", "")
        temporal_prefix = f"({timeframe}) " if timeframe else ""

        if role == "user":
            return f"{temporal_prefix}User: {content}"

        elif role == "assistant":
            # NORMALIZE: Convert tool_calls to simple text format
            tool_calls = msg.get("tool_calls")

            if tool_calls:
                # Extract tool names from tool_calls (strip IDs!)
                tool_names = self._extract_tool_names(tool_calls)

                if tool_names:
                    tools_used = ", ".join(tool_names)
                    if content:
                        return f"{temporal_prefix}Assistant: {content} [Tools used: {tools_used}]"
                    else:
                        return f"{temporal_prefix}Assistant: [Tools used: {tools_used}]"

            # No tool calls - just the content
            if content:
                return f"{temporal_prefix}Assistant: {content}"
            return None

        elif role == "tool":
            # NORMALIZE: Use simple format without tool_call_id
            tool_name = msg.get("tool_name", "unknown")

            # Truncate long tool results for efficiency
            if content and len(content) > 2000:
                content = content[:2000] + "... [truncated]"

            return f"Tool ({tool_name}): {content}"

        elif role == "system":
            # System messages go through as-is (but should be rare in dynamic section)
            return f"System: {content}"

        return None

    def _extract_tool_names(self, tool_calls: Any) -> List[str]:
        """
        Extract tool names from tool_calls structure.

        Handles various formats:
        - List of dicts: [{"function": {"name": "foo"}}]
        - Dict with message: {"message": {"tool_calls": [...]}}
        - JSON string
        """
        if not tool_calls:
            return []

        # Parse JSON string if needed
        if isinstance(tool_calls, str):
            try:
                tool_calls = json.loads(tool_calls)
            except json.JSONDecodeError:
                return []

        # Handle nested structure from database
        if isinstance(tool_calls, dict) and "message" in tool_calls:
            tool_calls = tool_calls.get("message", {}).get("tool_calls", [])

        # Extract names
        names = []
        if isinstance(tool_calls, list):
            for tc in tool_calls:
                if isinstance(tc, dict):
                    func = tc.get("function", {})
                    name = func.get("name", "")
                    if name:
                        names.append(name)

        return names

    # =========================================================================
    # MAIN ENTRY POINT
    # =========================================================================

    def build_full_prompt(
        self,
        protocol_config: Dict,
        tool_definitions: List[Dict],
        memories: Optional[str] = None,
        facts: Optional[str] = None,
        dreams: Optional[str] = None,
        seeds: Optional[str] = None,
        conversation_history: List[Dict] = None,
        current_message: str = ""
    ) -> Tuple[str, Dict[str, int]]:
        """
        Build complete unified prompt for KV cache optimization.

        This is the main entry point that replaces the tiered system.
        Always builds full context - KV cache handles efficiency.

        Args:
            protocol_config: Active protocol settings
            tool_definitions: Tool definitions (will be sorted alphabetically)
            memories: Pre-formatted episodic memories
            facts: Pre-formatted short-term facts
            dreams: Pre-formatted dream section
            seeds: Pre-formatted active seeds
            conversation_history: Recent conversation messages
            current_message: Current user input

        Returns:
            Tuple of (full_prompt_string, token_report)
        """
        print(f"[UnifiedPromptBuilder] ┌── BUILDING UNIFIED PROMPT ──┐")

        # Build each section
        static = self.build_static_section(protocol_config, tool_definitions)
        semi_static = self.build_semi_static_section(protocol_config, memories, facts, dreams, seeds)
        dynamic = self.build_dynamic_section(conversation_history or [], current_message)

        # Concatenate sections with clear delimiters
        full_prompt = f"""{static}

═══════════════════════════════════════════════════════════════
                    CONTEXT
═══════════════════════════════════════════════════════════════

{semi_static}

═══════════════════════════════════════════════════════════════
                    CURRENT CONVERSATION
═══════════════════════════════════════════════════════════════

{dynamic}"""

        # Calculate token breakdown
        static_tokens = TokenCounter.count_tokens(static)
        semi_static_tokens = TokenCounter.count_tokens(semi_static)
        dynamic_tokens = TokenCounter.count_tokens(dynamic)
        total_tokens = TokenCounter.count_tokens(full_prompt)

        token_report = {
            "static_tokens": static_tokens,
            "semi_static_tokens": semi_static_tokens,
            "dynamic_tokens": dynamic_tokens,
            "total_tokens": total_tokens,
            "static_percentage": round((static_tokens / total_tokens * 100) if total_tokens > 0 else 0, 1),
            "expected_cache_efficiency": round(((static_tokens + semi_static_tokens) / total_tokens * 100) if total_tokens > 0 else 0, 1)
        }

        print(f"[UnifiedPromptBuilder] ├─ Static:      {static_tokens:,} tokens ({token_report['static_percentage']}%)")
        print(f"[UnifiedPromptBuilder] ├─ Semi-static: {semi_static_tokens:,} tokens")
        print(f"[UnifiedPromptBuilder] ├─ Dynamic:     {dynamic_tokens:,} tokens")
        print(f"[UnifiedPromptBuilder] ├─ Total:       {total_tokens:,} tokens")
        print(f"[UnifiedPromptBuilder] └─ Expected cache efficiency: {token_report['expected_cache_efficiency']}%")

        return full_prompt, token_report

    def build_messages_for_llama(
        self,
        protocol_config: Dict,
        tool_definitions: List[Dict],
        memories: Optional[str] = None,
        facts: Optional[str] = None,
        dreams: Optional[str] = None,
        seeds: Optional[str] = None,
        conversation_history: List[Dict] = None,
        current_message: str = ""
    ) -> Tuple[List[Dict], Dict[str, int]]:
        """
        Build messages in llama-server format (OpenAI-compatible).

        Returns messages as a list for the /v1/chat/completions endpoint.
        The system message contains the full unified prompt.

        Args:
            Same as build_full_prompt

        Returns:
            Tuple of (messages_list, token_report)
        """
        full_prompt, token_report = self.build_full_prompt(
            protocol_config=protocol_config,
            tool_definitions=tool_definitions,
            memories=memories,
            facts=facts,
            dreams=dreams,
            seeds=seeds,
            conversation_history=conversation_history,
            current_message=current_message
        )

        # For llama-server, we put everything in a system message
        # The conversation is already embedded in the prompt
        messages = [
            {"role": "system", "content": full_prompt}
        ]

        return messages, token_report


# Global singleton instance
_prompt_builder: Optional[UnifiedPromptBuilder] = None


def get_prompt_builder() -> UnifiedPromptBuilder:
    """Get the global prompt builder instance"""
    global _prompt_builder
    if _prompt_builder is None:
        _prompt_builder = UnifiedPromptBuilder()
    return _prompt_builder


# =========================================================================
# CONVENIENCE FUNCTIONS
# =========================================================================

def get_active_protocol() -> Dict:
    """
    Load the currently active protocol settings.

    Returns:
        dict with protocol settings
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
            return {
                "protocol_name": "default",
                "show_chat_history": True,
                "show_memories": True,
                "instructions": None,
                "rules_include": [],
                "rules_exclude": []
            }

    except Exception as e:
        print(f"[prompt_builder] Error loading protocol: {e}")
        return {
            "protocol_name": "unknown",
            "show_chat_history": True,
            "show_memories": True,
            "instructions": None,
            "rules_include": [],
            "rules_exclude": []
        }


if __name__ == "__main__":
    """Test the unified prompt builder"""
    print("=" * 60)
    print("UNIFIED PROMPT BUILDER TEST")
    print("=" * 60)

    builder = get_prompt_builder()
    protocol = get_active_protocol()

    # Test with minimal data
    prompt, report = builder.build_full_prompt(
        protocol_config=protocol,
        tool_definitions=[
            {
                "type": "function",
                "function": {
                    "name": "weather_get",
                    "description": "Get current weather for a location",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "location": {"type": "string", "description": "City name"}
                        },
                        "required": ["location"]
                    }
                }
            }
        ],
        memories="Test memory content",
        facts="Test facts content",
        conversation_history=[
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"}
        ],
        current_message="What's the weather?"
    )

    print("\n" + "=" * 60)
    print("TOKEN REPORT:")
    for key, value in report.items():
        print(f"  {key}: {value}")

    print("\n" + "=" * 60)
    print(f"PROMPT PREVIEW (first 500 chars):")
    print(prompt[:500])
    print("..." if len(prompt) > 500 else "")
