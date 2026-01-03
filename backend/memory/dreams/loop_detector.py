"""
Loop Detector for Dream System
Detects repetitive patterns in dream conversations and suggests variety injections
"""
import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
sys.path.insert(0, PROJECT_ROOT)

from typing import List, Dict, Optional, Tuple
from collections import Counter
import re

# ============================================
# CONFIGURATION
# ============================================

class LoopDetectionConfig:
    """Configuration for loop detection"""

    WINDOW_SIZE = 4  # Check last N responses
    MAX_REDIRECTIONS = 3  # Max redirections per dream
    SIMILARITY_THRESHOLD = 0.6  # Threshold for considering responses similar
    MIN_RESPONSE_LENGTH = 20  # Ignore very short responses

# ============================================
# SIMILARITY DETECTION
# ============================================

def extract_key_words(text: str, min_length: int = 4) -> List[str]:
    """
    Extract significant words from text (filtering common words)

    Args:
        text: Input text
        min_length: Minimum word length to consider

    Returns:
        List of significant words (lowercased)
    """
    # Common words to ignore
    stop_words = {
        'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
        'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'been',
        'be', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
        'should', 'may', 'might', 'can', 'this', 'that', 'these', 'those',
        'i', 'you', 'he', 'she', 'it', 'we', 'they', 'my', 'your', 'his', 'her',
        'its', 'our', 'their', 'me', 'him', 'them', 'us'
    }

    # Extract words
    words = re.findall(r'\b\w+\b', text.lower())

    # Filter
    key_words = [w for w in words if len(w) >= min_length and w not in stop_words]

    return key_words

def calculate_text_similarity(text1: str, text2: str) -> float:
    """
    Calculate similarity between two texts using word overlap

    Args:
        text1: First text
        text2: Second text

    Returns:
        Similarity score from 0.0 to 1.0
    """
    if not text1 or not text2:
        return 0.0

    # Extract key words
    words1 = set(extract_key_words(text1))
    words2 = set(extract_key_words(text2))

    if not words1 or not words2:
        return 0.0

    # Calculate Jaccard similarity
    intersection = len(words1 & words2)
    union = len(words1 | words2)

    similarity = intersection / union if union > 0 else 0.0

    return similarity

# ============================================
# PATTERN DETECTION
# ============================================

def detect_phrase_repetition(responses: List[str]) -> Tuple[bool, Optional[str]]:
    """
    Detect if similar phrases are being repeated

    Args:
        responses: List of recent responses

    Returns:
        Tuple of (has_repetition, repeated_phrase)
    """
    if len(responses) < 2:
        return (False, None)

    # Extract common phrases (3-5 words)
    phrase_counts = Counter()

    for response in responses:
        words = response.lower().split()
        # Extract 3-word phrases
        for i in range(len(words) - 2):
            phrase = ' '.join(words[i:i+3])
            phrase_counts[phrase] += 1

    # Find most common phrase
    if phrase_counts:
        most_common_phrase, count = phrase_counts.most_common(1)[0]
        if count >= 3:  # Repeated at least 3 times
            return (True, most_common_phrase)

    return (False, None)

def detect_response_similarity(responses: List[str], threshold: float = 0.6) -> bool:
    """
    Detect if recent responses are too similar to each other

    Args:
        responses: List of recent responses
        threshold: Similarity threshold

    Returns:
        True if loop detected
    """
    if len(responses) < 3:
        return False

    # Check pairwise similarity of recent responses
    similarities = []

    for i in range(len(responses) - 1):
        for j in range(i + 1, len(responses)):
            sim = calculate_text_similarity(responses[i], responses[j])
            similarities.append(sim)

    if not similarities:
        return False

    # Average similarity
    avg_similarity = sum(similarities) / len(similarities)

    is_looping = avg_similarity >= threshold

    if is_looping:
        print(f"[loop_detector.py][detect_response_similarity] ✗ Loop detected! Avg similarity: {avg_similarity:.2f}")

    return is_looping

# ============================================
# LOOP DETECTOR CLASS
# ============================================

