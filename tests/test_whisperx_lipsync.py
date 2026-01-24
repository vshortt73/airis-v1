#!/usr/bin/env python3
"""
Quick test script for WhisperX lip sync endpoint
Tests the /api/tts/speak_with_whisperx endpoint
"""

import requests
import json
import base64
import sys

# Configuration
IRIS_SERVER = "http://localhost:8000"
ENDPOINT = f"{IRIS_SERVER}/api/tts/speak_with_whisperx"

# Test text
TEST_TEXT = "Hello world! This is a test of the lip sync system."

def test_endpoint():
    """Test the WhisperX endpoint"""

    print("=" * 60)
    print("WhisperX Lip Sync Endpoint Test")
    print("=" * 60)
    print(f"\nEndpoint: {ENDPOINT}")
    print(f"Test text: {TEST_TEXT}")
    print("\n" + "-" * 60)

    # Prepare request
    payload = {
        "text": TEST_TEXT,
        "include_phonemes": True
    }

    print("\n📤 Sending request...")
    print(f"Payload: {json.dumps(payload, indent=2)}")

    try:
        # Send request
        response = requests.post(
            ENDPOINT,
            json=payload,
            timeout=60
        )

        print(f"\n📥 Response received:")
        print(f"Status code: {response.status_code}")

        if response.status_code != 200:
            print(f"❌ Error: {response.status_code}")
            print(f"Response: {response.text[:500]}")
            return False

        # Parse response
        data = response.json()

        print(f"\n✅ Success!")
        print(f"Response keys: {list(data.keys())}")

        # Display results
        print("\n" + "=" * 60)
        print("RESULTS")
        print("=" * 60)

        print(f"\n✓ Success: {data.get('success')}")
        print(f"✓ Method: {data.get('method')}")
        print(f"✓ Audio format: {data.get('audio_format')}")
        print(f"✓ Duration: {data.get('duration'):.2f}s")
        print(f"✓ Text: {data.get('text')}")

        # Phoneme info
        phonemes = data.get('phonemes', [])
        print(f"\n✓ Phoneme count: {len(phonemes)}")

        if phonemes:
            print(f"\n📊 Phoneme Timeline:")
            print(f"{'Time':>12} | {'Phoneme':^8} | {'Duration':>10}")
            print("-" * 36)

            for i, p in enumerate(phonemes):
                start = p['start']
                end = p['end']
                value = p['value']
                duration = end - start
                print(f"{start:>5.2f}-{end:>5.2f} | {value:^8} | {duration:>6.2f}s")

                # Show first 10 and last 3
                if i == 9 and len(phonemes) > 13:
                    print(f"... ({len(phonemes) - 13} more) ...")
                    # Skip to last 3
                    continue
                elif i >= 10 and i < len(phonemes) - 3:
                    continue

        # Audio info
        audio_b64 = data.get('audio', '')
        audio_size = len(audio_b64)
        print(f"\n✓ Audio data size: {audio_size:,} bytes (base64)")

        if audio_b64:
            # Decode to check actual size
            audio_bytes = base64.b64decode(audio_b64)
            print(f"✓ Decoded audio size: {len(audio_bytes):,} bytes")

        print("\n" + "=" * 60)
        print("TEST PASSED! ✅")
        print("=" * 60)
        print("\nNext step: Open the HTML test harness")
        print(f"URL: {IRIS_SERVER}/static/xtts_lipsync_harness.html")
        print("=" * 60)

        return True

    except requests.exceptions.ConnectionError:
        print(f"\n❌ Connection error!")
        print(f"Make sure Iris server is running on {IRIS_SERVER}")
        print("\nStart with: ./scripts/start.sh")
        return False

    except requests.exceptions.Timeout:
        print(f"\n❌ Request timeout!")
        print("WhisperX might be loading models (can take 30s first time)")
        print("Try again in a moment")
        return False

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("\n")
    success = test_endpoint()
    print("\n")
    sys.exit(0 if success else 1)
