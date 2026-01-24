# Ship Deck Plan Processing Pipeline

## Overview

This document describes how to process cruise ship deck plan images into a unified navigation JSON file. The output enables pathfinding between any two locations on the ship, including cross-deck navigation via stairs and elevators.

## Target Output Structure

The final JSON should match this structure:

```json
{
  "ship": "Ship Name",
  "decks": [3, 4, 5, 6, ...],
  "note": "Any relevant notes (e.g., No deck 13)",
  "elevator_banks": {
    "forward": {
      "decks": [3, 4, 5, ...],
      "position": "forward"
    },
    "aft": {
      "decks": [3, 4, 5, ...],
      "position": "mid-aft"
    }
  },
  "venues": [
    {
      "id": "deck5-vitality-spa",
      "name": "Vitality Spa",
      "deck": 5,
      "position": "forward",
      "side": "center",
      "category": "spa",
      "neighbors": {
        "south": "deck5-royal-theater",
        "east": "deck5-staircase3"
      }
    },
    {
      "id": "deck5-staircase2",
      "name": "Royal Promenade Staircase Port",
      "deck": 5,
      "position": "mid-forward",
      "side": "port",
      "category": "stairs",
      "staircase_id": 2,
      "neighbors": {
        "vertical": ["deck4-staircase2", "deck6-staircase2"],
        "east": "deck5-spotlight-karaoke"
      }
    },
    {
      "id": "deck5-elevator-forward-port",
      "name": "Forward Elevator Port",
      "deck": 5,
      "position": "mid-forward",
      "side": "port",
      "category": "elevator",
      "elevator_bank": "forward",
      "neighbors": {
        "vertical": ["deck4-elevator-forward-port", "deck6-elevator-forward-port"],
        "east": "deck5-starbucks"
      }
    }
  ],
  "staircases": [
    {
      "id": 1,
      "name": "Forward Staircase",
      "position": "forward",
      "side": "center",
      "decks": [3, 4, 5, 6, 7, 8, ...]
    }
  ]
}
```

---

## Pipeline Components

### 1. PaddleOCR (Venues/Labels)
- **Input:** Deck plan image (JPG/PNG)
- **Output:** JSON with text detections, bounding boxes, centers, confidence scores
- **Detects:** Venue names, labels (e.g., "VITALITY SPA", "ROYAL THEATER", "STARBUCKS")
- **Note:** Does NOT reliably detect "ELEV." text (too small)

### 2. detect_stairs.py (OpenCV - Staircases)
- **Input:** Deck plan image
- **Output:** JSON with staircase bounding boxes and centers
- **Method:** Yellow/tan color segmentation in HSV space
- **Dependencies:** `opencv-python`, `numpy`
- **Usage:** `python detect_stairs.py image.jpg output.json [--debug]`

### 3. detect_elevators.py (Tesseract - Elevators)
- **Input:** Deck plan image
- **Output:** JSON with elevator locations
- **Method:** 4x upscale + Tesseract PSM 12 (sparse text mode) looking for "ELEV"
- **Dependencies:** `opencv-python`, `pytesseract`, `numpy`, Tesseract OCR installed
- **Usage:** `python detect_elevators.py image.jpg output.json [--debug]`

---

## Processing Steps

### Step 1: Process Each Deck Image

For each deck image, run all three detection passes:

```bash
# 1. PaddleOCR for venues
paddleocr --image deck05.jpg --output deck05_ocr.json

# 2. OpenCV for staircases  
python detect_stairs.py deck05.jpg deck05_stairs.json

# 3. Tesseract for elevators
python detect_elevators.py deck05.jpg deck05_elevators.json
```

### Step 2: Merge Into Unified Deck JSON

Combine the three outputs into a single deck JSON:

#### 2a. Process PaddleOCR Output
- **Merge multi-line labels:** Text on consecutive lines with similar X position = same venue
  - Example: "ROYAL" + "THEATER" → "ROYAL THEATER"
  - Example: "GLOBE" + "AND ATLAS" + "PUB" → "GLOBE AND ATLAS PUB"
- **Handle vertical text:** Labels with height > 2x width are vertical (e.g., "RUNNING TRACK", "ROYAL PROMENADE")
  - Merge vertical labels by X-proximity + Y-adjacency
- **Clean artifacts:** Remove leading periods (e.g., ".PROMENADE" → "PROMENADE")

#### 2b. Classify Position (Forward/Aft based on Y coordinate)
Using image height, divide into 5 zones:
- **forward:** Y < 20% of image height
- **mid-forward:** Y 20-40%
- **mid:** Y 40-60%
- **mid-aft:** Y 60-80%
- **aft:** Y > 80%

#### 2c. Classify Side (Port/Starboard based on X coordinate)
Using image width:
- **port:** X < 40% of image width
- **center:** X 40-60%
- **starboard:** X > 60%

#### 2d. Compute Directional Neighbors
For each venue, find the nearest venue in each cardinal direction:
- **north:** Lower Y, similar X (toward bow)
- **south:** Higher Y, similar X (toward stern)
- **east:** Higher X, similar Y (toward starboard)
- **west:** Lower X, similar Y (toward port)

Use 45° sectors to determine direction:
```python
angle = atan2(dy, dx) * 180 / pi
if -45 <= angle <= 45: return 'east'
elif 45 < angle <= 135: return 'south'
elif -135 <= angle < -45: return 'north'
else: return 'west'
```

