#!/usr/bin/env python3
"""
Test Harness for Ship Directions Module
Used to validate the MCP tool implementation matches expected behavior.

Run: python3 test_ship_directions.py
"""

import json
import sys
from pathlib import Path

# Import the module under test
from ship_directions import ShipNavigator


def test_location_resolution():
    """Test that various input formats resolve to correct venue IDs."""
    print("=" * 60)
    print("TEST: Location Resolution")
    print("=" * 60)
    
    test_cases = [
        # (input, expected_venue_id)
        ("deck6-carousel", "deck6-carousel"),
        ("deck16-zip-line", "deck16-zip-line"),
        ("carousel", "deck6-carousel"),
        ("carousel deck 6", "deck6-carousel"),
        ("deck 6 carousel", "deck6-carousel"),
        ("zip line", "deck16-zip-line"),
        ("zip-line", "deck16-zip-line"),
        ("zipline deck 16", "deck16-zip-line"),
        ("windjammer", "deck16-windjammer"),
        ("starbucks", "deck5-starbucks"),
        ("vitality spa", "deck5-vitality-spa"),
        ("main dining room deck 3", "deck3-main-dining-room"),
        ("main dining room deck 5", "deck5-main-dining-room"),
        ("casino royale deck 4", "deck4-casino-royale"),
        ("solarium deck 15", "deck15-solarium"),
        ("coastal kitchen", "deck17-coastal-kitchen"),
        ("aquatheater", "deck6-aquatheater"),
        ("music hall deck 8", "deck8-music-hall"),
        ("music hall deck 9", "deck9-music-hall"),
    ]
    
    nav = ShipNavigator(MAP_FILE)
    passed = 0
    failed = 0
    
    for query, expected in test_cases:
        result = nav.resolve_location(query)
        status = "✓" if result == expected else "✗"
        if result == expected:
            passed += 1
            print(f"  {status} '{query}' -> {result}")
        else:
            failed += 1
            print(f"  {status} '{query}' -> {result} (expected: {expected})")
    
    print(f"\nResults: {passed} passed, {failed} failed")
    return failed == 0


def test_pathfinding():
    """Test that paths are found between various locations."""
    print("\n" + "=" * 60)
    print("TEST: Pathfinding")
    print("=" * 60)
    
    test_cases = [
        # (start, end, expected_min_steps, expected_max_steps)
        ("deck6-carousel", "deck16-zip-line", 3, 10),
        ("deck3-main-dining-room", "deck5-vitality-spa", 3, 8),
        ("deck5-starbucks", "deck5-boleros", 1, 3),
        ("deck17-coastal-kitchen", "deck4-casino-royale", 5, 20),
        ("deck8-music-hall", "deck9-music-hall", 1, 3),
        ("deck15-solarium", "deck16-windjammer", 3, 15),
    ]
    
    nav = ShipNavigator(MAP_FILE)
    passed = 0
    failed = 0
    
    for start, end, min_steps, max_steps in test_cases:
        path = nav.find_path(start, end)
        if path is None:
            print(f"  ✗ {start} -> {end}: No path found!")
            failed += 1
        elif min_steps <= len(path) <= max_steps:
            print(f"  ✓ {start} -> {end}: {len(path)} steps")
            passed += 1
        else:
            print(f"  ✗ {start} -> {end}: {len(path)} steps (expected {min_steps}-{max_steps})")
            failed += 1
    
    print(f"\nResults: {passed} passed, {failed} failed")
    return failed == 0


