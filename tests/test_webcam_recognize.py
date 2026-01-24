#!/usr/bin/env python3
"""
Test harness for webcam_recognize tool

Usage:
    # Test with cached webcam frame (requires webcam enabled in UI)
    python tests/test_webcam_recognize.py

    # Test with a specific image file
    python tests/test_webcam_recognize.py --image /path/to/image.jpg

    # Test face recognition only (no vision)
    python tests/test_webcam_recognize.py --no-vision

    # Test with custom vision prompt
    python tests/test_webcam_recognize.py --prompt "What is the person holding?"

    # Verbose output
    python tests/test_webcam_recognize.py -v
"""

import sys
import os
import argparse
import json
from pathlib import Path
from datetime import datetime

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def check_webcam_cache():
    """Check if webcam cache exists and is fresh"""
    cache_dir = "/tmp/iris_webcam_cache"
    frame_path = os.path.join(cache_dir, "frame_latest.jpg")

    if not os.path.exists(frame_path):
        return None, "No cached frame found. Enable webcam in the chat UI."

    mtime = datetime.fromtimestamp(os.path.getmtime(frame_path))
    age = (datetime.now() - mtime).total_seconds()

    if age > 10:
        return None, f"Cached frame is stale ({age:.1f}s old). Re-enable webcam."

    return frame_path, f"Frame age: {age:.1f}s"


def test_face_recognition(image_path: str, threshold: float = None, verbose: bool = False):
    """Test face recognition on an image"""
    print("\n" + "=" * 60)
    print("FACE RECOGNITION TEST")
    print("=" * 60)

    try:
        from core import face_recognition as fr

        print(f"Loading image: {image_path}")
        img = fr.load_image_from_path(image_path)

        if img is None:
            print("ERROR: Failed to load image")
            return None

        print(f"Image shape: {img.shape}")
        print(f"Running face recognition (threshold: {threshold or 'default'})...")

        results = fr.recognize_face(img, similarity_threshold=threshold)

        if not results:
            print("No faces detected in image")
            return []

        print(f"\nDetected {len(results)} face(s):")

        recognized = []
        for i, face in enumerate(results):
            print(f"\n  Face {i + 1}:")
            if face.get('best_match'):
                match = face['best_match']
                name = match['name']
                similarity = match.get('avg_similarity', 0)
                print(f"    Name: {name}")
                print(f"    Confidence: {similarity * 100:.1f}%")
                print(f"    Relationship: {match.get('relationship', 'unknown')}")
                print(f"    Training images: {match.get('training_image_count', 0)}")
                recognized.append({
                    "name": name,
                    "confidence": round(similarity * 100, 1),
                    "relationship": match.get('relationship')
                })

                if verbose and 'all_matches' in face:
                    print(f"    All matches:")
                    for m in face['all_matches'][:5]:
                        print(f"      - {m['name']}: {m['similarity']*100:.1f}%")
            else:
                print(f"    Unknown face (no match above threshold)")
                if verbose and 'all_matches' in face:
                    print(f"    Top candidates:")
                    for m in face.get('all_matches', [])[:3]:
                        print(f"      - {m['name']}: {m['similarity']*100:.1f}%")

        return recognized

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return None


