#!/usr/bin/env python3
"""
EasyOCR with Geometric Consolidation
====================================

Extracts text and merges vertically-stacked label fragments
based purely on coordinate proximity. No hardcoded venue names.

Consolidation rule:
- If two labels have center_x within X_THRESHOLD pixels
- AND center_y gap < Y_THRESHOLD pixels
- Merge them (top label first)

Usage:
    python easyOCR_consolidate.py /path/to/deck_image.jpg
"""

import sys
import os
import json
from PIL import Image

# Force CPU only
os.environ['CUDA_VISIBLE_DEVICES'] = ''

import easyocr

# Consolidation thresholds (in pixels)
X_THRESHOLD = 20   # Max horizontal distance to consider "aligned"
Y_THRESHOLD = 35   # Max vertical gap to consider "stacked"
MIN_CONFIDENCE = 0.5  # Ignore low-confidence detections


def extract_labels(image_path: str) -> tuple:
    """Extract all text labels with bounding box data."""
    img = Image.open(image_path)
    img_width, img_height = img.size
    
    reader = easyocr.Reader(['en'], gpu=False, verbose=False)
    results = reader.readtext(image_path)
    
    labels = []
    for (bbox, text, confidence) in results:
        if confidence < MIN_CONFIDENCE:
            continue
        
        text = text.strip()
        if len(text) <= 1:
            continue
        
        min_x = min(p[0] for p in bbox)
        max_x = max(p[0] for p in bbox)
        min_y = min(p[1] for p in bbox)
        max_y = max(p[1] for p in bbox)
        center_x = (min_x + max_x) / 2
        center_y = (min_y + max_y) / 2
        
        labels.append({
            "text": text,
            "confidence": float(confidence),
            "center_x": float(center_x),
            "center_y": float(center_y),
            "min_x": float(min_x),
            "max_x": float(max_x),
            "min_y": float(min_y),
            "max_y": float(max_y),
        })
    
    # Sort by Y position (top to bottom)
    labels.sort(key=lambda x: x["center_y"])
    
    return labels, img_width, img_height


def consolidate_labels(labels: list) -> list:
    """
    Merge vertically-stacked label fragments.
    Pure geometric approach - no hardcoded names.
    """
    if not labels:
        return []
    
    # Track which labels have been merged
    merged = [False] * len(labels)
    consolidated = []
    
    for i, label in enumerate(labels):
        if merged[i]:
            continue
        
        # Start a new group with this label
        group = [label]
        merged[i] = True
        
        # Look for labels that stack below this one
        current = label
        while True:
            found_next = False
            
            for j, other in enumerate(labels):
                if merged[j]:
                    continue
                
                # Check if 'other' is directly below 'current'
                x_diff = abs(other["center_x"] - current["center_x"])
                y_diff = other["center_y"] - current["center_y"]  # Must be positive (below)
                
                if x_diff < X_THRESHOLD and 0 < y_diff < Y_THRESHOLD:
                    group.append(other)
                    merged[j] = True
                    current = other
                    found_next = True
                    break
            
            if not found_next:
                break
        
        # Merge the group into a single label
        merged_text = " ".join(item["text"] for item in group)
        avg_confidence = sum(item["confidence"] for item in group) / len(group)
        
        # Use bounding box that encompasses all items
        consolidated.append({
            "text": merged_text,
            "confidence": round(avg_confidence, 3),
            "center_x": round(group[0]["center_x"], 1),
            "center_y": round((group[0]["center_y"] + group[-1]["center_y"]) / 2, 1),
            "min_x": round(min(item["min_x"] for item in group), 1),
            "max_x": round(max(item["max_x"] for item in group), 1),
            "min_y": round(group[0]["min_y"], 1),
            "max_y": round(group[-1]["max_y"], 1),
            "fragments": len(group),
        })
    
    # Re-sort by Y position
    consolidated.sort(key=lambda x: x["center_y"])
    
    return consolidated


def get_position(norm_y: float) -> str:
    """Map normalized Y coordinate to ship position."""
    if norm_y < 0.15:
        return "forward"
    elif norm_y < 0.35:
        return "mid-forward"
    elif norm_y < 0.65:
        return "mid"
    elif norm_y < 0.85:
        return "mid-aft"
    else:
        return "aft"


def get_side(norm_x: float) -> str:
    """Map normalized X coordinate to ship side."""
    if norm_x < 0.35:
        return "port"
    elif norm_x > 0.65:
        return "starboard"
    else:
        return "center"