def test_directions_output():
    """Test that directions are generated correctly."""
    print("\n" + "=" * 60)
    print("TEST: Directions Output")
    print("=" * 60)
    
    nav = ShipNavigator(MAP_FILE)
    
    test_cases = [
        {
            "start": "carousel",
            "end": "zip line",
            "must_contain": [
                "Carousel",
                "Zip-Line",
                "Deck 6",
                "Deck 16",
                "Staircase",
            ],
            "must_not_contain": [
                "couldn't find",
                "No path",
            ]
        },
        {
            "start": "main dining room deck 3",
            "end": "vitality spa",
            "must_contain": [
                "Main Dining Room",
                "Vitality Spa",
                "Deck 3",
                "Deck 5",
            ],
            "must_not_contain": [
                "couldn't find",
                "No path",
            ]
        },
        {
            "start": "windjammer",
            "end": "starbucks",
            "must_contain": [
                "Windjammer",
                "Starbucks",
                "Staircase",
                "down",
            ],
            "must_not_contain": [
                "couldn't find",
            ]
        },
        {
            "start": "xyznonexistent",
            "end": "starbucks",
            "must_contain": [
                "couldn't find",
            ],
            "must_not_contain": []
        },
    ]
    
    passed = 0
    failed = 0
    
    for tc in test_cases:
        directions = nav.get_directions(tc["start"], tc["end"])
        
        missing = [s for s in tc["must_contain"] if s not in directions]
        forbidden = [s for s in tc["must_not_contain"] if s in directions]
        
        if not missing and not forbidden:
            print(f"  ✓ '{tc['start']}' -> '{tc['end']}'")
            passed += 1
        else:
            print(f"  ✗ '{tc['start']}' -> '{tc['end']}'")
            if missing:
                print(f"      Missing: {missing}")
            if forbidden:
                print(f"      Forbidden: {forbidden}")
            failed += 1
    
    print(f"\nResults: {passed} passed, {failed} failed")
    return failed == 0


def test_staircase_logic():
    """Test that staircases connect correct decks only."""
    print("\n" + "=" * 60)
    print("TEST: Staircase Logic")
    print("=" * 60)
    
    nav = ShipNavigator(MAP_FILE)
    
    # Verify staircase deck coverage from the map
    staircase_coverage = {}
    for vid, venue in nav.venues.items():
        if venue.get('category') == 'stairs':
            stair_id = venue.get('staircase_id')
            if stair_id not in staircase_coverage:
                staircase_coverage[stair_id] = set()
            staircase_coverage[stair_id].add(venue['deck'])
    
    expected_coverage = {
        1: {3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 14, 15},  # Forward
        2: {4, 5, 6, 7, 8},  # Royal Promenade Port
        3: {4, 5, 6, 7, 8},  # Royal Promenade Starboard
        4: {5, 6, 7, 8, 9, 10, 11, 12, 14, 15, 16},  # Central Park
        5: {5, 6, 7, 8, 9, 10, 11, 12, 14, 15, 16},  # Boardwalk
        6: {3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 14, 15, 16, 17},  # Aft Port
        7: {3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 14, 15, 16, 17},  # Aft Starboard
        8: {5, 6, 7, 8, 15, 16},  # Stern
    }
    
    passed = 0
    failed = 0
    
    for stair_id, expected_decks in expected_coverage.items():
        actual_decks = staircase_coverage.get(stair_id, set())
        if actual_decks == expected_decks:
            print(f"  ✓ Staircase {stair_id}: {sorted(actual_decks)}")
            passed += 1
        else:
            print(f"  ✗ Staircase {stair_id}: {sorted(actual_decks)}")
            print(f"      Expected: {sorted(expected_decks)}")
            missing = expected_decks - actual_decks
            extra = actual_decks - expected_decks
            if missing:
                print(f"      Missing decks: {sorted(missing)}")
            if extra:
                print(f"      Extra decks: {sorted(extra)}")
            failed += 1
    
    print(f"\nResults: {passed} passed, {failed} failed")
    return failed == 0


