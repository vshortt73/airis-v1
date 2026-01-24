"""
Simple test for weather_get tool via MCP

Tests ONLY the weather tool to validate the MCP Phase 2 foundation.
"""

import asyncio
import sys
from pathlib import Path

# Add project root
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

async def test_weather():
    """Test weather_get tool through MCP infrastructure"""
    
    print("="*60)
    print("WEATHER TOOL TEST")
    print("="*60)
    
    # Step 1: Load tool definitions from database
    print("\n[1/4] Loading tools from database...")
    from mcp_servers.tool_loader import load_enabled_tools
    
    tools = load_enabled_tools()
    weather_tool = next((t for t in tools if t["function"]["name"] == "weather_get"), None)
    
    if weather_tool:
        print(f"✓ Found weather_get tool")
        print(f"  Description: {weather_tool['function']['description'][:80]}...")
    else:
        print("✗ weather_get not found in database!")
        return
    
    # Step 2: Initialize MCP client
    print("\n[2/4] Initializing MCP client...")
    from mcp_servers.mcp_client import MCPClient
    from mcp_servers.server_configs import get_server_configs
    
    # Get only info server config
    all_configs = get_server_configs()
    info_config = [c for c in all_configs if c["name"] == "info"]
    
    client = MCPClient(info_config)
    print("✓ MCP client initialized")
    
    # Step 3: Connect to info server
    print("\n[3/4] Connecting to info server...")
    success = await client.connect_all()
    
    if success:
        print("✓ Connected to info server")
    else:
        print("✗ Failed to connect")
        return
    
    # Step 4: Call weather tool
    print("\n[4/4] Calling weather_get tool...")
    print("  Location: Seattle")
    print("  Units: imperial")
    
    result = await client.call_tool("weather_get", {
        "location": "Seattle",
        "units": "imperial"
    })
    
    print(f"\nResult:")
    if result.get("success"):
        print(f"✓ SUCCESS")
        print(f"  Temperature: {result.get('temperature')}°F")
        print(f"  Feels like: {result.get('feels_like_f')}°F")
        print(f"  Condition: {result.get('condition')}")
        print(f"  Location: {result.get('nearest')}")
        print(f"  Humidity: {result.get('humidity')}%")
        print(f"  Wind: {result.get('wind_speed_mph')} mph {result.get('wind_direction')}")
    else:
        print(f"✗ FAILED")
        print(f"  Error: {result.get('error')}")
    
    # Cleanup
    print("\nDisconnecting...")
    await client.disconnect_all()
    
    print("\n" + "="*60)
    print("TEST COMPLETE")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(test_weather())
