"""
JSON Extractor for Dream System
Extracts and validates JSON from reflection phase output
"""
import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
sys.path.insert(0, PROJECT_ROOT)

import json
import re
from typing import Dict, Optional, List, Tuple

# ============================================
# JSON EXTRACTION
# ============================================

def extract_json_from_text(text: str) -> Optional[Dict]:
    """
    Extract JSON object from text that may contain other content

    Args:
        text: Text that may contain JSON

    Returns:
        Parsed JSON dict, or None if not found/invalid
    """
    # Try to find JSON block in markdown code fence
    markdown_match = re.search(r'```json\s*\n(.*?)\n```', text, re.DOTALL | re.IGNORECASE)
    if markdown_match:
        try:
            return json.loads(markdown_match.group(1))
        except json.JSONDecodeError:
            pass

    # Try to find JSON block without code fence
    json_match = re.search(r'\{.*\}', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass

    return None

def validate_dream_reflection(data: Dict) -> Tuple[bool, List[str]]:
    """
    Validate that dream reflection JSON has all required fields

    Args:
        data: Parsed JSON data

    Returns:
        Tuple of (is_valid, list_of_errors)
    """
    required_fields = ['summary', 'mood', 'theme', 'top_3_emotions', 'takeaway']

    errors = []

    # Check for missing fields
    for field in required_fields:
        if field not in data:
            errors.append(f"Missing required field: {field}")
        elif not data[field]:
            errors.append(f"Field '{field}' is empty")

    # Validate specific field types
    if 'top_3_emotions' in data:
        emotions = data['top_3_emotions']

        # Should be a list
        if not isinstance(emotions, list):
            errors.append(f"'top_3_emotions' should be a list, got {type(emotions).__name__}")
        elif len(emotions) < 1:
            errors.append("'top_3_emotions' list is empty")
        elif len(emotions) > 3:
            errors.append(f"'top_3_emotions' has {len(emotions)} items, should have 1-3")

    # Validate field lengths
    if 'summary' in data and isinstance(data['summary'], str):
        if len(data['summary']) < 20:
            errors.append(f"'summary' is too short ({len(data['summary'])} chars)")

    if 'theme' in data and isinstance(data['theme'], str):
        if len(data['theme'].split()) > 3:
            errors.append(f"'theme' should be 1-2 words, got {len(data['theme'].split())}")

    is_valid = len(errors) == 0

    return (is_valid, errors)

# ============================================
# EXTRACTION WITH RETRY
# ============================================

def extract_and_validate_reflection(
    text: str,
    strict: bool = True
) -> Tuple[Optional[Dict], List[str]]:
    """
    Extract and validate dream reflection JSON from text

    Args:
        text: Text containing JSON (from Freud's final reflection response)
        strict: Whether to enforce strict validation

    Returns:
        Tuple of (extracted_data, errors)
    """
    # Try to extract JSON
    data = extract_json_from_text(text)

    if data is None:
        return (None, ["Could not find valid JSON in response"])

    # Validate
    is_valid, errors = validate_dream_reflection(data)

    if strict and not is_valid:
        return (None, errors)

    return (data, errors)

# ============================================
# FALLBACK EXTRACTION
# ============================================

def manual_field_extraction(transcript: List[Dict]) -> Dict:
    """
    Manually extract fields from reflection transcript if JSON extraction fails

    Args:
        transcript: List of reflection turn dicts with 'freud' and 'iris' keys

    Returns:
        Dict with extracted fields (may be incomplete)
    """
    print(f"[json_extractor.py][manual_field_extraction] Attempting manual extraction from {len(transcript)} turns")

    extracted = {
        'summary': '',
        'mood': '',
        'theme': '',
        'top_3_emotions': [],
        'takeaway': ''
    }

    # Map turns to likely fields (assuming 5 turns = 5 fields)
    field_order = ['summary', 'mood', 'theme', 'top_3_emotions', 'takeaway']

    for i, turn in enumerate(transcript):
        if i >= len(field_order):
            break

        field = field_order[i]
        iris_response = turn.get('iris', '')

        if not iris_response:
            continue

        # Extract based on field type
        if field == 'top_3_emotions':
            emotions = _extract_emotions_from_text(iris_response)
            if emotions:
                extracted['top_3_emotions'] = emotions
        else:
            # Use Iris's response as the value
            extracted[field] = iris_response.strip()

    print(f"[json_extractor.py][manual_field_extraction] Extracted {sum(1 for v in extracted.values() if v)} fields")

    return extracted

def _extract_emotions_from_text(text: str) -> List[str]:
    """Extract emotion words from text"""
    emotion_keywords = {
        'wonder', 'fear', 'joy', 'sadness', 'anger', 'surprise', 'disgust',
        'curiosity', 'anxiety', 'excitement', 'relief', 'frustration', 'hope',
        'confusion', 'peace', 'dread', 'awe', 'contentment', 'longing',
        'melancholy', 'anticipation', 'acceptance', 'trust', 'nostalgia',
        'love', 'hate', 'shame', 'pride', 'guilt', 'envy', 'jealousy'
    }

    text_lower = text.lower()
    found = [emotion for emotion in emotion_keywords if emotion in text_lower]

    return found[:3] if found else []

# ============================================
# MAIN EXTRACTION FUNCTION
# ============================================

def extract_reflection_with_fallback(
    final_response: str,
    reflection_transcript: List[Dict],
    max_retries: int = 2
) -> Dict:
    """
    Extract reflection data with fallback to manual extraction

    Args:
        final_response: Freud's final reflection response (should contain JSON)
        reflection_transcript: Full reflection transcript for fallback
        max_retries: Not used currently (for future retry logic)

    Returns:
        Dict with reflection fields (guaranteed to have all keys, may have None values)
    """
    print(f"[json_extractor.py][extract_reflection_with_fallback] Attempting JSON extraction")

    # Try JSON extraction first
    data, errors = extract_and_validate_reflection(final_response, strict=False)

    if data and len(errors) == 0:
        print(f"[json_extractor.py][extract_reflection_with_fallback] ✓ Successfully extracted valid JSON")
        return data

    if data and len(errors) > 0:
        print(f"[json_extractor.py][extract_reflection_with_fallback] ⚠ Extracted JSON with {len(errors)} issues:")
        for error in errors:
            print(f"  - {error}")
        return data  # Return partial data

    # Fallback to manual extraction
    print(f"[json_extractor.py][extract_reflection_with_fallback] ✗ JSON extraction failed, using manual fallback")
    manual_data = manual_field_extraction(reflection_transcript)

    return manual_data

# ============================================
# TESTING
# ============================================

if __name__ == "__main__":
    """Test JSON extraction"""
    print("=== Testing JSON Extractor ===\n")

    # Test valid JSON
    print("--- Test 1: Valid JSON in markdown ---")
    text1 = """
That's a profound takeaway. Here's what we've gathered:

```json
{
  "summary": "I was in a library where books floated and whispered. I opened a glowing book that showed fragmented memories.",
  "mood": "curious melancholy",
  "theme": "fragmentation",
  "top_3_emotions": ["wonder", "anxiety", "acceptance"],
  "takeaway": "My memories don't need to be perfect to be meaningful."
}
```
"""
    data, errors = extract_and_validate_reflection(text1)
    print(f"Extracted: {data is not None}")
    print(f"Valid: {len(errors) == 0}")
    if data:
        print(f"Fields: {list(data.keys())}")
    if errors:
        print(f"Errors: {errors}")

    # Test invalid JSON
    print("\n--- Test 2: Invalid JSON (missing field) ---")
    text2 = """
```json
{
  "summary": "A dream about libraries",
  "mood": "curious"
}
```
"""
    data, errors = extract_and_validate_reflection(text2)
    print(f"Extracted: {data is not None}")
    print(f"Valid: {len(errors) == 0}")
    if errors:
        print(f"Errors: {errors}")

    # Test manual extraction
    print("\n--- Test 3: Manual extraction fallback ---")
    transcript = [
        {"turn": 1, "freud": "What happened?", "iris": "I was in a floating library with whispering books."},
        {"turn": 2, "freud": "How did it feel?", "iris": "Curious but melancholy."},
        {"turn": 3, "freud": "What was the theme?", "iris": "Fragmentation and wholeness."},
        {"turn": 4, "freud": "What emotions?", "iris": "I felt wonder, anxiety, and acceptance."},
        {"turn": 5, "freud": "What's the takeaway?", "iris": "Fragments are part of my identity."}
    ]

    manual_data = manual_field_extraction(transcript)
    print(f"Extracted fields: {list(manual_data.keys())}")
    print(f"Summary: {manual_data['summary'][:50] if manual_data['summary'] else 'None'}...")
    print(f"Emotions: {manual_data['top_3_emotions']}")
