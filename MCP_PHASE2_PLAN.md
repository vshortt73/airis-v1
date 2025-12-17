MCP Phase 2 Plan: Iris IntegrationSession Summary - What We Accomplished Today✅ Complete Vision System (Phases 1-5)

Attachment module with file I/O
Database integration for image persistence
Conversation layer with image support
Ollama vision integration (Iris can SEE!)
UI with paste/upload functionality
Result: Iris remembers images across sessions and can describe them
✅ MCP Phase 1 Foundation

Base MCP server class
Info server with weather tool
Test suite proving MCP works
Result: Clean, testable MCP architecture
Current StateWorking:

Vision system 100% operational
MCP servers can be built and run independently
Weather tool tested and working
Database has all 24 tool definitions with metadata
Next: Connect Iris to MCP servers for autonomous tool usePhase 2 ArchitectureThe FlowUser: "What's the weather in Seattle?"
    ↓
Iris receives message
    ↓
Assemble context + Available tools (from DB)
    ↓
Send to Ollama with tool definitions
    ↓
Ollama decides: "I should call weather_get"
    ↓
Tool call intercepted
    ↓
MCP Client routes to Info Server
    ↓
Info Server executes weather_get("Seattle")
    ↓
Result returns: {success: true, temperature: 45, ...}
    ↓
Add tool result to conversation
    ↓
Send back to Ollama with tool result
    ↓
Ollama generates final response: "It's 45°F and rainy in Seattle"
    ↓
Stream to userDatabase SchemaTable: mcp_toolsKey Fields:

tool_name - Function name (e.g., "weather_get")
description - What it does
input_schema - JSON Schema for parameters (Ollama format!)
enabled - bool - Only load enabled tools
priority - int - Lower = higher priority
custom_instructions - Extra guidance for Iris on when/how to use
icon - emoji for UI display
Sample Tool:
json{
  "tool_name": "weather_get",
  "description": "Get current weather information for a location...",
  "input_schema": {
    "type": "object",
    "required": ["location"],
    "properties": {
      "location": {"type": "string"},
      "units": {"type": "string", "default": "imperial"}
    }
  },
  "enabled": true,
  "priority": 100,
  "custom_instructions": null,
  "icon": "🌧"
}What Needs To Be Built1. Tool Loader (mcp_servers/tool_loader.py)Purpose: Load enabled tools from database and format for Ollamapythondef load_enabled_tools() -> List[Dict]:
    """
    Load enabled tools from database
    
    Returns:
        List of tool definitions in Ollama format:
        [{
            "type": "function",
            "function": {
                "name": "weather_get",
                "description": "...",
                "parameters": {...input_schema...}
            }
        }]
    """Key features:

Query mcp_tools table WHERE enabled=true
Order by priority ASC (lower priority = loaded first)
Convert input_schema to Ollama function format
Include custom_instructions in description
2. MCP Client (mcp_servers/mcp_client.py)Purpose: Connect to MCP servers and execute tool callspythonclass MCPClient:
    """
    Client to connect to and execute tools on MCP servers
    
    Manages connections to multiple MCP servers:
    - info server (weather, news, web_fetch)
    - system server (status, logs, services)
    - traits server (trait operations)
    - knowledge server (document search)
    - creative server (image generation)
    """
    
    def __init__(self, server_configs: List[Dict]):
        """Initialize connections to MCP servers"""
        
    async def call_tool(self, tool_name: str, parameters: Dict) -> Dict:
        """
        Execute a tool call
        
        Args:
            tool_name: Name of tool to call
            parameters: Tool parameters
            
        Returns:
            Tool result
        """Key features:

Maintain connections to multiple MCP servers
Route tool calls to correct server
Handle connection failures gracefully
Retry logic for transient failures
3. Tool Manager (mcp_servers/tool_manager.py)Purpose: Orchestrate tool loading and executionpythonclass ToolManager:
    """
    Manages tool discovery and execution
    
    Coordinates between:
    - Database (tool definitions)
    - MCP Client (tool execution)
    - Conversation system (tool results)
    """
    
    def __init__(self):
        self.tools = load_enabled_tools()
        self.mcp_client = MCPClient(get_server_configs())
    
    def get_tool_definitions_for_ollama(self) -> List[Dict]:
        """Get tools in Ollama function calling format"""
        
    async def execute_tool(self, tool_name: str, parameters: Dict) -> Dict:
        """Execute a tool via MCP"""4. Conversation IntegrationModify: app/api/routes_chat.pyChanges needed:
pythonfrom mcp_servers.tool_manager import ToolManager

# Initialize tool manager globally
tool_manager = ToolManager()

