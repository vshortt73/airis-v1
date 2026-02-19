"""
Airis v1 - FastAPI Application
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

# Suppress huggingface tokenizers fork warning that pollutes journal on every subprocess spawn
os.environ["TOKENIZERS_PARALLELISM"] = "false"
from app.api import routes_chat, routes_session, routes_context, routes_tts, routes_vision, routes_protocols, routes_ephemeral, routes_stt, routes_faces, routes_admin, routes_video, routes_florence2, routes_paddleocr, routes_gpu, routes_meeting, routes_observability

# Add project root to path
import os; PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..' if '__file__' in dir() else '.')); sys.path.insert(0, PROJECT_ROOT)

from app import config
from core.conversation import ConversationHistory
from app.api import routes_chat, routes_session, routes_context, routes_tts, routes_vision, routes_protocols, routes_ephemeral
from database.character_traits import get_trait_list


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown events"""
    # === STARTUP ===
    print("[main.py] Starting background services...")

    # Log startup event for gap report
    try:
        from database.service_events import log_service_event
        log_service_event("startup", "iris_server", "lifespan")
    except Exception:
        pass

    # Sync context window from inference server
    import httpx
    backend = getattr(config, 'INFERENCE_BACKEND', 'llamacpp').lower()
    if backend == 'sglang':
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{config.OLLAMA_BASE_URL}/v1/models")
                models = resp.json()
                model_id = models.get("data", [{}])[0].get("id", "unknown")
                ctx = models.get("data", [{}])[0].get("max_model_len", config.OLLAMA_CONTEXT_WINDOW)
                if ctx != config.OLLAMA_CONTEXT_WINDOW:
                    print(f"[main.py] Context window sync: DB={config.OLLAMA_CONTEXT_WINDOW}, sglang={ctx} → updating")
                    config.OLLAMA_CONTEXT_WINDOW = ctx
                    config.CONTEXT_WINDOW = ctx
                else:
                    print(f"[main.py] ✓ sglang ready: {model_id} (context: {ctx})")
        except Exception as e:
            print(f"[main.py] ⚠ Could not reach sglang server: {e} (using DB value: {config.OLLAMA_CONTEXT_WINDOW})")
    else:
        try:
            url = f"{config.OLLAMA_BASE_URL}/props"
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url)
                props = resp.json()
                actual_ctx = props["default_generation_settings"]["n_ctx"]
                if actual_ctx != config.OLLAMA_CONTEXT_WINDOW:
                    print(f"[main.py] Context window sync: DB={config.OLLAMA_CONTEXT_WINDOW}, server={actual_ctx} → updating")
                    config.OLLAMA_CONTEXT_WINDOW = actual_ctx
                    config.CONTEXT_WINDOW = actual_ctx
                else:
                    print(f"[main.py] ✓ Context window: {actual_ctx} (matches DB)")
        except Exception as e:
            print(f"[main.py] ⚠ Could not sync context window from server: {e} (using DB value: {config.OLLAMA_CONTEXT_WINDOW})")

    # Detect current GPU service on Node2
    if getattr(config, 'NODE2_ENABLED', False) and getattr(config, 'GPU_MANAGER_ENABLED', True):
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
    else:
        print("[main.py] Node2 GPU manager disabled in config")

    # Write initial service status file and start background refresh
    try:
        from core.service_status import write_service_status, start_background_refresh
        await write_service_status()
        start_background_refresh(60)
        print("[main.py] ✓ Service status file written, background refresh started")
    except Exception as e:
        print(f"[main.py] ✗ Service status file setup failed: {e}")

    # Start face monitoring service
    try:
        from services import face_monitor
        if getattr(config, 'FACE_MONITORING_ENABLED', False):
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

    # Log shutdown event for gap report
    try:
        from database.service_events import log_service_event
        log_service_event("shutdown", "iris_server", "lifespan")
    except Exception:
        pass

    try:
        from services import face_monitor
        face_monitor.stop_monitoring()
        print("[main.py] ✓ Face monitoring stopped")
    except Exception as e:
        print(f"[main.py] ✗ Error stopping face monitoring: {e}")


