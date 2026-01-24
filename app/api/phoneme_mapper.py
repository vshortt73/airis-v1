"""
Text-to-Phoneme mapper for lip sync
Converts text to Rhubarb-compatible phonemes with timing
"""

from phonemizer import phonemize
from phonemizer.separator import Separator
import re

# Mapping from IPA phonemes to Rhubarb mouth shapes
# Rhubarb phonemes: X (silence), A (open), B (lips together), C (lips forward),
# D (tongue up), E (relaxed), F (bottom lip up), G (tongue back), H (tongue forward)

IPA_TO_RHUBARB = {
    # Vowels - open mouth shapes
    'ɑ': 'A',  # father
    'æ': 'A',  # cat
    'ʌ': 'A',  # cup
    'ɔ': 'A',  # caught
    'ɛ': 'E',  # bed
    'ə': 'E',  # about (schwa)
    'ɪ': 'E',  # bit
    'i': 'E',  # beet
    'ʊ': 'C',  # book
    'u': 'C',  # boot
    'aɪ': 'A', # my
    'eɪ': 'E', # day
    'ɔɪ': 'A', # boy
    'aʊ': 'A', # now
    'oʊ': 'C', # go

    # Bilabials - lips together
    'p': 'B',
    'b': 'B',
    'm': 'B',
    'w': 'B',

    # Labiodentals - bottom lip to upper teeth
    'f': 'F',
    'v': 'F',

    # Alveolar - tongue to ridge
    't': 'D',
    'd': 'D',
    'n': 'D',
    's': 'C',
    'z': 'C',
    'l': 'H',
    'r': 'H',

    # Post-alveolar - tongue further back
    'ʃ': 'C',  # sh
    'ʒ': 'C',  # measure
    'tʃ': 'C', # church
    'dʒ': 'C', # judge

    # Velar - tongue back
    'k': 'G',
    'g': 'G',
    'ŋ': 'G',  # sing

    # Glottal
    'h': 'E',

    # Silence/space
    ' ': 'X',
    '': 'X',
}

def text_to_rhubarb_phonemes(text, audio_duration):
    """
    Convert text to Rhubarb phonemes with timing

    Args:
        text: Input text to convert
        audio_duration: Duration of audio in seconds

    Returns:
        List of phoneme dicts: [{"start": 0.0, "end": 0.1, "value": "A"}, ...]
    """
    # Get IPA phonemes from text using espeak backend
    try:
        ipa_phonemes = phonemize(
            text,
            language='en-us',
            backend='espeak',
            separator=Separator(phone='|', word=' '),
            strip=True,
            preserve_punctuation=False,
            with_stress=False
        )
    except Exception as e:
        print(f"[phoneme_mapper.py] ✗ Phonemizer error: {e}")
        # Fallback: return silence
        return [{"start": 0.0, "end": audio_duration, "value": "X"}]

    print(f"[phoneme_mapper.py] IPA phonemes: {ipa_phonemes}")

    # Split into individual phonemes
    phones = [p for p in ipa_phonemes.split('|') if p.strip()]

    if not phones:
        return [{"start": 0.0, "end": audio_duration, "value": "X"}]

    # Convert IPA to Rhubarb phonemes
    rhubarb_phones = []
    for phone in phones:
        phone = phone.strip()
        # Try exact match first
        if phone in IPA_TO_RHUBARB:
            rhubarb_phones.append(IPA_TO_RHUBARB[phone])
        # Try mapping individual characters
        elif len(phone) > 0:
            # Take first character as approximation
            first_char = phone[0]
            rhubarb_phones.append(IPA_TO_RHUBARB.get(first_char, 'E'))
        else:
            rhubarb_phones.append('X')

    print(f"[phoneme_mapper.py] Rhubarb phonemes: {rhubarb_phones}")

    # Merge consecutive identical phonemes
    merged = []
    for phone in rhubarb_phones:
        if merged and merged[-1] == phone:
            continue
        merged.append(phone)

    # Distribute timing EVENLY across phonemes (simple and works well)
    phoneme_duration = audio_duration / len(merged)

    result = []
    for i, phone in enumerate(merged):
        start = i * phoneme_duration
        end = (i + 1) * phoneme_duration if i < len(merged) - 1 else audio_duration
        result.append({
            "start": round(start, 2),
            "end": round(end, 2),
            "value": phone
        })

    print(f"[phoneme_mapper.py] ✓ Generated {len(result)} phoneme cues")
    return result
