"""
Wav2Vec2 CTC Forced Alignment for Lip Sync
Frame-accurate phoneme boundaries using transformer-based alignment
This is simpler than MFA and works excellently with TTS audio
"""

import torch
import torchaudio
from dataclasses import dataclass
import re

# Monkey-patch for PyTorch 2.6 compatibility (same as whisperx_mapper)
_original_torch_load = torch.load

def _torch_load_wrapper(*args, **kwargs):
    """Wrapper for torch.load that sets weights_only=False"""
    kwargs['weights_only'] = False
    return _original_torch_load(*args, **kwargs)

torch.load = _torch_load_wrapper

# Cache model and components
_wav2vec2_model = None
_wav2vec2_labels = None
_wav2vec2_device = None

# ARPAbet phonemes to Rhubarb mouth shapes
ARPABET_TO_RHUBARB = {
    # Vowels - Open
    'AA': 'A', 'AE': 'A', 'AH': 'A', 'AO': 'A', 'AW': 'A',
    # Vowels - Medium/Relaxed
    'EH': 'E', 'ER': 'E', 'IH': 'E', 'IY': 'E', 'UH': 'E',
    'AY': 'E', 'EY': 'E', 'OY': 'E',
    # Vowels - Rounded
    'OW': 'C', 'UW': 'C',
    # Bilabial - Lips together
    'P': 'B', 'B': 'B', 'M': 'B',
    # Labiodental - Lip to teeth
    'F': 'F', 'V': 'F', 'TH': 'F', 'DH': 'F',
    # Alveolar - Tongue to ridge
    'T': 'D', 'D': 'D', 'N': 'D',
    'S': 'C', 'Z': 'C',
    'L': 'H', 'R': 'H',
    # Post-alveolar
    'SH': 'C', 'ZH': 'C', 'CH': 'C', 'JH': 'C',
    # Velar - Back of tongue
    'K': 'G', 'G': 'G', 'NG': 'G',
    # Other
    'HH': 'E', 'W': 'C', 'Y': 'E',
    # Silence
    'SIL': 'X', 'SP': 'X', '': 'X', '|': 'X'
}

@dataclass
class AlignmentSegment:
    """Represents a phoneme with timing"""
    label: str
    start: float
    end: float
    score: float

def get_device():
    """Get best available device - GPU 1 (RTX 4080) to avoid main model on GPU 0"""
    return "cuda:1" if torch.cuda.is_available() else "cpu"

def load_wav2vec2_model():
    """Load Wav2Vec2 model for phoneme recognition"""
    global _wav2vec2_model, _wav2vec2_labels, _wav2vec2_device

    if _wav2vec2_model is not None:
        return _wav2vec2_model, _wav2vec2_labels, _wav2vec2_device

    print("[wav2vec2_aligner.py] Loading Wav2Vec2 CTC model...")

    _wav2vec2_device = get_device()

    # Use the base wav2vec2 model with CTC for alignment
    # This model outputs phoneme-level predictions
    bundle = torchaudio.pipelines.WAV2VEC2_ASR_BASE_960H
    _wav2vec2_model = bundle.get_model().to(_wav2vec2_device)
    _wav2vec2_labels = bundle.get_labels()

    print(f"[wav2vec2_aligner.py] ✓ Wav2Vec2 loaded on {_wav2vec2_device}")
    print(f"[wav2vec2_aligner.py] ✓ Labels: {len(_wav2vec2_labels)} tokens")

    return _wav2vec2_model, _wav2vec2_labels, _wav2vec2_device