#### 2e. Generate Deck-Specific IDs
Format: `deck{N}-{slug}`
- Venue: `deck5-vitality-spa`
- Staircase: `deck5-staircase2` (using staircase_id)
- Elevator: `deck5-elevator-forward-port`

Slug generation:
```python
slug = name.lower().replace(" ", "-").replace("'", "").replace("&", "and")
# "Globe & Atlas Pub" → "globe-and-atlas-pub"
```

#### 2f. Add Stairs and Elevators as Venues
Staircases and elevators become venue entries with:
- `category: "stairs"` or `category: "elevator"`
- Their own directional neighbors to adjacent venues
- Placeholder for `vertical` neighbors (filled in Step 5/6)

### Step 3: Repeat for All Deck Images

Loop through all deck images (deck03.jpg through deck18.jpg, skipping 13).

### Step 4: Combine All Decks Into Ship JSON

Merge all deck JSONs:
```json
{
  "ship": "Oasis of the Seas",
  "decks": [3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 14, 15, 16, 17, 18],
  "venues": [
    ...all venues from all decks...
  ]
}
```

### Step 5: Link Staircases Across Decks

Staircases at the same X/Y position (within tolerance) on different decks are the same physical staircase.

**Algorithm:**
1. Group all staircase venues by approximate (X, Y) position (e.g., within 30px)
2. Assign each group a `staircase_id` (1, 2, 3, ...)
3. For each staircase venue, add `vertical` neighbors pointing to the same staircase on adjacent decks:
```json
"neighbors": {
  "vertical": ["deck4-staircase2", "deck6-staircase2"],
  "east": "deck5-spotlight-karaoke"
}
```
4. Build the top-level `staircases` array:
```json
"staircases": [
  {
    "id": 2,
    "name": "Royal Promenade Staircase Port",
    "position": "mid-forward",
    "side": "port",
    "decks": [4, 5, 6, 7, 8]
  }
]
```

### Step 6: Link Elevators Across Decks

Same approach as staircases:
1. Group elevators by (X, Y) position
2. Determine elevator bank (forward, aft, etc.) based on position
3. Add `vertical` neighbors
4. Build `elevator_banks` in top-level JSON

### Step 7: Category Classification (OPTIONAL - BYPASS FOR NOW)

If needed later, classify venues into categories:
- entertainment, dining, spa, shopping, cafe, bar, nightlife, casino, recreation, meeting, stairs, elevator

Can use LLM classification or keyword matching:
```python
if "theater" in name.lower(): category = "entertainment"
elif "dining" in name.lower() or "restaurant" in name.lower(): category = "dining"
elif "spa" in name.lower(): category = "spa"
# etc.
```

---

## Key Coordinate System Notes

**Deck plan orientation:** Bow (front of ship) is UP in the image.

| Direction | Image Axis | Ship Term |
|-----------|------------|-----------|
| North | -Y (up) | Forward/Bow |
| South | +Y (down) | Aft/Stern |
| East | +X (right) | Starboard |
| West | -X (left) | Port |

---

## File Locations

- **detect_stairs.py:** OpenCV staircase detector
- **detect_elevators.py:** Tesseract elevator detector
- **deck_label_processor.py:** PaddleOCR output processor (merges labels, computes neighbors)

---

## Edge Cases to Handle

1. **"PROMENADE ROYAL" vs "ROYAL PROMENADE":** Vertical text merge order can be ambiguous. May need a name normalization lookup table.

2. **Duplicate RUNNING TRACK:** Multiple "RUNNING TRACK" labels on same deck - deduplicate by name, keep highest confidence.

3. **Multi-deck venues:** Some venues span multiple decks (Royal Theater spans decks 3-5). Can be detected by same name appearing on multiple decks at same position. Add `spans_decks` array.

4. **No Deck 13:** Many ships skip deck 13 (superstition). Handle in deck list.

5. **Small staircases:** Some staircases are small - use min_area=150 in detect_stairs.py.

---

## Validation

After processing, validate:
1. **Graph connectivity:** Every venue should be reachable from every other venue
2. **Bidirectional neighbors:** If A has B as east neighbor, B should have A as west neighbor
3. **Vertical connections:** All stairs/elevators have vertical neighbors (except top/bottom decks)
4. **No orphan venues:** Every venue has at least one neighbor

---

## Example Processing Run

```bash
# Process deck 5
paddleocr --image deck05.jpg --output deck05_ocr.json
python detect_stairs.py deck05.jpg deck05_stairs.json
python detect_elevators.py deck05.jpg deck05_elevators.json
python merge_deck.py deck05_ocr.json deck05_stairs.json deck05_elevators.json 5 --output deck05_unified.json

# Repeat for all decks...

# Combine all decks
python combine_ship.py deck*_unified.json --output ship_combined.json

# Link vertical connections
python link_verticals.py ship_combined.json --output ship_final.json
```

---

## Output Verification

The final JSON should enable queries like:
- "How do I get from Vitality Spa (Deck 5) to Main Dining Room (Deck 3)?"
- Path: Vitality Spa → south → Royal Theater → south → Starbucks → west → Staircase2 → vertical → deck4-staircase2 → vertical → deck3-staircase2 → east → Main Dining Room
