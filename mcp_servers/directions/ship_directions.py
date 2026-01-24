#!/usr/bin/env python3
"""
Ship Directions Module for Iris
Provides natural language navigation directions between locations on a cruise ship.

Usage:
    from ship_directions import ShipNavigator
    nav = ShipNavigator('oasis_ship_map_with_stairs.json')
    directions = nav.get_directions("deck6-carousel", "deck16-zip-line")
    print(directions)
"""

import json
import re
from collections import deque
from pathlib import Path
from typing import Optional, List, Dict, Tuple


class ShipNavigator:
    def __init__(self, map_file: str):
        """Load ship map and build navigation graph."""
        with open(map_file, 'r') as f:
            self.data = json.load(f)
        
        self.ship_name = self.data.get('ship', 'Ship')
        self.venues = {v['id']: v for v in self.data['venues']}
        self.graph = self._build_graph()
        self.name_index = self._build_name_index()
    
    def _build_graph(self) -> Dict[str, set]:
        """Build adjacency graph from venue neighbors."""
        graph = {vid: set() for vid in self.venues}
        
        for vid, venue in self.venues.items():
            neighbors = venue.get('neighbors', {})
            for direction, target in neighbors.items():
                if direction == 'vertical':
                    for t in target:
                        if t in graph:
                            graph[vid].add(t)
                            graph[t].add(vid)
                elif target and target in graph:
                    graph[vid].add(target)
                    graph[target].add(vid)
        
        return graph
    
    def _build_name_index(self) -> Dict[str, List[str]]:
        """Build index for fuzzy name matching."""
        index = {}
        for vid, venue in self.venues.items():
            # Index by full ID
            index[vid.lower()] = vid
            
            # Index by name (lowercase, no special chars)
            name_key = re.sub(r'[^a-z0-9]', '', venue['name'].lower())
            if name_key not in index:
                index[name_key] = []
            if isinstance(index[name_key], list):
                index[name_key].append(vid)
            
            # Index by name + deck
            deck_name_key = f"deck{venue['deck']}{name_key}"
            index[deck_name_key] = vid
            
            # Index by words in name
            for word in venue['name'].lower().split():
                word_key = re.sub(r'[^a-z0-9]', '', word)
                if len(word_key) > 2:  # Skip short words
                    if word_key not in index:
                        index[word_key] = []
                    if isinstance(index[word_key], list) and vid not in index[word_key]:
                        index[word_key].append(vid)
        
        return index
    
    def resolve_location(self, query: str) -> Optional[str]:
        """
        Resolve a natural language location to a venue ID.
        Handles: "deck6-carousel", "deck 6 carousel", "carousel deck 6", "carousel"
        """
        # Handle empty/None input
        if not query or not query.strip():
            return None
            
        # Normalize query
        q = query.lower().strip()
        q_clean = re.sub(r'[^a-z0-9]', '', q)
        
        # Direct match
        if q in self.venues:
            return q
        if q.replace(' ', '-') in self.venues:
            return q.replace(' ', '-')
        if q_clean in self.name_index:
            result = self.name_index[q_clean]
            if isinstance(result, str):
                return result
            elif len(result) == 1:
                return result[0]
        
        # Try to extract deck number
        deck_match = re.search(r'deck\s*(\d+)', q)
        deck_num = int(deck_match.group(1)) if deck_match else None
        
        # Remove deck from query for name matching
        q_no_deck = re.sub(r'deck\s*\d+', '', q).strip()
        q_no_deck_clean = re.sub(r'[^a-z0-9]', '', q_no_deck)
        
        # If we have a deck, try deck+name combo
        if deck_num and q_no_deck_clean:
            combo_key = f"deck{deck_num}{q_no_deck_clean}"
            if combo_key in self.name_index:
                return self.name_index[combo_key]
        
        # Try name only, filter by deck if provided
        if q_no_deck_clean and q_no_deck_clean in self.name_index:
            candidates = self.name_index[q_no_deck_clean]
            if isinstance(candidates, str):
                return candidates
            if deck_num:
                for c in candidates:
                    if self.venues[c]['deck'] == deck_num:
                        return c
            # If only one candidate, return it
            if len(candidates) == 1:
                return candidates[0]
            # Multiple candidates - return None (ambiguous)
            return None
        
        # Fuzzy: try each word - require at least 4 chars to avoid false positives
        words = [re.sub(r'[^a-z0-9]', '', w) for w in q_no_deck.split() if len(w) >= 4]
        for word in words:
            if word in self.name_index:
                candidates = self.name_index[word]
                if isinstance(candidates, str):
                    return candidates
                if deck_num:
                    for c in candidates:
                        if self.venues[c]['deck'] == deck_num:
                            return c
                if len(candidates) == 1:
                    return candidates[0]
        
        return None
    
    def find_path(self, start_id: str, end_id: str) -> Optional[List[str]]:
        """Find shortest path using BFS."""
        if start_id not in self.graph or end_id not in self.graph:
            return None
        
        if start_id == end_id:
            return [start_id]
        
        queue = deque([(start_id, [start_id])])
        visited = {start_id}
        
        while queue:
            node, path = queue.popleft()
            
            if node == end_id:
                return path
            
            for neighbor in self.graph[node]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [neighbor]))
        
        return None
    
    def _get_direction_between(self, from_id: str, to_id: str) -> str:
        """Determine the direction from one venue to another."""
        from_venue = self.venues[from_id]
        to_venue = self.venues[to_id]
        
        # Check if it's a vertical move
        if from_venue['deck'] != to_venue['deck']:
            if to_venue['deck'] > from_venue['deck']:
                return "up"
            else:
                return "down"
        
        # Check explicit neighbor direction
        neighbors = from_venue.get('neighbors', {})
        for direction, target in neighbors.items():
            if direction == 'vertical':
                continue
            if target == to_id:
                return direction
        
        # Reverse check
        to_neighbors = to_venue.get('neighbors', {})
        opposites = {'north': 'south', 'south': 'north', 'east': 'west', 'west': 'east'}
        for direction, target in to_neighbors.items():
            if direction == 'vertical':
                continue
            if target == from_id:
                return opposites.get(direction, direction)
        
        return "toward"
    
    def _simplify_path(self, path: List[str]) -> List[Dict]:
        """
        Simplify path into segments (combine consecutive staircase steps, 
        identify deck changes via multi-deck venues).
        Returns list of segments with action descriptions.
        """
        if not path:
            return []
        
        segments = []
        i = 0
        
        while i < len(path):
            venue = self.venues[path[i]]
            
            # Check if this is start of a staircase sequence
            if venue.get('category') == 'stairs':
                stair_start = i
                stair_name = venue['name']
                start_deck = venue['deck']
                
                # Find end of staircase sequence (same staircase_id)
                stair_id = venue.get('staircase_id')
                while (i + 1 < len(path) and 
                       self.venues[path[i + 1]].get('staircase_id') == stair_id):
                    i += 1
                
                end_deck = self.venues[path[i]]['deck']
                
                if start_deck != end_deck:
                    direction = "up" if end_deck > start_deck else "down"
                    # Count actual stair steps taken, not deck number difference
                    stair_steps = i - stair_start
                    if stair_steps == 1:
                        deck_desc = "1 deck"
                    else:
                        deck_desc = f"{stair_steps} decks"
                    segments.append({
                        'type': 'stairs',
                        'name': stair_name,
                        'action': f"Take the {stair_name} {direction} {deck_desc} (to Deck {end_deck})",
                        'from_deck': start_deck,
                        'to_deck': end_deck
                    })
            else:
                # Check if this is a multi-deck venue transition
                is_deck_change = False
                if i > 0:
                    prev_venue = self.venues[path[i-1]]
                    if (prev_venue['name'] == venue['name'] and 
                        prev_venue['deck'] != venue['deck'] and
                        venue.get('category') != 'stairs'):
                        # Same venue, different deck - this is a vertical transition
                        direction = "up" if venue['deck'] > prev_venue['deck'] else "down"
                        deck_diff = abs(venue['deck'] - prev_venue['deck'])
                        segments.append({
                            'type': 'internal_stairs',
                            'name': venue['name'],
                            'action': f"Go {direction} inside {venue['name']} to Deck {venue['deck']}",
                            'from_deck': prev_venue['deck'],
                            'to_deck': venue['deck']
                        })
                        is_deck_change = True
                
                if not is_deck_change:
                    # Regular venue
                    segments.append({
                        'type': 'venue',
                        'id': path[i],
                        'name': venue['name'],
                        'deck': venue['deck'],
                        'position': venue.get('position', ''),
                        'side': venue.get('side', '')
                    })
            
            i += 1
        
        return segments
    
    def generate_directions(self, path: List[str]) -> str:
        """Generate human-readable directions from a path."""
        if not path:
            return "No path found."
        
        if len(path) == 1:
            venue = self.venues[path[0]]
            return f"You're already at {venue['name']}!"
        
        segments = self._simplify_path(path)
        
        start = self.venues[path[0]]
        end = self.venues[path[-1]]
        
        lines = []
        lines.append(f"Directions from {start['name']} (Deck {start['deck']}) to {end['name']} (Deck {end['deck']}):")
        lines.append("")
        
        step_num = 1
        prev_segment = None
        prev_deck = None
        
        for i, seg in enumerate(segments):
            if seg['type'] == 'stairs':
                lines.append(f"{step_num}. {seg['action']}")
                step_num += 1
                prev_deck = seg['to_deck']
            elif seg['type'] == 'internal_stairs':
                lines.append(f"{step_num}. {seg['action']}")
                step_num += 1
                prev_deck = seg['to_deck']
            elif seg['type'] == 'venue':
                is_start = (i == 0)
                is_end = (i == len(segments) - 1)
                is_after_stairs = (prev_segment and prev_segment['type'] == 'stairs')
                is_before_stairs = (i + 1 < len(segments) and segments[i + 1]['type'] == 'stairs')
                
                if is_start:
                    lines.append(f"{step_num}. Start at {seg['name']} on Deck {seg['deck']}")
                    step_num += 1
                    prev_deck = seg['deck']
                elif is_end:
                    if is_after_stairs:
                        # Exited stairs onto final deck
                        lines.append(f"{step_num}. Exit the stairs and head to {seg['name']}")
                    else:
                        lines.append(f"{step_num}. Arrive at {seg['name']}")
                    step_num += 1
                elif is_before_stairs:
                    stair_seg = segments[i + 1]
                    lines.append(f"{step_num}. Walk to the {stair_seg['name']} (located {self._describe_location(seg)})")
                    step_num += 1
                elif is_after_stairs:
                    # Just exited stairs, mention where we are
                    lines.append(f"{step_num}. Exit near {seg['name']}")
                    step_num += 1
            
            prev_segment = seg
        
        return "\n".join(lines)
    
    def _describe_location(self, seg: Dict) -> str:
        """Create a brief location description."""
        parts = []
        if seg.get('position'):
            pos_names = {
                'forward': 'toward the front of the ship',
                'mid-forward': 'front-center of the ship',
                'mid': 'mid-ship',
                'mid-aft': 'rear-center of the ship',
                'aft': 'toward the back of the ship'
            }
            parts.append(pos_names.get(seg['position'], seg['position']))
        if seg.get('side') and seg['side'] != 'center':
            side_names = {'port': 'port side (left)', 'starboard': 'starboard side (right)'}
            parts.append(side_names.get(seg['side'], seg['side']))
        return ', '.join(parts) if parts else 'nearby'
    
    def get_directions(self, start: str, end: str) -> str:
        """
        Main entry point: get directions between two locations.
        Accepts natural language location names.
        """
        # Resolve locations
        start_id = self.resolve_location(start)
        if not start_id:
            # Try to find similar locations
            suggestions = self._find_similar(start)
            if suggestions:
                return f"I couldn't find '{start}'. Did you mean: {', '.join(suggestions)}?"
            return f"I couldn't find a location matching '{start}'."
        
        end_id = self.resolve_location(end)
        if not end_id:
            suggestions = self._find_similar(end)
            if suggestions:
                return f"I couldn't find '{end}'. Did you mean: {', '.join(suggestions)}?"
            return f"I couldn't find a location matching '{end}'."
        
        # Find path
        path = self.find_path(start_id, end_id)
        if not path:
            return f"Sorry, I couldn't find a route from {self.venues[start_id]['name']} to {self.venues[end_id]['name']}."
        
        # Generate directions
        return self.generate_directions(path)
    
    def _find_similar(self, query: str, max_results: int = 3) -> List[str]:
        """Find similar location names for suggestions."""
        q = query.lower()
        q_words = set(re.sub(r'[^a-z0-9\s]', '', q).split())
        
        scores = []
        seen_names = set()
        
        for vid, venue in self.venues.items():
            if venue.get('category') == 'stairs':
                continue
            
            name = venue['name']
            if name in seen_names:
                continue
            seen_names.add(name)
            
            name_words = set(re.sub(r'[^a-z0-9\s]', '', name.lower()).split())
            overlap = len(q_words & name_words)
            
            # Check substring match
            if q in name.lower() or name.lower() in q:
                overlap += 2
            
            if overlap > 0:
                scores.append((overlap, f"{name} (Deck {venue['deck']})"))
        
        scores.sort(reverse=True)
        return [s[1] for s in scores[:max_results]]
    
    def list_locations(self, deck: int = None) -> List[str]:
        """List all locations, optionally filtered by deck."""
        locations = []
        for vid, venue in self.venues.items():
            if venue.get('category') == 'stairs':
                continue
            if deck is None or venue['deck'] == deck:
                locations.append(f"{venue['name']} (Deck {venue['deck']})")
        return sorted(set(locations))


# Command-line interface
if __name__ == "__main__":
    import sys
    
    # Default map location
    map_file = Path(__file__).parent / "oasis_ship_map_with_stairs.json"
    if not map_file.exists():
        map_file = Path("/mnt/user-data/uploads/oasis_ship_map_with_stairs.json")
    
    nav = ShipNavigator(str(map_file))
    
    if len(sys.argv) >= 3:
        start = sys.argv[1]
        end = sys.argv[2]
        print(nav.get_directions(start, end))
    else:
        # Interactive mode
        print(f"Ship Navigator - {nav.ship_name}")
        print("Enter 'quit' to exit\n")
        
        while True:
            try:
                start = input("Starting location: ").strip()
                if start.lower() == 'quit':
                    break
                
                end = input("Destination: ").strip()
                if end.lower() == 'quit':
                    break
                
                print()
                print(nav.get_directions(start, end))
                print()
            except (EOFError, KeyboardInterrupt):
                break
