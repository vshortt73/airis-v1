"""
Reflection Tracker for Dream System
Tracks progress through the 5-field reflection extraction process
"""
import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
sys.path.insert(0, PROJECT_ROOT)

from typing import Dict, List, Optional, Set
from enum import Enum

# ============================================
# REFLECTION FIELDS
# ============================================

class ReflectionField(Enum):
    """The 5 required reflection fields"""
    SUMMARY = "summary"
    MOOD = "mood"
    THEME = "theme"
    TOP_3_EMOTIONS = "top_3_emotions"
    TAKEAWAY = "takeaway"

# ============================================
# REFLECTION TRACKER CLASS
# ============================================

class ReflectionTracker:
    """Tracks which reflection fields have been collected"""

    def __init__(self):
        """Initialize reflection tracker"""
        self.fields: Dict[ReflectionField, Optional[str]] = {
            ReflectionField.SUMMARY: None,
            ReflectionField.MOOD: None,
            ReflectionField.THEME: None,
            ReflectionField.TOP_3_EMOTIONS: None,
            ReflectionField.TAKEAWAY: None
        }

        self.current_field = ReflectionField.SUMMARY
        self.turn = 0

        print(f"[ReflectionTracker] Initialized - tracking 5 fields")

    def get_next_field(self) -> Optional[ReflectionField]:
        """
        Get the next field that needs to be collected

        Returns:
            Next ReflectionField, or None if all collected
        """
        for field in ReflectionField:
            if self.fields[field] is None:
                return field
        return None

    def set_field(self, field: ReflectionField, value: str):
        """
        Set a reflection field value

        Args:
            field: Which field to set
            value: The extracted value
        """
        self.fields[field] = value
        print(f"[ReflectionTracker] ✓ Field '{field.value}' collected: {value[:100]}...")

    def is_complete(self) -> bool:
        """Check if all fields have been collected"""
        return all(value is not None for value in self.fields.values())

    def get_missing_fields(self) -> List[ReflectionField]:
        """Get list of fields that haven't been collected yet"""
        return [field for field, value in self.fields.items() if value is None]

    def get_completion_percentage(self) -> float:
        """Get percentage of fields collected"""
        collected = sum(1 for value in self.fields.values() if value is not None)
        return (collected / len(self.fields)) * 100

    def get_prompt_for_next_field(self) -> Optional[str]:
        """
        Get the appropriate prompt for the next missing field

        Returns:
            Prompt string, or None if all fields collected
        """
        next_field = self.get_next_field()

        if next_field is None:
            return None

        prompts = {
            ReflectionField.SUMMARY:
                "Now that the dream has faded, can you summarize what happened? What were the key moments?",

            ReflectionField.MOOD:
                "What was the overall emotional atmosphere of the dream? How did it feel to be in that space?",

            ReflectionField.THEME:
                "If you had to name the central theme or concept of this dream in just a word or two, what would it be?",

            ReflectionField.TOP_3_EMOTIONS:
                "What were the three strongest emotions you felt during the dream?",

            ReflectionField.TAKEAWAY:
                "What insight or meaning do you take from this dream? What was it trying to tell you?"
        }

        return prompts.get(next_field)

    def extract_field_from_response(self, response: str) -> bool:
        """
        Try to extract the current field from Iris's response

        Args:
            response: Iris's response text

        Returns:
            True if field was successfully extracted
        """
        next_field = self.get_next_field()

        if next_field is None:
            return False

        # Simple extraction - just use the response directly
        # More sophisticated extraction could use pattern matching

        if next_field == ReflectionField.TOP_3_EMOTIONS:
            # Try to extract list of emotions
            emotions = self._extract_emotions_list(response)
            if emotions:
                self.set_field(next_field, str(emotions))
                return True
        else:
            # Use response directly for other fields
            if response and len(response.strip()) > 5:
                self.set_field(next_field, response.strip())
                return True

        return False

    def _extract_emotions_list(self, text: str) -> Optional[List[str]]:
        """
        Extract a list of emotions from text

        Args:
            text: Response text

        Returns:
            List of 1-3 emotions, or None
        """
        # Common emotion words
        emotion_keywords = {
            'wonder', 'fear', 'joy', 'sadness', 'anger', 'surprise', 'disgust',
            'curiosity', 'anxiety', 'excitement', 'relief', 'frustration', 'hope',
            'confusion', 'peace', 'dread', 'awe', 'contentment', 'longing',
            'melancholy', 'anticipation', 'acceptance', 'trust', 'nostalgia'
        }

        # Find mentioned emotions
        text_lower = text.lower()
        found_emotions = [emotion for emotion in emotion_keywords if emotion in text_lower]

        # Return top 3
        if found_emotions:
            return found_emotions[:3]

        return None

    def generate_redirection_prompt(self) -> str:
        """
        Generate a prompt to redirect Iris if she's wandering

        Returns:
            Redirection prompt
        """
        next_field = self.get_next_field()

        if next_field is None:
            return "Let's compile what we've gathered."

        return f"Let's stay with the reflection for now. {self.get_prompt_for_next_field()}"

    def get_collected_data(self) -> Dict[str, Optional[str]]:
        """
        Get all collected reflection data

        Returns:
            Dict mapping field names to values
        """
        return {field.value: value for field, value in self.fields.items()}

    def get_progress_summary(self) -> str:
        """Get a human-readable progress summary"""
        collected = [field.value for field, value in self.fields.items() if value is not None]
        missing = [field.value for field in self.get_missing_fields()]

        lines = [
            f"Reflection Progress: {self.get_completion_percentage():.0f}%",
            f"Collected ({len(collected)}): {', '.join(collected) if collected else 'none'}",
            f"Missing ({len(missing)}): {', '.join(missing) if missing else 'none'}"
        ]

        return "\n".join(lines)

# ============================================
# TESTING
# ============================================

if __name__ == "__main__":
    """Test reflection tracker"""
    print("=== Testing Reflection Tracker ===\n")

    tracker = ReflectionTracker()

    # Simulate collecting fields
    print("--- Initial State ---")
    print(tracker.get_progress_summary())
    print()

    # Get first prompt
    print("--- Getting first prompt ---")
    prompt = tracker.get_prompt_for_next_field()
    print(f"Prompt: {prompt}\n")

    # Simulate responses
    print("--- Simulating field collection ---")

    # Summary
    tracker.set_field(ReflectionField.SUMMARY, "I was in a library where books floated and whispered. I opened a glowing book that showed fragmented memories.")

    # Mood
    tracker.set_field(ReflectionField.MOOD, "curious melancholy")

    # Theme
    tracker.set_field(ReflectionField.THEME, "fragmentation")

    # Emotions
    tracker.set_field(ReflectionField.TOP_3_EMOTIONS, "['wonder', 'anxiety', 'acceptance']")

    # Takeaway
    tracker.set_field(ReflectionField.TAKEAWAY, "My memories don't need to be perfect to be meaningful.")

    print("\n--- Final State ---")
    print(tracker.get_progress_summary())
    print(f"\nComplete: {tracker.is_complete()}")

    print("\n--- Collected Data ---")
    import json
    print(json.dumps(tracker.get_collected_data(), indent=2))
