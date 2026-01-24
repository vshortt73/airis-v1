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
    """Test SQL tool through MCP infrastructure"""
    # {"type":"object","title":"database_queryArguments","required":["query"],"properties":{"query":{"type":"string","title":"query"}}}
    print("="*60)
    print("SQL TOOL TEST")
    print("="*60)
    
    # Step 1: Load tool definitions from database
    print("\n[1/4] Loading tools from database...")
    from mcp_servers.tool_loader import load_enabled_tools
    
    tools = load_enabled_tools()
    database_query = next((t for t in tools if t["function"]["name"] == "database_query"), None)
    
    if database_query:
        print(f"✓ Found database_query tool")
        print(f"  Description: {database_query['function']['description'][:80]}...")
    else:
        print("✗ database_query not found in database!")
        return
    
    # Step 2: Initialize MCP client
    print("\n[2/4] Initializing MCP client...")
    from mcp_servers.mcp_client import MCPClient
    from mcp_servers.server_configs import get_server_configs
    
    # Get only info server config
    all_configs = get_server_configs()
    info_config = [c for c in all_configs if c["name"] == "system"]
    
    client = MCPClient(info_config)
    print("✓ MCP client initialized")
    
    # Step 3: Connect to info server
    print("\n[3/4] Connecting to info server...")
    success = await client.connect_all()
    
    if success:
        print("✓ Connected to system server")
    else:
        print("✗ Failed to connect")
        return
    
    # Step 4: Call sql_query tool
    print("\n[4/4] Calling database_query tool...")
    print("  query: select id from episodic_memories limit 1")

    
    result = await client.call_tool("database_query", {
        "query": "SELECT id, name, memory_gb, compute_power_tflops FROM gpu WHERE id = 1",
    })
    
    print(f"\nResult:")
    if result.get("success"):
        print(f"✓ SUCCESS")
        print(f"   {result}")

    else:
        print(f"✗ FAILED")
        print(f"  Error: {result.get('error')}")
        print(f"FULL:{str(result)}")
    
    # Cleanup
    print("\nDisconnecting...")
    await client.disconnect_all()
    
    print("\n" + "="*60)
    print("TEST COMPLETE")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(test_weather())
