#!/usr/bin/env python3
"""
Test face recognition similarity scores

Captures from webcam, detects faces, and shows similarity scores
for all registered persons (regardless of threshold).
"""
import os
import sys
sys.path.insert(0, '/iris-v3')

from core.face_recognition import (
    capture_from_camera,
    detect_faces,
    find_best_match,
    get_db_connection
)
from app import config
import psycopg2.extras

print("\n=== Face Recognition Similarity Test ===\n")

# Load latest cached frame
import cv2
cached_frame_path = "/tmp/iris_webcam_cache/frame_latest.jpg"

print(f"Loading cached frame: {cached_frame_path}")
frame = cv2.imread(cached_frame_path)

if frame is None:
    print("✗ Failed to load cached frame")
    print("Trying direct webcam capture...")
    frame = capture_from_camera("/dev/video0")
    if frame is None:
        print("✗ Failed to capture frame")
        sys.exit(1)

print("✓ Frame loaded")

# Detect faces
print("\nDetecting faces...")
faces = detect_faces(frame)

if not faces:
    print("✗ No faces detected")
    sys.exit(1)

print(f"✓ Detected {len(faces)} face(s)")

# For each face, find matches WITH NO THRESHOLD (0.0)
for i, face in enumerate(faces):
    print(f"\n--- Face {i+1} ---")
    print(f"Detection confidence: {face['confidence']:.3f}")

    # Find matches with very low threshold to see ALL similarities
    print("\nTesting similarity against all registered persons (no threshold)...")
    matches = find_best_match(face['embedding'], similarity_threshold=0.0, top_k=10)

    if not matches:
        print("  No persons registered in database")
    else:
        print(f"  Found {len(matches)} person(s) in database:\n")
        for match in matches:
            print(f"  {match['name']:15s} - Avg: {match['avg_similarity']:.4f}, Max: {match['max_similarity']:.4f} ({match['embedding_count']} embeddings)")

        # Show what threshold would match
        best = matches[0]
        print(f"\n  Best match: {best['name']} with avg similarity {best['avg_similarity']:.4f}")
        print(f"  Current threshold: {config.FACE_SIMILARITY_THRESHOLD}")

        if best['avg_similarity'] >= config.FACE_SIMILARITY_THRESHOLD:
            print(f"  ✓ Would match with current threshold")
        else:
            print(f"  ✗ Would NOT match with current threshold")
            suggested = best['avg_similarity'] - 0.05
            print(f"  Suggested threshold: {suggested:.2f} (allows 0.05 margin)")

print("\n=== Test Complete ===\n")