def test_edge_cases():
    """Test edge cases and error handling."""
    print("\n" + "=" * 60)
    print("TEST: Edge Cases")
    print("=" * 60)
    
    nav = ShipNavigator(MAP_FILE)
    passed = 0
    failed = 0
    
    # Same start and end
    result = nav.get_directions("starbucks", "starbucks")
    if "already at" in result.lower():
        print("  ✓ Same start/end returns 'already at' message")
        passed += 1
    else:
        print(f"  ✗ Same start/end: {result}")
        failed += 1
    
    # Invalid start - truly nonexistent
    result = nav.get_directions("xyznonexistent123", "starbucks")
    if "couldn't find" in result.lower():
        print("  ✓ Invalid start returns error message")
        passed += 1
    else:
        print(f"  ✗ Invalid start: {result}")
        failed += 1
    
    # Invalid end - truly nonexistent
    result = nav.get_directions("starbucks", "xyznonexistent123")
    if "couldn't find" in result.lower():
        print("  ✓ Invalid end returns error message")
        passed += 1
    else:
        print(f"  ✗ Invalid end: {result}")
        failed += 1
    
    # Empty strings
    result = nav.get_directions("", "starbucks")
    if "couldn't find" in result.lower():
        print("  ✓ Empty start returns error message")
        passed += 1
    else:
        print(f"  ✗ Empty start: {result}")
        failed += 1
    
    # Ambiguous location (multiple matches) - should still work or give clear error
    result = nav.get_directions("main dining room", "starbucks")
    if "Main Dining Room" in result or "couldn't find" in result.lower():
        print("  ✓ Ambiguous location handled")
        passed += 1
    else:
        print(f"  ✗ Ambiguous location: {result}")
        failed += 1
    
    print(f"\nResults: {passed} passed, {failed} failed")
    return failed == 0


def test_mcp_interface_simulation():
    """
    Simulate the MCP tool interface.
    This is what the MCP tool should accept and return.
    """
    print("\n" + "=" * 60)
    print("TEST: MCP Interface Simulation")
    print("=" * 60)
    
    nav = ShipNavigator(MAP_FILE)
    
    # Simulate MCP tool calls
    test_calls = [
        {"start": "deck6-carousel", "end": "deck16-zip-line"},
        {"start": "carousel deck 6", "end": "zip line deck 16"},
        {"start": "windjammer", "end": "starbucks"},
        {"start": "coastal kitchen", "end": "casino royale deck 4"},
        {"start": "xyzinvalid123", "end": "starbucks"},
    ]
    
    print("\nMCP Tool: get_ship_directions")
    print("-" * 40)
    
    for call in test_calls:
        print(f"\n>>> get_ship_directions(start=\"{call['start']}\", end=\"{call['end']}\")")
        result = nav.get_directions(call['start'], call['end'])
        print(result)
    
    return True


def run_all_tests():
    """Run all tests and report summary."""
    print("\n" + "#" * 60)
    print("# SHIP DIRECTIONS TEST HARNESS")
    print("#" * 60)
    
    results = []
    
    results.append(("Location Resolution", test_location_resolution()))
    results.append(("Pathfinding", test_pathfinding()))
    results.append(("Directions Output", test_directions_output()))
    results.append(("Staircase Logic", test_staircase_logic()))
    results.append(("Edge Cases", test_edge_cases()))
    results.append(("MCP Interface", test_mcp_interface_simulation()))
    
    print("\n" + "#" * 60)
    print("# SUMMARY")
    print("#" * 60)
    
    all_passed = True
    for name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {status}: {name}")
        if not passed:
            all_passed = False
    
    print()
    if all_passed:
        print("All tests passed! ✓")
        return 0
    else:
        print("Some tests failed! ✗")
        return 1


# Find map file
MAP_FILE = None
for path in [
    Path(__file__).parent / "oasis_ship_map_with_stairs.json",
    Path("/mnt/user-data/uploads/oasis_ship_map_with_stairs.json"),
    Path("/mnt/user-data/outputs/oasis_ship_map_with_stairs.json"),
    Path("oasis_ship_map_with_stairs.json"),
]:
    if path.exists():
        MAP_FILE = str(path)
        break

if MAP_FILE is None:
    print("ERROR: Could not find oasis_ship_map_with_stairs.json")
    sys.exit(1)


if __name__ == "__main__":
    sys.exit(run_all_tests())
