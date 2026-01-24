"""
Test script for web surfing 


"""

import asyncio
import sys
from pathlib import Path
import json

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from mcp_servers.tool_manager import get_tool_manager


async def test_web_surfer():
    """Test the traits server tools"""
    
    print("\n" + "="*60)
    print("TESTING WEB MCP MCP SERVER")
    print("="*60)
    
    # Initialize tool manager
    tool_manager = get_tool_manager()
    await tool_manager.connect()
    
    print(f"\n✓ Connected to MCP servers")
    print(f"  Loaded {tool_manager.get_tool_count()} tools")
    
    # #########################################################
    # Test 1: View all traits
    print("\n" + "-"*60)
    print("TEST 1: web fetch VER2")
    print("-"*60)
    
    #[{"id":"call_qtcqj2fr","function":{"name":"web_fetch","index":0,"arguments":{"url":"https://www.google.com/search?q=U.S.+invasion+Venezuela+2025+official+statements","max_length":10000}}}]

    data = await tool_manager.execute_tool("web_fetch", {"search_term":"official US statements regarding the capture of Maduro","max_length":10000})
    print(data)

        

    #rlist = result["result"]
    #if result["success"]:
    #    for trait_name, trait_info in rlist.items():
    #        if trait_name == "success":
    #            continue
    #        print(trait_name + ":" +  trait_info["value"] + ":" + trait_info["description"])

    #else:
    #    print(f"✗ Error: {result['error']}")
    # ############################################################
if __name__ == "__main__":
    asyncio.run(test_web_surfer())
