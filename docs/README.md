# Iris v3 Documentation Package

**Complete System Documentation**  
**Generated**: December 6, 2025  
**For**: Iris v3.0.0 (Organized Architecture)

---

## 📦 What's Included

This documentation package provides complete, fresh documentation for the Iris v3 codebase based on the current state of the code.

### Documentation Files

1. **[INDEX.md](computer:///mnt/user-data/outputs/INDEX.md)** - Start Here!
   - Navigation guide for all documentation
   - Learning paths for different roles
   - How to find information quickly

2. **[SYSTEM_MAP.md](computer:///mnt/user-data/outputs/SYSTEM_MAP.md)** - Architecture & Diagrams
   - 10+ Mermaid diagrams
   - Complete system architecture
   - Component relationships
   - Token budgets and flows

3. **[FILE_BREAKDOWN.md](computer:///mnt/user-data/outputs/FILE_BREAKDOWN.md)** - File Reference
   - All 33 Python files documented
   - Purpose, functions, dependencies
   - Code examples
   - Common tasks mapped to files

4. **[DATA_FLOWS.md](computer:///mnt/user-data/outputs/DATA_FLOWS.md)** - Operation Flows
   - 8 major operation flows
   - Step-by-step sequences
   - Data transformations
   - Complete examples

5. **[QUICK_REFERENCE.md](computer:///mnt/user-data/outputs/QUICK_REFERENCE.md)** - Fast Lookups
   - "Where do I change X?"
   - Configuration changes
   - Common commands
   - Troubleshooting guide

---

## 🚀 Quick Start

### For New Developers
```
1. Start with INDEX.md
2. Read SYSTEM_MAP.md 
3. Browse FILE_BREAKDOWN.md
4. Try one example from DATA_FLOWS.md
5. Bookmark QUICK_REFERENCE.md
```

### For Specific Tasks
```
- Changing config? → QUICK_REFERENCE.md
- Understanding flow? → DATA_FLOWS.md
- Finding code? → FILE_BREAKDOWN.md
- System overview? → SYSTEM_MAP.md
```

---

## 📊 Statistics

- **Total Documentation**: ~70 KB across 5 files
- **Mermaid Diagrams**: 10+ visual diagrams
- **Code Examples**: 100+ snippets
- **Files Documented**: 33 Python files
- **Operations Covered**: 8 major flows
- **Quick Ref Entries**: 50+ tasks

---

## 🎯 Coverage

✅ **Architecture**: Complete system design with diagrams  
✅ **Files**: Every file documented with purpose  
✅ **Operations**: All major flows explained  
✅ **Database**: Schema and queries documented  
✅ **Configuration**: All settings explained  
✅ **Tools**: MCP system fully documented  
✅ **Deployment**: Operations and maintenance  
✅ **Troubleshooting**: Common issues and solutions  

---

## 💡 Key Insights

### Session-Independent Memory
Sessions are for analytics only. Memory loads across ALL sessions - continuous conversation history regardless of session boundaries.

### Token Governance
Multi-level limits with priorities: fixed allocations (system prompt), high priority (memories), medium (tools), low (conversation).

### MCP Tool System
Modular, extensible tool architecture using Model Context Protocol. Easy to add new tools without touching core code.

### Vision Support
Images flow through the entire pipeline - user uploads, tool outputs, context assembly, Ollama processing.

---

## 🔧 Technology

- **Model**: Qwen 2.5 14B (configurable)
- **Context**: 32,768 tokens
- **Backend**: FastAPI + Python 3.8+
- **Database**: PostgreSQL with pgvector
- **AI**: Ollama (local LLM)
- **Tools**: MCP (Model Context Protocol)

---

## 📝 Documentation Features

### Mermaid Diagrams
All diagrams render in GitHub/IDEs **and** are pure text (readable by Claude):
- Architecture overviews
- Sequence diagrams
- Entity-relationship diagrams
- State machines
- Dependency graphs

### Code Examples
Every concept includes working examples:
- Python code snippets
- SQL queries
- Configuration samples
- API calls
- WebSocket messages

### Cross-References
Documents link to each other:
- "See SYSTEM_MAP.md for architecture"
- "Reference DATA_FLOWS.md for complete flow"
- "Check QUICK_REFERENCE.md for how-to"

---

## 🎓 Learning Paths

### Week 1 - Understanding
- Read INDEX.md
- Study SYSTEM_MAP.md diagrams
- Skim FILE_BREAKDOWN.md structure
- Work through one DATA_FLOWS.md example

### Week 2 - Practice  
- Make a config change using QUICK_REFERENCE.md
- Trace a data flow using DATA_FLOWS.md
- Find code using FILE_BREAKDOWN.md
- Debug an issue

### Week 3 - Mastery
- Contribute a feature
- Update documentation
- Review code using docs
- Help onboard others

---

## ✅ What You'll Learn

After working through this documentation:

1. Complete system architecture
2. Every component's purpose
3. How data flows through the system
4. Where to make any change
5. Database structure and queries
6. Token management strategies
7. Tool system and extension
8. Best practices and patterns
9. Deployment and operations
10. Troubleshooting techniques

---

## 🔗 Additional Resources

- **Repository**: /home/claude/
- **Config File**: app/config.py
- **Database**: PostgreSQL (irisdb)
- **API Docs**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/api/health

---

## 📅 Version Info

- **Documentation Version**: 1.0
- **Generated**: December 6, 2025
- **Iris Version**: 3.0.0
- **Codebase**: ~6,100 lines
- **Status**: ✅ Complete and current

---

## 🎯 Next Steps

1. **Read INDEX.md** - Understand the documentation structure
2. **Pick your path** - New developer vs. experienced
3. **Bookmark docs** - Keep handy for reference
4. **Make first change** - Apply what you learned
5. **Update docs** - Keep documentation current

---

**Happy coding with Iris v3! 🚀**

This documentation was generated fresh from the current codebase on December 6, 2025.
All content reflects the actual, current implementation.