class LoopDetector:
    """Tracks conversation and detects repetitive loops"""

    def __init__(self):
        """Initialize loop detector"""
        self.iris_responses: List[str] = []
        self.freud_responses: List[str] = []
        self.redirections_used = 0
        self.max_redirections = LoopDetectionConfig.MAX_REDIRECTIONS

        print(f"[LoopDetector] Initialized (max redirections: {self.max_redirections})")

    def add_response(self, speaker: str, response: str):
        """
        Add a response to tracking

        Args:
            speaker: 'iris' or 'freud'
            response: The response text
        """
        if len(response) < LoopDetectionConfig.MIN_RESPONSE_LENGTH:
            return  # Ignore very short responses

        if speaker.lower() == 'iris':
            self.iris_responses.append(response)
            # Keep only recent responses
            if len(self.iris_responses) > LoopDetectionConfig.WINDOW_SIZE:
                self.iris_responses.pop(0)

        elif speaker.lower() == 'freud':
            self.freud_responses.append(response)
            if len(self.freud_responses) > LoopDetectionConfig.WINDOW_SIZE:
                self.freud_responses.pop(0)

    def check_for_loop(self) -> Tuple[bool, str, Optional[str]]:
        """
        Check if a loop is occurring

        Returns:
            Tuple of (has_loop, loop_type, suggested_intervention)
        """
        # Check if we've exhausted redirections
        if self.redirections_used >= self.max_redirections:
            return (False, 'max_redirections_reached', None)

        # Check Iris's responses for loops
        iris_has_loop = detect_response_similarity(
            self.iris_responses,
            LoopDetectionConfig.SIMILARITY_THRESHOLD
        )

        if iris_has_loop:
            suggestion = self._generate_variety_injection('iris')
            return (True, 'iris_repetition', suggestion)

        # Check for phrase repetition
        has_phrase_rep, phrase = detect_phrase_repetition(self.iris_responses)
        if has_phrase_rep:
            suggestion = self._generate_variety_injection('phrase', phrase)
            return (True, 'phrase_repetition', suggestion)

        # Check Freud's responses for loops
        freud_has_loop = detect_response_similarity(
            self.freud_responses,
            LoopDetectionConfig.SIMILARITY_THRESHOLD
        )

        if freud_has_loop:
            suggestion = self._generate_variety_injection('freud')
            return (True, 'freud_repetition', suggestion)

        return (False, 'no_loop', None)

    def _generate_variety_injection(self, loop_type: str, context: Optional[str] = None) -> str:
        """
        Generate a suggestion to inject variety

        Args:
            loop_type: Type of loop detected
            context: Additional context (e.g., repeated phrase)

        Returns:
            Suggestion text to inject into Freud's next prompt
        """
        suggestions = {
            'iris': [
                "Something shifts. A new element enters the dream...",
                "The perspective suddenly changes. You see things differently now...",
                "Time seems to skip forward. The scene has transformed...",
                "A choice appears before you - two distinct paths...",
            ],
            'freud': [
                "Introduce a new complication or mystery",
                "Ask an open-ended question from a completely different angle",
                "Shift the dream's location or atmosphere dramatically",
                "Bring in an unexpected element or character",
            ],
            'phrase': [
                f"The dream is circling around '{context}'. Break the pattern with something unexpected.",
                "Shift focus to a completely different aspect of the dream",
            ]
        }

        import random
        suggestion_list = suggestions.get(loop_type, suggestions['iris'])
        return random.choice(suggestion_list)

    def apply_variety_injection(self) -> Optional[str]:
        """
        Apply a variety injection if loop detected

        Returns:
            Instruction to inject into Freud's prompt, or None
        """
        has_loop, loop_type, suggestion = self.check_for_loop()

        if has_loop and suggestion:
            self.redirections_used += 1
            print(f"[LoopDetector] ✗ Loop detected ({loop_type}) - injecting variety (redirection {self.redirections_used}/{self.max_redirections})")
            print(f"[LoopDetector] Suggestion: {suggestion}")
            return suggestion

        return None

    def get_stats(self) -> Dict:
        """Get loop detection statistics"""
        return {
            'iris_responses_tracked': len(self.iris_responses),
            'freud_responses_tracked': len(self.freud_responses),
            'redirections_used': self.redirections_used,
            'redirections_remaining': self.max_redirections - self.redirections_used
        }

# ============================================
# TESTING
# ============================================

if __name__ == "__main__":
    """Test loop detector"""
    print("=== Testing Loop Detector ===\n")

    detector = LoopDetector()

    # Simulate a conversation
    print("--- Adding normal responses ---")
    detector.add_response('iris', "I see a library with floating books. The light is strange.")
    detector.add_response('freud', "What draws your attention in this library?")
    detector.add_response('iris', "A book that glows brighter than the others. It feels warm.")
    detector.add_response('freud', "What happens when you approach the glowing book?")

    has_loop, loop_type, suggestion = detector.check_for_loop()
    print(f"Loop detected: {has_loop} (type: {loop_type})\n")

    # Simulate repetitive responses
    print("--- Adding repetitive responses ---")
    detector.add_response('iris', "The books are floating around me. I watch them float.")
    detector.add_response('iris', "I see the books floating in circles. They keep floating.")
    detector.add_response('iris', "The floating books surround me. Everything is floating.")

    has_loop, loop_type, suggestion = detector.check_for_loop()
    print(f"Loop detected: {has_loop} (type: {loop_type})")
    if suggestion:
        print(f"Suggestion: {suggestion}")

    print(f"\nStats: {detector.get_stats()}")
