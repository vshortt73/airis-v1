"""
Simple test for document_search tool via MCP

Tests ONLY the document_search
"""

import asyncio
import sys
from pathlib import Path

# Add project root
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

async def test_doc_search():
    """Test document_search tool through MCP infrastructure"""
    
    print("="*60)
    print("DOCUMENT_SEARCH  TEST")
    print("="*60)
    
    # Step 1: Load tool definitions from database
    print("\n[1/4] Loading tools from database...")
    from mcp_servers.tool_loader import load_enabled_tools
    
    tools = load_enabled_tools()

    doc_tool = next((t for t in tools if t["function"]["name"] == "document_search"), None)
    
    if doc_tool:
        print(f"✓ Found found document_search tool")
        print(f"  Description: {doc_tool['function']['description'][:80]}...")
    else:
        print("✗ document_search not found in database!")
        return
    
    # Step 2: Initialize MCP client
    print("\n[2/4] Initializing MCP client...")
    from mcp_servers.mcp_client import MCPClient
    from mcp_servers.server_configs import get_server_configs
    
    # Get only knowledge server config
    all_configs = get_server_configs()
    info_config = [c for c in all_configs if c["name"] == "knowledge"]
    
    client = MCPClient(info_config)
    print("✓ MCP client initialized")
    
    # Step 3: Connect to info server
    print("\n[3/4] Connecting to knowledge server...")
    success = await client.connect_all()
    
    if success:
        print("✓ Connected to knowledge server")
    else:
        print("✗ Failed to connect")
        return
    
    # Step 4: Call weather tool
    print("\n[4/4] Calling document_search tool...")
    print("  Location: Seattle")
    print("  Units: imperial")
    
    result = await client.call_tool("document_search", {
        "query": "Adding new MCP tools"
   
    })
    
    print(f"\nResult:")
    if result.get("success"):
        print(result)
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
    asyncio.run(test_doc_search())
