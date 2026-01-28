"""
TTS API route - proxies requests to XTTS server to avoid CORS issues
NOW WITH RHUBARB LIP SYNC: Returns audio + phoneme timing for 3D avatar animation
"""

from fastapi import APIRouter, HTTPException, File, UploadFile, Form
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
import httpx
import os
import sys
import re
import subprocess
import tempfile
import json
import base64
import wave
import emoji

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, PROJECT_ROOT)

from app import config
from app.api.phoneme_mapper import text_to_rhubarb_phonemes
from app.api.whisperx_mapper import whisperx_text_to_phonemes
from app.api.wav2vec2_aligner import align_audio_wav2vec2
from app.api.tts_normalizer import normalize_for_tts

router = APIRouter(tags=["tts"])

# XTTS server configuration
# Note: No trailing slash - XTTS redirects if present
# Supports environment variable override for flexibility
_xtts_base = os.environ.get('XTTS_SERVER_URL', config.XTTS_SERVER_URL)
XTTS_SERVER_URL = f"{_xtts_base}/speak_stream_mp3"
XTTS_WAV_URL = f"{_xtts_base}/speak_stream_wav"  # For Rhubarb (needs WAV)

class TTSRequest(BaseModel):
    text: str

class TTSWithPhonemeRequest(BaseModel):
    text: str
    include_phonemes: bool = True  # Set to False to skip Rhubarb processing

def clean_text_for_tts(text: str) -> str:
    """
    Clean text for TTS by removing markdown formatting and special characters,
    then normalize technical terms for proper pronunciation.

    Args:
        text: Raw text with possible markdown formatting

    Returns:
        Cleaned and normalized text suitable for TTS
    """
    # Remove markdown bold/italic
    text = re.sub(r'\*\*\*(.+?)\*\*\*', r'\1', text)  # ***bold italic***
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)      # **bold**
    text = re.sub(r'\*(.+?)\*', r'\1', text)          # *italic*
    text = re.sub(r'__(.+?)__', r'\1', text)          # __bold__
    text = re.sub(r'_(.+?)_', r'\1', text)            # _italic_

    # Remove markdown headers
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)

    # Remove markdown horizontal rules
    text = re.sub(r'^---+$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\*\*\*+$', '', text, flags=re.MULTILINE)

    # Remove markdown links but keep text
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)

    # Remove markdown code blocks
    text = re.sub(r'```[^\n]*\n.*?```', '', text, flags=re.DOTALL)
    text = re.sub(r'`([^`]+)`', r'\1', text)

    # Remove markdown lists markers
    text = re.sub(r'^[\*\-\+]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\d+\.\s+', '', text, flags=re.MULTILINE)

    # Replace newlines with spaces
    text = text.replace('\n', ' ')

    # Remove multiple spaces
    text = re.sub(r'\s+', ' ', text)

    text = emoji.replace_emoji(text, replace='')

    # Remove leading/trailing whitespace
    text = text.strip()

    # Normalize technical terms for proper pronunciation
    # (GPU names, acronyms, storage units, etc.)
    text = normalize_for_tts(text)

    return text

@router.post("/api/tts/speak")
async def speak(request: TTSRequest):
    """
    Proxy TTS requests to XTTS server

    Args:
        request: TTSRequest with text to speak

    Returns:
        Audio stream (OGG format)
    """



    try:
        # Clean text for TTS (remove markdown, special chars, etc.)
        cleaned_text = clean_text_for_tts(request.text)

        # Skip if text becomes empty after cleaning
        if not cleaned_text:
            print(f"[routes_tts.py][speak] ⚠ Text empty after cleaning, skipping")
            raise HTTPException(status_code=400, detail="Text empty after cleaning")

        print(f"[routes_tts.py][speak] Original: {request.text[:50]}...")
        print(f"[routes_tts.py][speak] Cleaned: {cleaned_text[:50]}...")
        print(f"[routes_tts.py][speak] Target URL: {XTTS_SERVER_URL}")

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            # Forward request to XTTS server with cleaned text
            response = await client.post(
                XTTS_SERVER_URL,
                json={"text": cleaned_text},
                headers={"Content-Type": "application/json"}
            )

            print(f"[routes_tts.py][speak] XTTS response status: {response.status_code}")
            print(f"[routes_tts.py][speak] XTTS response headers: {response.headers}")

            if response.status_code != 200:
                # Log the error response body
                error_body = response.text[:500]  # First 500 chars
                print(f"[routes_tts.py][speak] ✗ XTTS server error: {response.status_code}")
                print(f"[routes_tts.py][speak] ✗ XTTS error response: {error_body}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"XTTS server error: {error_body}"
                )

            print(f"[routes_tts.py][speak] ✓ TTS completed successfully, audio size: {len(response.content)} bytes")

            # Return audio stream with proper headers
            return StreamingResponse(
                iter([response.content]),
                media_type="audio/mpeg",
                headers={
                    "Content-Type": "audio/mpeg",
                    "Cache-Control": "no-cache"
                }
            )

    except httpx.TimeoutException:
        print(f"[routes_tts.py][speak] ✗ XTTS server timeout")
        raise HTTPException(status_code=504, detail="XTTS server timeout")
    except httpx.ConnectError:
        print(f"[routes_tts.py][speak] ✗ Cannot connect to XTTS server")
        raise HTTPException(status_code=503, detail="Cannot connect to XTTS server")
    except Exception as e:
        print(f"[routes_tts.py][speak] ✗ Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/tts/speak_with_phonemes")
