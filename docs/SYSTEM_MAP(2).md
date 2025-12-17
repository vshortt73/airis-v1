# Iris v3 - System Architecture Map

**Generated**: December 6, 2025  
**Codebase**: ~6,100 lines of Python  
**Model**: Qwen 2.5 14B (configurable)  
**Context Window**: 32,768 tokens

---

## Table of Contents

1. [High-Level System Overview](#high-level-system-overview)
2. [Core Request Flow](#core-request-flow)
3. [Database Schema](#database-schema)
4. [Module Dependencies](#module-dependencies)
5. [Token Budget](#token-budget)
6. [Session Management](#session-management)
7. [Tool Execution](#tool-execution)
8. [Image Flow](#image-flow)
9. [Context Assembly](#context-assembly)
10. [MCP Architecture](#mcp-architecture)
11. [Quick Reference](#quick-reference)

---

## High-Level System Overview

```mermaid
graph TB
    User[👤 User] --> WebUI[🌐 index.html]
    WebUI --> FastAPI[⚡ main.py]
    FastAPI --> WSChat[🔌 routes_chat.py]
    
    WSChat --> Conv[💬 conversation.py]
    WSChat --> Ollama[🤖 ollama/client.py]
    WSChat --> ToolMgr[🔧 tool_manager.py]
    
    Conv --> DB[(🗄️ PostgreSQL)]
    Ollama --> OllamaAPI[🦙 Ollama :11434]
    ToolMgr --> MCP[🔌 mcp_client.py]
    
    MCP --> Info[📰 info_server]
    MCP --> Traits[🎭 traits_server]
    MCP --> Creative[🎨 creative_server]
    
    style User fill:#e1f5ff
    style DB fill:#ffe1e1
    style OllamaAPI fill:#fff4e1
```

---

## Core Request Flow

```mermaid
sequenceDiagram
    participant U as User
    participant W as WebSocket<br/>(routes_chat.py)
    participant C as Conversation
    participant S as SystemPrompt
    participant O as Ollama
    participant T as ToolManager
    participant D as Database
    
    Note over U,D: User sends message
    U->>W: message + images
    W->>C: add_user_message()
    C->>D: save to chat_history
    
    Note over W,S: Assemble context
    W->>S: assemble_full_context()
    S->>D: load system prompt
    S->>D: load traits & memories
    S->>C: get conversation messages
    S->>S: load & encode images
    S-->>W: full context array
    
    Note over W,T: Get tools
    W->>T: get_tool_definitions()
    T-->>W: tool schemas
    
    Note over W,O: First Ollama call (non-streaming)
    W->>O: chat_completion_with_tools()
    O-->>W: response
    
    alt Ollama calls tool(s)
        Note over W,T: Execute tool(s)
        loop Each tool call
            W->>T: execute_tool(name, params)
            T->>T: call MCP server
            T-->>W: tool result
            W->>C: add_tool_message()
            C->>D: save tool result
        end
        
        W->>C: add_assistant_message("")<br/>with tool_calls
        C->>D: save assistant msg
        
        Note over W,S: Reassemble context with results
        W->>S: assemble_full_context()
        S-->>W: updated context
        
        Note over W,O: Second Ollama call (streaming)
        W->>O: chat_completion_stream()
        loop Stream response
            O-->>W: chunk
            W->>U: send chunk
        end
    else No tool calls (direct response)
        W->>U: send response
        W->>C: add_assistant_message()
        C->>D: save message
    end
    
    Note over W,C: Save final response
    W->>C: add_assistant_message()
    C->>D: save to chat_history
    W->>U: done signal
```

---

## Complete Turn Flow (Linear)

Simple step-by-step flow from user message to assistant response:

```mermaid
flowchart TD
    Start([User Sends Message]) --> SaveUser[Save User Message to DB]
    SaveUser --> LoadPrompt[Load System Prompt from DB]
    LoadPrompt --> LoadTraits[Load Character Traits from DB]
    LoadTraits --> LoadMemories[Load Episodic Memories from DB]
    LoadMemories --> LoadHistory[Load Conversation History from DB]
    LoadHistory --> LoadImages[Load & Encode Any Images]
    LoadImages --> BuildContext[Build Complete Context Array]
    
    BuildContext --> GetTools[Get Tool Definitions from DB]
    GetTools --> FirstCall[Call Ollama with Tools<br/>non-streaming]
    
    FirstCall --> CheckTools{Did Ollama<br/>call tools?}
    
    CheckTools -->|Yes| LoopTools[Execute Each Tool via MCP]
    LoopTools --> SaveToolResults[Save Tool Results to DB]
    SaveToolResults --> SaveAssistantTools[Save Assistant Message<br/>with tool_calls to DB]
    SaveAssistantTools --> RebuildContext[Rebuild Context<br/>with Tool Results]
    RebuildContext --> SecondCall[Call Ollama Streaming<br/>for Final Response]
    
    CheckTools -->|No| DirectResponse[Use Direct Response]
    DirectResponse --> SaveAssistant[Save Assistant Message to DB]
    SaveAssistant --> Done([Send Done Signal])
    
    SecondCall --> StreamToUser[Stream Chunks to User]
    StreamToUser --> SaveFinal[Save Final Assistant<br/>Message to DB]
    SaveFinal --> Done
    
    style Start fill:#e1f5ff
    style Done fill:#e1ffe1
    style CheckTools fill:#fff4e1
    style LoopTools fill:#ffe1e1
```

**Key Points**:
- **Context Assembly**: Steps 2-7 build the complete context
- **Two Paths**: Tool execution path vs. direct response path
- **Two Ollama Calls**: First with tools (if used), second for streaming
- **Database Saves**: User message, tool results, assistant message(s)

---

## Database Schema

```mermaid
erDiagram
    CHAT_SESSIONS ||--o{ CHAT_HISTORY : contains
    CHAT_HISTORY ||--o{ ATTACHMENTS : has
    CHARACTER_TRAITS ||--o{ TRAIT_LOG : modified
    MCP_SERVERS ||--o{ MCP_TOOLS : provides
    
    CHAT_SESSIONS {
        uuid session_id PK
        timestamp start_time
        int message_count
    }
    
    CHAT_HISTORY {
        serial id PK
        uuid session_id FK
        string role
        text message
        jsonb tool_calls
        jsonb attachments
    }
    
    CHARACTER_TRAITS {
        serial id PK
        string name
        string value
    }
    
    MCP_TOOLS {
        serial id PK
        string tool_name
        jsonb schema
        boolean enabled
    }
```

**Critical**: Sessions are for analytics only. Memory loads across ALL sessions!

---

## Module Dependencies

```mermaid
graph LR
    Main[main.py] --> Routes
    Routes --> Conv[conversation.py]
    Routes --> Ollama[client.py]
    Routes --> Tools[tool_manager.py]
    
    Conv --> DB[persistence.py]
    Conv --> Tokens[token_counter.py]
    
    SysPrompt[system_prompt.py] --> DB
    SysPrompt --> Traits[character_traits.py]
    SysPrompt --> Memory[memory_loader.py]
    
    Tools --> MCP[mcp_client.py]
    MCP --> Servers[MCP Servers]
```

---

## Token Budget

**Total Context**: 32,768 tokens

| Component | Tokens | Priority |
|-----------|--------|----------|
| System Prompt | 600 | Fixed |
| Character Traits | 200 | Fixed |
| Response Buffer | 2,500 | Fixed |
| Episodic Memory | 2,500 | High |
| Tool Definitions | 1,500 | Medium |
| Tool Results | 800 | Medium |
| Conversation | 7,000 | Low |

**Truncation Order**: Oldest conversation → Tool results → Tool defs → Memory

---

## Session Management

```mermaid
stateDiagram-v2
    [*] --> CheckGap
    CheckGap --> Continue: < 30 min
    CheckGap --> NewSession: >= 30 min
    Continue --> [*]
    NewSession --> [*]
    
    note right of NewSession
        New UUID generated
        For analytics only
        Memory spans sessions
    end note
```

---

## Tool Execution

```mermaid
graph TB
    Ollama[Ollama calls tool] --> TM[ToolManager]
    TM --> Check{Confirmation<br/>required?}
    Check -->|Yes| Wait[Wait for approval]
    Check -->|No| Exec[Execute via MCP]
    Wait --> Exec
    Exec --> Result[Format result]
    Result --> DB[Save to history]
```

---

## Image Flow

**User Uploads**:
1. Base64 in WebSocket → Save to `attachments/user/`
2. Create metadata → Save to `attachments` table
3. Add to `chat_history.attachments` JSON

**Tool Generated**:
1. Tool returns filename
2. Load file → Encode base64
3. Save to `attachments/generated/`
4. Add metadata to DB

**Context Loading**:
1. Load messages with attachments JSON
2. Parse JSON → Load files → Encode
3. Add `images` array to message
4. Send to Ollama with images

---

## Context Assembly

1. **System Message**: Load instructions + traits + memories
2. **Load History**: Last 30 turns across ALL sessions
3. **Process Images**: Parse attachments, load files, encode
4. **Format**: Add role, content, tool_calls, images
5. **Token Check**: Truncate if over 12,000 tokens

---

## MCP Architecture

**Servers**:
- **info_server**: weather, news, web search
- **traits_server**: personality modification
- **creative_server**: image generation (ComfyUI)

**Communication**: stdio/JSON-RPC  
**Lifecycle**: Managed by MCPClient  
**Tool Discovery**: Schemas in database

---

## Quick Reference

| Change | File |
|--------|------|
| Model | `config.py` → OLLAMA_MODEL |
| Context window | `config.py` → OLLAMA_CONTEXT_WINDOW |
| Session timeout | `config.py` → SESSION_TIMEOUT_MINUTES |
| Token limits | `config.py` → MAX_CONTEXT_TOKENS |
| Chat flow | `routes_chat.py` |
| Context assembly | `system_prompt.py` |
| Message loading | `persistence.py` |
| Tool execution | `tool_manager.py` |
| Add MCP server | `mcp_servers/{name}/` + `server_configs.py` |
| System prompt | Database: `system_instructions` table |

---

## Architecture Principles

1. **Session-Independent Memory**: Load across ALL sessions
2. **Token Governance**: Multi-level limits with priorities
3. **Database-Driven**: Prompts and tools from PostgreSQL
4. **Streaming**: Real-time WebSocket updates
5. **Vision**: Images throughout entire pipeline
6. **MCP Tools**: Modular, extensible tool system
7. **Explicit Context**: Always set `num_ctx` for Ollama

---

**Documentation Generated**: December 6, 2025
