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
        print(f"[ship] Loaded map: {navigator.ship_name}", file=sys.stderr)
    return navigator


def _handle_directions(start: str, end: str) -> dict:
    """Get directions between two locations"""
    try:
        nav = get_navigator()
        print(f"[ship][directions] From: '{start}' To: '{end}'", file=sys.stderr)

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

        print(f"[ship][directions] ✓ Found route: {result['steps']} steps", file=sys.stderr)
        return result

    except Exception as e:
        print(f"[ship][directions] ✗ Error: {e}", file=sys.stderr)
        return {"success": False, "error": str(e)}


def _handle_locations(deck: Optional[int] = None) -> dict:
    """List available locations"""
    try:
        nav = get_navigator()
        print(f"[ship][locations] Deck filter: {deck}", file=sys.stderr)

        locations = nav.list_locations(deck=deck)

        result = {
            "success": True,
            "ship_name": nav.ship_name,
            "deck_filter": deck,
            "locations": locations,
            "count": len(locations)
        }

        print(f"[ship][locations] ✓ Found {result['count']} locations", file=sys.stderr)
        return result

    except Exception as e:
        print(f"[ship][locations] ✗ Error: {e}", file=sys.stderr)
        return {"success": False, "error": str(e)}


@server.register_tool
def ship_directions(
    start: str,
    end: str
) -> dict:
    """
    Get walking directions between two locations on the ship.

    Args:
        start: Starting location name (e.g. "Schooner Bar")
        end: Destination location name (e.g. "Windjammer Marketplace")

    Returns:
        dict with route directions, deck info, and step count
    """
    print(f"[ship] directions: {start} -> {end}", file=sys.stderr)
    if not start or not end:
        missing = []
        if not start:
            missing.append("start")
        if not end:
            missing.append("end")
        return {"success": False, "error": f"Missing: {', '.join(missing)}"}
    return _handle_directions(start, end)


@server.register_tool
def ship_locations(
    deck: int = None
) -> dict:
    """
    List locations on the ship, optionally filtered by deck number.

    Args:
        deck: Deck number to filter by (optional, omit for all decks)

    Returns:
        dict with ship name and list of locations
    """
    print(f"[ship] locations: deck={deck}", file=sys.stderr)
    return _handle_locations(deck)


# Keep unified entry point for backwards compatibility (not exposed to model)
def ship(action: str, start: str = None, end: str = None, deck: int = None) -> dict:
    """Legacy unified entry point — kept for any direct Python callers."""
    action = action.lower().strip()
    if action == "directions":
        return ship_directions(start=start, end=end)
    elif action in ("locations", "list"):
        return ship_locations(deck=deck)
    else:
        return {"success": False, "error": f"Unknown action: {action}"}


if __name__ == "__main__":
    print("=" * 60, file=sys.stderr)
    print("IRIS DIRECTIONS SERVER (Unified)", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    try:
        nav = get_navigator()
        print(f"Ship: {nav.ship_name}", file=sys.stderr)
        print(f"Venues: {len(nav.venues)}", file=sys.stderr)
    except Exception as e:
        print(f"WARNING: Could not load ship map: {e}", file=sys.stderr)

    print("\nTools: ship_directions(start, end), ship_locations(deck?)", file=sys.stderr)
    print("Starting server...", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    server.run()
