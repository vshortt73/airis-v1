"""
MCP Server Configurations

Defines which MCP servers to connect to and which tools each server provides.
"""

from pathlib import Path
from typing import List, Dict, Any

# Get the project root directory
PROJECT_ROOT = Path(__file__).parent.parent


def get_server_configs() -> List[Dict[str, Any]]:
    """
    Get MCP server connection configurations
    
    Returns:
        List of server configs with:
        - name: Server identifier
        - command: Command to run (python, node, etc.)
        - args: Command arguments (path to server script)
        - tools: List of tool names this server provides
    """
    
    configs = [
        # ====================================================================
        # INFO SERVER - Information retrieval tools
        # ====================================================================
        {
            "name": "info",
            "command": "python",
            "args": [str(PROJECT_ROOT / "mcp_servers" / "info" / "info_server.py")],
            "tools": [
                "weather_get",
                "forecast_get",
                "news_headlines",
                "web_fetch",
                "webcam",
                "rtsp_show_named",
                "rtsp_popup_show"
            ]
        },
        
        # ====================================================================
        # SYSTEM SERVER - System management and monitoring
        # ====================================================================
        # {
        #     "name": "system",
        #     "command": "python",
        #     "args": [str(PROJECT_ROOT / "mcp_servers" / "system" / "system_server.py")],
        #     "tools": [
        #         "system_status",
        #         "system_status_summary",
        #         "system_logs",
        #         "service_status",
        #         "service_start",
        #         "service_stop",
        #         "service_restart",
        #         "monitor_add",
        #         "monitor_list",
        #         "monitor_remove"
        #     ]
        # },
        
        # ====================================================================
        # KNOWLEDGE SERVER - Document and knowledge search
        # ====================================================================
        # {
        #     "name": "knowledge",
        #     "command": "python",
        #     "args": [str(PROJECT_ROOT / "mcp_servers" / "knowledge" / "knowledge_server.py")],
        #     "tools": [
        #         "document_search",
        #         "knowledge_search",
        #         "knowledge_stats"
        #     ]
        # },
        
        # ====================================================================
        # TRAITS SERVER - Personality trait management
        # ====================================================================
        {
            "name": "traits",
            "command": "python",
            "args": [str(PROJECT_ROOT / "mcp_servers" / "traits" / "traits_server.py")],
            "tools": [
                "trait_get",
                "trait_list",
                "trait_modify"  
            ]
        },
        
        # ====================================================================
        # CREATIVE SERVER - Image generation and creative tools
        # ====================================================================
         # {
         #     "name": "creative",
         #     "command": "python",
         #     "args": [str(PROJECT_ROOT / "mcp_servers" / "creative" / "creative_server.py")],
         #     "tools": [
         #         "image_generate",
         #         "image_generate_iris"
         #     ]
         # },
        # ====================================================================
        # SYSTEM SERVER - System Stats and Controls
        # ====================================================================
         {
             "name": "system",
             "command": "python",
             "args": [str(PROJECT_ROOT / "mcp_servers" / "system" / "system_server.py")],
             "tools": [
               #  "get_drive_statistics",
               #  "get_ram_statistics",
               #  "get_nvidia_gpu_statistics",
               #  "get_cpu_statistics",
               #  "get_process_statistics",
                  "generate_alerts",
                  "get_system_health_statistics",
                  "system_status_summary",
                  "linux_shell",
                  "database_query",
               #  "format_system_health_summary",

             ]
         }
    ]
    
    return configs


def get_tools_by_server() -> Dict[str, List[str]]:
    """
    Get mapping of server names to their tools
    
    Returns:
        Dict mapping server name to list of tool names
    """
    configs = get_server_configs()
    return {config["name"]: config["tools"] for config in configs}


def get_server_for_tool(tool_name: str) -> str:
    """
    Get which server provides a specific tool
    
    Args:
        tool_name: Name of the tool
        
    Returns:
        Server name, or None if tool not found
    """
    for config in get_server_configs():
        if tool_name in config["tools"]:
            return config["name"]
    return None


def get_autonomous_tools() -> List[str]:
    """
    Get list of tools that can be called autonomously without confirmation
    
    Returns:
        List of tool names that are safe for autonomous use
    """
    return [
        # Info tools - all safe
        "weather_get",
        "forecast_get",
        "news_headlines",
        "web_fetch",
        "webcam",
        
        # System tools - read-only operations
        "system_status",
        "system_status_summary",
        "system_logs",
        "service_status",
        "linux_shell",
        
        # Knowledge tools - all safe
        "document_search",
        "knowledge_search",
        "knowledge_stats",
        
        # Traits tools - read-only
        "trait_get",
        "trait_list",

        # System tools - all safe
        "system_status"
    ]


def get_confirmation_required_tools() -> List[str]:
    """
    Get list of tools that require user confirmation before execution
    
    Returns:
        List of tool names that need confirmation
    """
    return [
        # System tools - modify state
        "service_start",
        "service_stop",
        "service_restart",
        "monitor_add",
        "monitor_remove",
        
        # Traits tools - modify personality
        "trait_modify",
        
        # Creative tools - can be autonomous or require confirmation
      #  "image_generate",
      #  "image_generate_iris",
        
        # RTSP tools - display operations
        "rtsp_show_named",
        "rtsp_popup_show"
    ]


def is_tool_autonomous(tool_name: str) -> bool:
    """
    Check if a tool can be called autonomously
    
    Args:
        tool_name: Name of the tool
        
    Returns:
        True if tool can be called without confirmation
    """
    return tool_name in get_autonomous_tools()


if __name__ == "__main__":
    """Test server configurations"""
    print("=" * 60)
    print("MCP SERVER CONFIGURATIONS")
    print("=" * 60)
    
    configs = get_server_configs()
    print(f"\nConfigured servers: {len(configs)}")
    
    for config in configs:
        print(f"\n{config['name'].upper()} Server:")
        print(f"  Command: {config['command']} {' '.join(config['args'])}")
        print(f"  Tools ({len(config['tools'])}):")
        for tool in config["tools"]:
            auto = "🟢 AUTO" if is_tool_autonomous(tool) else "🔴 CONFIRM"
            print(f"    - {tool} {auto}")
    
    print("\n" + "=" * 60)
    print(f"Total tools: {sum(len(c['tools']) for c in configs)}")
    print(f"Autonomous: {len(get_autonomous_tools())}")
    print(f"Require confirmation: {len(get_confirmation_required_tools())}")
