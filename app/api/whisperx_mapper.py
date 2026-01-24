"""
WhisperX-based phoneme alignment for lip sync
Provides accurate frame-level phoneme timing from actual audio
"""

import torch
import os
import gc

# Fix for PyTorch 2.6+ weights_only security change
# WhisperX models from HuggingFace are trusted, so we can use weights_only=False
# This monkey-patch stays active for the lifetime of this module
_original_torch_load = torch.load

def _torch_load_wrapper(*args, **kwargs):
    """Wrapper for torch.load that sets weights_only=False for WhisperX compatibility"""
    # Force weights_only to False for WhisperX models (they're from trusted HuggingFace)
    kwargs['weights_only'] = False
    return _original_torch_load(*args, **kwargs)

# Monkey-patch torch.load (stays active for WhisperX model loading)
torch.load = _torch_load_wrapper

# Now import whisperx
import whisperx

# Cache models to avoid reloading
_whisperx_model = None
_align_model = None
_align_metadata = None
_device = None

def get_device():
    """Get the best available device - GPU 1 (RTX 4080) to avoid main model on GPU 0"""
    if torch.cuda.is_available():
        return "cuda:1"
    else:
        return "cpu"

def load_whisperx_models():
    """Load WhisperX models (cached after first load)"""
    global _whisperx_model, _align_model, _align_metadata, _device

    if _whisperx_model is not None:
        return _whisperx_model, _align_model, _align_metadata, _device

    print("[whisperx_mapper.py] Loading WhisperX models...")

    _device = get_device()
    compute_type = "float16" if _device.startswith("cuda") else "int8"

    # Load Whisper model for transcription
    _whisperx_model = whisperx.load_model(
        "base.en",  # Fast and accurate for English
        _device,
        compute_type=compute_type
    )

    # Load alignment model for phoneme-level timing
    _align_model, _align_metadata = whisperx.load_align_model(
        language_code="en",
        device=_device
    )

    print(f"[whisperx_mapper.py] ✓ WhisperX models loaded on {_device}")

    return _whisperx_model, _align_model, _align_metadata, _device

# Mapping from WhisperX phonemes to Rhubarb mouth shapes
# WhisperX uses CMU ARPAbet phonemes, so we map to Rhubarb
ARPABET_TO_RHUBARB = {
    # Vowels - Open mouth
    'AA': 'A',  # father
    'AE': 'A',  # cat
    'AH': 'A',  # cut
    'AO': 'A',  # caught
    'AW': 'A',  # cow

    # Vowels - Medium/Relaxed
    'EH': 'E',  # bed
    'ER': 'E',  # bird
    'IH': 'E',  # bit
    'IY': 'E',  # beet
    'UH': 'E',  # book
    'AY': 'E',  # buy
    'EY': 'E',  # day
    'OY': 'E',  # boy

    # Vowels - Rounded
    'OW': 'C',  # go
    'UW': 'C',  # food

    # Bilabial - Lips together
    'P': 'B',
    'B': 'B',
    'M': 'B',

    # Labiodental - Lip to teeth
    'F': 'F',
    'V': 'F',

    # Dental - Tongue to teeth
    'TH': 'F',  # thin
    'DH': 'F',  # then

    # Alveolar - Tongue to ridge
    'T': 'D',
    'D': 'D',
    'N': 'D',
    'S': 'C',
    'Z': 'C',
    'L': 'H',
    'R': 'H',

    # Post-alveolar - Rounded/forward
    'SH': 'C',  # she
    'ZH': 'C',  # measure
    'CH': 'C',  # church
    'JH': 'C',  # judge

    # Velar - Back of tongue
    'K': 'G',
    'G': 'G',
    'NG': 'G',  # sing

    # Glottal/Approximants
    'HH': 'E',  # hello
    'W': 'C',   # we (rounded)
    'Y': 'E',   # yes

    # Silence
    'SIL': 'X',
    'SP': 'X',
}

