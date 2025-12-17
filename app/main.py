"""
Iris v3 - FastAPI Application
Main application entry point
"""

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import sys
import os
import json

# Add project root to path
import os; PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..' if '__file__' in dir() else '.')); sys.path.insert(0, PROJECT_ROOT)

from app import config
from core.conversation import ConversationHistory
from app.api import routes_chat, routes_session, routes_context, routes_tts, routes_vision
from database.character_traits import get_trait_list
from core.system_prompt import build_system_message

# Create FastAPI app
app = FastAPI(
    title="Iris v3",
    description="AI Assistant",
    version="3.0.0"
)

# Initialize conversation
# Persistnace = "store in database" no persistance "use session only"
active_conversation = ConversationHistory(enable_persistence=True)

# Set active conversation in route modules
routes_chat.set_active_conversation(active_conversation)
routes_session.set_active_conversation(active_conversation)
routes_context.set_active_conversation(active_conversation)

# Include routers
app.include_router(routes_chat.router)
app.include_router(routes_session.router)
app.include_router(routes_context.router)
app.include_router(routes_tts.router)
app.include_router(routes_vision.router, prefix="/api/vision", tags=["vision"])

@app.get("/prompt")
def show_prompt():
    msg = build_system_message()
    return msg

@app.get("/")
async def root():
    """Serve the chat interface"""
    static_path = os.path.join(os.path.dirname(__file__), "..", "static", "index.html")
    with open(static_path, "r") as f:
        return HTMLResponse(content=f.read())

@app.get("/api/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "ok",
        "model": config.OLLAMA_MODEL,
        "context_window": config.OLLAMA_CONTEXT_WINDOW,
        "session_timeout_minutes": config.SESSION_TIMEOUT_MINUTES,
        "max_conversation_turns": config.MAX_CONVERSATION_TURNS,
        "max_context_tokens": config.MAX_CONTEXT_TOKENS,
        "vision_enabled": config.VISION_ENABLED
    }

if __name__ == "__main__":
    import uvicorn
    print(f"[main.py] Starting Iris v3 on {config.HOST}:{config.PORT}")
    print(f"[main.py] Model: {config.OLLAMA_MODEL}")
    print(f"[main.py] Context Window: {config.OLLAMA_CONTEXT_WINDOW} tokens")
    print(f"[main.py] Session Timeout: {config.SESSION_TIMEOUT_MINUTES} minutes")
    uvicorn.run(
        app,
        host=config.HOST,
        port=config.PORT,
        log_level="info"
    )
