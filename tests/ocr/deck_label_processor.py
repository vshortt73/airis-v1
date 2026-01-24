#!/usr/bin/env python3
"""
Deck Plan Label Processor
Processes PaddleOCR output to:
1. Merge multi-line labels
2. Compute spatial neighbors
3. Classify port/starboard/center positions

Usage:
    python deck_label_processor.py input.json [output.json]
    cat input.json | python deck_label_processor.py -
"""

import json
import math
import sys
from dataclasses import dataclass, field
from typing import List, Dict, Tuple
from collections import defaultdict


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
    """Merged venue with computed properties"""
    name: str
    center: Tuple[float, float]
    bbox: Tuple[int, int, int, int]
    confidence: float
    source_detections: List[Detection] = field(default_factory=list)
    position: str = ""  # port, starboard, center
    neighbors: Dict[str, str] = field(default_factory=dict)  # direction -> venue name
    
    @property
    def x(self) -> float:
        return self.center[0]
    
    @property
    def y(self) -> float:
        return self.center[1]


class DeckLabelProcessor:
    def __init__(self, 
                 merge_y_threshold: int = 35,
                 merge_x_threshold: int = 50,
                 port_x_ratio: float = 0.4,
                 starboard_x_ratio: float = 0.6):
        """
        Initialize processor with configurable thresholds.
        
        Args:
            merge_y_threshold: Max Y distance to consider labels part of same venue
            merge_x_threshold: Max X center difference to merge labels
            port_x_ratio: Ratio of image width below which is "port" side
            starboard_x_ratio: Ratio of image width above which is "starboard" side
        """
        self.merge_y_threshold = merge_y_threshold
        self.merge_x_threshold = merge_x_threshold
        self.port_x_ratio = port_x_ratio
        self.starboard_x_ratio = starboard_x_ratio
        
        self.detections: List[Detection] = []
        self.venues: List[Venue] = []
        self.image_size: Tuple[int, int] = (0, 0)
    
    def load_paddleocr_json(self, json_data: dict) -> None:
        """Load detections from PaddleOCR JSON output."""
        self.image_size = (
            json_data['image_size']['width'],
            json_data['image_size']['height']
        )
        
        self.detections = []
        for det in json_data['detections']:
            self.detections.append(Detection(
                text=det['text'],
                bbox=tuple(det['bbox']),
                center=tuple(det['center']),
                confidence=det['confidence']
            ))
        
        print(f"Loaded {len(self.detections)} detections from {self.image_size[0]}x{self.image_size[1]} image", file=sys.stderr)
    
    def merge_multiline_labels(self) -> None:
        """
        Merge detections that form multi-line labels.
        - Horizontal text: Groups by X proximity, sorts by Y to concatenate
        - Vertical text: Groups by X proximity (tight), sorts by Y to concatenate
        """
        # Separate vertical labels (like RUNNING TRACK, ROYAL PROMENADE)
        vertical = [d for d in self.detections if d.is_vertical]
        horizontal = [d for d in self.detections if not d.is_vertical]
        
        # First, merge vertical text by X-proximity
        merged_vertical = self._merge_vertical_labels(vertical)
        
        # Sort horizontal by Y (top to bottom)
        horizontal.sort(key=lambda d: d.center[1])
        
        merged_groups: List[List[Detection]] = []
        used = set()
        
        for i, det in enumerate(horizontal):
            if i in used:
                continue
            
            # Start a new group
            group = [det]
            used.add(i)
            
            # Look for labels directly below with similar X
            # Keep checking until no more matches
            changed = True
            while changed:
                changed = False
                for j, other in enumerate(horizontal):
                    if j in used:
                        continue
                    
                    # Check against all items in current group
                    for member in group:
                        y_gap = other.center[1] - member.center[1]
                        x_diff = abs(other.center[0] - member.center[0])
                        
                        # Must be below (positive y_gap) and x-aligned
                        if 0 < y_gap < self.merge_y_threshold and x_diff < self.merge_x_threshold:
                            group.append(other)
                            used.add(j)
                            changed = True
                            break
                
                # Re-sort group by Y after adding
                group.sort(key=lambda d: d.center[1])
            
            merged_groups.append(group)
        
        # Convert groups to Venues
        self.venues = []
        
        for group in merged_groups:
            # Sort by Y and concatenate text
            group.sort(key=lambda d: d.center[1])
            name = " ".join(d.text for d in group)
            
            # Clean up common OCR artifacts
            name = name.strip()
            if name.startswith("."):
                name = name[1:]
            
            # Compute merged bounding box
            x1 = min(d.bbox[0] for d in group)
            y1 = min(d.bbox[1] for d in group)
            x2 = max(d.bbox[2] for d in group)
            y2 = max(d.bbox[3] for d in group)
            
            # Center is middle of merged bbox
            center = ((x1 + x2) / 2, (y1 + y2) / 2)
            
            # Average confidence
            confidence = sum(d.confidence for d in group) / len(group)
            
            self.venues.append(Venue(
                name=name,
                center=center,
                bbox=(x1, y1, x2, y2),
                confidence=confidence,
                source_detections=group
            ))
        
        # Add vertical labels (already merged)
        for venue in merged_vertical:
            self.venues.append(venue)
        
        # Remove duplicates (like multiple RUNNING TRACK)
        self._deduplicate_venues()
        
        print(f"Merged {len(self.detections)} detections into {len(self.venues)} venues", file=sys.stderr)
    
    def _merge_vertical_labels(self, vertical: List[Detection]) -> List[Venue]:
        """
        Merge vertical text detections that are X-aligned AND Y-adjacent.
        Vertical text stacks side-by-side, so we merge by X proximity,
        but only if the Y ranges overlap or are close.
        """
        if not vertical:
            return []
        
        # Sort by Y position (top to bottom)
        vertical.sort(key=lambda d: d.center[1])
        
        merged_groups: List[List[Detection]] = []
        used = set()
        
        # Thresholds for vertical text
        vertical_merge_x_threshold = 25  # Must be very X-close
        vertical_merge_y_gap_max = 100   # Max gap between Y ranges to merge
        
        for i, det in enumerate(vertical):
            if i in used:
                continue
            
            group = [det]
            used.add(i)
            
            # Iteratively find adjacent vertical labels
            changed = True
            while changed:
                changed = False
                for j, other in enumerate(vertical):
                    if j in used:
                        continue
                    
                    # Check X alignment
                    x_diff = abs(other.center[0] - det.center[0])
                    if x_diff >= vertical_merge_x_threshold:
                        continue
                    
                    # Check Y adjacency - ranges should overlap or be close
                    # Get Y range of current group
                    group_y_min = min(d.bbox[1] for d in group)
                    group_y_max = max(d.bbox[3] for d in group)
                    
                    other_y_min = other.bbox[1]
                    other_y_max = other.bbox[3]
                    
                    # Check if overlapping or adjacent
                    y_gap = max(0, max(other_y_min - group_y_max, group_y_min - other_y_max))
                    
                    if y_gap <= vertical_merge_y_gap_max:
                        group.append(other)
                        used.add(j)
                        changed = True
            
            merged_groups.append(group)
        
        # Convert groups to Venues
        venues = []
        for group in merged_groups:
            # Sort by Y (top to bottom) for reading order
            # Note: This assumes text reads top-to-bottom. 
            # For "ROYAL PROMENADE", if ROYAL bbox starts higher, it should come first.
            group.sort(key=lambda d: d.bbox[1])  # Sort by top of bbox, not center
            
            # Concatenate text, clean up artifacts
            name = " ".join(d.text for d in group)
            name = name.strip()
            if name.startswith("."):
                name = name[1:].strip()
            
            # Compute merged bounding box
            x1 = min(d.bbox[0] for d in group)
            y1 = min(d.bbox[1] for d in group)
            x2 = max(d.bbox[2] for d in group)
            y2 = max(d.bbox[3] for d in group)
            
            # Center of merged bbox
            center = ((x1 + x2) / 2, (y1 + y2) / 2)
            
            # Average confidence
            confidence = sum(d.confidence for d in group) / len(group)
            
            venues.append(Venue(
                name=name,
                center=center,
                bbox=(x1, y1, x2, y2),
                confidence=confidence,
                source_detections=group
            ))
        
        return venues
    
    def _deduplicate_venues(self) -> None:
        """Remove duplicate venue names, keeping highest confidence."""
        seen = {}
        for venue in self.venues:
            normalized = venue.name.strip().upper()
            if normalized not in seen or venue.confidence > seen[normalized].confidence:
                seen[normalized] = venue
        self.venues = list(seen.values())
    
    def classify_positions(self) -> None:
        """Classify each venue as port, starboard, or center based on image width."""
        port_threshold = self.image_size[0] * self.port_x_ratio
        starboard_threshold = self.image_size[0] * self.starboard_x_ratio
        
        for venue in self.venues:
            if venue.x < port_threshold:
                venue.position = "port"
            elif venue.x > starboard_threshold:
                venue.position = "starboard"
            else:
                venue.position = "center"
    
    def compute_neighbors(self) -> None:
        """
        Compute directional neighbors (N/S/E/W) for each venue.
        
        Coordinate system (bow-up deck plan):
        - North = lower Y (toward bow/forward)
        - South = higher Y (toward stern/aft)
        - East = higher X (toward starboard)
        - West = lower X (toward port)
        
        A venue is considered a directional neighbor if:
        1. It's the closest venue in that direction
        2. The angle is within 45° of the cardinal direction
        """
        def distance(v1: Venue, v2: Venue) -> float:
            return math.sqrt((v1.x - v2.x)**2 + (v1.y - v2.y)**2)
        
        def get_direction(from_venue: Venue, to_venue: Venue) -> str:
            """
            Determine cardinal direction from one venue to another.
            Returns 'north', 'south', 'east', 'west', or None if too close.
            """
            dx = to_venue.x - from_venue.x
            dy = to_venue.y - from_venue.y
            
            # Skip if venues are at same position
            if abs(dx) < 1 and abs(dy) < 1:
                return None
            
            # Calculate angle (0° = east, 90° = south, etc.)
            angle = math.atan2(dy, dx) * 180 / math.pi
            
            # Determine direction based on 45° sectors
            # North: -135° to -45° (or 225° to 315°)
            # South: 45° to 135°
            # East: -45° to 45°
            # West: 135° to 180° or -180° to -135°
            
            if -45 <= angle <= 45:
                return 'east'
            elif 45 < angle <= 135:
                return 'south'
            elif -135 <= angle < -45:
                return 'north'
            else:  # angle > 135 or angle < -135
                return 'west'
        
        for venue in self.venues:
            # Track closest venue in each direction
            directional = {
                'north': (float('inf'), None),
                'south': (float('inf'), None),
                'east': (float('inf'), None),
                'west': (float('inf'), None)
            }
            
            for other in self.venues:
                if other.name == venue.name:
                    continue
                
                direction = get_direction(venue, other)
                if direction is None:
                    continue
                
                dist = distance(venue, other)
                
                # Keep only the closest in each direction
                if dist < directional[direction][0]:
                    directional[direction] = (dist, other.name)
            
            # Build neighbor dict with only valid directions
            venue.neighbors = {}
            for direction, (dist, name) in directional.items():
                if name is not None:
                    venue.neighbors[direction] = name
    
    def process(self) -> List[Venue]:
        """Run full processing pipeline."""
        self.merge_multiline_labels()
        self.classify_positions()
        self.compute_neighbors()
        return self.venues
    
    def to_dict(self) -> Dict:
        """Export processed data as dictionary."""
        return {
            "image_size": {
                "width": self.image_size[0],
                "height": self.image_size[1]
            },
            "processing_params": {
                "merge_y_threshold": self.merge_y_threshold,
                "merge_x_threshold": self.merge_x_threshold,
                "port_x_ratio": self.port_x_ratio,
                "starboard_x_ratio": self.starboard_x_ratio
            },
            "venues": [
                {
                    "name": v.name,
                    "center": {"x": round(v.center[0], 1), "y": round(v.center[1], 1)},
                    "bbox": {"x1": v.bbox[0], "y1": v.bbox[1], "x2": v.bbox[2], "y2": v.bbox[3]},
                    "position": v.position,
                    "neighbors": v.neighbors,
                    "confidence": round(v.confidence, 4)
                }
                for v in sorted(self.venues, key=lambda x: x.y)
            ],
            "summary": {
                "total_venues": len(self.venues),
                "by_position": {
                    "port": len([v for v in self.venues if v.position == "port"]),
                    "center": len([v for v in self.venues if v.position == "center"]),
                    "starboard": len([v for v in self.venues if v.position == "starboard"])
                }
            }
        }
    
    def print_summary(self) -> None:
        """Print human-readable summary to stderr."""
        print("\n" + "="*60, file=sys.stderr)
        print("DECK PLAN ANALYSIS", file=sys.stderr)
        print("="*60, file=sys.stderr)
        
        # Group by position
        by_position = defaultdict(list)
        for v in sorted(self.venues, key=lambda x: x.y):
            by_position[v.position].append(v)
        
        for position in ["port", "center", "starboard"]:
            venues = by_position[position]
            print(f"\n{position.upper()} ({len(venues)} venues):", file=sys.stderr)
            print("-" * 40, file=sys.stderr)
            for v in venues:
                print(f"  {v.name}", file=sys.stderr)
                print(f"    pos: ({v.x:.0f}, {v.y:.0f})", file=sys.stderr)
                if v.neighbors:
                    for direction, neighbor in v.neighbors.items():
                        print(f"      {direction}: {neighbor}", file=sys.stderr)
                else:
                    print(f"      (no neighbors)", file=sys.stderr)
        
        print("\n" + "="*60, file=sys.stderr)


def main():
    if len(sys.argv) < 2:
        print("Usage: python deck_label_processor.py input.json [output.json]", file=sys.stderr)
        print("       cat input.json | python deck_label_processor.py -", file=sys.stderr)
        sys.exit(1)
    
    # Read input
    input_path = sys.argv[1]
    if input_path == "-":
        ocr_data = json.load(sys.stdin)
    else:
        with open(input_path, 'r') as f:
            ocr_data = json.load(f)
    
    # Process
    processor = DeckLabelProcessor()
    processor.load_paddleocr_json(ocr_data)
    processor.process()
    processor.print_summary()
    
    # Output
    result = processor.to_dict()
    
    if len(sys.argv) >= 3:
        output_path = sys.argv[2]
        with open(output_path, 'w') as f:
            json.dump(result, f, indent=2)
        print(f"\nWrote output to {output_path}", file=sys.stderr)
    else:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()