def whisperx_align_audio(audio_path, text=None):
    """
    Use WhisperX to get accurate phoneme timing from audio

    Args:
        audio_path: Path to audio file (WAV preferred)
        text: Optional transcript (if None, will transcribe)

    Returns:
        List of phoneme dicts: [{"start": 0.0, "end": 0.1, "value": "A"}, ...]
    """
    try:
        # Load models
        model, align_model, metadata, device = load_whisperx_models()

        print(f"[whisperx_mapper.py] Processing audio: {audio_path}")

        # Load audio
        audio = whisperx.load_audio(audio_path)

        # Transcribe if no text provided
        if text is None:
            print("[whisperx_mapper.py] Transcribing audio...")
            result = model.transcribe(audio, batch_size=16)
            text = result["segments"][0]["text"] if result["segments"] else ""
            print(f"[whisperx_mapper.py] Transcribed: '{text}'")
        else:
            # Just get segments for alignment
            result = model.transcribe(audio, batch_size=16)

        # Align to get word-level timestamps
        print("[whisperx_mapper.py] Aligning audio to get word timestamps...")
        result = whisperx.align(
            result["segments"],
            align_model,
            metadata,
            audio,
            device,
            return_char_alignments=True  # This gives us character-level timing
        )

        # Extract character/phoneme timing
        phonemes = []

        if "word_segments" in result:
            for segment in result["word_segments"]:
                word = segment.get("word", "")
                word_start = segment.get("start", 0.0)
                word_end = segment.get("end", 0.0)

                # Check if we have character alignments
                if "chars" in segment:
                    # Use character-level timing to approximate phonemes
                    for char_info in segment["chars"]:
                        char = char_info.get("char", "")
                        char_start = char_info.get("start", word_start)
                        char_end = char_info.get("end", word_end)

                        # Simple char to phoneme mapping
                        phoneme = char_to_rhubarb(char)
                        if phoneme:
                            phonemes.append({
                                "start": round(char_start, 2),
                                "end": round(char_end, 2),
                                "value": phoneme
                            })
                else:
                    # Fallback: distribute word duration evenly
                    word_duration = word_end - word_start
                    chars_in_word = len(word)

                    if chars_in_word > 0:
                        char_duration = word_duration / chars_in_word
                        for i, char in enumerate(word):
                            char_start = word_start + (i * char_duration)
                            char_end = char_start + char_duration
                            phoneme = char_to_rhubarb(char)
                            if phoneme:
                                phonemes.append({
                                    "start": round(char_start, 2),
                                    "end": round(char_end, 2),
                                    "value": phoneme
                                })

        # Merge consecutive identical phonemes
        phonemes = merge_consecutive_phonemes(phonemes)

        # Clean up GPU memory if using CUDA
        if device.startswith("cuda"):
            gc.collect()
            torch.cuda.empty_cache()

        print(f"[whisperx_mapper.py] ✓ Generated {len(phonemes)} phoneme cues")
        return phonemes

    except Exception as e:
        print(f"[whisperx_mapper.py] ✗ WhisperX error: {e}")
        import traceback
        traceback.print_exc()

        # Return silence fallback
        return [{"start": 0.0, "end": 1.0, "value": "X"}]

def char_to_rhubarb(char):
    """Simple character to Rhubarb phoneme mapping"""
    char = char.lower().strip()

    # Skip spaces and punctuation
    if not char.isalpha():
        return None

    # Very basic mapping (simplified)
    mapping = {
        'a': 'A', 'e': 'E', 'i': 'E', 'o': 'A', 'u': 'C',
        'b': 'B', 'm': 'B', 'p': 'B',
        'f': 'F', 'v': 'F',
        'w': 'C',
        't': 'D', 'd': 'D', 'n': 'D', 's': 'C', 'z': 'C',
        'l': 'H', 'r': 'H',
        'k': 'G', 'g': 'G', 'c': 'G',
        'h': 'E', 'y': 'E', 'j': 'C',
        'q': 'G', 'x': 'G'
    }

    return mapping.get(char, 'E')

def merge_consecutive_phonemes(phonemes):
    """Merge consecutive identical phonemes to reduce jitter"""
    if not phonemes:
        return phonemes

    merged = []
    current = phonemes[0].copy()

    for phoneme in phonemes[1:]:
        if phoneme["value"] == current["value"]:
            # Extend current phoneme duration
            current["end"] = phoneme["end"]
        else:
            # Save current and start new one
            merged.append(current)
            current = phoneme.copy()

    # Don't forget the last one
    merged.append(current)

    return merged

