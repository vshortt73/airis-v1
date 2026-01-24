#!/usr/bin/env python3
"""
Add staircases to the Oasis of the Seas ship map.
Each staircase is a unique vertical connector with specific deck coverage.
"""

import json
from copy import deepcopy

# Load existing map
with open('/mnt/user-data/uploads/oasis_ship_map_complete.json', 'r') as f:
    ship_map = json.load(f)

# Define staircases with their positions and deck ranges
# Format: (staircase_id, name, position, side, decks_served)
STAIRCASES = [
    (1, "Forward Staircase", "forward", "center", [3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 14, 15]),
    (2, "Royal Promenade Staircase Port", "mid-forward", "port", [4, 5, 6, 7, 8]),
    (3, "Royal Promenade Staircase Starboard", "mid-forward", "starboard", [4, 5, 6, 7, 8]),
    (4, "Central Park Staircase Port", "mid", "port", [5, 6, 7, 8, 9, 10, 11, 12, 14, 15, 16]),
    (5, "Boardwalk Staircase Starboard", "mid", "starboard", [5, 6, 7, 8, 9, 10, 11, 12, 14, 15, 16]),
    (6, "Aft Staircase Port", "mid-aft", "port", [3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 14, 15, 16, 17]),
    (7, "Aft Staircase Starboard", "mid-aft", "starboard", [3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 14, 15, 16, 17]),
    (8, "Stern Staircase", "aft", "center", [5, 6, 7, 8, 15, 16]),
]

# Create staircase venue entries
staircase_venues = []
for stair_id, name, position, side, decks in STAIRCASES:
    for i, deck in enumerate(decks):
        venue_id = f"deck{deck}-staircase{stair_id}"
        
        # Build vertical connections (up/down within same staircase)
        vertical = []
        if i > 0:  # Has deck below
            vertical.append(f"deck{decks[i-1]}-staircase{stair_id}")
        if i < len(decks) - 1:  # Has deck above
            vertical.append(f"deck{decks[i+1]}-staircase{stair_id}")
        
        venue = {
            "id": venue_id,
            "name": name,
            "deck": deck,
            "position": position,
            "side": side,
            "category": "stairs",
            "staircase_id": stair_id,
            "neighbors": {}
        }
        
        if vertical:
            venue["neighbors"]["vertical"] = vertical
            
        staircase_venues.append(venue)

print(f"Created {len(staircase_venues)} staircase entries")

# Now we need to connect staircases to nearby venues
# Build a lookup of venues by deck and position
venues_by_deck = {}
for v in ship_map['venues']:
    deck = v['deck']
    if deck not in venues_by_deck:
        venues_by_deck[deck] = []
    venues_by_deck[deck].append(v)

# Add staircase venues to the map
ship_map['venues'].extend(staircase_venues)

# Build index for quick lookup
venue_index = {v['id']: v for v in ship_map['venues']}

