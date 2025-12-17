# Iris v3 - Complete Documentation Package

**Generated**: December 6, 2025  
**Codebase**: ~6,100 lines of Python  
**Model**: Qwen 2.5 14B  
**Version**: 3.0.0

---

## 📚 Documentation Files

This package contains four comprehensive documentation files:

### 1. [SYSTEM_MAP.md](computer:///mnt/user-data/outputs/SYSTEM_MAP.md) - System Architecture
**Purpose**: Visual understanding of the entire system  
**Contents**:
- High-level architecture diagrams (Mermaid)
- Complete request flow sequence
- Database schema with relationships
- Module dependency graphs
- Token budget allocation
- Session management flow
- Tool execution flow
- Image attachment flow
- Context assembly process
- MCP server architecture

**Use When**:
- Learning the system architecture
- Understanding component relationships
- Planning architectural changes
- Onboarding new developers
- Debugging complex interactions

---

### 2. [FILE_BREAKDOWN.md](computer:///mnt/user-data/outputs/FILE_BREAKDOWN.md) - File-by-File Reference
**Purpose**: Detailed reference for every file in the codebase  
**Contents**:
- Complete directory structure
- File-by-file breakdown with:
  - Purpose and responsibilities
  - Key functions and classes
  - Dependencies (what it uses)
  - Dependents (what uses it)
  - Code examples
  - Line counts
- Common development tasks
- File statistics

**Use When**:
- Understanding what a specific file does
- Finding where functionality lives
- Planning modifications
- Reviewing code structure
- Tracing dependencies

---

### 3. [DATA_FLOWS.md](computer:///mnt/user-data/outputs/DATA_FLOWS.md) - Complete Operation Flows
**Purpose**: Step-by-step data transformations for major operations  
**Contents**:
- Application startup flow
- User message processing (complete sequence)
- Tool execution flow with examples
- Image upload & attachment handling
- Context assembly process
- Session management logic
- Database operations
- MCP server communication

**Use When**:
- Tracing how data moves through the system
- Debugging issues
- Understanding operation sequences
- Optimizing performance
- Planning modifications to flows

---

### 4. [QUICK_REFERENCE.md](computer:///mnt/user-data/outputs/QUICK_REFERENCE.md) - "Where Do I Change X?"
**Purpose**: Fast answers for common development tasks  
**Contents**:
- Configuration changes
- Conversation & context modifications
- Tools & MCP server management
- API & endpoint additions
- Database operations
- File & attachment handling
- Ollama integration changes
- Token management
- Frontend/UI updates
- Testing & debugging
- Deployment & operations
- Common issues & solutions
- Best practices
- Quick commands

**Use When**:
- Making specific changes quickly
- Troubleshooting issues
- Learning common patterns
- Looking up commands
- Finding best practices

---

## 🎯 How to Use This Documentation