# Alternative: Use text-based approach with WhisperX word timing
def whisperx_text_to_phonemes(text, audio_path):
    """
    Hybrid approach: Use WhisperX for word boundaries,
    then distribute phonemes within each word

    Args:
        text: Text that was spoken
        audio_path: Path to audio file

    Returns:
        List of phoneme dicts with accurate timing
    """
    try:
        from phonemizer import phonemize
        from phonemizer.separator import Separator

        # Load models
        model, align_model, metadata, device = load_whisperx_models()

        # Load and transcribe audio
        audio = whisperx.load_audio(audio_path)
        result = model.transcribe(audio, batch_size=16)

        # Align to get word timestamps
        result = whisperx.align(
            result["segments"],
            align_model,
            metadata,
            audio,
            device
        )

        phonemes = []

        if "word_segments" in result:
            for word_seg in result["word_segments"]:
                word = word_seg.get("word", "").strip()
                word_start = word_seg.get("start", 0.0)
                word_end = word_seg.get("end", 0.0)

                if not word:
                    continue

                # Get phonemes for this word
                try:
                    word_phonemes = phonemize(
                        word,
                        language='en-us',
                        backend='espeak',
                        separator=Separator(phone='|', word=' '),
                        strip=True,
                        preserve_punctuation=False,
                        with_stress=False
                    )

                    phones = [p.strip() for p in word_phonemes.split('|') if p.strip()]

                    if phones:
                        # Distribute word duration across phonemes
                        word_duration = word_end - word_start
                        phone_duration = word_duration / len(phones)

                        for i, phone in enumerate(phones):
                            start = word_start + (i * phone_duration)
                            end = start + phone_duration

                            # Map IPA to Rhubarb (reuse from phoneme_mapper)
                            rhubarb = ipa_to_rhubarb(phone)

                            phonemes.append({
                                "start": round(start, 2),
                                "end": round(end, 2),
                                "value": rhubarb
                            })

                except Exception as e:
                    print(f"[whisperx_mapper.py] ⚠ Error phonemizing word '{word}': {e}")
                    # Fallback: use simple char mapping
                    word_duration = word_end - word_start
                    char_duration = word_duration / len(word)
                    for i, char in enumerate(word):
                        phoneme = char_to_rhubarb(char)
                        if phoneme:
                            phonemes.append({
                                "start": round(word_start + (i * char_duration), 2),
                                "end": round(word_start + ((i + 1) * char_duration), 2),
                                "value": phoneme
                            })

        # Merge consecutive
        phonemes = merge_consecutive_phonemes(phonemes)

        # Cleanup
        if device.startswith("cuda"):
            gc.collect()
            torch.cuda.empty_cache()

        print(f"[whisperx_mapper.py] ✓ Generated {len(phonemes)} phoneme cues with WhisperX timing")
        return phonemes

    except Exception as e:
        print(f"[whisperx_mapper.py] ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return [{"start": 0.0, "end": 1.0, "value": "X"}]

def ipa_to_rhubarb(ipa_phone):
    """Convert IPA phoneme to Rhubarb (simplified)"""
    # Reuse mapping from phoneme_mapper
    mapping = {
        'ɑ': 'A', 'æ': 'A', 'ʌ': 'A', 'ɔ': 'A',
        'ɛ': 'E', 'ə': 'E', 'ɪ': 'E', 'i': 'E',
        'ʊ': 'C', 'u': 'C',
        'p': 'B', 'b': 'B', 'm': 'B', 'w': 'B',
        'f': 'F', 'v': 'F',
        't': 'D', 'd': 'D', 'n': 'D',
        's': 'C', 'z': 'C', 'l': 'H', 'r': 'H',
        'ʃ': 'C', 'ʒ': 'C', 'tʃ': 'C', 'dʒ': 'C',
        'k': 'G', 'g': 'G', 'ŋ': 'G',
        'h': 'E',
        ' ': 'X', '': 'X'
    }

    # Try exact match
    if ipa_phone in mapping:
        return mapping[ipa_phone]

    # Try first character
    if len(ipa_phone) > 0 and ipa_phone[0] in mapping:
        return mapping[ipa_phone[0]]

    # Default
    return 'E'
