"""
Iris v3 - FastAPI Application
Main application entry point
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import sys
import os
import json
from app.api import routes_chat, routes_session, routes_context, routes_tts, routes_vision, routes_protocols, routes_ephemeral, routes_stt, routes_faces, routes_admin, routes_video, routes_florence2, routes_paddleocr, routes_gpu

# Add project root to path
import os; PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..' if '__file__' in dir() else '.')); sys.path.insert(0, PROJECT_ROOT)

from app import config
from core.conversation import ConversationHistory
from app.api import routes_chat, routes_session, routes_context, routes_tts, routes_vision, routes_protocols, routes_ephemeral
from database.character_traits import get_trait_list
from core.system_prompt import build_system_message


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown events"""
    # === STARTUP ===
    print("[main.py] Starting background services...")

    # Detect current GPU service on Node2
    try:
        from core.gpu_manager import get_gpu_manager
        gpu = get_gpu_manager()
        current = await gpu.detect_current_service()
        if current:
            print(f"[main.py] ✓ Node2 GPU 0: {current} running")
        else:
            print(f"[main.py] Node2 GPU 0: no service detected")
    except Exception as e:
        print(f"[main.py] ✗ Failed to detect Node2 GPU service: {e}")

    # Start face monitoring service
    try:
        from services import face_monitor
        if getattr(config, 'FACE_MONITORING_ENABLED', True):
            interval = getattr(config, 'FACE_MONITORING_INTERVAL_SECONDS', 5)
            face_monitor.start_monitoring(interval_seconds=interval)
            print(f"[main.py] ✓ Face monitoring started (interval: {interval}s)")
        else:
            print("[main.py] Face monitoring disabled in config")
    except Exception as e:
        print(f"[main.py] ✗ Failed to start face monitoring: {e}")

    yield  # App runs here

    # === SHUTDOWN ===
    print("[main.py] Stopping background services...")

    try:
        from services import face_monitor
        face_monitor.stop_monitoring()
        print("[main.py] ✓ Face monitoring stopped")
    except Exception as e:
        print(f"[main.py] ✗ Error stopping face monitoring: {e}")


# Create FastAPI app
app = FastAPI(
    title="Iris v3",
    description="AI Assistant",
    version="3.0.0",
    lifespan=lifespan
)

# Add CORS middleware to allow requests from browser
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for local testing
    allow_credentials=True,
    allow_methods=["*"],  # Allow all methods (GET, POST, etc.)
    allow_headers=["*"],  # Allow all headers
)

# Mount attachments directory as static files
# This allows serving images via URLs instead of base64 encoding
attachments_path = os.path.join(os.path.dirname(__file__), "..", "attachments")
app.mount("/attachments", StaticFiles(directory=attachments_path), name="attachments")

# Mount assets directory for 3D models, audio, etc.
assets_path = os.path.join(os.path.dirname(__file__), "..", "assets")
app.mount("/assets", StaticFiles(directory=assets_path), name="assets")

# Mount static directory for HTML/CSS/JS files
static_path = os.path.join(os.path.dirname(__file__), "..", "static")
app.mount("/static", StaticFiles(directory=static_path), name="static")

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
app.include_router(routes_protocols.router, prefix="/api", tags=["protocols"])
app.include_router(routes_ephemeral.router, tags=["ephemeral"])
app.include_router(routes_stt.router)
app.include_router(routes_faces.router, tags=["faces"])
app.include_router(routes_admin.router, tags=["admin"])
app.include_router(routes_video.router, tags=["video"])
app.include_router(routes_florence2.router, tags=["florence2"])
app.include_router(routes_paddleocr.router, tags=["ocr"])
app.include_router(routes_gpu.router, tags=["gpu"])

@app.get("/prompt")
def show_prompt():
    """
    Show the complete system prompt that would be sent to Ollama
    
    This mirrors what assemble_full_context() does:
    1. Loads recent conversation
    2. Extracts last user message
    3. Builds system message with fast reactive context
    """
    from database.persistence import load_recent_conversation
    
    # Load recent conversation to get last user message
    # (same as what happens in real chat)
    recent = load_recent_conversation(max_messages=10)
    
    # Find last user message (same logic as in assemble_full_context)
    user_message = None
    for msg in reversed(recent):
        if msg.get('role') == 'user':
            user_message = msg.get('content', '')
            break
    
    # Build system message with fast reactive context
    # (if there's a user message, fast memory will search)
    msg = build_system_message(user_message=user_message)
    
    # Return the system message
    # This shows EXACTLY what Iris sees, including fast context if found
    return msg



