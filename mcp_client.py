"""
MCP Client - Connect to and execute tools on MCP servers using FastMCP

This client uses FastMCP's Client class to connect to MCP servers
and route tool calls to the appropriate server.
"""

import asyncio
from typing import Dict, Any, List, Optional
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from fastmcp import Client
except ImportError:
    print("ERROR: fastmcp not installed. Run: pip install fastmcp")
    sys.exit(1)


class MCPServerConnection:
    """Connection to a single MCP server using FastMCP Client"""
    
    def __init__(self, name: str, command: str, args: List[str], tools: List[str]):
        """
        Initialize MCP server connection
        
        Args:
            name: Server name (e.g., "info", "system")
            command: Command to run (e.g., "python")
            args: Command arguments (e.g., ["/path/to/info_server.py"])
            tools: List of tool names this server provides
        """
        self.name = name
        self.command = command
        self.args = args
        self.tools = set(tools)  # Tools this server provides
        self.client: Optional[Client] = None
        self.connected = False
    
    async def connect(self):
        """Connect to the MCP server using FastMCP Client"""
        try:
            print(f"[MCPClient] Connecting to {self.name} server...")
            
            # Create FastMCP client with stdio transport
            # FastMCP will automatically handle the server process
            server_path = self.args[0]  # Path to server script
            self.client = Client(server_path)
            
            # Enter the client context (connects and initializes)
            await self.client.__aenter__()
            
            self.connected = True
            print(f"[MCPClient] {self.name} server connected")
            return True
                
        except Exception as e:
            print(f"[MCPClient] Error connecting to {self.name} server: {e}")
            self.connected = False
            return False
    
    async def call_tool(self, tool_name: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Call a tool on this server using FastMCP
        
        Args:
            tool_name: Name of tool to call
            parameters: Tool parameters
            
        Returns:
            Tool result in Iris format (with success flag)
        """
        if not self.connected or not self.client:
            return {
                "success": False,
                "error": f"Server {self.name} not connected"
            }
        
        try:
            print(f"[MCPClient] Calling {tool_name} on {self.name} server")
            
            # Call tool via FastMCP client
            result = await self.client.call_tool(tool_name, parameters)
            
            # FastMCP returns CallToolResult object
            # Extract the actual data from result.content
            if hasattr(result, 'content') and result.content:
                # Content is a list of content blocks
                content_text = ""
                for content_block in result.content:
                    if hasattr(content_block, 'text'):
                        content_text += content_block.text
                
                # Try to parse as JSON (tools should return JSON strings)
                import json
                try:
                    tool_result = json.loads(content_text)
                    return tool_result
                except json.JSONDecodeError:
                    # If not JSON, wrap in success response
                    return {
                        "success": True,
                        "result": content_text
                    }
            
            # Fallback: return raw result
            return {
                "success": True,
                "result": str(result)
            }
            
        except Exception as e:
            error_msg = f"Error calling tool: {str(e)}"
            print(f"[MCPClient] {error_msg}")
            return {
                "success": False,
                "error": error_msg
            }
    
    async def disconnect(self):
        """Disconnect from the MCP server"""
        if self.client:
            print(f"[MCPClient] Disconnecting from {self.name} server...")
            try:
                await self.client.__aexit__(None, None, None)
            except Exception as e:
                print(f"[MCPClient] Error disconnecting: {e}")
            self.connected = False


class MCPClient:
    """
    Client to connect to and execute tools on MCP servers using FastMCP
    
    Manages connections to multiple MCP servers and routes tool calls
    to the appropriate server based on which tools each server provides.
    """
    
    def __init__(self, server_configs: List[Dict[str, Any]]):
        """
        Initialize MCP client with server configurations
        
        Args:
            server_configs: List of server configurations:
                [{
                    "name": "info",
                    "command": "python",
                    "args": ["/iris-v3/mcp_servers/info/info_server.py"],
                    "tools": ["weather_get", "news_headlines", ...]
                }, ...]
        """
        self.servers: List[MCPServerConnection] = []
        self.tool_to_server: Dict[str, MCPServerConnection] = {}
        
        # Create server connections
        for config in server_configs:
            server = MCPServerConnection(
                name=config["name"],
                command=config["command"],
                args=config["args"],
                tools=config["tools"]
            )
            self.servers.append(server)
            
            # Map tools to their server
            for tool_name in config["tools"]:
                self.tool_to_server[tool_name] = server
    
    async def connect_all(self):
        """Connect to all MCP servers"""
        print("[MCPClient] Connecting to all MCP servers...")
        
        # Connect to all servers concurrently
        results = await asyncio.gather(
            *[server.connect() for server in self.servers],
            return_exceptions=True
        )
        
        # Check results
        success_count = sum(1 for r in results if r is True)
        print(f"[MCPClient] Connected to {success_count}/{len(self.servers)} servers")
        
        return success_count > 0
    
    async def call_tool(self, tool_name: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a tool call by routing to the correct server
        
        Args:
            tool_name: Name of tool to call
            parameters: Tool parameters
            
        Returns:
            Tool result
        """
        # Find which server provides this tool
        server = self.tool_to_server.get(tool_name)
        
        if not server:
            return {
                "success": False,
                "error": f"Unknown tool: {tool_name}"
            }
        
        if not server.connected:
            # Try to reconnect
            print(f"[MCPClient] Server {server.name} not connected, attempting reconnect...")
            await server.connect()
            
            if not server.connected:
                return {
                    "success": False,
                    "error": f"Server {server.name} not available"
                }
        
        # Call the tool
        print(f"[MCPClient] Routing {tool_name} to {server.name} server")
        result = await server.call_tool(tool_name, parameters)
        
        return result
    
    async def disconnect_all(self):
        """Disconnect from all MCP servers"""
        print("[MCPClient] Disconnecting from all servers...")
        await asyncio.gather(
            *[server.disconnect() for server in self.servers],
            return_exceptions=True
        )
    
    def get_available_tools(self) -> List[str]:
        """Get list of all available tools across all servers"""
        return list(self.tool_to_server.keys())
    
    def get_server_status(self) -> Dict[str, Any]:
        """Get status of all servers"""
        return {
            server.name: {
                "connected": server.connected,
                "tools": list(server.tools)
            }
            for server in self.servers
        }


async def test_mcp_client():
    """Test the MCP client with weather tool"""
    from mcp_servers.server_configs import get_server_configs
    
    print("="*60)
    print("MCP CLIENT TEST - WEATHER TOOL ONLY")
    print("="*60)
    
    # Get only the info server config (has weather tool)
    all_configs = get_server_configs()
    info_config = [c for c in all_configs if c["name"] == "info"]
    
    if not info_config:
        print("ERROR: Info server config not found")
        return
    
    print("\nInitializing MCP Client (info server only)...")
    client = MCPClient(info_config)
    
    print("\nConnecting to info server...")
    success = await client.connect_all()
    
    if not success:
        print("Failed to connect to server")
        return
    
    print("\nServer status:")
    status = client.get_server_status()
    for server_name, info in status.items():
        print(f"  {server_name}: {'✓ Connected' if info['connected'] else '✗ Disconnected'}")
        print(f"    Tools: {', '.join(info['tools'][:3])}...")  # Show first 3 tools
    
    print("\nTesting weather_get tool...")
    result = await client.call_tool("weather_get", {
        "location": "Seattle",
        "units": "imperial"
    })
    
    if result.get("success"):
        print(f"✓ Success!")
        print(f"  Temperature: {result.get('temperature')}°{result.get('units', 'F')}")
        print(f"  Condition: {result.get('condition')}")
        print(f"  Location: {result.get('nearest')}")
    else:
        print(f"✗ Failed: {result.get('error')}")
    
    print("\nDisconnecting...")
    await client.disconnect_all()
    
    print("\n" + "="*60)


if __name__ == "__main__":
    """Test the MCP client"""
    asyncio.run(test_mcp_client())
