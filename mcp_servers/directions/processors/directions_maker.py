#!/usr/bin/env python3
"""
Ship Deck Plan Processing Pipeline - directions_maker

Processes cruise ship deck plan images into a unified navigation JSON file.
Uses PaddleOCR (node2), Tesseract (local), and OpenCV (local) for detection.

Usage:
    python directions_maker.py --title "Oasis of the Seas" \
        --input_dir /path/to/deck/images \
        --output_dir /path/to/output

    python directions_maker.py --title "Oasis of the Seas" \
        --input_dir ./ships/RC_oasis_of_the_seas \
        --output_dir ./output \
        --debug --verbose
"""

import argparse
import base64
import json
import logging
import math
import os
import re
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import cv2
import httpx
import numpy as np
import pytesseract

# Configuration
PADDLEOCR_URL = os.environ.get("PADDLEOCR_URL", "http://node2:5200")
PADDLEOCR_TIMEOUT = 120.0  # seconds - deck plans can be large

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class Detection:
    """Raw OCR detection"""
    text: str
    bbox: Tuple[int, int, int, int]  # x1, y1, x2, y2
    center: Tuple[float, float]
    confidence: float

    @property
    def width(self) -> int:
        return self.bbox[2] - self.bbox[0]

    @property
    def height(self) -> int:
        return self.bbox[3] - self.bbox[1]

    @property
    def is_vertical(self) -> bool:
        return self.height > self.width * 2


@dataclass
class Venue:
    """Processed venue with computed properties"""
    name: str
    center: Tuple[float, float]
    bbox: Tuple[int, int, int, int]
    confidence: float
    deck: int = 0
    category: str = "venue"
    position: str = ""  # forward, mid-forward, mid, mid-aft, aft
    side: str = ""  # port, center, starboard
    venue_id: str = ""
    neighbors: Dict[str, str] = field(default_factory=dict)
    staircase_id: Optional[int] = None
    elevator_bank: Optional[str] = None

    @property
    def x(self) -> float:
        return self.center[0]

    @property
    def y(self) -> float:
        return self.center[1]


# =============================================================================
# PaddleOCR Client
# =============================================================================

class PaddleOCRClient:
    """Client for PaddleOCR server on node2"""

    def __init__(self, base_url: str = PADDLEOCR_URL):
        self.base_url = base_url
        self.client = httpx.Client(timeout=PADDLEOCR_TIMEOUT)

    def check_status(self) -> bool:
        """Check if PaddleOCR server is available"""
        try:
            response = self.client.get(f"{self.base_url}/health")
            return response.json().get("ocr_loaded", False)
        except Exception as e:
            logger.error(f"PaddleOCR server not available: {e}")
            return False

    def run_ocr(self, image_path: str, min_confidence: float = 0.5) -> Dict:
        """Run OCR on an image file"""
        # Read and encode image
        with open(image_path, "rb") as f:
            image_data = f.read()
        image_b64 = base64.b64encode(image_data).decode("utf-8")

        # Call PaddleOCR API
        response = self.client.post(
            f"{self.base_url}/ocr",
            json={
                "image": image_b64,
                "min_confidence": min_confidence
            }
        )
        response.raise_for_status()
        return response.json()


# =============================================================================
# Staircase Detection (OpenCV)
# =============================================================================

