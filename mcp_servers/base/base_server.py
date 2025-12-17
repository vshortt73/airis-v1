"""
Base MCP Server for Iris v3
Provides foundation for all MCP servers
"""

from mcp.server.fastmcp import FastMCP
from typing import Dict, Any, Optional
import sys
from pathlib import Path

class IrisMCPServer:
    """
    Base class for all Iris MCP servers
    
    Provides common functionality:
    - Server initialization
    - Error handling patterns
    - Logging
    - Configuration management
    """
    
    def __init__(self, name: str, description: str = ""):
        """
        Initialize MCP server
        
        Args:
            name: Server name (e.g., "Iris Info Server")
            description: Optional server description
        """
        self.name = name
        self.description = description
        self.mcp = FastMCP(name)
        self._tools_registered = 0
        
        print(f"[{self.name}] Initialized")
    
    def register_tool(self, func):
        """
        Register a tool with the MCP server
        
        Args:
            func: Function to register as a tool
            
        Returns:
            Decorated function
        """
        decorated = self.mcp.tool()(func)
        self._tools_registered += 1
        print(f"[{self.name}] Registered tool: {func.__name__}")
        return decorated
    
    def run(self):
        """Start the MCP server"""
        print(f"[{self.name}] Starting server with {self._tools_registered} tools...")
        self.mcp.run()
    
    @staticmethod
    def format_error(error: Exception) -> Dict[str, Any]:
        """
        Standard error response format
        
        Args:
            error: Exception that occurred
            
        Returns:
            Error dictionary
        """
        return {
            "success": False,
            "error": str(error)
        }
    
    @staticmethod
    def format_success(data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Standard success response format
        
        Args:
            data: Response data
            
        Returns:
            Success dictionary with data
        """
        return {
            "success": True,
            **data
        }
