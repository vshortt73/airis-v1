#!/usr/bin/env python3
"""
Map Reasoning - Proof of Concept
================================

Extracts text from deck map, maps to spatial positions, outputs structured JSON.

Usage:
    python map_poc.py /path/to/deck_image.jpg "Ship Name" deck_number

Example:
    python map_poc.py oasis-of-the-seas-deck05.jpg "Oasis of the Seas" 5
"""

import sys
import os
import json
from PIL import Image

# Force CPU only
os.environ['CUDA_VISIBLE_DEVICES'] = ''

import easyocr


def extract_labels(image_path: str, confidence_threshold: float = 0.6) -> list:
    """
    Extract text labels from deck map image.
    Returns list of labels with positions.
    """
    # Get image dimensions
    img = Image.open(image_path)
    img_width, img_height = img.size
    
    # Run OCR
    reader = easyocr.Reader(['en'], gpu=False, verbose=False)
    results = reader.readtext(image_path)
    
    labels = []
    for (bbox, text, confidence) in results:
        # Skip low confidence
        if confidence < confidence_threshold:
            continue
        
        # Skip single characters or numbers
        if len(text.strip()) <= 1:
            continue
        
        # Calculate center point
        center_x = sum(point[0] for point in bbox) / 4
        center_y = sum(point[1] for point in bbox) / 4
        
        # Normalize to 0-1
        norm_x = center_x / img_width
        norm_y = center_y / img_height
        
        labels.append({
            "text": text.strip(),
            "confidence": round(confidence, 2),
            "norm_x": round(norm_x, 3),
            "norm_y": round(norm_y, 3),
            "position": get_position(norm_y),
            "side": get_side(norm_x),
        })
    
    # Sort by Y position (forward to aft)
    labels.sort(key=lambda x: x["norm_y"])
    
    return labels


def get_position(norm_y: float) -> str:
    """Map Y coordinate to ship position."""
    if norm_y < 0.20:
        return "forward"
    elif norm_y < 0.40:
        return "mid-forward"
    elif norm_y < 0.60:
        return "mid"
    elif norm_y < 0.80:
        return "mid-aft"
    else:
        return "aft"


def get_side(norm_x: float) -> str:
    """Map X coordinate to ship side."""
    if norm_x < 0.35:
        return "port"
    elif norm_x > 0.65:
        return "starboard"
    else:
        return "center"


def find_nearby(labels: list, threshold: float = 0.12) -> dict:
    """Find nearby locations for each label."""
    nearby_map = {}
    
    for i, label1 in enumerate(labels):
        nearby = []
        for j, label2 in enumerate(labels):
            if i == j:
                continue
            
            dx = label1["norm_x"] - label2["norm_x"]
            dy = label1["norm_y"] - label2["norm_y"]
            distance = (dx**2 + dy**2) ** 0.5
            
            if distance < threshold:
                nearby.append(label2["text"])
        
        nearby_map[label1["text"]] = nearby[:5]  # Top 5
    
    return nearby_map


def build_deck_json(labels: list, nearby_map: dict, ship_name: str, deck_number: int) -> dict:
    """Build the final structured deck representation."""
    
    locations = []
    elevators = []
    
    for label in labels:
        text_lower = label["text"].lower()
        
        # Check if elevator
        if "elev" in text_lower:
            elevators.append({
                "name": label["text"],
                "position": label["position"],
                "side": label["side"]
            })
            continue
        
        locations.append({
            "name": label["text"],
            "position": label["position"],
            "side": label["side"],
            "nearby": nearby_map.get(label["text"], []),
            "confidence": label["confidence"]
        })
    
    return {
        "ship_name": ship_name,
        "deck_number": deck_number,
        "total_locations": len(locations),
        "locations": locations,
        "elevators": elevators
    }


def print_summary(deck_data: dict):
    """Print a human-readable summary."""
    print(f"\n{'='*60}")
    print(f"  {deck_data['ship_name']} - Deck {deck_data['deck_number']}")
    print(f"{'='*60}\n")
    
    print(f"Found {deck_data['total_locations']} locations:\n")
    
    # Group by position
    positions = ["forward", "mid-forward", "mid", "mid-aft", "aft"]
    
    for pos in positions:
        locs = [l for l in deck_data['locations'] if l['position'] == pos]
        if locs:
            print(f"  {pos.upper()}:")
            for loc in locs:
                side = f"({loc['side']})"
                print(f"    - {loc['name']:<30} {side}")
            print()
    
    if deck_data['elevators']:
        print(f"  ELEVATORS:")
        for elev in deck_data['elevators']:
            print(f"    - {elev['position']} ({elev['side']})")
    
    print(f"\n{'='*60}\n")


def main():
    if len(sys.argv) < 4:
        print("Usage: python map_poc.py <image_path> <ship_name> <deck_number>")
        print("Example: python map_poc.py deck05.jpg \"Oasis of the Seas\" 5")
        sys.exit(1)
    
    image_path = sys.argv[1]
    ship_name = sys.argv[2]
    deck_number = int(sys.argv[3])
    
    print(f"Processing: {image_path}")
    print(f"Ship: {ship_name}, Deck: {deck_number}\n")
    
    # Extract labels
    print("Extracting text labels...")
    labels = extract_labels(image_path)
    print(f"Found {len(labels)} labels above confidence threshold.\n")
    
    # Find nearby relationships
    print("Mapping spatial relationships...")
    nearby_map = find_nearby(labels)
    
    # Build structured output
    deck_data = build_deck_json(labels, nearby_map, ship_name, deck_number)
    
    # Print summary
    print_summary(deck_data)
    
    # Save JSON
    output_file = f"deck_{deck_number}_map.json"
    with open(output_file, 'w') as f:
        json.dump(deck_data, f, indent=2)
    print(f"Saved structured data to: {output_file}")
    
    # Also print the JSON
    print("\nJSON Output:")
    print("-" * 60)
    print(json.dumps(deck_data, indent=2))


if __name__ == "__main__":
    main()