### For New Developers
**Recommended Path**:
1. Read [SYSTEM_MAP.md](computer:///mnt/user-data/outputs/SYSTEM_MAP.md) to understand the architecture
2. Skim [FILE_BREAKDOWN.md](computer:///mnt/user-data/outputs/FILE_BREAKDOWN.md) to see what files exist
3. Study one data flow in [DATA_FLOWS.md](computer:///mnt/user-data/outputs/DATA_FLOWS.md)
4. Bookmark [QUICK_REFERENCE.md](computer:///mnt/user-data/outputs/QUICK_REFERENCE.md) for daily use

**Time Investment**:
- Day 1-2: Read SYSTEM_MAP.md thoroughly
- Day 3-4: Browse FILE_BREAKDOWN.md
- Day 5: Work through DATA_FLOWS.md examples
- Week 2: Make first change using QUICK_REFERENCE.md

---

### For Experienced Developers
**Recommended Path**:
1. Use [QUICK_REFERENCE.md](computer:///mnt/user-data/outputs/QUICK_REFERENCE.md) for fast answers
2. Reference [FILE_BREAKDOWN.md](computer:///mnt/user-data/outputs/FILE_BREAKDOWN.md) when working with specific modules
3. Consult [DATA_FLOWS.md](computer:///mnt/user-data/outputs/DATA_FLOWS.md) for complex operations
4. Use [SYSTEM_MAP.md](computer:///mnt/user-data/outputs/SYSTEM_MAP.md) for architectural decisions

---

### For Code Reviews
**Focus On**:
1. [SYSTEM_MAP.md](computer:///mnt/user-data/outputs/SYSTEM_MAP.md) - Does the change fit the architecture?
2. [DATA_FLOWS.md](computer:///mnt/user-data/outputs/DATA_FLOWS.md) - Are data transformations correct?
3. [FILE_BREAKDOWN.md](computer:///mnt/user-data/outputs/FILE_BREAKDOWN.md) - Are dependencies appropriate?

---

### For Debugging
**Use**:
1. [DATA_FLOWS.md](computer:///mnt/user-data/outputs/DATA_FLOWS.md) - Trace the data path
2. [QUICK_REFERENCE.md](computer:///mnt/user-data/outputs/QUICK_REFERENCE.md) - Common issues section
3. [FILE_BREAKDOWN.md](computer:///mnt/user-data/outputs/FILE_BREAKDOWN.md) - Find the relevant code
4. [SYSTEM_MAP.md](computer:///mnt/user-data/outputs/SYSTEM_MAP.md) - Understand component interactions

---

## 🔍 Finding Information

### "How does X work?"
→ [DATA_FLOWS.md](computer:///mnt/user-data/outputs/DATA_FLOWS.md) (e.g., "How does tool execution work?")

### "What does file Y do?"
→ [FILE_BREAKDOWN.md](computer:///mnt/user-data/outputs/FILE_BREAKDOWN.md) (complete file reference)

### "Where do I change Z?"
→ [QUICK_REFERENCE.md](computer:///mnt/user-data/outputs/QUICK_REFERENCE.md) (indexed by task)

### "How are A and B connected?"
→ [SYSTEM_MAP.md](computer:///mnt/user-data/outputs/SYSTEM_MAP.md) (dependency graphs)

### "What's the overall architecture?"
→ [SYSTEM_MAP.md](computer:///mnt/user-data/outputs/SYSTEM_MAP.md) (diagrams and overview)

---

## 📊 Documentation Statistics

- **Total Pages**: ~100+ pages
- **Mermaid Diagrams**: 10+ architectural diagrams
- **Code Examples**: 100+ code snippets
- **File Coverage**: All 33 core Python files documented
- **Operations Documented**: 8 major flows
- **Quick Reference Entries**: 50+ common tasks

---

## 🎨 Diagram Key (Mermaid)

All diagrams use these conventions:

**Shapes**:
- Rectangles: Components, modules, files
- Cylinders: Databases
- Parallelograms: Data inputs/outputs
- Diamonds: Decision points
- Circles: Start/end states

**Colors**:
- Blue (`#e1f5ff`): User-facing, input
- Red/Pink (`#ffe1e1`): Storage, database
- Yellow (`#fff4e1`): AI/Ollama components
- Green (`#e1ffe1`): Tool system, processing

**Arrows**:
- Solid: Synchronous calls / Direct dependencies
- Dashed: Async calls / Loose coupling

---

## 🔧 Technology Stack

**Backend**:
- Python 3.8+
- FastAPI (web framework)
- PostgreSQL (database)
- psycopg2 (database driver)
- tiktoken (token counting)
- httpx (HTTP client)
- FastMCP (MCP framework)

**AI/ML**:
- Ollama (local LLM server)
- Qwen 2.5 14B (default model)

**Frontend**:
- Vanilla JavaScript
- WebSocket API
- HTML5/CSS3

**Tools**:
- MCP (Model Context Protocol)
- JSON-RPC (server communication)
- Base64 encoding (images)

---

## 📈 Project Scale

- **Lines of Code**: ~6,100 (Python)
- **Python Files**: 33 core files
- **Database Tables**: 10+ tables
- **API Endpoints**: 10+ endpoints
- **MCP Tools**: 20+ tools across 3+ servers
- **Dependencies**: 10+ Python packages

---

## 🎯 Core Architecture Principles

1. **Session-Independent Memory**: History loads across ALL sessions
2. **Time-Based Sessions**: 30-minute gap creates new session (analytics only)
3. **Token Governance**: Multi-level limits prevent context overflow
4. **Explicit Context**: Always set Ollama's `num_ctx` parameter
5. **Database-Driven**: System prompts and tools from PostgreSQL
6. **Streaming Responses**: Real-time UI updates via WebSocket
7. **Modular Tools**: MCP servers for extensibility
8. **Vision Support**: Images flow through entire conversation pipeline

---

## 🚀 Quick Start Commands

```bash
# Set database password
export IRIS_DB_PASSWORD='your_password'

# Start Iris
./scripts/start.sh

# Test database
python tests/test_database.py

# View context
curl http://localhost:8000/api/conversation/context/summary | jq

# Check health
curl http://localhost:8000/api/health
```

---

## 📝 Documentation Maintenance

### When to Update

**SYSTEM_MAP.md**:
- Adding new modules or major components
- Changing architecture patterns
- Modifying data flow between components

**FILE_BREAKDOWN.md**:
- Creating new files
- Changing file responsibilities
- Adding/removing dependencies

**DATA_FLOWS.md**:
- Modifying operation sequences
- Changing data transformations
- Adding new major operations

**QUICK_REFERENCE.md**:
- Adding new configuration options
- Creating new common tasks
- Discovering new debugging techniques

---

## 🤝 Contributing to Documentation

When contributing code, please:

1. **Update relevant docs** for your changes
2. **Add code examples** for new functionality
3. **Update diagrams** if architecture changes
4. **Add to Quick Reference** if creating common tasks
5. **Document database changes** (schema, queries)
6. **Include error handling** in data flows

---

## 🎓 Learning Path

**Week 1 - Understanding**:
- Day 1-2: Read SYSTEM_MAP.md thoroughly
- Day 3-4: Skim FILE_BREAKDOWN.md
- Day 5: Work through a data flow in DATA_FLOWS.md

**Week 2 - Hands-On**:
- Day 1-3: Make a small change using QUICK_REFERENCE.md
- Day 4-5: Debug an issue using the documentation

**Week 3 - Mastery**:
- Contribute a new feature
- Update documentation for your changes
- Review someone else's code using the docs

---

## 🔗 Related Resources

- **README.md** - Project readme with setup instructions
- **CLAUDE.md** - Developer guide for Claude Code integration
- **DEPLOYMENT.md** - Deployment and operations guide
- **IMPLEMENTATION_STATUS.md** - Current implementation status
- **requirements.txt** - Python dependencies
- **Database schema** - SQL migration files

---

## 📅 Documentation Version

- **Version**: 1.0
- **Generated**: December 6, 2025
- **Iris Version**: v3.0.0 (Organized Architecture)
- **Status**: ✅ Complete and current

---

## ✅ Documentation Completeness

- [x] System architecture documented with diagrams
- [x] All files documented with purpose and dependencies
- [x] Major data flows documented with examples
- [x] Quick reference guide created
- [x] Mermaid diagrams for visualization
- [x] Database schema documented
- [x] API endpoints documented
- [x] Error handling documented
- [x] Configuration options documented
- [x] Best practices included
- [x] Common issues and solutions
- [x] Code examples throughout
- [x] Cross-references between documents

---

## 🎯 What You'll Know After Reading

After working through this documentation, you'll understand:

1. ✅ Complete system architecture and component interactions
2. ✅ How every major operation works (message → response, tools, sessions)
3. ✅ Where to find any piece of functionality
4. ✅ How to make changes safely and effectively
5. ✅ Database schema and all relationships
6. ✅ Token management and context limits
7. ✅ MCP tool system and how to extend it
8. ✅ Error handling and recovery strategies
9. ✅ Configuration and deployment options
10. ✅ Best practices and common patterns

---

## 📧 Questions or Issues?

If you find:
- Missing information
- Unclear explanations
- Outdated content
- Broken examples
- Incorrect diagrams

Please update the documentation or create an issue for review.

---

**Welcome to Iris v3! This documentation provides everything you need to work effectively with the codebase. Happy coding! 🚀**
