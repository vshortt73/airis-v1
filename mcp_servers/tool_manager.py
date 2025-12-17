"""
Tool Manager - Orchestrates tool discovery and execution

Coordinates between:
- Database (tool definitions)
- MCP Client (tool execution)
- Conversation system (tool results)
"""
from colorama import Fore, Back, Style, init
init(autoreset=True) # Resets styles after each print statement
import asyncio
from typing import List, Dict, Any, Optional
from pathlib import Path
import sys

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from mcp_servers.tool_loader import load_enabled_tools, get_tool_by_name
from mcp_servers.mcp_client import MCPClient
from mcp_servers.server_configs import get_server_configs, is_tool_autonomous


class ToolManager:
    """
    Manages tool discovery and execution
    
    This is the main interface between Iris's conversation system and
    the MCP tool infrastructure. It:
    - Loads tool definitions from database
    - Manages MCP client connections
    - Executes tools and returns results
    - Handles autonomous vs confirmation-required tools
    """
    
    def __init__(self):
        """Initialize tool manager"""
        print("[ToolManager] Initializing...")
        
        # Load tool definitions from database
        self.tools = load_enabled_tools()
        print(f"[ToolManager] Loaded {len(self.tools)} tools from database")
        
        # Initialize MCP client
        self.mcp_client = MCPClient(get_server_configs())
        self._connected = False
        
        print("[ToolManager] Ready")
    
    async def connect(self):
        """Connect to all MCP servers"""
        if not self._connected:
            print("[ToolManager] Connecting to MCP servers...")
            success = await self.mcp_client.connect_all()
            self._connected = success
            
            if success:
                print("[ToolManager] Connected to MCP servers")
            else:
                print("[ToolManager] WARNING: Failed to connect to some MCP servers")
            
            return success
        return True
    
    async def disconnect(self):
        """Disconnect from all MCP servers"""
        if self._connected:
            print("[ToolManager] Disconnecting from MCP servers...")
            await self.mcp_client.disconnect_all()
            self._connected = False
    
    def get_tool_definitions_for_ollama(self) -> List[Dict[str, Any]]:
        """
        Get tool definitions in Ollama function calling format
        
        Returns:
            List of tool definitions ready to send to Ollama:
            [{
                "type": "function",
                "function": {
                    "name": "weather_get",
                    "description": "...",
                    "parameters": {...}
                }
            }, ...]
        """
        return self.tools
    
    async def execute_tool(
        self, 
        tool_name: str, 
        parameters: Dict[str, Any],
        require_confirmation: bool = False
    ) -> Dict[str, Any]:
        """
        Execute a tool via MCP
        
        Args:
            tool_name: Name of tool to execute
            parameters: Tool parameters
            require_confirmation: If True, check if tool needs confirmation
                                 (for testing, can be set to False)
        
        Returns:
            Tool execution result:
            {
                "success": bool,
                "tool_name": str,
                "parameters": dict,
                "result": any,
                "error": str (if success=False),
                "requires_confirmation": bool (if tool needs user approval)
            }
        """
        print(f"[ToolManager] Executing tool: {tool_name}")
        print(f"[ToolManager] Parameters: {parameters}")
        
        # Ensure we're connected
        if not self._connected:
            await self.connect()
        
        # Check if tool requires confirmation
        if require_confirmation and not is_tool_autonomous(tool_name):
            return {
                "success": False,
                "tool_name": tool_name,
                "parameters": parameters,
                "requires_confirmation": True,
                "error": "This tool requires user confirmation before execution"
            }
        
        try:
            # Execute tool via MCP client
            print("[TOOL_MANAGER][execute_tool] " + Fore.MAGENTA + f"calling {tool_name}")

            result = await self.mcp_client.call_tool(tool_name, parameters)
            # Package the response
            response = {
                "success": result.get("success", False),
                "tool_name": tool_name,
                "parameters": parameters,
                "result": result
            }
            
            if not result.get("success", False):
                response["error"] = result.get("error", "Unknown error")
            
            print(f"[ToolManager] Tool execution {Fore.GREEN + 'succeeded' if response['success'] else  Fore.RED + '❌failed'}")
            return response
            
        except Exception as e:
            error_msg = f" ❌Tool execution failed: {str(e)}"
            print(f"❌ [ToolManager] Error: {error_msg}")
            
            return {
                "success": False,
                "tool_name": tool_name,
                "parameters": parameters,
                "error": error_msg
            }
    
    def get_tool_count(self) -> int:
        """Get number of available tools"""
        return len(self.tools)
    
    def get_tool_names(self) -> List[str]:
        """Get list of all available tool names"""
        return [tool["function"]["name"] for tool in self.tools]
    
    def has_tool(self, tool_name: str) -> bool:
        """Check if a tool is available"""
        return tool_name in self.get_tool_names()
    
    def get_server_status(self) -> Dict[str, Any]:
        """Get status of all MCP servers"""
        if not self._connected:
            return {"error": "Not connected to MCP servers"}
        return self.mcp_client.get_server_status()


# Global tool manager instance
_tool_manager: Optional[ToolManager] = None


def get_tool_manager() -> ToolManager:
    """
    Get the global tool manager instance (singleton pattern)
    
    Returns:
        ToolManager instance
    """
    global _tool_manager
    if _tool_manager is None:
        _tool_manager = ToolManager()
    return _tool_manager


async def test_tool_manager():
    """Test the tool manager"""
    print("=" * 60)
    print("TOOL MANAGER TEST")
    print("=" * 60)
    
    # Initialize
    manager = ToolManager()
    print(f"\nLoaded {manager.get_tool_count()} tools")
    
    # Connect to servers
    print("\nConnecting to MCP servers...")
    await manager.connect()
    
    # Show server status
    print("\nServer status:")
    status = manager.get_server_status()
    for server_name, info in status.items():
        print(f"  {server_name}: {'✓' if info['connected'] else '✗'}")
    
    # Test a tool
    print("\nTesting weather_get tool...")
    result = await manager.execute_tool(
        "weather_get",
        {"location": "Seattle", "units": "imperial"},
        require_confirmation=False  # Skip confirmation for testing
    )
    
    if result["success"]:
        weather = result["result"]
        print(f"  ✓ Success!")
        print(f"  Temperature: {weather.get('temperature')}°F")
        print(f"  Condition: {weather.get('condition')}")
    else:
        print(f"  ✗ Failed: {result.get('error')}")
    
    # Disconnect
    print("\nDisconnecting...")
    await manager.disconnect()
    
    print("\n" + "=" * 60)


if __name__ == "__main__":
    """Test the tool manager"""
    asyncio.run(test_tool_manager())