# Define which venues should connect to which staircases based on position
# Format: venue_id -> [(staircase_id, direction_from_venue)]
VENUE_STAIRCASE_CONNECTIONS = {
    # Deck 3
    "deck3-royal-theater": [(1, "north")],  # Forward staircase is north of theater
    "deck3-conference-center": [(6, "west"), (7, "east")],  # Mid staircases
    "deck3-main-dining-room": [(6, "west"), (7, "east")],  # Aft staircases flank MDR
    
    # Deck 4
    "deck4-royal-theater": [(1, "north")],
    "deck4-entertainment-place": [(2, "west"), (3, "east")],
    "deck4-blaze": [(2, "north")],
    "deck4-comedy": [(2, "south")],
    "deck4-casino-royale-non-smoking": [(3, "north")],
    "deck4-crown-lounge": [(3, "south")],
    "deck4-studio-b": [(2, "east"), (3, "west")],
    "deck4-center-ice-rink": [(4, "west"), (5, "east")],
    "deck4-casino-royale": [(6, "west"), (7, "east")],
    "deck4-izumi": [(6, "south")],
    "deck4-main-dining-room": [(6, "west"), (7, "east")],
    
    # Deck 5
    "deck5-vitality-spa": [(1, "south")],  
    "deck5-royal-theater": [(1, "north")],
    "deck5-starbucks": [(2, "west"), (3, "east")],
    "deck5-spotlight-karaoke": [(2, "west")],
    "deck5-boleros": [(3, "east")],
    "deck5-solera": [(2, "south")],
    "deck5-port-merchants": [(4, "west")],
    "deck5-the-shop": [(3, "south")],
    "deck5-sorrentos": [(5, "east")],
    "deck5-globe-and-atlas-pub": [(4, "west")],
    "deck5-island-market": [(4, "west"), (5, "east")],
    "deck5-cafe-promenade": [(4, "west")],
    "deck5-the-collection": [(5, "east")],
    "deck5-royal-promenade": [(4, "west"), (5, "east")],
    "deck5-rising-tide-bar": [(4, "west"), (5, "east")],
    "deck5-guest-services": [(4, "south"), (5, "south")],
    "deck5-regalia-fine-watches": [(6, "west")],
    "deck5-bionic-bar": [(7, "east")],
    "deck5-main-dining-room": [(6, "west"), (7, "east"), (8, "south")],
    "deck5-running-track": [(8, "north")],
    
    # Deck 6
    "deck6-vitality-fitness-center": [(1, "south")],
    "deck6-schooner-bar": [(4, "west")],
    "deck6-picture-this": [(5, "east")],
    "deck6-focus": [(5, "east")],
    "deck6-shore-excursions": [(5, "east")],
    "deck6-next-cruise": [(6, "west")],
    "deck6-playmakers": [(6, "south")],
    "deck6-carousel": [(6, "east"), (7, "west")],
    "deck6-johnny-rockets": [(7, "east")],
    "deck6-boardwalk-dog-house": [(7, "south")],
    "deck6-sugar-beach": [(7, "south")],
    "deck6-aquatheater": [(8, "north")],
    "deck6-ultimate-abyss-landing": [(8, "north")],
    
    # Deck 7
    "deck7-rock-climbing-wall": [(6, "west"), (7, "east"), (8, "north")],
    
    # Deck 8
    "deck8-trend": [(2, "west"), (3, "east")],
    "deck8-tiffany": [(2, "south")],
    "deck8-john-hardy": [(2, "south")],
    "deck8-vintages": [(3, "south")],
    "deck8-central-park": [(4, "west"), (5, "east")],
    "deck8-trellis-bar": [(4, "east"), (5, "west")],
    "deck8-rising-tide-bar": [(4, "east"), (5, "west")],
    "deck8-central-park-library": [(4, "south")],
    "deck8-park-cafe": [(4, "south")],
    "deck8-giovannis-table": [(5, "east")],
    "deck8-150-central-park": [(5, "east")],
    "deck8-chops-grille": [(6, "west")],
    "deck8-music-hall": [(6, "east"), (7, "west")],
    
    # Deck 9
    "deck9-music-hall": [(6, "east"), (7, "west")],
    
    # Deck 11
    "deck11-card-room": [(6, "east"), (7, "west")],
    
    # Deck 12
    "deck12-card-room": [(6, "east"), (7, "west")],
    
    # Deck 14
    "deck14-adventure-ocean": [(1, "south")],
    "deck14-nursery": [(1, "south")],
    "deck14-royal-escape-room": [(6, "east"), (7, "west")],
    
    # Deck 15
    "deck15-solarium": [(1, "south")],
    "deck15-solarium-bistro": [(1, "south")],
    "deck15-whirlpool-forward": [(1, "north")],
    "deck15-the-perfect-storm": [(4, "east"), (5, "west")],
    "deck15-main-pool": [(4, "east")],
    "deck15-lime-and-coconut": [(4, "east"), (5, "west")],
    "deck15-beach-pool": [(5, "west")],
    "deck15-splashaway-bay": [(5, "east")],
    "deck15-sports-pool": [(6, "west")],
    "deck15-padi": [(6, "west")],
    "deck15-portside-bbq": [(6, "north")],
    "deck15-teen": [(6, "east"), (7, "west")],
    "deck15-challengers-arcade": [(7, "north")],
    "deck15-el-loco-fresh": [(8, "east")],
    "deck15-oasis-dunes": [(8, "west")],
    "deck15-sports-court": [(8, "north")],
    
    # Deck 16
    "deck16-solarium-bar": [(4, "south"), (5, "south")],
    "deck16-lime-and-coconut": [(4, "east"), (5, "west")],
    "deck16-whirlpool-port": [(4, "east")],
    "deck16-whirlpool-starboard": [(5, "west")],
    "deck16-windjammer": [(6, "north"), (7, "north")],
    "deck16-zip-line": [(6, "south"), (7, "south")],
    "deck16-flowrider-port": [(6, "south")],
    "deck16-flowrider-starboard": [(7, "south")],
    "deck16-wipeout-bar": [(8, "north")],
    "deck16-ultimate-abyss-slide": [(8, "south")],
    
    # Deck 17
    "deck17-suite-sun-deck": [(6, "south"), (7, "south")],
    "deck17-bar": [(6, "north")],
    "deck17-lounge": [(7, "north")],
    "deck17-suite-lounge": [(6, "east")],
    "deck17-coastal-kitchen": [(7, "west")],
}

