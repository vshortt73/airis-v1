"""
Test Ollama tool calling with weather tool

This verifies that:
1. Tools can be loaded from database
2. Ollama receives tool definitions
3. Ollama decides to call the tool
4. Tool executes via MCP
5. Results go back to Ollama for final response
"""

import asyncio
import sys
from pathlib import Path

# Add project root
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


async def test_ollama_tool_calling():
    """Test the complete tool calling flow"""
    
    print("="*60)
    print("OLLAMA TOOL CALLING TEST")
    print("="*60)
    
    # Step 1: Load tools from database
    print("\n[1/6] Loading tool definitions from database...")
    from mcp_servers.tool_loader import load_enabled_tools
    
    tools = load_enabled_tools()
    weather_tool = next((t for t in tools if t["function"]["name"] == "weather_get"), None)
    
    if not weather_tool:
        print("✗ weather_get not found!")
        return
    
    print(f"✓ Loaded {len(tools)} tools from database")
    print(f"  Found weather_get tool")
    
    # Step 2: Initialize tool manager
    print("\n[2/6] Initializing tool manager...")
    from mcp_servers.tool_manager import ToolManager
    
    tool_manager = ToolManager()
    await tool_manager.connect()
    print("✓ Tool manager connected to MCP servers")
    
    # Step 3: Prepare messages for Ollama
    print("\n[3/6] Preparing messages for Ollama...")
    messages = [
        {
            "role": "system",
            "content": "You are Iris, a helpful AI assistant. When users ask about weather, use the weather_get tool."
        },
        {
            "role": "user",
            "content": "What's the weather like in Seattle?"
        }
    ]
    print("✓ Messages prepared")
    
    # Step 4: Call Ollama with tools
    print("\n[4/6] Calling Ollama with tool definitions...")
    from ollama.client import chat_completion_with_tools
    
    tool_definitions = tool_manager.get_tool_definitions_for_ollama()
    response = await chat_completion_with_tools(messages, tools=tool_definitions)
    
    if not response.has_tool_calls():
        print("✗ Ollama did not call any tools!")
        print(f"  Response: {response.get_content()}")
        tool_manager.disconnect()
        return
    
    print(f"✓ Ollama called {len(response.tool_calls)} tool(s)")
    
    # Step 5: Execute tool calls
    print("\n[5/6] Executing tool calls via MCP...")
    for tool_call in response.tool_calls:
        function_info = tool_call.get("function", {})
        tool_name = function_info.get("name")
        arguments = function_info.get("arguments", {})
        
        print(f"  Executing: {tool_name}")
        print(f"  Arguments: {arguments}")
        
        result = await tool_manager.execute_tool(
            tool_name, 
            arguments,
            require_confirmation=False  # Skip confirmation for test
        )
        
        if result["success"]:
            print(f"  ✓ Tool executed successfully")
            weather = result["result"]
            print(f"    Temperature: {weather.get('temperature')}°F")
            print(f"    Condition: {weather.get('condition')}")
        else:
            print(f"  ✗ Tool execution failed: {result.get('error')}")
            tool_manager.disconnect()
            return
        
        # Add tool result to conversation
        messages.append({
            "role": "assistant",
            "content": "",
            "tool_calls": [tool_call]
        })
        messages.append({
            "role": "tool",
            "content": str(result["result"])
        })
    
    # Step 6: Get final response from Ollama
    print("\n[6/6] Getting final response from Ollama...")
    from ollama.client import chat_completion_stream
    
    print("\nIris's response:")
    print("-" * 60)
    
    full_response = ""
    async for chunk in chat_completion_stream(messages):
        print(chunk, end="", flush=True)
        full_response += chunk
    
    print("\n" + "-" * 60)
    
    # Cleanup
    print("\nDisconnecting...")
    await tool_manager.disconnect()
    
    print("\n" + "="*60)
    print("TEST COMPLETE ✓")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(test_ollama_tool_calling())