def find_neighbors(labels: list) -> list:
    """
    For each label, find nearest neighbor in each cardinal direction.
    Based purely on coordinates.
    """
    for label in labels:
        cx, cy = label["center_x"], label["center_y"]
        
        north = None
        south = None
        east = None
        west = None
        
        north_dist = float('inf')
        south_dist = float('inf')
        east_dist = float('inf')
        west_dist = float('inf')
        
        for other in labels:
            if other["text"] == label["text"] and other["center_x"] == cx and other["center_y"] == cy:
                continue
            
            ox, oy = other["center_x"], other["center_y"]
            dx = ox - cx
            dy = oy - cy
            
            # North (above, so dy < 0)
            if dy < 0 and abs(dx) < abs(dy):
                dist = abs(dy)
                if dist < north_dist:
                    north_dist = dist
                    north = other["text"]
            
            # South (below, so dy > 0)
            if dy > 0 and abs(dx) < abs(dy):
                dist = abs(dy)
                if dist < south_dist:
                    south_dist = dist
                    south = other["text"]
            
            # East (right, so dx > 0)
            if dx > 0 and abs(dy) < abs(dx):
                dist = abs(dx)
                if dist < east_dist:
                    east_dist = dist
                    east = other["text"]
            
            # West (left, so dx < 0)
            if dx < 0 and abs(dy) < abs(dx):
                dist = abs(dx)
                if dist < west_dist:
                    west_dist = dist
                    west = other["text"]
        
        label["neighbors"] = {
            "north": north or "none",
            "south": south or "none",
            "east": east or "none",
            "west": west or "none",
        }
    
    return labels


def main():
    if len(sys.argv) < 2:
        print("Usage: python easyOCR_consolidate.py <image_path>")
        sys.exit(1)
    
    image_path = sys.argv[1]
    
    print(f"Processing: {image_path}\n")
    
    # Step 1: Extract raw labels
    print("Step 1: Extracting text labels...")
    labels, img_width, img_height = extract_labels(image_path)
    print(f"  Image dimensions: {img_width} x {img_height}")
    print(f"  Found {len(labels)} raw labels\n")
    
    # Show raw labels if verbose
    if "--verbose" in sys.argv or "-v" in sys.argv:
        print("  Raw labels detected:")
        for label in labels:
            print(f"    {label['text']:<20} Y:{label['center_y']:<8.1f} X:{label['center_x']:<8.1f} conf:{label['confidence']:.2f}")
        print()
    
    # Step 2: Consolidate stacked fragments
    print("Step 2: Consolidating stacked labels...")
    consolidated = consolidate_labels(labels)
    print(f"  Consolidated to {len(consolidated)} labels\n")
    
    # Step 3: Add position info
    print("Step 3: Calculating positions...")
    for label in consolidated:
        label["norm_x"] = round(label["center_x"] / img_width, 3)
        label["norm_y"] = round(label["center_y"] / img_height, 3)
        label["position"] = get_position(label["norm_y"])
        label["side"] = get_side(label["norm_x"])
    
    # Step 4: Find neighbors
    print("Step 4: Mapping neighbors...")
    consolidated = find_neighbors(consolidated)
    
    # Print results
    print(f"\n{'='*70}")
    print(f"  CONSOLIDATED LABELS")
    print(f"{'='*70}\n")
    
    for label in consolidated:
        frags = f"[{label['fragments']} fragments]" if label['fragments'] > 1 else ""
        print(f"  {label['text']:<30} {label['position']:<12} {label['side']:<10} {frags}")
    
    print(f"\n{'='*70}")
    print(f"  NEIGHBOR MAP")
    print(f"{'='*70}\n")
    
    for label in consolidated:
        n = label["neighbors"]
        print(f"  {label['text']}")
        print(f"    N: {n['north']:<25} S: {n['south']}")
        print(f"    E: {n['east']:<25} W: {n['west']}")
        print()
    
    # Save JSON output
    output = {
        "image_width": img_width,
        "image_height": img_height,
        "total_labels": len(consolidated),
        "labels": consolidated,
    }
    
    output_file = "deck_consolidated.json"
    with open(output_file, 'w') as f:
        json.dump(output, f, indent=2)
    
    print(f"Saved to: {output_file}")


if __name__ == "__main__":
    main()