# Apply connections
connections_made = 0
for venue_id, stair_connections in VENUE_STAIRCASE_CONNECTIONS.items():
    if venue_id not in venue_index:
        print(f"WARNING: Venue {venue_id} not found in map")
        continue
    
    venue = venue_index[venue_id]
    deck = venue['deck']
    
    for stair_id, direction in stair_connections:
        stair_venue_id = f"deck{deck}-staircase{stair_id}"
        
        if stair_venue_id not in venue_index:
            print(f"WARNING: Staircase {stair_venue_id} not found")
            continue
        
        stair_venue = venue_index[stair_venue_id]
        
        # Add staircase as neighbor of venue
        if direction not in venue['neighbors']:
            venue['neighbors'][direction] = stair_venue_id
            connections_made += 1
        
        # Add venue as neighbor of staircase (opposite direction)
        opposite = {"north": "south", "south": "north", "east": "west", "west": "east"}
        opp_dir = opposite[direction]
        if opp_dir not in stair_venue['neighbors']:
            stair_venue['neighbors'][opp_dir] = venue_id
            connections_made += 1

print(f"Made {connections_made} horizontal connections between venues and staircases")

# Update deck list to reflect staircase coverage
all_decks = set(ship_map['decks'])
for s in STAIRCASES:
    all_decks.update(s[4])
ship_map['decks'] = sorted(list(all_decks))

# Add staircase metadata
ship_map['staircases'] = []
for stair_id, name, position, side, decks in STAIRCASES:
    ship_map['staircases'].append({
        "id": stair_id,
        "name": name,
        "position": position,
        "side": side,
        "decks": decks
    })

# Validate all neighbor references
print("\nValidating neighbor references...")
all_ids = {v['id'] for v in ship_map['venues']}
errors = []
for v in ship_map['venues']:
    neighbors = v.get('neighbors', {})
    for direction, target in neighbors.items():
        if direction == 'vertical':
            for t in target:
                if t not in all_ids:
                    errors.append(f"{v['id']}: vertical neighbor '{t}' not found")
        elif target and target not in all_ids:
            errors.append(f"{v['id']}: {direction} neighbor '{target}' not found")

if errors:
    print("ERRORS:")
    for e in errors[:20]:
        print(f"  {e}")
    if len(errors) > 20:
        print(f"  ... and {len(errors) - 20} more errors")
else:
    print("✓ All neighbor references valid")

# Count totals
total_venues = len(ship_map['venues'])
staircase_count = len([v for v in ship_map['venues'] if v.get('category') == 'stairs'])
other_venues = total_venues - staircase_count

total_neighbors = 0
for v in ship_map['venues']:
    n = v.get('neighbors', {})
    for dir, target in n.items():
        if dir == 'vertical':
            total_neighbors += len(target)
        elif target:
            total_neighbors += 1

print(f"\nFinal stats:")
print(f"  Total venues: {total_venues}")
print(f"  - Regular venues: {other_venues}")
print(f"  - Staircase entries: {staircase_count}")
print(f"  Total neighbor relationships: {total_neighbors}")
print(f"  Staircases defined: {len(STAIRCASES)}")

# Save updated map
output_path = '/home/claude/oasis_ship_map_with_stairs.json'
with open(output_path, 'w') as f:
    json.dump(ship_map, f, indent=2)
print(f"\nSaved to {output_path}")
