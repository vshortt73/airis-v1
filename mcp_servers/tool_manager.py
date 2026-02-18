"""
Tool Manager - Orchestrates tool discovery and execution

Coordinates between:
- Database (tool definitions + smart selection metadata)
- MCP Client (tool execution)
- Conversation system (tool results)

Smart Tool Selection (Database-Driven):
- Core tools (is_core=TRUE) are always included
- Contextual groups are loaded from mcp_tools.tool_group and trigger_keywords
- At snapshot boundaries, recent user messages are scanned for trigger keywords
- Only relevant tool groups are included, saving ~60-80% of tool definition tokens
- Safety net: tool_miss detection forces group inclusion on next rebuild
"""
from colorama import Fore, Back, Style, init
init(autoreset=True)
import asyncio
from typing import List, Dict, Any, Optional, Set
from pathlib import Path
import sys

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from mcp_servers.tool_loader import load_enabled_tools, get_tool_by_name
from mcp_servers.mcp_client import MCPClient
from mcp_servers.server_configs import get_server_configs, is_tool_autonomous


def _load_smart_selection_metadata():
    """
    Load tool groups, triggers, and core tools from database.

    Returns:
        tuple: (core_tools: Set[str], tool_groups: Dict, tool_to_group: Dict)
            - core_tools: Set of tool names that are always included
            - tool_groups: Dict mapping group_name -> {"tools": set, "triggers": list}
            - tool_to_group: Dict mapping tool_name -> group_name
    """
    import psycopg2
    import os
    from app import config

    core_tools = set()
    tool_groups = {}
    tool_to_group = {}

    password = os.environ.get('IRIS_DB_PASSWORD') or getattr(config, 'DB_PASSWORD', None)
    conn_params = {
        'host': config.DB_HOST,
        'port': config.DB_PORT,
        'database': config.DB_NAME,
        'user': config.DB_USER
    }
    if password:
        conn_params['password'] = password

    try:
        conn = psycopg2.connect(**conn_params)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT tool_name, tool_group, trigger_keywords, is_core
            FROM mcp_tools
            WHERE enabled = true
        """)

        for row in cursor.fetchall():
            tool_name, tool_group, trigger_keywords, is_core = row

            # Track core tools
            if is_core:
                core_tools.add(tool_name)

            # Build tool groups
            if tool_group:
                if tool_group not in tool_groups:
                    tool_groups[tool_group] = {"tools": set(), "triggers": []}

                tool_groups[tool_group]["tools"].add(tool_name)

                # Add triggers (avoid duplicates)
                if trigger_keywords:
                    for trigger in trigger_keywords:
                        if trigger not in tool_groups[tool_group]["triggers"]:
                            tool_groups[tool_group]["triggers"].append(trigger)

                # Build reverse lookup
                tool_to_group[tool_name] = tool_group

        cursor.close()
        conn.close()

        print(f"[ToolManager] Loaded smart selection: {len(core_tools)} core tools, {len(tool_groups)} groups")
        return core_tools, tool_groups, tool_to_group

    except Exception as e:
        print(f"[ToolManager] WARNING: Failed to load smart selection from DB: {e}")
        print("[ToolManager] Falling back to hardcoded defaults")
        # Fallback to hardcoded values for resilience
        return _get_fallback_metadata()


def _get_fallback_metadata():
    """Fallback hardcoded metadata if database is unavailable."""
    core_tools = {"weather", "memory", "knowledge", "knowledge_save", "face"}

    tool_groups = {
        "navigation": {
            "tools": {"ship_directions", "ship_locations"},
            "triggers": ["directions", "where is", "how to get", "navigate", "deck", "location", "find the"],
        },
        "social": {
            "tools": {"moltbook", "moltbook_post"},
            "triggers": ["moltbook", "post", "submolt", "social", "community", "molt"],
        },
        "creative": {
            "tools": {"image"},
            "triggers": ["image", "picture", "draw", "paint", "generate", "selfie", "photo"],
        },
        "calendar": {
            "tools": {"calendar", "calendar_add"},
            "triggers": ["calendar", "event", "schedule", "remind", "appointment"],
        },
        "meeting": {
            "tools": {"meeting", "meeting_start"},
            "triggers": ["meeting", "record", "transcri", "minutes"],
        },
        "research": {
            "tools": {"web_search", "url_fetch", "research", "news_headlines"},
            "triggers": ["search", "look up", "find out", "news", "article", "arxiv", "pubmed", "website", "url"],
        },
        "system": {
            "tools": {"linux_shell", "database_query", "webcam_recognize", "distributed_system_health"},
            "triggers": ["system", "server", "shell", "command", "database", "query", "sql", "webcam", "look at", "health", "gpu", "service", "memory", "diagnose", "status"],
        },
        "personality": {
            "tools": {"trait", "protocol", "seed"},
            "triggers": ["trait", "personality", "protocol", "mode", "seed", "motivation", "goal"],
        },
    }

    tool_to_group = {}
    for group_name, group_def in tool_groups.items():
        for tool_name in group_def["tools"]:
            tool_to_group[tool_name] = group_name

    return core_tools, tool_groups, tool_to_group


# Module-level cached metadata (loaded once at import, can be reloaded)
_CORE_TOOLS, _TOOL_GROUPS, _TOOL_TO_GROUP = _load_smart_selection_metadata()


def reload_smart_selection_metadata():
    """Reload smart selection metadata from database."""
    global _CORE_TOOLS, _TOOL_GROUPS, _TOOL_TO_GROUP
    _CORE_TOOLS, _TOOL_GROUPS, _TOOL_TO_GROUP = _load_smart_selection_metadata()
    return _CORE_TOOLS, _TOOL_GROUPS, _TOOL_TO_GROUP


def check_message_for_missing_groups(message: str, current_tools: List[str]) -> Set[str]:
    """
    Check if a user message triggers any tool groups not in the current selection.

    Args:
        message: The current user message text
        current_tools: Tool names currently in the snapshot

    Returns:
        Set of group names that are triggered but not currently included
    """
    text = message.lower()
    current_set = set(current_tools) if current_tools else set()
    missing = set()

    for group_name, group_def in _TOOL_GROUPS.items():
        # Skip if this group's tools are already in the selection
        if group_def["tools"] & current_set:
            continue
        # Check if any trigger matches
        for trigger in group_def["triggers"]:
            if trigger in text:
                missing.add(group_name)
                break

    return missing


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

            print(f"[ToolManager] Tool execution {Fore.GREEN + 'succeeded' if response['success'] else  Fore.RED + 'failed'}")
            return response

        except Exception as e:
            error_msg = f" Tool execution failed: {str(e)}"
            print(f"[ToolManager] Error: {error_msg}")

            return {
                "success": False,
                "tool_name": tool_name,
                "parameters": parameters,
                "error": error_msg
            }

    def get_tools_for_context(
        self,
        recent_messages: List[str],
        force_groups: Optional[Set[str]] = None,
        blocked_tools: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Select tools relevant to recent conversation context.

        Scans recent user messages for trigger keywords and returns CORE tools
        plus any contextual groups whose triggers match.

        Args:
            recent_messages: Last N user message texts
            force_groups: Group names to force-include (from tool_miss spoil)
            blocked_tools: Tool names to exclude (from protocol blocked_tools)

        Returns:
            Filtered list of tool definitions
        """
        # Build lowercase text window from recent messages
        text_window = " ".join(recent_messages).lower()

        # Start with core tools
        selected_tools = set(_CORE_TOOLS)
        matched_groups = []

        # Check each contextual group for trigger matches
        for group_name, group_def in _TOOL_GROUPS.items():
            # Force-included groups skip trigger check
            if force_groups and group_name in force_groups:
                selected_tools.update(group_def["tools"])
                matched_groups.append(f"{group_name}(forced)")
                continue

            # Check if any trigger keyword appears in the text window
            for trigger in group_def["triggers"]:
                if trigger in text_window:
                    selected_tools.update(group_def["tools"])
                    matched_groups.append(group_name)
                    break

        # Apply blocked_tools exclusions (from protocol)
        if blocked_tools:
            excluded_count = len(selected_tools & set(blocked_tools))
            selected_tools -= set(blocked_tools)
            if excluded_count > 0:
                print(f"[ToolManager] Excluded {excluded_count} tools via protocol blocked_tools")

        # Filter tool definitions to only selected tools
        filtered = [t for t in self.tools if t["function"]["name"] in selected_tools]

        groups_str = ", ".join(matched_groups) if matched_groups else "none"
        print(f"[ToolManager] Smart selection: {len(filtered)}/{len(self.tools)} tools "
              f"(CORE + {groups_str})")

        return filtered

    def get_tools_by_names(self, names: Optional[List[str]]) -> List[Dict[str, Any]]:
        """
        Return tool definitions for specific tool names only.

        Args:
            names: List of tool names to include, or None for all tools

        Returns:
            Filtered list of tool definitions
        """
        if names is None:
            return self.tools
        name_set = set(names)
        return [t for t in self.tools if t["function"]["name"] in name_set]

    @staticmethod
    def get_group_for_tool(tool_name: str) -> Optional[str]:
        """
        Look up which contextual group a tool belongs to.

        Args:
            tool_name: The tool name to look up

        Returns:
            Group name string, or None if tool is in CORE or unknown
        """
        return _TOOL_TO_GROUP.get(tool_name)

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

    # Test smart selection metadata
    print(f"\nCore tools: {_CORE_TOOLS}")
    print(f"Tool groups: {list(_TOOL_GROUPS.keys())}")

    # Connect to servers
    print("\nConnecting to MCP servers...")
    await manager.connect()

    # Show server status
    print("\nServer status:")
    status = manager.get_server_status()
    for server_name, info in status.items():
        print(f"  {server_name}: {'✓' if info['connected'] else '✗'}")

    # Test smart selection
    print("\nTesting smart selection with 'what is the weather':")
    tools = manager.get_tools_for_context(["what is the weather"])
    print(f"  Selected {len(tools)} tools")

    print("\nTesting smart selection with 'give me directions to the pool':")
    tools = manager.get_tools_for_context(["give me directions to the pool"])
    print(f"  Selected {len(tools)} tools")
    print(f"  Tools: {[t['function']['name'] for t in tools]}")

    print("\nTesting blocked_tools exclusion:")
    tools = manager.get_tools_for_context(
        ["give me directions to the pool"],
        blocked_tools=["ship_directions"]
    )
    print(f"  Selected {len(tools)} tools (with ship_directions blocked)")
    print(f"  Tools: {[t['function']['name'] for t in tools]}")

    # Test a tool
    print("\nTesting weather tool...")
    result = await manager.execute_tool(
        "weather",
        {"location": "Seattle", "units": "imperial"},
        require_confirmation=False
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
