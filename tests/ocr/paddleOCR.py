#!/usr/bin/env python3
"""
PaddleOCR Test Harness - Minimal Version
=========================================

Just answers: Can PaddleOCR read the text on this deck map?

Usage:
    python test_paddle_ocr.py /path/to/deck_image.jpg
"""

import sys
from paddleocr import PaddleOCR

def main():
    if len(sys.argv) < 2:
        print("Usage: python test_paddle_ocr.py <image_path>")
        sys.exit(1)
    
    image_path = sys.argv[1]
    print(f"Testing PaddleOCR on: {image_path}\n")
    
    # Initialize OCR
    ocr = PaddleOCR(lang='en')
    
    # Run OCR
    results = ocr.ocr(image_path, cls=True)
    
    # Print everything it found
    if not results or not results[0]:
        print("No text detected!")
        return
    
    print(f"Found {len(results[0])} text regions:\n")
    print("-" * 60)
    
    for line in results[0]:
        text = line[1][0]
        confidence = line[1][1]
        print(f"{text:<40} (confidence: {confidence:.2f})")
    
    print("-" * 60)
    print(f"\nTotal: {len(results[0])} labels detected")


if __name__ == "__main__":
    main()