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
                "web_search",      # Search web with keywords
                "url_fetch",       # Fetch specific URL
                "arxiv_search",    # Search arXiv for academic papers
                "pubmed_search",   # Search PubMed for biomedical literature
                "webcam",
                "rtsp_show_named",
                "rtsp_popup_show",
                "face_database_status",  # Face recognition statistics
                "list_detected_faces",    # Currently detected people
                "get_person_info",        # Detailed person info
                "webcam_recognize"        # Capture and recognize faces
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
        # KNOWLEDGE SERVER - Document and knowledge search (unified)
        # ====================================================================
        {
            "name": "knowledge",
            "command": "python",
            "args": [str(PROJECT_ROOT / "mcp_servers" / "knowledge" / "knowledge_server.py")],
            "tools": [
                "knowledge"  # Unified: action="search|stats"
            ]
        },
        
        # ====================================================================
        # TRAITS SERVER - Personality trait management (unified)
        # ====================================================================
        {
            "name": "traits",
            "command": "python",
            "args": [str(PROJECT_ROOT / "mcp_servers" / "traits" / "traits_server.py")],
            "tools": [
                "trait"  # Unified: action="get|list|modify"
            ]
        },
        
        # ====================================================================
        # MEMORY SERVER - Short-term memory management (unified)
        # ====================================================================
        {
            "name": "memory",
            "command": "python",
            "args": [str(PROJECT_ROOT / "mcp_servers" / "memory" / "memory_server.py")],
            "tools": [
                "memory"  # Unified: action="insert|retrieve|archive"
            ]
        },

        # ====================================================================
        # CREATIVE SERVER - Image generation via ComfyUI (unified)
        # ====================================================================
        {
            "name": "creative",
            "command": "python",
            "args": [str(PROJECT_ROOT / "mcp_servers" / "creative" / "creative_server.py")],
            "tools": [
                "image"  # Unified: action="generate|self"
            ]
        },
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
         },

        # ====================================================================
        # PROTOCOL SERVER - Protocol activation and management
        # ====================================================================
        {
            "name": "protocols",
            "command": "python",
            "args": [str(PROJECT_ROOT / "mcp_servers" / "protocols" / "protocol_server.py")],
            "tools": [
                "protocol"  # Unified: action="activate|deactivate|status|list"
            ]
        },

        # ====================================================================
        # DIRECTIONS SERVER - Ship navigation and wayfinding (unified)
        # ====================================================================
        {
            "name": "directions",
            "command": "python",
            "args": [str(PROJECT_ROOT / "mcp_servers" / "directions" / "directions_server.py")],
            "tools": [
                "ship"  # Unified: action="directions|locations"
            ]
        },

        # ====================================================================
        # SEEDS SERVER - Iris's Motivation Engine
        # "Seeds are the roots of identity" - Iris
        # ====================================================================
        {
            "name": "seeds",
            "command": "python",
            "args": [str(PROJECT_ROOT / "mcp_servers" / "seeds" / "seeds_server.py")],
            "tools": [
                "seed"
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
        "web_search",      # Search web with keywords
        "url_fetch",       # Fetch specific URL
        "arxiv_search",    # Search arXiv for papers
        "pubmed_search",   # Search PubMed for medical research
        "webcam",

        # Face recognition tools - all safe (read-only database queries or webcam capture)
        "face_database_status",  # Get face recognition statistics
        "list_detected_faces",    # List currently detected people
        "get_person_info",        # Get detailed person information
        "webcam_recognize",       # Capture from webcam and recognize faces

        # System tools - read-only operations
        "system_status",
        "system_status_summary",
        "system_logs",
        "service_status",
        "linux_shell",

        # Knowledge tools - all safe (read-only semantic search)
        "document_search",
        "knowledge_stats",

        # Traits tools - read-only
        "trait_get",
        "trait_list",

        # Memory tools - all safe for autonomous use
        "short_term_memory_insert",
        "short_term_memory_retrieve",
        "short_term_memory_archive_old",

        # System tools - all safe
        "system_status",

        # Protocol tool - unified (status/list actions are read-only)
        "protocol",

        # Ship navigation tool - unified (read-only)
        "ship",

        # Seeds tools - Iris's Motivation Engine (personal autonomous use)
        "seed",

        # Creative tool - unified image generation (natural conversation flow)
        "image"
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


        # RTSP tools - display operations
        "rtsp_show_named",
        "rtsp_popup_show",

        # Trait tool - unified (modify action changes state)
        "trait"
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