async def speak_with_phonemes(request: TTSWithPhonemeRequest):
    """
    Generate speech with phoneme timing data for lip-sync animation

    Flow:
    1. Send text to XTTS → get MP3 audio
    2. Save audio to temp file
    3. Run Rhubarb Lip Sync on audio → get phoneme timing
    4. Return JSON: {audio: base64_mp3, phonemes: [{start, end, value}, ...]}

    Args:
        request: TTSWithPhonemeRequest with text and phoneme flag

    Returns:
        JSON with audio (base64) and phoneme timing data
    """
    temp_audio_path = None

    try:
        # Clean text for TTS
        cleaned_text = clean_text_for_tts(request.text)

        if not cleaned_text:
            raise HTTPException(status_code=400, detail="Text empty after cleaning")

        print(f"[routes_tts.py][speak_with_phonemes] Processing: '{cleaned_text[:50]}...'")

        # Step 1: Get WAV audio from XTTS (Rhubarb needs WAV, not MP3)
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.post(
                XTTS_WAV_URL,  # Use WAV endpoint instead of MP3
                json={"text": cleaned_text},
                headers={"Content-Type": "application/json"}
            )

            if response.status_code != 200:
                error_body = response.text[:500]
                print(f"[routes_tts.py][speak_with_phonemes] ✗ XTTS error: {response.status_code}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"XTTS server error: {error_body}"
                )

            audio_data = response.content
            print(f"[routes_tts.py][speak_with_phonemes] ✓ WAV audio generated: {len(audio_data)} bytes")

        # Step 2: Save WAV to temp file for Rhubarb
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.wav', delete=False) as f:
            temp_audio_path = f.name
            f.write(audio_data)

        print(f"[routes_tts.py][speak_with_phonemes] ✓ WAV saved to: {temp_audio_path}")

        # Step 3: Use ONLY text-based phonemes (simple, direct)
        phonemes = []

        if request.include_phonemes:
            try:
                # Get audio duration
                with wave.open(temp_audio_path, 'rb') as wav_file:
                    frames = wav_file.getnframes()
                    rate = wav_file.getframerate()
                    audio_duration = frames / float(rate)

                # Use ONLY text analysis - simplest approach
                phonemes = text_to_rhubarb_phonemes(cleaned_text, audio_duration)
                print(f"[routes_tts.py][speak_with_phonemes] ✓ Generated {len(phonemes)} phonemes from text")

            except Exception as e:
                print(f"[routes_tts.py][speak_with_phonemes] ✗ Phoneme generation error: {e}")
                print(f"[routes_tts.py][speak_with_phonemes] ⚠ Continuing without phonemes")

        # Step 4: Encode audio as base64
        audio_base64 = base64.b64encode(audio_data).decode('utf-8')

        # Step 5: Return combined response
        response_data = {
            "success": True,
            "audio": audio_base64,
            "audio_format": "wav",  # Now returning WAV instead of MP3
            "phonemes": phonemes,
            "text": cleaned_text,
            "duration": phonemes[-1]["end"] if phonemes else None
        }

        print(f"[routes_tts.py][speak_with_phonemes] ✓ Complete: {len(phonemes)} phonemes, {len(audio_base64)} chars base64")

        return JSONResponse(content=response_data)

    except subprocess.TimeoutExpired:
        print(f"[routes_tts.py][speak_with_phonemes] ✗ Rhubarb timeout")
        raise HTTPException(status_code=504, detail="Rhubarb lip sync timeout")
    except httpx.TimeoutException:
        print(f"[routes_tts.py][speak_with_phonemes] ✗ XTTS timeout")
        raise HTTPException(status_code=504, detail="XTTS server timeout")
    except httpx.ConnectError:
        print(f"[routes_tts.py][speak_with_phonemes] ✗ Cannot connect to XTTS")
        raise HTTPException(status_code=503, detail="Cannot connect to XTTS server")
    except Exception as e:
        print(f"[routes_tts.py][speak_with_phonemes] ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Clean up temp files
        if temp_audio_path and os.path.exists(temp_audio_path):
            try:
                os.unlink(temp_audio_path)
            except Exception as e:
                print(f"[routes_tts.py][speak_with_phonemes] ⚠ Failed to delete temp file {temp_audio_path}: {e}")

@router.post("/api/tts/speak_with_whisperx")
async def speak_with_whisperx(request: TTSWithPhonemeRequest):
    """
    Generate speech with WhisperX-based phoneme timing (MOST ACCURATE)

    Flow:
    1. Send text to XTTS → get WAV audio
    2. Save audio to temp file
    3. Run WhisperX alignment → get accurate word + phoneme timing
    4. Return JSON: {audio: base64_wav, phonemes: [{start, end, value}, ...]}

    Args:
        request: TTSWithPhonemeRequest with text and phoneme flag

    Returns:
        JSON with audio (base64) and accurate phoneme timing data
    """
    temp_audio_path = None

    try:
        # Clean text for TTS
        cleaned_text = clean_text_for_tts(request.text)

        if not cleaned_text:
            raise HTTPException(status_code=400, detail="Text empty after cleaning")

        print(f"[routes_tts.py][speak_with_whisperx] Processing: '{cleaned_text[:50]}...'")

        # Step 1: Get WAV audio from XTTS
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.post(
                XTTS_WAV_URL,
                json={"text": cleaned_text},
                headers={"Content-Type": "application/json"}
            )

            if response.status_code != 200:
                error_body = response.text[:500]
                print(f"[routes_tts.py][speak_with_whisperx] ✗ XTTS error: {response.status_code}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"XTTS server error: {error_body}"
                )

            audio_data = response.content
            print(f"[routes_tts.py][speak_with_whisperx] ✓ WAV audio generated: {len(audio_data)} bytes")

        # Step 2: Save WAV to temp file for WhisperX
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.wav', delete=False) as f:
            temp_audio_path = f.name
            f.write(audio_data)

        print(f"[routes_tts.py][speak_with_whisperx] ✓ WAV saved to: {temp_audio_path}")

        # Step 3: Use WhisperX for accurate phoneme timing
        phonemes = []

        if request.include_phonemes:
            try:
                print("[routes_tts.py][speak_with_whisperx] Running WhisperX alignment...")
                phonemes = whisperx_text_to_phonemes(cleaned_text, temp_audio_path)
                print(f"[routes_tts.py][speak_with_whisperx] ✓ Generated {len(phonemes)} phonemes via WhisperX")

            except Exception as e:
                print(f"[routes_tts.py][speak_with_whisperx] ✗ WhisperX error: {e}")
                import traceback
                traceback.print_exc()
                print(f"[routes_tts.py][speak_with_whisperx] ⚠ Continuing without phonemes")

        # Step 4: Get audio duration
        duration = phonemes[-1]["end"] if phonemes else None
        if duration is None:
            try:
                with wave.open(temp_audio_path, 'rb') as wav_file:
                    frames = wav_file.getnframes()
                    rate = wav_file.getframerate()
                    duration = frames / float(rate)
            except:
                duration = 0.0

        # Step 5: Encode audio as base64
        audio_base64 = base64.b64encode(audio_data).decode('utf-8')

        # Step 6: Return combined response
        response_data = {
            "success": True,
            "audio": audio_base64,
            "audio_format": "wav",
            "phonemes": phonemes,
            "text": cleaned_text,
            "duration": duration,
            "method": "whisperx"
        }

        print(f"[routes_tts.py][speak_with_whisperx] ✓ Complete: {len(phonemes)} phonemes, {len(audio_base64)} chars base64")

        return JSONResponse(content=response_data)

    except httpx.TimeoutException:
        print(f"[routes_tts.py][speak_with_whisperx] ✗ XTTS timeout")
        raise HTTPException(status_code=504, detail="XTTS server timeout")
    except httpx.ConnectError:
        print(f"[routes_tts.py][speak_with_whisperx] ✗ Cannot connect to XTTS")
        raise HTTPException(status_code=503, detail="Cannot connect to XTTS server")
    except Exception as e:
        print(f"[routes_tts.py][speak_with_whisperx] ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Clean up temp files
        if temp_audio_path and os.path.exists(temp_audio_path):
            try:
                os.unlink(temp_audio_path)
            except Exception as e:
                print(f"[routes_tts.py][speak_with_whisperx] ⚠ Failed to delete temp file {temp_audio_path}: {e}")

@router.post("/api/tts/speak_with_wav2vec2")
async def speak_with_wav2vec2(request: TTSWithPhonemeRequest):
    """
    Generate speech with Wav2Vec2 CTC forced alignment (FRAME-ACCURATE)

    Flow:
    1. Send text to XTTS → get WAV audio
    2. Save audio to temp file
    3. Run Wav2Vec2 CTC alignment → get frame-level phoneme timing
    4. Return JSON: {audio: base64_wav, phonemes: [{start, end, value}, ...]}

    This is the BEST method for lip sync - frame-accurate phoneme boundaries.

    Args:
        request: TTSWithPhonemeRequest with text and phoneme flag

    Returns:
        JSON with audio (base64) and frame-accurate phoneme timing data
    """
    temp_audio_path = None

    try:
        # Clean text for TTS
        cleaned_text = clean_text_for_tts(request.text)

        if not cleaned_text:
            raise HTTPException(status_code=400, detail="Text empty after cleaning")

        print(f"[routes_tts.py][speak_with_wav2vec2] Processing: '{cleaned_text[:50]}...'")

        # Step 1: Get WAV audio from XTTS
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.post(
                XTTS_WAV_URL,
                json={"text": cleaned_text},
                headers={"Content-Type": "application/json"}
            )

            if response.status_code != 200:
                error_body = response.text[:500]
                print(f"[routes_tts.py][speak_with_wav2vec2] ✗ XTTS error: {response.status_code}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"XTTS server error: {error_body}"
                )

            audio_data = response.content
            print(f"[routes_tts.py][speak_with_wav2vec2] ✓ WAV audio generated: {len(audio_data)} bytes")

        # Step 2: Save WAV to temp file for Wav2Vec2
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.wav', delete=False) as f:
            temp_audio_path = f.name
            f.write(audio_data)

        print(f"[routes_tts.py][speak_with_wav2vec2] ✓ WAV saved to: {temp_audio_path}")

        # Step 3: Use Wav2Vec2 for frame-accurate phoneme timing
        phonemes = []

        if request.include_phonemes:
            try:
                print("[routes_tts.py][speak_with_wav2vec2] Running Wav2Vec2 CTC alignment...")
                phonemes = align_audio_wav2vec2(temp_audio_path, cleaned_text)
                print(f"[routes_tts.py][speak_with_wav2vec2] ✓ Generated {len(phonemes)} phonemes via Wav2Vec2")

            except Exception as e:
                print(f"[routes_tts.py][speak_with_wav2vec2] ✗ Wav2Vec2 error: {e}")
                import traceback
                traceback.print_exc()
                print(f"[routes_tts.py][speak_with_wav2vec2] ⚠ Continuing without phonemes")

        # Step 4: Get audio duration
        duration = phonemes[-1]["end"] if phonemes else None
        if duration is None:
            try:
                with wave.open(temp_audio_path, 'rb') as wav_file:
                    frames = wav_file.getnframes()
                    rate = wav_file.getframerate()
                    duration = frames / float(rate)
            except:
                duration = 0.0

        # Step 5: Encode audio as base64
        audio_base64 = base64.b64encode(audio_data).decode('utf-8')

        # Step 6: Return combined response
        response_data = {
            "success": True,
            "audio": audio_base64,
            "audio_format": "wav",
            "phonemes": phonemes,
            "text": cleaned_text,
            "duration": duration,
            "method": "wav2vec2-ctc"
        }

        print(f"[routes_tts.py][speak_with_wav2vec2] ✓ Complete: {len(phonemes)} phonemes, {len(audio_base64)} chars base64")

        return JSONResponse(content=response_data)

    except httpx.TimeoutException:
        print(f"[routes_tts.py][speak_with_wav2vec2] ✗ XTTS timeout")
        raise HTTPException(status_code=504, detail="XTTS server timeout")
    except httpx.ConnectError:
        print(f"[routes_tts.py][speak_with_wav2vec2] ✗ Cannot connect to XTTS")
        raise HTTPException(status_code=503, detail="Cannot connect to XTTS server")
    except Exception as e:
        print(f"[routes_tts.py][speak_with_wav2vec2] ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Clean up temp files
        if temp_audio_path and os.path.exists(temp_audio_path):
            try:
                os.unlink(temp_audio_path)
            except Exception as e:
                print(f"[routes_tts.py][speak_with_wav2vec2] ⚠ Failed to delete temp file {temp_audio_path}: {e}")

@router.post("/api/tts/analyze_uploaded_audio")
async def analyze_uploaded_audio(audio: UploadFile = File(...), text: str = Form(...)):
    """
    Analyze uploaded audio file with Rhubarb to get phoneme timing
    Tests whether Rhubarb works better with human voice vs synthetic TTS

    Args:
        audio: Uploaded audio file (WAV, MP3, etc)
        text: Transcript of what's spoken in the audio

    Returns:
        JSON with phonemes: [{"start": 0.0, "end": 0.5, "value": "A"}, ...]
    """
    temp_audio_path = None
    temp_dialog_path = None
    temp_output_path = None

    try:
        print(f"[routes_tts.py][analyze_uploaded_audio] Received audio: {audio.filename}, transcript: '{text}'")

        # Step 1: Save uploaded audio to temp file
        suffix = os.path.splitext(audio.filename)[1] or '.wav'
        with tempfile.NamedTemporaryFile(mode='wb', suffix=suffix, delete=False) as f:
            temp_audio_path = f.name
            content = await audio.read()
            f.write(content)

        print(f"[routes_tts.py][analyze_uploaded_audio] ✓ Audio saved to: {temp_audio_path} ({len(content)} bytes)")

        # Step 2: Create dialog file for Rhubarb
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            temp_dialog_path = f.name
            f.write(text)

        print(f"[routes_tts.py][analyze_uploaded_audio] ✓ Dialog file created: {temp_dialog_path}")

        # Step 3: Create temp output file path
        temp_output_fd, temp_output_path = tempfile.mkstemp(suffix='.json')
        os.close(temp_output_fd)

        print(f"[routes_tts.py][analyze_uploaded_audio] ✓ Output path: {temp_output_path}")

        # Step 4: Run Rhubarb
        rhubarb_cmd = [
            '/home/captain/bin/rhubarb',
            '-f', 'json',
            '-o', temp_output_path,
            '--dialogFile', temp_dialog_path,
            temp_audio_path
        ]

        print(f"[routes_tts.py][analyze_uploaded_audio] Running Rhubarb: {' '.join(rhubarb_cmd)}")

        result = subprocess.run(
            rhubarb_cmd,
            capture_output=True,
            text=True,
            timeout=30
        )

        print(f"[routes_tts.py][analyze_uploaded_audio] Rhubarb exit code: {result.returncode}")
        if result.stdout:
            print(f"[routes_tts.py][analyze_uploaded_audio] Rhubarb stdout: {result.stdout}")
        if result.stderr:
            print(f"[routes_tts.py][analyze_uploaded_audio] Rhubarb stderr: {result.stderr}")

        if result.returncode != 0:
            raise Exception(f"Rhubarb failed with exit code {result.returncode}: {result.stderr}")

        # Step 5: Parse Rhubarb output
        with open(temp_output_path, 'r') as f:
            rhubarb_output = json.load(f)

        print(f"[routes_tts.py][analyze_uploaded_audio] ✓ Rhubarb output: {json.dumps(rhubarb_output, indent=2)}")

        # Convert mouthCues to our phoneme format
        mouth_cues = rhubarb_output.get('mouthCues', [])
        phonemes = [
            {
                "start": cue["start"],
                "end": cue["end"],
                "value": cue["value"]
            }
            for cue in mouth_cues
        ]

        print(f"[routes_tts.py][analyze_uploaded_audio] ✓ Extracted {len(phonemes)} phonemes")

        # Step 6: Return response
        response_data = {
            "success": True,
            "phonemes": phonemes,
            "text": text,
            "duration": rhubarb_output.get('metadata', {}).get('duration', None)
        }

        return JSONResponse(content=response_data)

    except subprocess.TimeoutExpired:
        print(f"[routes_tts.py][analyze_uploaded_audio] ✗ Rhubarb timeout")
        raise HTTPException(status_code=504, detail="Rhubarb analysis timeout")
    except Exception as e:
        print(f"[routes_tts.py][analyze_uploaded_audio] ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Clean up temp files
        for path in [temp_audio_path, temp_dialog_path, temp_output_path]:
            if path and os.path.exists(path):
                try:
                    os.unlink(path)
                except Exception as e:
                    print(f"[routes_tts.py][analyze_uploaded_audio] ⚠ Failed to delete temp file {path}: {e}")
