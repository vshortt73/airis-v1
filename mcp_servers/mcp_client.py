"""
MCP Client - Connect to and execute tools on MCP servers using FastMCP

This client uses FastMCP's Client class to connect to MCP servers
and route tool calls to the appropriate server.

Supports MCP Native Discovery:
- After connecting to a server, queries available tools via MCP list_tools
- Automatically registers discovered tools in the database
- Maps tool_name → server dynamically
"""
from colorama import Fore, Back, Style, init
init(autoreset=True)
import asyncio
from typing import Dict, Any, List, Optional
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from fastmcp import Client
    from fastmcp.client.transports import PythonStdioTransport
except ImportError:
    print("ERROR: fastmcp not installed. Run: pip install fastmcp")
    sys.exit(1)

import os


class MCPServerConnection:
    """Connection to a single MCP server using FastMCP Client"""

    def __init__(self, name: str, command: str, args: List[str], tools: List[str]):
        """
        Initialize MCP server connection

        Args:
            name: Server name (e.g., "info", "system")
            command: Command to run (e.g., "python")
            args: Command arguments (e.g., ["/path/to/info_server.py"])
            tools: List of tool names this server provides (may be empty if using discovery)
        """
        self.name = name
        self.command = command
        self.args = args
        self.tools = set(tools)  # Tools this server provides (from config)
        self.discovered_tools: Dict[str, Dict] = {}  # Tools discovered via MCP protocol
        self.client: Optional[Client] = None
        self.connected = False

    async def connect(self):
        """Connect to the MCP server using FastMCP Client"""
        try:
            print(f"[MCPClient][connect] Connecting to {self.name} server...")

            # Create FastMCP client with stdio transport
            # MCP SDK strips env vars by default (security feature), so we
            # explicitly pass IRIS_DB_PASSWORD so subprocesses can reach the DB
            server_path = self.args[0]  # Path to server script
            env = {}
            db_password = os.environ.get('IRIS_DB_PASSWORD')
            if db_password:
                env['IRIS_DB_PASSWORD'] = db_password
            transport = PythonStdioTransport(script_path=server_path, env=env or None)
            self.client = Client(transport)

            # Enter the client context (connects and initializes)
            await self.client.__aenter__()

            self.connected = True
            print(f"[MCPClient][connect] {self.name}" + Style.BRIGHT + Fore.GREEN + " server connected")
            return True

        except Exception as e:
            print(f"[MCPClient][connect] " + Style.BRIGHT + Fore.RED + f"Error connecting to {self.name} server: {e}")
            self.connected = False
            return False

    async def discover_tools(self) -> List[Dict[str, Any]]:
        """
        Discover tools available on this server via MCP list_tools.

        Returns:
            List of tool definitions discovered from the server
        """
        if not self.connected or not self.client:
            return []

        try:
            # Query server for available tools via MCP protocol
            tools_result = await self.client.list_tools()

            discovered = []
            for tool in tools_result:
                tool_info = {
                    "name": tool.name,
                    "description": tool.description or "",
                    "input_schema": tool.inputSchema if hasattr(tool, 'inputSchema') else {}
                }
                self.discovered_tools[tool.name] = tool_info
                discovered.append(tool_info)

            print(f"[MCPClient][discover_tools] {self.name}: discovered {len(discovered)} tools")
            return discovered

        except Exception as e:
            print(f"[MCPClient][discover_tools] {self.name}: discovery failed: {e}")
            return []

    def has_tool(self, tool_name: str) -> bool:
        """Check if this server provides a specific tool."""
        return tool_name in self.tools or tool_name in self.discovered_tools

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
                "error": f"[MCP_CLIENT][call_tool] Server {self.name} " + Style.BRIGHT + Fore.RED + "not connected"
            }

        try:
            print(f"[MCPClient][call_tool] Calling {tool_name} on {self.name} server with parameters: {parameters}")

            # Call tool via FastMCP client
            try:
                result = await self.client.call_tool(tool_name, parameters)
            except Exception as e:
                print(f"[MCPClient][call_tool] FastMCP call failed: {e}")
                return {
                    "success": False,
                    "error": f"Tool execution failed: {str(e)}"
                }


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
            error_msg = f"[MCP_CLIENT][call_tool] Error calling tool: {str(e)}"
            print(f"[MCPClient][call_tool] {error_msg}")
            return {
                "success": False,
                "error": error_msg
            }

    async def disconnect(self):
        """Disconnect from the MCP server"""
        if self.client:
            print(f"[MCPClient][disconnect] Disconnecting from {self.name} server...")
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

    Supports MCP Native Discovery:
    - After connecting, discovers tools from each server
    - Auto-registers new tools in the database
    - Updates tool-to-server mapping dynamically
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
                tools=config.get("tools", [])
            )
            self.servers.append(server)

            # Map tools to their server (from config)
            for tool_name in config.get("tools", []):
                self.tool_to_server[tool_name] = server

    async def connect_all(self, discover_tools: bool = True):
        """
        Connect to all MCP servers

        Args:
            discover_tools: If True, discover and register tools after connecting
        """
        print("[MCPClient][connect_all] Connecting to all MCP servers...")

        # Connect to all servers concurrently
        results = await asyncio.gather(
            *[server.connect() for server in self.servers],
            return_exceptions=True
        )

        # Check results
        success_count = sum(1 for r in results if r is True)
        print(f"[MCPClient][connect_all] Connected to {success_count}/{len(self.servers)} servers")

        # Discover tools from connected servers
        if discover_tools and success_count > 0:
            await self._discover_and_register_tools()

        return success_count > 0

    async def _discover_and_register_tools(self):
        """
        Discover tools from all connected servers and register in database.
        Also updates the tool_to_server mapping for routing.
        """
        from mcp_servers.tool_loader import upsert_discovered_tool

        for server in self.servers:
            if not server.connected:
                continue

            # Discover tools via MCP protocol
            discovered = await server.discover_tools()

            for tool_info in discovered:
                tool_name = tool_info["name"]

                # Update tool-to-server mapping
                if tool_name not in self.tool_to_server:
                    self.tool_to_server[tool_name] = server
                    print(f"[MCPClient] Mapped new tool {tool_name} -> {server.name}")

                # Register/update tool in database
                try:
                    upsert_discovered_tool(
                        tool_name=tool_name,
                        server_name=server.name,
                        description=tool_info.get("description", ""),
                        input_schema=tool_info.get("input_schema", {})
                    )
                except Exception as e:
                    print(f"[MCPClient] Warning: Failed to register tool {tool_name}: {e}")

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
        print(f"[MCP_CLIENT][call_tool]" + Fore.MAGENTA + f" looking for tool {tool_name}")

        server = self.tool_to_server.get(tool_name)

        # If not in mapping, search all servers (discovery may have added it)
        if not server:
            for s in self.servers:
                if s.has_tool(tool_name):
                    server = s
                    self.tool_to_server[tool_name] = s  # Cache for next time
                    print(f"[MCPClient] Found tool {tool_name} on {s.name} via discovery")
                    break

        if not server:
            return {
                "success": False,
                "error": Fore.RED + f"Unknown tool: {tool_name}"
            }

        if not server.connected:
            # Try to reconnect
            print(f"[MCPClient][call_tool] Server {server.name} not connected, attempting reconnect...")
            await server.connect()

            if not server.connected:
                return {
                    "success": False,
                    "error": f"Server {server.name} not available"
                }

        # Call the tool
        print(f"[MCPClient][call_tool] Routing {tool_name} to {server.name} server")
        result = await server.call_tool(tool_name, parameters)

        return result

    async def disconnect_all(self):
        """Disconnect from all MCP servers"""
        print("[MCPClient][disconnect_all] Disconnecting from all servers...")
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
                "tools": list(server.tools),
                "discovered_tools": list(server.discovered_tools.keys())
            }
            for server in self.servers
        }


