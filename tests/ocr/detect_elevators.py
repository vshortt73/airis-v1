#!/usr/bin/env python3
"""
Elevator Detection via Tesseract OCR

Detects elevators by finding "ELEV" text in deck plan images using
Tesseract OCR with PSM 12 (sparse text mode).

Usage:
    python detect_elevators.py image.jpg [output.json]
    python detect_elevators.py image.jpg --debug
"""

import cv2
import pytesseract
import numpy as np
import json
import sys
from pathlib import Path


def find_elevators(image_path: str, debug: bool = False) -> dict:
    """
    Find elevator labels in a deck plan image using Tesseract OCR.
    
    Args:
        image_path: Path to the deck plan image
        debug: If True, save debug images
        
    Returns:
        Dict with detected elevator regions
    """
    # Load image
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"Could not load image: {image_path}")
    
    height, width = img.shape[:2]
    
    # Upscale 4x for better small text detection
    scale = 4
    upscaled = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    
    # Convert to grayscale
    gray = cv2.cvtColor(upscaled, cv2.COLOR_BGR2GRAY)
    
    # Run Tesseract with PSM 12 (sparse text with OSD)
    custom_config = '--oem 3 --psm 12'
    data = pytesseract.image_to_data(gray, config=custom_config, output_type=pytesseract.Output.DICT)
    
    # Find ELEV text
    elevators = []
    
    for i, text in enumerate(data['text']):
        conf = int(data['conf'][i])
        text_clean = text.strip().upper()
        
        # Match ELEV or ELEV.
        if conf > 30 and ('ELEV' in text_clean):
            # Scale coordinates back to original image size
            x = data['left'][i] // scale
            y = data['top'][i] // scale
            w = data['width'][i] // scale
            h = data['height'][i] // scale
            
            # Center point
            cx = x + w // 2
            cy = y + h // 2
            
            elevators.append({
                "id": len(elevators) + 1,
                "text": text.strip(),
                "bbox": {"x1": x, "y1": y, "x2": x + w, "y2": y + h},
                "center": {"x": cx, "y": cy},
                "confidence": conf
            })
    
    # Sort by Y position (top to bottom), then X (left to right)
    elevators.sort(key=lambda e: (e["center"]["y"], e["center"]["x"]))
    
    # Reassign IDs after sorting
    for i, e in enumerate(elevators):
        e["id"] = i + 1
    
    if debug:
        debug_dir = Path(image_path).parent
        
        # Save annotated image
        debug_img = img.copy()
        for e in elevators:
            bbox = e["bbox"]
            cv2.rectangle(debug_img, 
                         (bbox["x1"], bbox["y1"]), 
                         (bbox["x2"], bbox["y2"]), 
                         (255, 0, 255), 2)  # Magenta
            cv2.circle(debug_img, 
                      (e["center"]["x"], e["center"]["y"]), 
                      5, (0, 0, 255), -1)
            cv2.putText(debug_img, f"E{e['id']}", 
                       (bbox["x1"], bbox["y1"] - 5),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 255), 2)
        
        cv2.imwrite(str(debug_dir / "debug_elevators_detected.png"), debug_img)
        print(f"Debug image saved to {debug_dir}", file=sys.stderr)
    
    return {
        "image_size": {"width": width, "height": height},
        "image_path": str(image_path),
        "detections": elevators,
        "count": len(elevators)
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python detect_elevators.py image.jpg [output.json] [--debug]", file=sys.stderr)
        sys.exit(1)
    
    image_path = sys.argv[1]
    debug = "--debug" in sys.argv
    
    # Find output path
    output_path = None
    for arg in sys.argv[2:]:
        if arg != "--debug" and arg.endswith(".json"):
            output_path = arg
            break
    
    result = find_elevators(image_path, debug=debug)
    
    print(f"Found {result['count']} elevators", file=sys.stderr)
    
    if output_path:
        with open(output_path, 'w') as f:
            json.dump(result, f, indent=2)
        print(f"Wrote output to {output_path}", file=sys.stderr)
    else:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