def detect_stairs(image_path: str, debug_dir: Optional[Path] = None) -> Dict:
    """
    Find yellow-colored regions (staircases) in a deck plan image.
    """
    img = cv2.imread(str(image_path))
    if img is None:
        raise ValueError(f"Could not load image: {image_path}")

    height, width = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

    # Yellow color ranges
    yellow_ranges = [
        ((18, 40, 150), (35, 180, 255)),
        ((15, 30, 140), (30, 150, 240)),
        ((10, 50, 160), (25, 200, 255)),
    ]

    combined_mask = np.zeros((height, width), dtype=np.uint8)
    for lower, upper in yellow_ranges:
        lower = np.array(lower, dtype=np.uint8)
        upper = np.array(upper, dtype=np.uint8)
        mask = cv2.inRange(hsv, lower, upper)
        combined_mask = cv2.bitwise_or(combined_mask, mask)

    # Morphological cleanup
    kernel = np.ones((5, 5), np.uint8)
    combined_mask = cv2.morphologyEx(combined_mask, cv2.MORPH_CLOSE, kernel)
    combined_mask = cv2.morphologyEx(combined_mask, cv2.MORPH_OPEN, kernel)

    # Find contours
    contours, _ = cv2.findContours(combined_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    staircases = []
    min_area = 150
    max_area = width * height * 0.1

    for i, contour in enumerate(contours):
        area = cv2.contourArea(contour)
        if area < min_area or area > max_area:
            continue

        x, y, w, h = cv2.boundingRect(contour)
        M = cv2.moments(contour)
        if M["m00"] > 0:
            cx = int(M["m10"] / M["m00"])
            cy = int(M["m01"] / M["m00"])
        else:
            cx = x + w // 2
            cy = y + h // 2

        staircases.append({
            "bbox": (x, y, x + w, y + h),
            "center": (cx, cy),
            "area": area
        })

    # Sort by Y position
    staircases.sort(key=lambda s: s["center"][1])

    if debug_dir:
        debug_img = img.copy()
        for i, s in enumerate(staircases):
            bbox = s["bbox"]
            cv2.rectangle(debug_img, (bbox[0], bbox[1]), (bbox[2], bbox[3]), (0, 255, 0), 2)
            cv2.circle(debug_img, s["center"], 5, (0, 0, 255), -1)
            cv2.putText(debug_img, f"S{i+1}", (bbox[0], bbox[1] - 5),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
        cv2.imwrite(str(debug_dir / f"debug_stairs_{Path(image_path).stem}.png"), debug_img)

    return {
        "image_size": (width, height),
        "detections": staircases,
        "count": len(staircases)
    }


# =============================================================================
# Elevator Detection (Tesseract)
# =============================================================================

def detect_elevators(image_path: str, debug_dir: Optional[Path] = None) -> Dict:
    """
    Find elevator labels using Tesseract OCR.
    """
    img = cv2.imread(str(image_path))
    if img is None:
        raise ValueError(f"Could not load image: {image_path}")

    height, width = img.shape[:2]

    # Upscale 4x for better small text detection
    scale = 4
    upscaled = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(upscaled, cv2.COLOR_BGR2GRAY)

    # Run Tesseract
    custom_config = '--oem 3 --psm 12'
    data = pytesseract.image_to_data(gray, config=custom_config, output_type=pytesseract.Output.DICT)

    elevators = []
    for i, text in enumerate(data['text']):
        conf = int(data['conf'][i])
        text_clean = text.strip().upper()

        if conf > 30 and 'ELEV' in text_clean:
            x = data['left'][i] // scale
            y = data['top'][i] // scale
            w = data['width'][i] // scale
            h = data['height'][i] // scale
            cx = x + w // 2
            cy = y + h // 2

            elevators.append({
                "text": text.strip(),
                "bbox": (x, y, x + w, y + h),
                "center": (cx, cy),
                "confidence": conf
            })

    # Sort by Y, then X
    elevators.sort(key=lambda e: (e["center"][1], e["center"][0]))

    if debug_dir:
        debug_img = img.copy()
        for i, e in enumerate(elevators):
            bbox = e["bbox"]
            cv2.rectangle(debug_img, (bbox[0], bbox[1]), (bbox[2], bbox[3]), (255, 0, 255), 2)
            cv2.circle(debug_img, e["center"], 5, (0, 0, 255), -1)
            cv2.putText(debug_img, f"E{i+1}", (bbox[0], bbox[1] - 5),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 255), 2)
        cv2.imwrite(str(debug_dir / f"debug_elevators_{Path(image_path).stem}.png"), debug_img)

    return {
        "image_size": (width, height),
        "detections": elevators,
        "count": len(elevators)
    }


# =============================================================================
# Label Processing
# =============================================================================

class LabelProcessor:
    """Process and merge OCR detections into venues"""

    def __init__(self, image_size: Tuple[int, int]):
        self.image_width, self.image_height = image_size
        self.merge_y_threshold = 35
        self.merge_x_threshold = 50

    def process_ocr_results(self, ocr_data: Dict) -> List[Venue]:
        """Process PaddleOCR results into merged venues"""
        detections = []
        for det in ocr_data.get('detections', []):
            detections.append(Detection(
                text=det['text'],
                bbox=tuple(det['bbox']),
                center=tuple(det['center']),
                confidence=det['confidence']
            ))

        # Separate vertical and horizontal
        vertical = [d for d in detections if d.is_vertical]
        horizontal = [d for d in detections if not d.is_vertical]

        # Merge labels
        venues = self._merge_horizontal(horizontal)
        venues.extend(self._merge_vertical(vertical))

        # Filter out cabin numbers (mostly numeric names)
        venues = self._filter_cabin_numbers(venues)

        # Deduplicate
        venues = self._deduplicate(venues)

        return venues

    def _merge_horizontal(self, detections: List[Detection]) -> List[Venue]:
        """Merge horizontal multi-line labels"""
        detections.sort(key=lambda d: d.center[1])

        merged_groups = []
        used = set()

        for i, det in enumerate(detections):
            if i in used:
                continue

            group = [det]
            used.add(i)

            changed = True
            while changed:
                changed = False
                for j, other in enumerate(detections):
                    if j in used:
                        continue

                    for member in group:
                        y_gap = other.center[1] - member.center[1]
                        x_diff = abs(other.center[0] - member.center[0])

                        if 0 < y_gap < self.merge_y_threshold and x_diff < self.merge_x_threshold:
                            group.append(other)
                            used.add(j)
                            changed = True
                            break

                group.sort(key=lambda d: d.center[1])

            merged_groups.append(group)

        venues = []
        for group in merged_groups:
            group.sort(key=lambda d: d.center[1])
            name = " ".join(d.text for d in group).strip()
            if name.startswith("."):
                name = name[1:].strip()

            x1 = min(d.bbox[0] for d in group)
            y1 = min(d.bbox[1] for d in group)
            x2 = max(d.bbox[2] for d in group)
            y2 = max(d.bbox[3] for d in group)
            center = ((x1 + x2) / 2, (y1 + y2) / 2)
            confidence = sum(d.confidence for d in group) / len(group)

            venues.append(Venue(
                name=name,
                center=center,
                bbox=(x1, y1, x2, y2),
                confidence=confidence
            ))

        return venues

    def _merge_vertical(self, detections: List[Detection]) -> List[Venue]:
        """Merge vertical text labels"""
        if not detections:
            return []

        detections.sort(key=lambda d: d.center[1])

        merged_groups = []
        used = set()

        for i, det in enumerate(detections):
            if i in used:
                continue

            group = [det]
            used.add(i)

            changed = True
            while changed:
                changed = False
                for j, other in enumerate(detections):
                    if j in used:
                        continue

                    x_diff = abs(other.center[0] - det.center[0])
                    if x_diff >= 25:
                        continue

                    group_y_min = min(d.bbox[1] for d in group)
                    group_y_max = max(d.bbox[3] for d in group)
                    y_gap = max(0, max(other.bbox[1] - group_y_max, group_y_min - other.bbox[3]))

                    if y_gap <= 100:
                        group.append(other)
                        used.add(j)
                        changed = True

            merged_groups.append(group)

        venues = []
        for group in merged_groups:
            group.sort(key=lambda d: d.bbox[1])
            name = " ".join(d.text for d in group).strip()
            if name.startswith("."):
                name = name[1:].strip()

            x1 = min(d.bbox[0] for d in group)
            y1 = min(d.bbox[1] for d in group)
            x2 = max(d.bbox[2] for d in group)
            y2 = max(d.bbox[3] for d in group)
            center = ((x1 + x2) / 2, (y1 + y2) / 2)
            confidence = sum(d.confidence for d in group) / len(group)

            venues.append(Venue(
                name=name,
                center=center,
                bbox=(x1, y1, x2, y2),
                confidence=confidence
            ))

        return venues

    def _deduplicate(self, venues: List[Venue]) -> List[Venue]:
        """Remove duplicate venue names, keeping highest confidence"""
        seen = {}
        for venue in venues:
            normalized = venue.name.strip().upper()
            if normalized not in seen or venue.confidence > seen[normalized].confidence:
                seen[normalized] = venue
        return list(seen.values())

    def _filter_cabin_numbers(self, venues: List[Venue]) -> List[Venue]:
        """Filter out cabin numbers (mostly numeric strings)"""
        import re
        filtered = []

        for venue in venues:
            name = venue.name.strip()

            # Skip very short names (single letters/numbers)
            if len(name) <= 2:
                continue

            # Remove spaces, symbols and count digits vs letters
            clean = re.sub(r'[\s\+\*\-\.]', '', name)
            digit_count = sum(1 for c in clean if c.isdigit())
            letter_count = sum(1 for c in clean if c.isalpha())

            # Skip if mostly numeric (>60% digits and less than 4 letters)
            if len(clean) > 0:
                digit_ratio = digit_count / len(clean)
                if digit_ratio > 0.6 and letter_count < 4:
                    continue

            # Skip names that look like cabin number lists (e.g., "3578 3580 3582")
            if re.match(r'^[A-Z]?\s*\d{3,4}(\s+[\*\+]?\s*\d{3,4})+', name):
                continue

            # Skip names that are mostly 4-digit numbers
            words = name.split()
            four_digit_count = sum(1 for w in words if re.match(r'^\d{4}$', w.strip('*+')))
            if len(words) > 3 and four_digit_count > len(words) * 0.5:
                continue

            # Skip names starting with * (typically cabin number noise)
            if name.startswith('*'):
                continue

            # Skip names with OCR noise patterns (letters that look like numbers: G/6, E/3, B/8)
            if re.search(r'\d{4}\s+\*?\s*(GEEB|GEES|EEBE|BEEB)', name):
                continue

            filtered.append(venue)

        return filtered

    def classify_position(self, venue: Venue) -> None:
        """Classify forward/aft position based on Y coordinate"""
        y_ratio = venue.y / self.image_height
        if y_ratio < 0.2:
            venue.position = "forward"
        elif y_ratio < 0.4:
            venue.position = "mid-forward"
        elif y_ratio < 0.6:
            venue.position = "mid"
        elif y_ratio < 0.8:
            venue.position = "mid-aft"
        else:
            venue.position = "aft"

    def classify_side(self, venue: Venue) -> None:
        """Classify port/starboard/center based on X coordinate"""
        x_ratio = venue.x / self.image_width
        if x_ratio < 0.4:
            venue.position = "port"
        elif x_ratio > 0.6:
            venue.side = "starboard"
        else:
            venue.side = "center"


# =============================================================================
# Deck Processor
# =============================================================================

class DeckProcessor:
    """Process a single deck image"""

    def __init__(self, ocr_client: PaddleOCRClient, debug_dir: Optional[Path] = None):
        self.ocr_client = ocr_client
        self.debug_dir = debug_dir

    def process(self, image_path: Path, deck_number: int) -> Dict:
        """Process a single deck image"""
        logger.info(f"Processing deck {deck_number}: {image_path.name}")

        # 1. Run PaddleOCR for venues
        logger.info(f"  Running PaddleOCR...")
        start = time.time()
        ocr_result = self.ocr_client.run_ocr(str(image_path), min_confidence=0.5)
        logger.info(f"  PaddleOCR: {ocr_result['count']} detections in {time.time()-start:.2f}s")

        image_size = (ocr_result['image_size']['width'], ocr_result['image_size']['height'])

        # 2. Detect staircases (OpenCV)
        logger.info(f"  Detecting staircases...")
        start = time.time()
        stairs_result = detect_stairs(str(image_path), self.debug_dir)
        logger.info(f"  Stairs: {stairs_result['count']} found in {time.time()-start:.2f}s")

        # 3. Detect elevators (Tesseract)
        logger.info(f"  Detecting elevators...")
        start = time.time()
        elevator_result = detect_elevators(str(image_path), self.debug_dir)
        logger.info(f"  Elevators: {elevator_result['count']} found in {time.time()-start:.2f}s")

        # 4. Process OCR into venues
        processor = LabelProcessor(image_size)
        venues = processor.process_ocr_results(ocr_result)

        # 5. Add deck number and classify positions
        for venue in venues:
            venue.deck = deck_number
            processor.classify_position(venue)
            processor.classify_side(venue)
            venue.venue_id = self._make_id(venue.name, deck_number)
            venue.category = self._classify_category(venue.name)

        # 6. Add staircases as venues
        for i, stair in enumerate(stairs_result['detections']):
            venue = Venue(
                name=f"Staircase {i+1}",
                center=stair['center'],
                bbox=stair['bbox'],
                confidence=1.0,
                deck=deck_number,
                category="stairs"
            )
            processor.classify_position(venue)
            processor.classify_side(venue)
            venue.venue_id = f"deck{deck_number}-staircase{i+1}"
            venues.append(venue)

        # 7. Add elevators as venues
        for i, elev in enumerate(elevator_result['detections']):
            venue = Venue(
                name=f"Elevator {i+1}",
                center=elev['center'],
                bbox=elev['bbox'],
                confidence=elev.get('confidence', 50) / 100.0,
                deck=deck_number,
                category="elevator"
            )
            processor.classify_position(venue)
            processor.classify_side(venue)
            venue.venue_id = f"deck{deck_number}-elevator{i+1}"
            venues.append(venue)

        # 8. Compute neighbors
        self._compute_neighbors(venues)

        logger.info(f"  Total venues: {len(venues)}")

        return {
            "deck": deck_number,
            "image_size": image_size,
            "venues": venues,
            "raw_ocr": ocr_result,
            "raw_stairs": stairs_result,
            "raw_elevators": elevator_result
        }

    def _make_id(self, name: str, deck: int) -> str:
        """Generate venue ID from name"""
        slug = name.lower()
        slug = re.sub(r"[^a-z0-9]+", "-", slug)
        slug = slug.strip("-")
        return f"deck{deck}-{slug}"

    def _classify_category(self, name: str) -> str:
        """Classify venue category based on name keywords"""
        name_lower = name.lower()

        # Check keywords in priority order
        if any(kw in name_lower for kw in ['theater', 'theatre', 'comedy', 'music hall', 'studio b']):
            return 'entertainment'
        if any(kw in name_lower for kw in ['dining', 'restaurant', 'grille', 'table', 'kitchen', 'bistro', 'sorrento', 'izumi', 'rockets', 'dog house', 'bbq', 'el loco']):
            return 'dining'
        if any(kw in name_lower for kw in ['spa', 'vitality']):
            return 'spa'
        if any(kw in name_lower for kw in ['fitness', 'gym']):
            return 'fitness'
        if any(kw in name_lower for kw in ['casino']):
            return 'casino'
        if any(kw in name_lower for kw in ['bar', 'pub', 'lounge', 'boleros', 'vintages', 'schooner']):
            return 'bar'
        if any(kw in name_lower for kw in ['cafe', 'starbucks', 'coffee']):
            return 'cafe'
        if any(kw in name_lower for kw in ['pool', 'whirlpool', 'solarium', 'aqua']):
            return 'pool'
        if any(kw in name_lower for kw in ['shop', 'gallery', 'merchant', 'collection', 'regalia', 'tiffany', 'focus', 'picture']):
            return 'shopping'
        if any(kw in name_lower for kw in ['rock climbing', 'flowrider', 'zip', 'abyss', 'carousel', 'arcade', 'sports court', 'track', 'ice rink', 'dunes', 'splashaway', 'storm']):
            return 'recreation'
        if any(kw in name_lower for kw in ['library']):
            return 'library'
        if any(kw in name_lower for kw in ['conference', 'meeting']):
            return 'meeting'
        if any(kw in name_lower for kw in ['guest service', 'shore excursion', 'next cruise', 'padi']):
            return 'services'
        if any(kw in name_lower for kw in ['nursery', 'adventure ocean', 'teen', 'kids']):
            return 'kids'
        if any(kw in name_lower for kw in ['promenade', 'boardwalk']):
            return 'promenade'
        if any(kw in name_lower for kw in ['central park', 'sun deck']):
            return 'outdoor'

        return 'venue'

    def _compute_neighbors(self, venues: List[Venue]) -> None:
        """Compute directional neighbors for each venue"""
        def distance(v1: Venue, v2: Venue) -> float:
            return math.sqrt((v1.x - v2.x)**2 + (v1.y - v2.y)**2)

        def get_direction(from_v: Venue, to_v: Venue) -> Optional[str]:
            dx = to_v.x - from_v.x
            dy = to_v.y - from_v.y
            if abs(dx) < 1 and abs(dy) < 1:
                return None
            angle = math.atan2(dy, dx) * 180 / math.pi
            if -45 <= angle <= 45:
                return 'east'
            elif 45 < angle <= 135:
                return 'south'
            elif -135 <= angle < -45:
                return 'north'
            else:
                return 'west'

        for venue in venues:
            directional = {d: (float('inf'), None) for d in ['north', 'south', 'east', 'west']}

            for other in venues:
                if other.venue_id == venue.venue_id:
                    continue
                direction = get_direction(venue, other)
                if direction is None:
                    continue
                dist = distance(venue, other)
                if dist < directional[direction][0]:
                    directional[direction] = (dist, other.venue_id)

            venue.neighbors = {d: vid for d, (_, vid) in directional.items() if vid}


# =============================================================================
# Ship Processor
# =============================================================================

class ShipProcessor:
    """Process all decks for a ship"""

    def __init__(self, ship_name: str, ocr_client: PaddleOCRClient,
                 debug_dir: Optional[Path] = None):
        self.ship_name = ship_name
        self.ocr_client = ocr_client
        self.debug_dir = debug_dir
        self.deck_processor = DeckProcessor(ocr_client, debug_dir)

    def find_deck_images(self, input_dir: Path) -> Dict[int, Path]:
        """Find all deck images and extract deck numbers"""
        deck_images = {}
        patterns = ['*.jpg', '*.jpeg', '*.png', '*.webp']

        for pattern in patterns:
            for path in input_dir.glob(pattern):
                # Try to extract deck number from filename
                match = re.search(r'deck[_-]?(\d+)', path.name.lower())
                if match:
                    deck_num = int(match.group(1))
                    deck_images[deck_num] = path

        return dict(sorted(deck_images.items()))

    def process(self, input_dir: Path) -> Dict:
        """Process all deck images"""
        deck_images = self.find_deck_images(input_dir)

        if not deck_images:
            raise ValueError(f"No deck images found in {input_dir}")

        logger.info(f"Found {len(deck_images)} deck images: {list(deck_images.keys())}")

        all_venues = []
        deck_data = {}

        for deck_num, image_path in deck_images.items():
            result = self.deck_processor.process(image_path, deck_num)
            deck_data[deck_num] = result
            all_venues.extend(result['venues'])

        # Link vertical connections
        logger.info("Linking vertical connections...")
        self._link_verticals(all_venues, list(deck_images.keys()))

        # Build final output
        output = {
            "ship": self.ship_name,
            "decks": list(deck_images.keys()),
            "note": self._detect_missing_decks(list(deck_images.keys())),
            "venues": [self._venue_to_dict(v) for v in all_venues],
            "staircases": self._build_staircase_summary(all_venues),
            "elevator_banks": self._build_elevator_summary(all_venues),
            "summary": {
                "total_venues": len(all_venues),
                "by_category": self._count_by_category(all_venues),
                "by_deck": {d: len([v for v in all_venues if v.deck == d])
                          for d in deck_images.keys()}
            }
        }

        return output

    def _link_verticals(self, venues: List[Venue], deck_list: List[int]) -> None:
        """Link stairs and elevators across decks"""
        # Group by category and approximate position
        stairs = [v for v in venues if v.category == "stairs"]
        elevators = [v for v in venues if v.category == "elevator"]

        # Link stairs
        stair_groups = self._group_by_position(stairs, tolerance=50)
        for group_id, group in enumerate(stair_groups, 1):
            group.sort(key=lambda v: v.deck)
            for i, venue in enumerate(group):
                venue.staircase_id = group_id
                vertical = []
                if i > 0:
                    vertical.append(group[i-1].venue_id)
                if i < len(group) - 1:
                    vertical.append(group[i+1].venue_id)
                if vertical:
                    venue.neighbors['vertical'] = vertical

        # Link elevators
        elev_groups = self._group_by_position(elevators, tolerance=50)
        for group_id, group in enumerate(elev_groups, 1):
            group.sort(key=lambda v: v.deck)
            bank_name = f"bank{group_id}"
            for i, venue in enumerate(group):
                venue.elevator_bank = bank_name
                vertical = []
                if i > 0:
                    vertical.append(group[i-1].venue_id)
                if i < len(group) - 1:
                    vertical.append(group[i+1].venue_id)
                if vertical:
                    venue.neighbors['vertical'] = vertical

    def _group_by_position(self, venues: List[Venue], tolerance: int = 50) -> List[List[Venue]]:
        """Group venues by similar X,Y positions (ignoring deck)"""
        groups = []
        used = set()

        for v in venues:
            if id(v) in used:
                continue

            group = [v]
            used.add(id(v))

            for other in venues:
                if id(other) in used:
                    continue
                if abs(v.x - other.x) < tolerance and abs(v.y - other.y) < tolerance:
                    group.append(other)
                    used.add(id(other))

            groups.append(group)

        return groups

    def _detect_missing_decks(self, deck_list: List[int]) -> str:
        """Detect and note missing decks (like 13)"""
        if not deck_list:
            return ""

        min_d, max_d = min(deck_list), max(deck_list)
        missing = [d for d in range(min_d, max_d + 1) if d not in deck_list]

        if missing:
            return f"No deck {', '.join(map(str, missing))}"
        return ""

    def _normalize_name(self, name: str) -> str:
        """Convert OCR uppercase names to title case"""
        # Handle all-caps names from OCR
        if name.isupper():
            # Title case but preserve special words
            words = name.split()
            result = []
            for i, word in enumerate(words):
                # Keep small words lowercase unless first
                if i > 0 and word.lower() in ('and', 'the', 'of', 'at', 'in', 'on', '&'):
                    result.append(word.lower() if word != '&' else '&')
                else:
                    result.append(word.title())
            return ' '.join(result)
        return name

    def _venue_to_dict(self, venue: Venue) -> Dict:
        """Convert venue to dictionary for JSON output"""
        result = {
            "id": venue.venue_id,
            "name": self._normalize_name(venue.name),
            "deck": venue.deck,
            "position": venue.position,
            "side": venue.side,
            "category": venue.category,
            "center": {"x": round(venue.x, 1), "y": round(venue.y, 1)},
            "confidence": round(venue.confidence, 4),
            "neighbors": venue.neighbors
        }

        if venue.staircase_id:
            result["staircase_id"] = venue.staircase_id
        if venue.elevator_bank:
            result["elevator_bank"] = venue.elevator_bank

        return result

    def _build_staircase_summary(self, venues: List[Venue]) -> List[Dict]:
        """Build staircase summary"""
        stairs = [v for v in venues if v.category == "stairs"]
        by_id = defaultdict(list)
        for s in stairs:
            if s.staircase_id:
                by_id[s.staircase_id].append(s)

        summary = []
        for stair_id, group in sorted(by_id.items()):
            first = group[0]
            summary.append({
                "id": stair_id,
                "name": f"Staircase {stair_id}",
                "position": first.position,
                "side": first.side,
                "decks": sorted(set(s.deck for s in group))
            })
        return summary

    def _build_elevator_summary(self, venues: List[Venue]) -> Dict[str, Dict]:
        """Build elevator bank summary"""
        elevators = [v for v in venues if v.category == "elevator"]
        by_bank = defaultdict(list)
        for e in elevators:
            if e.elevator_bank:
                by_bank[e.elevator_bank].append(e)

        summary = {}
        for bank_name, group in sorted(by_bank.items()):
            first = group[0]
            summary[bank_name] = {
                "decks": sorted(set(e.deck for e in group)),
                "position": first.position
            }
        return summary

    def _count_by_category(self, venues: List[Venue]) -> Dict[str, int]:
        """Count venues by category"""
        counts = defaultdict(int)
        for v in venues:
            counts[v.category] += 1
        return dict(counts)


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Process ship deck plans into navigation JSON",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python directions_maker.py --title "Oasis of the Seas" \\
        --input_dir ./ships/RC_oasis_of_the_seas \\
        --output_dir ./output

    python directions_maker.py --title "Symphony of the Seas" \\
        --input_dir /path/to/decks --output_dir /path/to/output \\
        --debug --verbose
        """
    )

    parser.add_argument("--title", required=True, help="Ship name")
    parser.add_argument("--input_dir", required=True, help="Directory containing deck images")
    parser.add_argument("--output_dir", required=True, help="Output directory")
    parser.add_argument("--debug", action="store_true", help="Save debug images")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--ocr-url", default=PADDLEOCR_URL, help=f"PaddleOCR server URL (default: {PADDLEOCR_URL})")
    parser.add_argument("--min-confidence", type=float, default=0.5, help="Min OCR confidence (default: 0.5)")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)

    if not input_dir.exists():
        logger.error(f"Input directory does not exist: {input_dir}")
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    debug_dir = output_dir / "debug" if args.debug else None
    if debug_dir:
        debug_dir.mkdir(exist_ok=True)

    # Check PaddleOCR
    logger.info(f"Checking PaddleOCR server at {args.ocr_url}...")
    ocr_client = PaddleOCRClient(args.ocr_url)
    if not ocr_client.check_status():
        logger.error("PaddleOCR server not available. Make sure it's running on node2.")
        sys.exit(1)
    logger.info("PaddleOCR server OK")

    # Process
    logger.info(f"Processing ship: {args.title}")
    logger.info(f"Input: {input_dir}")
    logger.info(f"Output: {output_dir}")

    start_time = time.time()

    processor = ShipProcessor(args.title, ocr_client, debug_dir)
    result = processor.process(input_dir)

    elapsed = time.time() - start_time

    # Save output
    output_file = output_dir / f"{args.title.lower().replace(' ', '_')}_navigation.json"
    with open(output_file, 'w') as f:
        json.dump(result, f, indent=2)

    logger.info(f"")
    logger.info(f"{'='*60}")
    logger.info(f"COMPLETE")
    logger.info(f"{'='*60}")
    logger.info(f"Ship: {result['ship']}")
    logger.info(f"Decks: {result['decks']}")
    logger.info(f"Total venues: {result['summary']['total_venues']}")
    logger.info(f"By category: {result['summary']['by_category']}")
    logger.info(f"Staircases: {len(result['staircases'])}")
    logger.info(f"Elevator banks: {len(result['elevator_banks'])}")
    logger.info(f"Processing time: {elapsed:.1f}s")
    logger.info(f"Output: {output_file}")


if __name__ == "__main__":
    main()