@app.get("/")
async def root():
    """Serve the chat interface"""
    static_path = os.path.join(os.path.dirname(__file__), "..", "static", "index.html")
    with open(static_path, "r") as f:
        return HTMLResponse(content=f.read())

@app.get("/protocols")
async def protocol_editor():
    """Serve the protocol editor"""
    editor_path = os.path.join(os.path.dirname(__file__), "..", "static", "protocol_editor.html")
    with open(editor_path, "r") as f:
        return HTMLResponse(content=f.read())

@app.get("/ephemeral")
async def ephemeral_chat():
    """Serve the ephemeral chat interface"""
    chat_path = os.path.join(os.path.dirname(__file__), "..", "static", "ephemeral_chat.html")
    with open(chat_path, "r") as f:
        return HTMLResponse(content=f.read())

@app.get("/faces")
async def face_manager():
    """Serve the face recognition manager"""
    face_path = os.path.join(os.path.dirname(__file__), "..", "static", "face_manager.html")
    with open(face_path, "r") as f:
        return HTMLResponse(content=f.read())

@app.get("/admin")
async def admin_console():
    """Serve the admin console"""
    admin_path = os.path.join(os.path.dirname(__file__), "..", "static", "admin.html")
    with open(admin_path, "r") as f:
        return HTMLResponse(content=f.read())

@app.get("/florence2")
async def florence2_lab():
    """Serve the Florence2 experiment UI"""
    florence2_path = os.path.join(os.path.dirname(__file__), "..", "static", "florence2_lab.html")
    with open(florence2_path, "r") as f:
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

@app.get("/api/ui-videos")
async def list_ui_videos():
    """List available UI videos for idle and thinking states"""
    import glob

    ui_videos_path = os.path.join(os.path.dirname(__file__), "..", "static", "ui-videos")

    # Get idle videos
    idle_path = os.path.join(ui_videos_path, "idle")
    idle_videos = []
    if os.path.exists(idle_path):
        for f in os.listdir(idle_path):
            if f.lower().endswith(('.mp4', '.webm', '.mov')):
                idle_videos.append(f"/static/ui-videos/idle/{f}")

    # Get thinking videos
    thinking_path = os.path.join(ui_videos_path, "thinking")
    thinking_videos = []
    if os.path.exists(thinking_path):
        for f in os.listdir(thinking_path):
            if f.lower().endswith(('.mp4', '.webm', '.mov')):
                thinking_videos.append(f"/static/ui-videos/thinking/{f}")

    return {
        "idle": sorted(idle_videos),
        "thinking": sorted(thinking_videos)
    }




if __name__ == "__main__":
    import uvicorn
    from pathlib import Path

    # SSL certificate paths
    ssl_dir = Path(__file__).parent.parent / "ssl"
    ssl_keyfile = ssl_dir / "key.pem"
    ssl_certfile = ssl_dir / "cert.pem"

    # Check if SSL certificates exist
    use_ssl = ssl_keyfile.exists() and ssl_certfile.exists()
    protocol = "HTTPS" if use_ssl else "HTTP"

    print(f"[main.py] Starting Iris v3 on {config.HOST}:{config.PORT} ({protocol})")
    print(f"[main.py] Model: {config.OLLAMA_MODEL}")
    print(f"[main.py] Context Window: {config.OLLAMA_CONTEXT_WINDOW} tokens")
    print(f"[main.py] Session Timeout: {config.SESSION_TIMEOUT_MINUTES} minutes")

    if use_ssl:
        print(f"[main.py] SSL Enabled: {ssl_certfile}")
        print(f"[main.py] Access at: https://{config.HOST}:{config.PORT}/")
        uvicorn.run(
            app,
            host=config.HOST,
            port=config.PORT,
            log_level="info",
            ssl_keyfile=str(ssl_keyfile),
            ssl_certfile=str(ssl_certfile),
            ws="wsproto"  # Use wsproto instead of deprecated websockets
        )
    else:
        print(f"[main.py] SSL Disabled (no certificates found)")
        print(f"[main.py] Access at: http://{config.HOST}:{config.PORT}/")
        uvicorn.run(
            app,
            host=config.HOST,
            port=config.PORT,
            log_level="info",
            ws="wsproto"  # Use wsproto instead of deprecated websockets
        )