async def test_mcp_client():
    """Test the MCP client with weather tool"""
    from mcp_servers.server_configs import get_server_configs

    print("="*60)
    print("MCP CLIENT TEST - WITH TOOL DISCOVERY")
    print("="*60)

    # Get all server configs
    all_configs = get_server_configs()

    print("\n[MCP_CLIENT][test] Initializing MCP Client...")
    client = MCPClient(all_configs)

    print("\nConnecting to servers (with discovery)...")
    success = await client.connect_all(discover_tools=True)

    if not success:
        print("Failed to connect to servers")
        return

    print("\nServer status:")
    status = client.get_server_status()
    for server_name, info in status.items():
        connected = '✓ Connected' if info['connected'] else '✗ Disconnected'
        print(f"  {server_name}: {connected}")
        if info['discovered_tools']:
            print(f"    Discovered: {', '.join(info['discovered_tools'][:5])}...")

    print(f"\nTotal tools mapped: {len(client.get_available_tools())}")

    print("\nTesting weather tool...")
    result = await client.call_tool("weather", {
        "location": "Seattle",
    })

    if result.get("success"):
        print(f"✓ Success!")
        print(f"  Result: {result}")
    else:
        print(f"✗ Failed: {result.get('error')}")

    print("\nDisconnecting...")
    await client.disconnect_all()

    print("\n" + "="*60)


if __name__ == "__main__":
    """Test the MCP client"""
    asyncio.run(test_mcp_client())