def test_vision_analysis(image_path: str, prompt: str = None, verbose: bool = False):
    """Test vision analysis on an image"""
    print("\n" + "=" * 60)
    print("VISION ANALYSIS TEST")
    print("=" * 60)

    try:
        from core.vision_manager import VisionManager
        import base64

        # Read and encode image
        print(f"Loading image: {image_path}")
        with open(image_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode('utf-8')

        # Default prompt
        if not prompt:
            prompt = "Describe what you see in this image. Include any people, objects, actions, and the setting."

        print(f"Vision prompt: {prompt[:100]}...")
        print("Calling vision model...")

        vm = VisionManager()
        description = vm.analyze_image(image_data, prompt)

        if description:
            print(f"\nVision Analysis Result:")
            print("-" * 40)
            print(description)
            print("-" * 40)
            return description
        else:
            print("No description returned from vision model")
            return None

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return None


def test_full_webcam_recognize(image_path: str = None, threshold: float = None,
                                describe_scene: bool = True, vision_prompt: str = None,
                                verbose: bool = False):
    """Test the full webcam_recognize tool flow"""
    print("\n" + "=" * 60)
    print("FULL WEBCAM_RECOGNIZE TOOL TEST")
    print("=" * 60)

    # Determine image path
    if image_path:
        if not os.path.exists(image_path):
            print(f"ERROR: Image not found: {image_path}")
            return None
        print(f"Using provided image: {image_path}")
    else:
        image_path, status = check_webcam_cache()
        if not image_path:
            print(f"ERROR: {status}")
            return None
        print(f"Using cached webcam frame: {image_path}")
        print(f"  {status}")

    # Import and call the actual tool
    try:
        from mcp_servers.info.info_server import webcam_recognize

        print(f"\nCalling webcam_recognize tool...")
        print(f"  describe_scene: {describe_scene}")
        print(f"  vision_prompt: {vision_prompt or 'default'}")
        print(f"  threshold: {threshold or 'default'}")

        # Temporarily copy test image to webcam cache if using custom image
        if image_path and not image_path.startswith("/tmp/iris_webcam_cache"):
            import shutil
            cache_dir = "/tmp/iris_webcam_cache"
            os.makedirs(cache_dir, exist_ok=True)
            cache_path = os.path.join(cache_dir, "frame_latest.jpg")
            shutil.copy2(image_path, cache_path)
            print(f"  Copied test image to webcam cache")

        result = webcam_recognize(
            camera_id=0,
            similarity_threshold=threshold,
            describe_scene=describe_scene,
            vision_prompt=vision_prompt
        )

        print(f"\n{'=' * 60}")
        print("RESULT")
        print("=" * 60)
        print(json.dumps(result, indent=2, default=str))

        return result

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return None


def main():
    parser = argparse.ArgumentParser(description="Test webcam_recognize tool")
    parser.add_argument("--image", "-i", help="Path to test image (uses webcam cache if not provided)")
    parser.add_argument("--threshold", "-t", type=float, help="Face recognition similarity threshold")
    parser.add_argument("--no-vision", action="store_true", help="Skip vision analysis")
    parser.add_argument("--prompt", "-p", help="Custom vision prompt")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--face-only", action="store_true", help="Only test face recognition (not full tool)")
    parser.add_argument("--vision-only", action="store_true", help="Only test vision analysis (not full tool)")

    args = parser.parse_args()

    print("=" * 60)
    print("WEBCAM RECOGNIZE TOOL TEST HARNESS")
    print("=" * 60)
    print(f"Time: {datetime.now().isoformat()}")

    # Determine image path
    if args.image:
        image_path = args.image
        if not os.path.exists(image_path):
            print(f"ERROR: Image not found: {image_path}")
            sys.exit(1)
    else:
        image_path, status = check_webcam_cache()
        if not image_path:
            print(f"\nNo image provided and {status}")
            print("\nOptions:")
            print("  1. Enable webcam in the Iris chat UI")
            print("  2. Provide a test image: python tests/test_webcam_recognize.py --image /path/to/image.jpg")
            sys.exit(1)
        print(f"\nUsing cached webcam frame: {status}")

    # Run tests based on flags
    if args.face_only:
        test_face_recognition(image_path, args.threshold, args.verbose)
    elif args.vision_only:
        test_vision_analysis(image_path, args.prompt, args.verbose)
    else:
        # Full tool test
        test_full_webcam_recognize(
            image_path=args.image,  # Pass original arg so it knows if we're using custom image
            threshold=args.threshold,
            describe_scene=not args.no_vision,
            vision_prompt=args.prompt,
            verbose=args.verbose
        )

    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