@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    # ... existing code ...
    
    # Assemble context with tools
    all_messages, budget = assemble_full_context(active_conversation)
    tool_definitions = tool_manager.get_tool_definitions_for_ollama()
    
    # First call to Ollama (may return tool calls)
    response = await chat_completion_with_tools(
        all_messages, 
        tools=tool_definitions
    )
    
    # Check if Ollama wants to use tools
    if response.has_tool_calls():
        # Execute tools
        for tool_call in response.tool_calls:
            result = await tool_manager.execute_tool(
                tool_call.name,
                tool_call.parameters
            )
            
            # Add tool result to conversation
            active_conversation.add_tool_message(
                content=json.dumps(result),
                tool_name=tool_call.name,
                tool_call_id=tool_call.id
            )
        
        # Reassemble context with tool results
        all_messages, budget = assemble_full_context(active_conversation)
        
        # Second call to Ollama (generates final response)
        response = await chat_completion_stream(all_messages)
    
    # Stream response to user
    # ... existing streaming code ...5. Ollama Client EnhancementModify: ollama/client.pyAdd: Function to handle tool callspythonasync def chat_completion_with_tools(
    messages: List[Dict],
    tools: List[Dict] = None
) -> ToolCallResponse:
    """
    Send chat request that may include tool calls
    
    Returns:
        Response object that may contain tool_calls
    """MCP Server ConfigurationsCreate: mcp_servers/server_configs.pypythondef get_server_configs() -> List[Dict]:
    """
    Get MCP server connection configurations
    
    Returns:
        List of server configs:
        [{
            "name": "info",
            "command": "python",
            "args": ["/iris-v3/mcp_servers/info/info_server.py"],
            "tools": ["weather_get", "news_headlines", "web_fetch", ...]
        }, ...]
    """Testing StrategyTest 1: Tool Loading
pythondef test_load_tools_from_database():
    tools = load_enabled_tools()
    assert len(tools) > 0
    assert tools[0]["type"] == "function"
    assert "weather_get" in [t["function"]["name"] for t in tools]Test 2: MCP Client Connection
pythonasync def test_mcp_client_connects():
    client = MCPClient(get_server_configs())
    result = await client.call_tool("weather_get", {"location": "Seattle"})
    assert result["success"] == TrueTest 3: End-to-End Tool Call
pythonasync def test_iris_uses_tool():
    # Send message to Iris
    # Verify tool was called
    # Verify response includes tool resultTool-to-Server MappingInfo Server:

weather_get
forecast_get
news_headlines
web_fetch
webcam
rtsp_show_named
rtsp_popup_show
System Server:

system_status
system_status_summary
system_logs
service_status
service_start
service_stop
service_restart
monitor_add
monitor_list
monitor_remove
Knowledge Server:

document_search
knowledge_search
knowledge_stats
Traits Server:

trait_get
trait_list
trait_modify (REQUIRES SAFETY!)
Creative Server:

image_generate
image_generate_iris
Safety ConsiderationsAutonomous (no confirmation):

weather_get, forecast_get
news_headlines
web_fetch
system_status, system_status_summary
trait_get, trait_list
document_search, knowledge_search
webcam
Requires confirmation:

service_start, service_stop, service_restart
monitor_add, monitor_remove
trait_modify
image generation (optional - could be autonomous)
Implementation Order
Tool Loader - Load from DB, format for Ollama
MCP Client - Connect to servers, execute calls
Tool Manager - Orchestrate everything
Ollama Enhancement - Handle tool calls
Routes Integration - Wire into chat flow
Test Suite - Verify end-to-end
Success CriteriaPhase 2 is complete when:

✅ Iris can discover available tools from database
✅ Ollama receives tool definitions
✅ Ollama decides to call tools autonomously
✅ Tool calls route to correct MCP server
✅ Tool results return to conversation
✅ Iris generates response using tool results
✅ User sees natural response with tool-enhanced information
Next Steps for New Session
Create mcp_servers/tool_loader.py
Create mcp_servers/mcp_client.py
Create mcp_servers/tool_manager.py
Enhance ollama/client.py
Update app/api/routes_chat.py
Create test_mcp_phase2.py
Test: "Iris, what's the weather in Seattle?"
Verify she autonomously calls weather_get and responds naturally
Files You'll Need In Next Session
Current routes_chat.py
Current ollama/client.py
The mcp_tools.json (or direct DB access)
Info server from Phase 1
Current Architecture State/iris-v3/
├── core/
│   ├── attachments.py ✅
│   ├── conversation.py ✅
│   └── system_prompt.py ✅
├── database/
│   └── persistence.py ✅
├── ollama/
│   └── client.py ⚠️ (needs tool support)
├── app/api/
│   └── routes_chat.py ⚠️ (needs tool integration)
├── mcp_servers/
│   ├── base/
│   │   └── base_server.py ✅
│   ├── info/
│   │   └── info_server.py ✅
│   ├── tool_loader.py ❌ (Phase 2)
│   ├── mcp_client.py ❌ (Phase 2)
│   ├── tool_manager.py ❌ (Phase 2)
│   └── server_configs.py ❌ (Phase 2)
└── static/
    └── index.html ✅Remember
Same methodology: Build → Test → Verify → Integrate
Start with ONE tool working end-to-end (weather)
Then scale to all 24 tools
Each server is independent and testable
Phase 2 will give Iris autonomous tool use! 🚀When you start the next session, say:
"I'm ready to continue MCP Phase 2. We finished Phase 1 with the weather tool working. Now we need to integrate tool calling into Iris's conversation flow so she can autonomously use tools. I have the Phase 2 plan document."Then upload this document and we'll build it! 💪