# Create FastAPI app
app = FastAPI(
    title="Airis",
    description="AI Companion — Designed Around Dignity",
    version="1.0.0-alpha",
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
app.include_router(routes_meeting.router, tags=["meeting"])
app.include_router(routes_observability.router, tags=["observability"])

@app.get("/prompt")
def show_prompt():
    """
    Ground truth: returns the EXACT payload sent to the LLM.
    Includes messages, tools, temperature, and all other parameters.
    Stored at send-time by client.py, falls back to DB after restart.
    """
    from core.system_prompt import get_last_prompt

    payload = get_last_prompt()
    if not payload:
        return {"error": "No prompt captured yet — send a message first"}

    return payload



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

@app.get("/observability")
async def observability_dashboard():
    """Serve the observability dashboard"""
    obs_path = os.path.join(os.path.dirname(__file__), "..", "static", "observability.html")
    with open(obs_path, "r") as f:
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
    from app.version import __version__
    return {
        "status": "ok",
        "version": __version__,
        "model": config.OLLAMA_MODEL,
        "context_window": config.OLLAMA_CONTEXT_WINDOW,
        "session_timeout_minutes": config.SESSION_TIMEOUT_MINUTES,
        "max_conversation_turns": config.MAX_CONVERSATION_TURNS,
        "max_context_tokens": config.MAX_CONTEXT_TOKENS,
        "vision_enabled": config.VISION_ENABLED,
        "node2_enabled": getattr(config, 'NODE2_ENABLED', False)
    }

@app.get("/api/capabilities")
async def capabilities():
    """Feature flags for UI — which Node2-dependent controls are available"""
    from core.node2_check import is_node2_service_enabled
    return {
        "node2_enabled": getattr(config, 'NODE2_ENABLED', False),
        "tts": is_node2_service_enabled("TTS_ENABLED"),
        "stt": is_node2_service_enabled("STT_ENABLED"),
        "video": is_node2_service_enabled("VIDEO_ENABLED"),
        "vision": is_node2_service_enabled("VISION_ENABLED"),
        "transcribe": is_node2_service_enabled("TRANSCRIBE_ENABLED"),
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
    import threading
    from pathlib import Path

    # SSL certificate paths
    ssl_dir = Path(__file__).parent.parent / "ssl"
    ssl_keyfile = ssl_dir / "key.pem"
    ssl_certfile = ssl_dir / "cert.pem"

    # Port layout: 8000 = HTTP, 8443 = HTTPS (standard convention)
    HTTP_PORT = config.PORT          # 8000
    HTTPS_PORT = 8443

    # Check if SSL certificates exist
    use_ssl = ssl_keyfile.exists() and ssl_certfile.exists()

    from app.version import __version__
    print(f"[main.py] Starting Airis v{__version__}")
    print(f"[main.py] Model: {config.OLLAMA_MODEL}")
    print(f"[main.py] Context Window: {config.OLLAMA_CONTEXT_WINDOW} tokens")
    print(f"[main.py] Session Timeout: {config.SESSION_TIMEOUT_MINUTES} minutes")

    if use_ssl:
        # Dual-port setup: HTTPS on 8443 (primary), HTTP on 8000 (redirect)

        # --- HTTP redirect server (port 8000) ---
        from fastapi import FastAPI as _FastAPI, Request
        from fastapi.responses import PlainTextResponse, RedirectResponse

        redirect_app = _FastAPI()

        @redirect_app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
        async def _redirect_to_https(request: Request, path: str = ""):
            https_url = f"https://{request.headers.get('host', 'localhost').split(':')[0]}:{HTTPS_PORT}/{path}"
            if str(request.query_params):
                https_url += f"?{request.query_params}"
            return RedirectResponse(url=https_url, status_code=301)

        def _run_http_redirect():
            """Serve HTTP redirect on port 8000."""
            uvicorn.run(
                redirect_app,
                host=config.HOST,
                port=HTTP_PORT,
                log_level="warning",
            )

        print(f"[main.py] SSL Enabled: {ssl_certfile}")
        print(f"[main.py] HTTPS: https://{config.HOST}:{HTTPS_PORT}/")
        print(f"[main.py] HTTP redirect: http://{config.HOST}:{HTTP_PORT}/ → HTTPS")

        # Start HTTP redirect in background thread
        redirect_thread = threading.Thread(target=_run_http_redirect, daemon=True)
        redirect_thread.start()

        # Main HTTPS server on 8443
        uvicorn.run(
            app,
            host=config.HOST,
            port=HTTPS_PORT,
            log_level="info",
            ssl_keyfile=str(ssl_keyfile),
            ssl_certfile=str(ssl_certfile),
            ws="wsproto"
        )
    else:
        print(f"[main.py] SSL Disabled (no certificates found)")
        print(f"[main.py] Access at: http://{config.HOST}:{HTTP_PORT}/")
        uvicorn.run(
            app,
            host=config.HOST,
            port=HTTP_PORT,
            log_level="info",
            ws="wsproto"
        )
