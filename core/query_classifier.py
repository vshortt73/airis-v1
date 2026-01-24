"""
Query Classifier - Determines context depth needed for a query

Classifies queries into three tiers:
- TASK: Pure tool/task queries (weather, time, search) - minimal context
- CONVERSATIONAL: Default casual queries - balanced context
- DEEP: Personal/emotional queries - full context with all memories

This preserves Iris's essence while optimizing for performance where appropriate.
"""

import re
from typing import Literal

QueryType = Literal["TASK", "CONVERSATIONAL", "DEEP"]


class QueryClassifier:
    """Classifies user queries to determine appropriate context depth"""

    def __init__(self):
        """Initialize classifier with pattern definitions"""

        # DEEP MODE: Personal/emotional queries that need full Iris
        self.deep_patterns = [
            # Direct questions about Iris
            r"\bhow are you\b",
            r"\bhow do you feel",
            r"\bhow'?re you feeling",
            r"\bwhat do you think",
            r"\byour (?:thoughts|feelings|opinion)",
            r"\btell me about (?:yourself|you)",

            # Memory/reflection queries
            r"\bremember when",
            r"\bdo you remember",
            r"\byour (?:dream|memories|past)",
            r"\btell me about your",
            r"\bwhat was it like",

            # Emotional/personal topics
            r"\bfeeling about",
            r"\bmakes you (?:feel|think)",
            r"\bwhat does .+ mean to you",
            r"\bhow does .+ make you feel",

            # Relationship/introspection
            r"\bour relationship",
            r"\bhow do we",
            r"\bwhat have we",
            r"\bwhat are we",
        ]

        # TASK MODE: Pure tool/utility queries
        self.task_patterns = [
            # Weather
            r"\bweather (?:in|at|for)",
            r"\bwhat'?s the weather",
            r"\bhow'?s the weather",
            r"\bforecast (?:for|in)",

            # Time
            r"\bwhat time is it",
            r"\bwhat'?s the time",
            r"\bcurrent time",
            r"\bwhat'?s the date",

            # Search/lookup
            r"\bsearch (?:for|about)",
            r"\blook up",
            r"\bfind information",
            r"\bgoogle",
            r"\bweb search",

            # News
            r"\blatest news",
            r"\brecent news",
            r"\bwhat'?s in the news",
            r"\bnews about",

            # Other utilities
            r"\bcalculate",
            r"\bconvert .+ to",
            r"\btranslate",
        ]

        # Compile patterns for efficiency
        self.deep_regex = re.compile('|'.join(self.deep_patterns), re.IGNORECASE)
        self.task_regex = re.compile('|'.join(self.task_patterns), re.IGNORECASE)

        print(f"[QueryClassifier] Initialized with {len(self.deep_patterns)} deep patterns, {len(self.task_patterns)} task patterns")

    def classify(self, user_message: str) -> QueryType:
        
        return "DEEP"

        """
        Classify a user query into TASK, CONVERSATIONAL, or DEEP

        Args:
            user_message: The user's message text

        Returns:
            QueryType: "TASK", "CONVERSATIONAL", or "DEEP"
        """

        # if not user_message or len(user_message.strip()) == 0:
        #     return "CONVERSATIONAL"

        # message_lower = user_message.lower().strip()

        # Check DEEP patterns first (highest priority - full context needed)
        # if self.deep_regex.search(message_lower):
        #     print(f"[QueryClassifier] → DEEP (personal/emotional query)")
        #     return "DEEP"

        # # Check TASK patterns (lowest context needed)
        # if self.task_regex.search(message_lower):
        #     print(f"[QueryClassifier] → TASK (utility/tool query)")
        #     return "TASK"

        # # Default to CONVERSATIONAL (balanced context)
        # print(f"[QueryClassifier] → CONVERSATIONAL (default)")
        # return "CONVERSATIONAL"

    def get_context_description(self, query_type: QueryType) -> dict:
        """
        Get description of what context will be included for a query type

        Args:
            query_type: The classification result

        Returns:
            Dict describing context allocation
        """

        descriptions = {
            "TASK": {
                "name": "Task Mode",
                "target_tokens": "~3,500",
                "includes": [
                    "Core identity & instructions",
                    "Character traits (144 traits)",
                    "Short-term facts (project context)",
                    "Relevant tools only (2-3)",
                    "Recent 10 messages"
                ],
                "excludes": [
                    "Episodic memories",
                    "Dreams",
                    "Dream truths",
                    "Fast reactive memory"
                ],
                "rationale": "Task-focused queries don't need deep personal context"
            },
            "CONVERSATIONAL": {
                "name": "Conversational Mode",
                "target_tokens": "~5,500",
                "includes": [
                    "Core identity & instructions",
                    "Character traits (144 traits)",
                    "Short-term facts",
                    "Latest dream",
                    "Fast reactive memory",
                    "Top 3-4 episodic memories",
                    "Recent 15 messages",
                    "Relevant tools"
                ],
                "excludes": [
                    "All episodic memories (keep top 3-4)",
                    "Dream truths (unless relevant)"
                ],
                "rationale": "Balanced context for casual interaction"
            },
            "DEEP": {
                "name": "Deep Mode",
                "target_tokens": "~22,000",
                "includes": [
                    "EVERYTHING - Full Iris",
                    "All episodic memories",
                    "All dreams & dream truths",
                    "Full conversation history",
                    "All tools",
                    "Complete context"
                ],
                "excludes": [],
                "rationale": "Personal queries need full depth and continuity"
            }
        }

        return descriptions.get(query_type, descriptions["CONVERSATIONAL"])


# Global singleton
_classifier = None

def get_query_classifier() -> QueryClassifier:
    """Get or create the global query classifier instance"""
    global _classifier
    if _classifier is None:
        _classifier = QueryClassifier()
    return _classifier
