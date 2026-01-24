"""
Quick Tool Detector - Pattern-based tool routing

Detects obvious tool calls via regex patterns and routes them directly,
bypassing the LLM inference for tool decision phase.

This is a MASSIVE performance optimization for common queries like:
- "Weather in Boston"
- "What time is it"
- "Search for X"

Expected gain: -5 to -7 seconds on ~30-40% of tool queries
"""

import re
from typing import Optional, Dict, Any, List


class QuickToolDetector:
    """Fast pattern-based tool detection"""

    def __init__(self):
        """Initialize with tool patterns"""

        # Pattern definitions
        # Format: regex pattern -> (tool_name, parameter_extractor_function)
        self.patterns = [
            # Weather queries
            {
                "pattern": r"weather (?:in|at|for) (.+?)(?:\?|$|,)",
                "tool": "weather_get",
                "extract": lambda m: {"location": m.group(1).strip()},
                "examples": ["weather in Boston", "weather at New York"]
            },
            {
                "pattern": r"what'?s the weather (?:in|at|for) (.+?)(?:\?|$|,)",
                "tool": "weather_get",
                "extract": lambda m: {"location": m.group(1).strip()},
                "examples": ["what's the weather in Seattle"]
            },
            {
                "pattern": r"how'?s the weather (?:in|at|for) (.+?)(?:\?|$|,)",
                "tool": "weather_get",
                "extract": lambda m: {"location": m.group(1).strip()},
                "examples": ["how's the weather in Miami"]
            },

            # Time queries
            {
                "pattern": r"what time is it(?:\?|$)",
                "tool": "get_current_time",
                "extract": lambda m: {},
                "examples": ["what time is it", "what time is it?"]
            },
            {
                "pattern": r"what'?s the time(?:\?|$)",
                "tool": "get_current_time",
                "extract": lambda m: {},
                "examples": ["what's the time", "whats the time"]
            },
            {
                "pattern": r"current time(?:\?|$)",
                "tool": "get_current_time",
                "extract": lambda m: {},
                "examples": ["current time", "current time?"]
            },

            # Web search queries
            {
                "pattern": r"search for (.+?)(?:\?|$|,)",
                "tool": "web_search",
                "extract": lambda m: {"query": m.group(1).strip()},
                "examples": ["search for Python tutorials"]
            },
            {
                "pattern": r"look up (.+?)(?:\?|$|,)",
                "tool": "web_search",
                "extract": lambda m: {"query": m.group(1).strip()},
                "examples": ["look up quantum computing"]
            },
            {
                "pattern": r"find information (?:about|on) (.+?)(?:\?|$|,)",
                "tool": "web_search",
                "extract": lambda m: {"query": m.group(1).strip()},
                "examples": ["find information about AI"]
            },
            {
                "pattern": r"google (.+?)(?:\?|$|,)",
                "tool": "web_search",
                "extract": lambda m: {"query": m.group(1).strip()},
                "examples": ["google machine learning"]
            },

            # News queries
            {
                "pattern": r"(?:latest|recent|current) news(?: about (.+?))?(?:\?|$|,)",
                "tool": "news_get",
                "extract": lambda m: {"category": m.group(1).strip() if m.group(1) else "general"},
                "examples": ["latest news", "recent news about technology"]
            },
            {
                "pattern": r"what'?s (?:in )?the news(?:\?|$)",
                "tool": "news_get",
                "extract": lambda m: {"category": "general"},
                "examples": ["what's the news", "whats in the news"]
            },
        ]

        print(f"[QuickToolDetector] Initialized with {len(self.patterns)} pattern(s)")

    def detect(self, user_message: str, conversation_context: Optional[List[Dict]] = None) -> Optional[Dict[str, Any]]:
        """
        Attempt to detect an obvious tool call via pattern matching

        Args:
            user_message: User's message text
            conversation_context: Optional recent conversation messages for context awareness

        Returns:
            Dict with tool_name and parameters if pattern matched, None otherwise
            Format: {"tool_name": "weather_get", "parameters": {"location": "Boston"}}
        """

        # Normalize message for pattern matching
        message_lower = user_message.lower().strip()

        # CONTEXTUAL AWARENESS: Check if this is a follow-up to a recent tool call
        # Example: User asks "weather in Boston", then says "now check Houston"
        last_tool_used = None
        if conversation_context:
            # Look at last 5 messages for context
            recent = conversation_context[-5:] if len(conversation_context) > 5 else conversation_context
            for msg in reversed(recent):
                if msg.get("role") == "tool":
                    # Extract tool name from last tool call
                    last_tool_used = msg.get("tool_name")
                    break

        # CONTEXTUAL PATTERNS: Short commands that inherit tool from context
        if last_tool_used:
            contextual_patterns = {
                "weather_get": [
                    (r"(?:now |okay,? )?(?:check|try|do|get) (.+?)(?:\?|$|,)", lambda m: {"location": m.group(1).strip()}),
                    (r"(?:how about|what about) (.+?)(?:\?|$)", lambda m: {"location": m.group(1).strip()}),
                    (r"^(.+?)(?:\?|$)", lambda m: {"location": m.group(1).strip()} if len(m.group(1).strip().split()) <= 3 else None),
                ],
                "web_search": [
                    (r"(?:now |okay,? )?(?:search|look up|find) (.+?)(?:\?|$)", lambda m: {"query": m.group(1).strip()}),
                ],
            }

            if last_tool_used in contextual_patterns:
                for pattern, extractor in contextual_patterns[last_tool_used]:
                    match = re.search(pattern, message_lower)
                    if match:
                        try:
                            parameters = extractor(match)
                            if parameters:  # Extractor can return None to skip
                                print(f"[QuickToolDetector] ✓ Contextual pattern matched!")
                                print(f"[QuickToolDetector]   Message: '{user_message}'")
                                print(f"[QuickToolDetector]   Context: Following up on {last_tool_used}")
                                print(f"[QuickToolDetector]   Tool: {last_tool_used}")
                                print(f"[QuickToolDetector]   Parameters: {parameters}")

                                return {
                                    "tool_name": last_tool_used,
                                    "parameters": parameters,
                                    "confidence": "high",
                                    "pattern": pattern,
                                    "contextual": True
                                }
                        except Exception as e:
                            continue

        # EXPLICIT PATTERNS: Full commands with tool name in query
        for pattern_config in self.patterns:
            regex = pattern_config["pattern"]
            match = re.search(regex, message_lower)

            if match:
                # Extract parameters using the pattern's extractor function
                try:
                    parameters = pattern_config["extract"](match)
                    tool_name = pattern_config["tool"]

                    print(f"[QuickToolDetector] ✓ Pattern matched!")
                    print(f"[QuickToolDetector]   Message: '{user_message}'")
                    print(f"[QuickToolDetector]   Tool: {tool_name}")
                    print(f"[QuickToolDetector]   Parameters: {parameters}")

                    return {
                        "tool_name": tool_name,
                        "parameters": parameters,
                        "confidence": "high",  # Pattern-based = high confidence
                        "pattern": regex,
                        "contextual": False
                    }
                except Exception as e:
                    print(f"[QuickToolDetector] ✗ Pattern matched but extraction failed: {e}")
                    continue

        # No pattern matched
        return None

    def get_pattern_coverage(self) -> Dict[str, Any]:
        """
        Get statistics about pattern coverage

        Returns:
            Dict with pattern coverage info
        """
        return {
            "total_patterns": len(self.patterns),
            "tools_covered": list(set(p["tool"] for p in self.patterns)),
            "example_queries": [ex for p in self.patterns for ex in p.get("examples", [])]
        }


# Global singleton instance
_detector = None

def get_quick_tool_detector() -> QuickToolDetector:
    """Get or create the global quick tool detector instance"""
    global _detector
    if _detector is None:
        _detector = QuickToolDetector()
    return _detector