def align_audio_wav2vec2(audio_path, transcript):
    """
    Use Wav2Vec2 + CTC forced alignment to get frame-accurate phoneme boundaries

    Args:
        audio_path: Path to WAV file
        transcript: Text transcript of what was spoken

    Returns:
        List of phoneme dicts: [{"start": 0.0, "end": 0.1, "value": "A"}, ...]
    """
    try:
        # Load model
        model, labels, device = load_wav2vec2_model()

        print(f"[wav2vec2_aligner.py] Aligning audio: {audio_path}")
        print(f"[wav2vec2_aligner.py] Transcript: {transcript}")

        # Load audio
        waveform, sample_rate = torchaudio.load(audio_path)

        # Resample if needed (Wav2Vec2 expects 16kHz)
        if sample_rate != bundle.sample_rate:
            resampler = torchaudio.transforms.Resample(sample_rate, bundle.sample_rate)
            waveform = resampler(waveform)
            sample_rate = bundle.sample_rate

        # Move to device
        waveform = waveform.to(device)

        # Get emissions (CTC output)
        with torch.inference_mode():
            emissions, _ = model(waveform)
            emissions = torch.log_softmax(emissions, dim=-1)

        emission = emissions[0].cpu().detach()

        # Prepare transcript for alignment
        transcript_clean = transcript.upper().replace("'", "").replace("-", " ")
        transcript_clean = re.sub(r'[^A-Z ]', '', transcript_clean)

        # Convert to token indices
        dictionary = {c: i for i, c in enumerate(labels)}
        tokens = [dictionary[c] for c in transcript_clean if c in dictionary]

        print(f"[wav2vec2_aligner.py] Transcript tokens: {len(tokens)}")

        # Perform CTC forced alignment
        trellis = get_trellis(emission, tokens)
        path = backtrack(trellis, emission, tokens)
        segments = merge_repeats(path, transcript_clean)

        # Convert to phoneme format with Rhubarb mapping
        phonemes = []
        frame_duration = 1.0 / (sample_rate / 320)  # Wav2Vec2 frame rate

        for seg in segments:
            # Simple letter-to-phoneme (could be improved with phonemizer)
            char = seg.label

            # Map character to approximate phoneme
            phoneme_map = {
                'A': 'AA', 'E': 'EH', 'I': 'IH', 'O': 'AO', 'U': 'UH',
                'B': 'B', 'C': 'K', 'D': 'D', 'F': 'F', 'G': 'G',
                'H': 'HH', 'J': 'JH', 'K': 'K', 'L': 'L', 'M': 'M',
                'N': 'N', 'P': 'P', 'Q': 'K', 'R': 'R', 'S': 'S',
                'T': 'T', 'V': 'V', 'W': 'W', 'X': 'K', 'Y': 'Y', 'Z': 'Z',
                ' ': 'SIL'
            }

            arpabet = phoneme_map.get(char, 'SIL')
            rhubarb = ARPABET_TO_RHUBARB.get(arpabet, 'E')

            start_time = seg.start * frame_duration
            end_time = seg.end * frame_duration

            phonemes.append({
                "start": round(start_time, 2),
                "end": round(end_time, 2),
                "value": rhubarb
            })

        # Merge consecutive identical phonemes
        phonemes = merge_consecutive_phonemes(phonemes)

        print(f"[wav2vec2_aligner.py] ✓ Generated {len(phonemes)} phoneme cues")
        return phonemes

    except Exception as e:
        print(f"[wav2vec2_aligner.py] ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return [{"start": 0.0, "end": 1.0, "value": "X"}]

def get_trellis(emission, tokens, blank_id=0):
    """Build CTC trellis for alignment"""
    num_frame = emission.size(0)
    num_tokens = len(tokens)

    # Initialize trellis
    trellis = torch.full((num_frame + 1, num_tokens + 1), float('-inf'))
    trellis[0, 0] = 0

    for t in range(num_frame):
        trellis[t + 1, 0] = trellis[t, 0] + emission[t, blank_id]

    for j in range(1, num_tokens + 1):
        for t in range(num_frame):
            trellis[t + 1, j] = torch.logaddexp(
                trellis[t, j] + emission[t, blank_id],
                trellis[t, j - 1] + emission[t, tokens[j - 1]]
            )

    return trellis

def backtrack(trellis, emission, tokens, blank_id=0):
    """Backtrack through trellis to find best path"""
    j = trellis.size(1) - 1
    t_start = torch.argmax(trellis[:, j]).item()

    path = []
    for t in range(t_start, 0, -1):
        stayed = trellis[t - 1, j] + emission[t - 1, blank_id]
        changed = trellis[t - 1, j - 1] + emission[t - 1, tokens[j - 1]]

        prob = emission[t - 1, tokens[j - 1] if changed > stayed else blank_id].exp().item()

        path.append(AlignmentSegment(
            label=tokens[j - 1] if changed > stayed else blank_id,
            start=t - 1,
            end=t,
            score=prob
        ))

        if changed > stayed:
            j -= 1
            if j == 0:
                break

    return path[::-1]

def merge_repeats(path, transcript):
    """Merge repeated characters and map to transcript"""
    i1, i2 = 0, 0
    segments = []

    while i1 < len(path):
        while i2 < len(path) and path[i1].label == path[i2].label:
            i2 += 1

        score = sum(path[k].score for k in range(i1, i2)) / (i2 - i1)

        segments.append(AlignmentSegment(
            label=transcript[len(segments)] if len(segments) < len(transcript) else ' ',
            start=path[i1].start,
            end=path[i2 - 1].end,
            score=score
        ))

        i1 = i2

    return segments

def merge_consecutive_phonemes(phonemes):
    """Merge consecutive identical phonemes to reduce jitter"""
    if not phonemes:
        return phonemes

    merged = []
    current = phonemes[0].copy()

    for phoneme in phonemes[1:]:
        if phoneme["value"] == current["value"]:
            current["end"] = phoneme["end"]
        else:
            merged.append(current)
            current = phoneme.copy()

    merged.append(current)
    return merged

# Global reference to bundle
bundle = torchaudio.pipelines.WAV2VEC2_ASR_BASE_960H
