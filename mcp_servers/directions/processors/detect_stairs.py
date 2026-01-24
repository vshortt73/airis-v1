#!/usr/bin/env python3
"""
Staircase and Elevator Detection via Color Segmentation

Detects staircases by finding "dirty yellow" colored regions in deck plan images.

Usage:
    python detect_stairs.py image.jpg [output.json]
    python detect_stairs.py image.jpg --debug  # saves debug images
"""

import cv2
import numpy as np
import json
import sys
from pathlib import Path


def find_yellow_regions(image_path: str, debug: bool = False) -> dict:
    """
    Find yellow-colored regions (staircases) in a deck plan image.
    
    Args:
        image_path: Path to the deck plan image
        debug: If True, save intermediate images for debugging
        
    Returns:
        Dict with detected staircase regions
    """
    # Load image
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"Could not load image: {image_path}")
    
    height, width = img.shape[:2]
    
    # Convert to HSV for color detection
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    
    # Yellow color range in HSV
    # "Dirty yellow" / tan / beige tends to be:
    # - Hue: 15-35 (yellow-orange range)
    # - Saturation: 30-180 (not too gray, not too vivid)
    # - Value: 150-255 (fairly bright)
    
    # Try multiple yellow ranges to catch variations
    yellow_ranges = [
        # Standard yellow
        ((18, 40, 150), (35, 180, 255)),
        # Dirty/tan yellow
        ((15, 30, 140), (30, 150, 240)),
        # More orange-yellow
        ((10, 50, 160), (25, 200, 255)),
    ]
    
    # Combine masks from all ranges
    combined_mask = np.zeros((height, width), dtype=np.uint8)
    
    for lower, upper in yellow_ranges:
        lower = np.array(lower, dtype=np.uint8)
        upper = np.array(upper, dtype=np.uint8)
        mask = cv2.inRange(hsv, lower, upper)
        combined_mask = cv2.bitwise_or(combined_mask, mask)
    
    # Morphological operations to clean up
    kernel = np.ones((5, 5), np.uint8)
    combined_mask = cv2.morphologyEx(combined_mask, cv2.MORPH_CLOSE, kernel)
    combined_mask = cv2.morphologyEx(combined_mask, cv2.MORPH_OPEN, kernel)
    
    # Find contours
    contours, _ = cv2.findContours(combined_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    # Filter and extract staircase regions
    staircases = []
    min_area = 150  # Minimum area to consider (lowered to catch small stairs)
    max_area = width * height * 0.1  # Max 10% of image (filter huge false positives)
    
    for i, contour in enumerate(contours):
        area = cv2.contourArea(contour)
        if area < min_area or area > max_area:
            continue
        
        # Get bounding box
        x, y, w, h = cv2.boundingRect(contour)
        
        # Get center
        M = cv2.moments(contour)
        if M["m00"] > 0:
            cx = int(M["m10"] / M["m00"])
            cy = int(M["m01"] / M["m00"])
        else:
            cx = x + w // 2
            cy = y + h // 2
        
        # Aspect ratio (helps filter out non-staircase shapes)
        aspect_ratio = w / h if h > 0 else 0
        
        staircases.append({
            "id": i + 1,
            "bbox": {"x1": x, "y1": y, "x2": x + w, "y2": y + h},
            "center": {"x": cx, "y": cy},
            "area": area,
            "aspect_ratio": round(aspect_ratio, 2)
        })
    
    # Sort by Y position (top to bottom)
    staircases.sort(key=lambda s: s["center"]["y"])
    
    # Reassign IDs after sorting
    for i, s in enumerate(staircases):
        s["id"] = i + 1
    
    if debug:
        debug_dir = Path(image_path).parent
        
        # Save mask
        cv2.imwrite(str(debug_dir / "debug_yellow_mask.png"), combined_mask)
        
        # Save annotated image
        debug_img = img.copy()
        for s in staircases:
            bbox = s["bbox"]
            cv2.rectangle(debug_img, 
                         (bbox["x1"], bbox["y1"]), 
                         (bbox["x2"], bbox["y2"]), 
                         (0, 255, 0), 2)
            cv2.circle(debug_img, 
                      (s["center"]["x"], s["center"]["y"]), 
                      5, (0, 0, 255), -1)
            cv2.putText(debug_img, f"S{s['id']}", 
                       (bbox["x1"], bbox["y1"] - 5),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
        cv2.imwrite(str(debug_dir / "debug_stairs_detected.png"), debug_img)
        
        print(f"Debug images saved to {debug_dir}", file=sys.stderr)
    
    return {
        "image_size": {"width": width, "height": height},
        "image_path": str(image_path),
        "detections": staircases,
        "count": len(staircases)
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python detect_stairs.py image.jpg [output.json] [--debug]", file=sys.stderr)
        sys.exit(1)
    
    image_path = sys.argv[1]
    debug = "--debug" in sys.argv
    
    # Find output path
    output_path = None
    for arg in sys.argv[2:]:
        if arg != "--debug" and arg.endswith(".json"):
            output_path = arg
            break
    
    result = find_yellow_regions(image_path, debug=debug)
    
    print(f"Found {result['count']} potential staircase regions", file=sys.stderr)
    
    if output_path:
        with open(output_path, 'w') as f:
            json.dump(result, f, indent=2)
        print(f"Wrote output to {output_path}", file=sys.stderr)
    else:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
