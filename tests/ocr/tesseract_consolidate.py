#!/usr/bin/env python3
"""
Tesseract OCR with Geometric Consolidation
==========================================

Extracts text using Tesseract and merges vertically-stacked label fragments
based purely on coordinate proximity. No hardcoded venue names.

Consolidation rule:
- If two labels have center_x within X_THRESHOLD pixels
- AND center_y gap < Y_THRESHOLD pixels
- Merge them (top label first)

Usage:
    python tesseract_consolidate.py /path/to/deck_image.jpg
    python tesseract_consolidate.py /path/to/deck_image.jpg -v  # verbose
    
Requirements:
    sudo apt install tesseract-ocr
    pip install pytesseract pillow
"""

import sys
import os
import json
from PIL import Image
import pytesseract

# Consolidation thresholds (in pixels)
X_THRESHOLD = 20   # Max horizontal distance to consider "vertically aligned"
Y_THRESHOLD = 35   # Max vertical gap to consider "stacked"
H_Y_THRESHOLD = 15  # Max vertical distance to consider "same line" for horizontal merge
H_X_THRESHOLD = 25  # Max horizontal gap between bounding boxes for horizontal merge
MIN_CONFIDENCE = 50  # Tesseract confidence is 0-100
MIN_TEXT_LENGTH = 2  # Minimum characters to keep

# Noise patterns to filter out
NOISE_PATTERNS = ['@', 'fe', '|', '—', '-']


def extract_labels(image_path: str, scale: int = 2) -> tuple:
    """Extract all text labels with bounding box data using Tesseract."""
    img = Image.open(image_path)
    orig_width, orig_height = img.size
    
    # Upscale for better OCR accuracy
    if scale > 1:
        img = img.resize((img.width * scale, img.height * scale), Image.LANCZOS)
        temp_path = "/tmp/upscaled_deck.png"
        img.save(temp_path)
        ocr_target = temp_path
    else:
        ocr_target = image_path
    
    # Get detailed OCR data with bounding boxes
    # Output includes: level, page_num, block_num, par_num, line_num, word_num,
    #                  left, top, width, height, conf, text
    data = pytesseract.image_to_data(ocr_target, output_type=pytesseract.Output.DICT)
    
    labels = []
    n_boxes = len(data['text'])
    
    for i in range(n_boxes):
        text = data['text'][i].strip()
        conf = int(data['conf'][i])
        
        # Skip empty or low confidence
        if not text or conf < MIN_CONFIDENCE:
            continue
        
        # Skip single characters
        if len(text) <= 1:
            continue
        
        # Skip noise patterns
        if text.lower() in NOISE_PATTERNS or any(p in text.lower() for p in NOISE_PATTERNS):
            continue
        
        left = data['left'][i]
        top = data['top'][i]
        width = data['width'][i]
        height = data['height'][i]
        
        # Scale coordinates back to original image size
        if scale > 1:
            left = left / scale
            top = top / scale
            width = width / scale
            height = height / scale
        
        center_x = left + width / 2
        center_y = top + height / 2
        
        labels.append({
            "text": text,
            "confidence": conf / 100.0,  # Normalize to 0-1
            "center_x": float(center_x),
            "center_y": float(center_y),
            "min_x": float(left),
            "max_x": float(left + width),
            "min_y": float(top),
            "max_y": float(top + height),
        })
    
    # Sort by Y position (top to bottom)
    labels.sort(key=lambda x: x["center_y"])
    
    return labels, orig_width, orig_height
    
    # Sort by Y position (top to bottom)
    labels.sort(key=lambda x: x["center_y"])
    
    return labels, img_width, img_height


def consolidate_labels(labels: list, debug: bool = False) -> list:
    """
    Merge label fragments in two passes:
    1. Horizontal merge (same line, left to right)
    2. Vertical merge (stacked, top to bottom)
    
    Pure geometric approach - no hardcoded names.
    """
    if not labels:
        return []
    
    if debug:
        print("\n  === BEFORE HORIZONTAL MERGE ===")
        for l in labels:
            print(f"    {l['text']:<20} X:{l['center_x']:<8.1f} Y:{l['center_y']:<8.1f}")
    
    # Pass 1: Horizontal consolidation (same line)
    labels = consolidate_horizontal(labels)
    
    if debug:
        print("\n  === AFTER HORIZONTAL MERGE ===")
        for l in labels:
            print(f"    {l['text']:<20} X:{l['center_x']:<8.1f} Y:{l['center_y']:<8.1f}")
        # Check if CAFE exists
        cafe_found = any("CAFE" in l['text'] for l in labels)
        guest_found = any("GUEST" in l['text'] for l in labels)
        print(f"\n  CAFE found after horizontal: {cafe_found}")
        print(f"  GUEST found after horizontal: {guest_found}")
    
    # Pass 2: Vertical consolidation (stacked)
    labels = consolidate_vertical(labels, debug)
    
    if debug:
        print("\n  === AFTER VERTICAL MERGE ===")
        for l in labels:
            print(f"    {l['text']:<20} X:{l['center_x']:<8.1f} Y:{l['center_y']:<8.1f}")
    
    return labels


