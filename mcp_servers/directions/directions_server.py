"""
Iris Directions Server - Unified MCP Server for Ship Navigation
Provides directions and location listing for cruise ship navigation
"""

import sys
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DIRECTIONS_DIR = Path(__file__).parent
sys.path.insert(0, str(DIRECTIONS_DIR))

from mcp_servers.base.base_server import IrisMCPServer
from ship_directions import ShipNavigator

server = IrisMCPServer(
    name="Iris Directions Server",
    description="Unified ship navigation: directions and locations"
)

MAP_FILE = DIRECTIONS_DIR / "oasis_ship_map_with_stairs.json"
navigator = None


def get_navigator() -> ShipNavigator:
    """Get or initialize the ship navigator."""
    global navigator
    if navigator is None:
        if not MAP_FILE.exists():
            raise FileNotFoundError(f"Ship map not found: {MAP_FILE}")
        navigator = ShipNavigator(str(MAP_FILE))
        print(f"[ship] Loaded map: {navigator.ship_name}")
    return navigator


def _handle_directions(start: str, end: str) -> dict:
    """Get directions between two locations"""
    try:
        nav = get_navigator()
        print(f"[ship][directions] From: '{start}' To: '{end}'")

        start_id = nav.resolve_location(start)
        end_id = nav.resolve_location(end)
        directions = nav.get_directions(start, end)

        if "couldn't find" in directions.lower() or "sorry" in directions.lower():
            return {
                "success": False,
                "error": directions,
                "start_input": start,
                "end_input": end
            }

        path = nav.find_path(start_id, end_id) if start_id and end_id else None

        result = {
            "success": True,
            "directions": directions,
            "start_resolved": nav.venues[start_id]['name'] if start_id else None,
            "end_resolved": nav.venues[end_id]['name'] if end_id else None,
            "start_deck": nav.venues[start_id]['deck'] if start_id else None,
            "end_deck": nav.venues[end_id]['deck'] if end_id else None,
            "steps": len(path) if path else 0
        }

        print(f"[ship][directions] ✓ Found route: {result['steps']} steps")
        return result

    except Exception as e:
        print(f"[ship][directions] ✗ Error: {e}")
        return {"success": False, "error": str(e)}


def _handle_locations(deck: Optional[int] = None) -> dict:
    """List available locations"""
    try:
        nav = get_navigator()
        print(f"[ship][locations] Deck filter: {deck}")

        locations = nav.list_locations(deck=deck)

        result = {
            "success": True,
            "ship_name": nav.ship_name,
            "deck_filter": deck,
            "locations": locations,
            "count": len(locations)
        }

        print(f"[ship][locations] ✓ Found {result['count']} locations")
        return result

    except Exception as e:
        print(f"[ship][locations] ✗ Error: {e}")
        return {"success": False, "error": str(e)}


@server.register_tool
def ship(
    action: str,
    start: str = None,
    end: str = None,
    deck: int = None
) -> dict:
    """
    Unified ship navigation tool.

    Actions:
        - "directions": Get walking directions between two locations
        - "locations": List available locations (optionally by deck)

    Args:
        action: "directions" or "locations"
        start: Starting location (required for directions)
        end: Destination location (required for directions)
        deck: Filter locations by deck number (optional, for locations)

    Returns:
        dict with action-specific navigation data

    Examples:
        ship(action="directions", start="carousel", end="zip line")
        ship(action="locations")
        ship(action="locations", deck=6)
    """
    action = action.lower().strip()
    print(f"[ship] Action: {action}")

    if action == "directions":
        if not start or not end:
            return {
                "success": False,
                "error": "start and end parameters required for directions"
            }
        return _handle_directions(start, end)

    elif action in ("locations", "list"):
        return _handle_locations(deck)

    else:
        return {
            "success": False,
            "error": f"Unknown action: {action}",
            "valid_actions": ["directions", "locations"]
        }


if __name__ == "__main__":
    print("=" * 60)
    print("IRIS DIRECTIONS SERVER (Unified)")
    print("=" * 60)

    try:
        nav = get_navigator()
        print(f"Ship: {nav.ship_name}")
        print(f"Venues: {len(nav.venues)}")
    except Exception as e:
        print(f"WARNING: Could not load ship map: {e}")

    print("\nTool: ship(action, start?, end?, deck?)")
    print("Actions: directions, locations")
    print("Starting server...")
    print("=" * 60)
    server.run()
