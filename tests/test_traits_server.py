"""
Test script for Traits MCP Server

Tests all three trait management tools:
1. trait_view - View current traits
2. trait_modify - Modify a trait value
3. trait_log - View modification history
"""

import asyncio
import sys
from pathlib import Path
import json

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from mcp_servers.tool_manager import get_tool_manager


async def test_traits_server():
    """Test the traits server tools"""
    
    print("\n" + "="*60)
    print("TESTING TRAITS MCP SERVER")
    print("="*60)
    
    # Initialize tool manager
    tool_manager = get_tool_manager()
    await tool_manager.connect()
    
    print(f"\n✓ Connected to MCP servers")
    print(f"  Loaded {tool_manager.get_tool_count()} tools")
    
    # #########################################################
    # Test 1: View all traits
    print("\n" + "-"*60)
    print("TEST 1: View all traits")
    print("-"*60)
    
    result = await tool_manager.execute_tool("trait_list", {})
    rlist = result["result"]
    if result["success"]:
        for trait_name, trait_info in rlist.items():
            if trait_name == "success":
                continue
            print(trait_name + ":" +  trait_info["value"] + ":" + trait_info["description"])

    #else:
    #    print(f"✗ Error: {result['error']}")
    # ############################################################

    # # Test 2: View specific trait
    # print("\n" + "-"*60)
    # print("TEST 2: View specific trait (Curiosity)")
    # print("-"*60)
    
    # result = await tool_manager.execute_tool("trait_view", {
    #     "trait_name": "Curiosity"
    # })
    # if result["success"]:
    #     trait  = result['result']['trait']
    #     print(f"✓ Trait: {trait['name']}")
    #     print(f"  Value: {trait['value']}")
    #     print(f"  Desc: {trait['description']}")
    # else:
    #     print(f"✗ Error: {result['error']}")
    # #############################################################

     # Test 3: Modify a trait
    print("\n" + "-"*60)
    print("TEST 3: Modify trait (Curiosity: 8 → 9)")
    print("-"*60)
   # {"type":"object","title":"trait_modifyArguments","required":["trait_name","value","reason"],"properties":{"value":{"title":"Value"},"reason":{"type":"string","title":"reason"},"trait_name":{"type":"string","title":"Trait Name"}}}
    result = await tool_manager.execute_tool("trait_modify", {
         "trait_name": "Curiosity",
         "value": "4",
         "reason": "Testing trait modification system - increasing curiosity after successful tool implementation"
    })
    
    if result["success"]:
         result = result["result"]
         print(f"✓ {result['message']}")
         print(f"  Old value: {result['old_value']}")
         print(f"  New value: {result['new_value']}")
         print(f"  Reason: {result['reason']}")
         print(f"  Log ID: {result['log_id']}")
    else:
         print(f"✗ Error: {result['error']}")
    
    # # Test 4: View trait log
    # print("\n" + "-"*60)
    # print("TEST 4: View trait modification log")
    # print("-"*60)
    
    # result = await tool_manager.execute_tool("trait_log", {
    #     "limit": 5
    # })
    
    # if result["success"]:
    #     print(f"✓ Found {result['modification_count']} recent modifications:")
    #     for mod in result["modifications"]:
    #         print(f"\n  [{mod['timestamp']}]")
    #         print(f"  Trait: {mod['trait_name']}")
    #         print(f"  Change: {mod['old_value']} → {mod['new_value']}")
    #         print(f"  Reason: {mod['reason']}")
    # else:
    #     print(f"✗ Error: {result['error']}")
    
    # # Test 5: View log for specific trait
    # print("\n" + "-"*60)
    # print("TEST 5: View log for Curiosity trait")
    # print("-"*60)
    
    # result = await tool_manager.execute_tool("trait_log", {
    #     "trait_name": "Curiosity",
    #     "limit": 3
    # })
    
    # if result["success"]:
    #     print(f"✓ Found {result['modification_count']} modifications for Curiosity:")
    #     for mod in result["modifications"]:
    #         print(f"  {mod['old_value']} → {mod['new_value']} - {mod['reason'][:50]}...")
    # else:
    #     print(f"✗ Error: {result['error']}")
    
    # # Restore original value
    # print("\n" + "-"*60)
    # print("CLEANUP: Restoring Curiosity to original value (8)")
    # print("-"*60)
    
    # result = await tool_manager.execute_tool("trait_modify", {
    #     "trait_name": "Curiosity",
    #     "new_value": "8",
    #     "reason": "Restoring original value after test"
    # })
    
    # if result["success"]:
    #     print(f"✓ Restored to {result['new_value']}")
    
    # Disconnect
    await tool_manager.disconnect()
    print("\n" + "="*60)
    print("TESTS COMPLETE")
    print("="*60 + "\n")


if __name__ == "__main__":
    asyncio.run(test_traits_server())