def consolidate_horizontal(labels: list) -> list:
    """Merge labels that are on the same horizontal line."""
    if not labels:
        return []
    
    # Sort by Y first, then by X
    labels.sort(key=lambda x: (x["center_y"], x["center_x"]))
    
    merged = [False] * len(labels)
    consolidated = []
    
    for i, label in enumerate(labels):
        if merged[i]:
            continue
        
        # Start a new group
        group = [label]
        merged[i] = True
        
        # Keep looking for more labels to add until no more found
        found_more = True
        while found_more:
            found_more = False
            
            for j, other in enumerate(labels):
                if merged[j]:
                    continue
                
                # Check if on same line as any item in group (similar Y)
                same_line = False
                for item in group:
                    if abs(other["center_y"] - item["center_y"]) < H_Y_THRESHOLD:
                        same_line = True
                        break
                
                if not same_line:
                    continue
                
                # Check horizontal distance to any item in group
                for item in group:
                    gap = max(other["min_x"] - item["max_x"], item["min_x"] - other["max_x"])
                    
                    if gap < H_X_THRESHOLD:
                        group.append(other)
                        merged[j] = True
                        found_more = True
                        break
        
        # Sort group by X position (left to right)
        group.sort(key=lambda x: x["center_x"])
        
        # Merge the group
        merged_text = " ".join(item["text"] for item in group)
        avg_confidence = sum(item["confidence"] for item in group) / len(group)
        
        consolidated.append({
            "text": merged_text,
            "confidence": round(avg_confidence, 3),
            "center_x": round(sum(item["center_x"] for item in group) / len(group), 1),
            "center_y": round(sum(item["center_y"] for item in group) / len(group), 1),
            "min_x": round(min(item["min_x"] for item in group), 1),
            "max_x": round(max(item["max_x"] for item in group), 1),
            "min_y": round(min(item["min_y"] for item in group), 1),
            "max_y": round(max(item["max_y"] for item in group), 1),
            "fragments": len(group),
        })
    
    # Re-sort by Y position
    consolidated.sort(key=lambda x: x["center_y"])
    
    return consolidated


def consolidate_vertical(labels: list, debug: bool = False) -> list:
    """Merge labels that are vertically stacked."""
    if not labels:
        return []
    
    # Sort by Y position
    labels.sort(key=lambda x: x["center_y"])
    
    merged = [False] * len(labels)
    consolidated = []
    
    for i, label in enumerate(labels):
        if merged[i]:
            continue
        
        # Start a new group
        group = [label]
        merged[i] = True
        current = label
        
        # Look for labels stacked below
        while True:
            found_next = False
            
            for j, other in enumerate(labels):
                if merged[j]:
                    continue
                
                x_diff = abs(other["center_x"] - current["center_x"])
                y_diff = other["center_y"] - current["center_y"]
                
                if debug and (other["text"] in ["PROMENADE", "SERVICES"] or current["text"] in ["CAFE", "GUEST"]):
                    print(f"    Checking: {current['text']} -> {other['text']}: x_diff={x_diff:.1f}, y_diff={y_diff:.1f}")
                
                if x_diff < X_THRESHOLD and 0 < y_diff < Y_THRESHOLD:
                    if debug:
                        print(f"    MATCH: {current['text']} + {other['text']}")
                    group.append(other)
                    merged[j] = True
                    current = other
                    found_next = True
                    break
            
            if not found_next:
                break
        
        # Merge the group
        merged_text = " ".join(item["text"] for item in group)
        total_fragments = sum(item.get("fragments", 1) for item in group)
        avg_confidence = sum(item["confidence"] for item in group) / len(group)
        
        consolidated.append({
            "text": merged_text,
            "confidence": round(avg_confidence, 3),
            "center_x": round(group[0]["center_x"], 1),
            "center_y": round((group[0]["center_y"] + group[-1]["center_y"]) / 2, 1),
            "min_x": round(min(item["min_x"] for item in group), 1),
            "max_x": round(max(item["max_x"] for item in group), 1),
            "min_y": round(group[0]["min_y"], 1),
            "max_y": round(group[-1]["max_y"], 1),
            "fragments": total_fragments,
        })
    
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
        print("Usage: python tesseract_consolidate.py <image_path> [-v]")
        sys.exit(1)
    
    image_path = sys.argv[1]
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    
    print(f"Processing: {image_path}\n")
    
    # Step 1: Extract raw labels
    print("Step 1: Extracting text labels with Tesseract...")
    labels, img_width, img_height = extract_labels(image_path)
    print(f"  Image dimensions: {img_width} x {img_height}")
    print(f"  Found {len(labels)} raw labels\n")
    
    # Show raw labels if verbose
    if verbose:
        print("  Raw labels detected:")
        for label in labels:
            print(f"    {label['text']:<20} Y:{label['center_y']:<8.1f} X:{label['center_x']:<8.1f} conf:{label['confidence']:.2f}")
        print()
    
    # Step 2: Consolidate stacked fragments
    print("Step 2: Consolidating stacked labels...")
    debug = "--debug" in sys.argv or "-d" in sys.argv
    consolidated = consolidate_labels(labels, debug)
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