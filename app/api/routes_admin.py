"""
Admin Console API Routes

Provides endpoints for:
- System stats and monitoring
- Configuration management
- Service control
- Quick actions
"""

import os
import sys
import psutil
import subprocess
from typing import Dict, Any, Optional
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import psycopg2
import psycopg2.extras

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, PROJECT_ROOT)

from app import config

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ============================================================================
# Request Models
# ============================================================================

class ConfigUpdate(BaseModel):
    """Model for configuration updates"""
    key: str
    value: Any


# ============================================================================
# Database Connection
# ============================================================================

def get_db_connection():
    """Get database connection"""
    password = os.environ.get('IRIS_DB_PASSWORD') or getattr(config, 'DB_PASSWORD', None)
    conn_params = {
        'host': config.DB_HOST,
        'port': config.DB_PORT,
        'database': config.DB_NAME,
        'user': config.DB_USER
    }
    if password:
        conn_params['password'] = password
    return psycopg2.connect(**conn_params)


# ============================================================================
# System Stats Endpoints
# ============================================================================

@router.get("/stats")
async def get_system_stats():
    """Get system statistics"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Helper to safely query counts (handles missing tables)
        def safe_count(table_name):
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                return cursor.fetchone()[0]
            except Exception:
                conn.rollback()  # Reset transaction state after error
                return 0

        # Get counts (gracefully handle missing tables)
        session_count = safe_count("chat_sessions")
        message_count = safe_count("chat_history")
        memory_count = safe_count("episodic_memories")  # Note: plural
        knowledge_count = safe_count("knowledge_documents")

        cursor.close()
        conn.close()

        # Get active WebSocket clients (would need to import connection_manager)
        # Placeholder for now
        active_clients = 0

        # System resources
        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        memory_percent = memory.percent

        return {
            "success": True,
            "stats": {
                "sessions": session_count,
                "messages": message_count,
                "memories": memory_count,
                "knowledge_docs": knowledge_count,
                "active_clients": active_clients,
                "cpu_percent": cpu_percent,
                "memory_percent": memory_percent,
                "memory_used_gb": round(memory.used / (1024**3), 2),
                "memory_total_gb": round(memory.total / (1024**3), 2)
            }
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/services/ollama/{port}")
async def check_ollama_service(port: int):
    """Check if Ollama service is running on specified port (legacy endpoint)"""
    try:
        import httpx

        url = f"http://localhost:{port}"
        with httpx.Client(timeout=3) as client:
            response = client.get(f"{url}/api/tags")
            return {
                "success": True,
                "status": "running" if response.status_code == 200 else "error",
                "port": port
            }
    except Exception as e:
        return {
            "success": False,
            "status": "stopped",
            "port": port,
            "error": str(e)
        }


@router.get("/services/check")
async def check_service(url: str, service_type: str = "llama"):
    """
    Check if a service is running and get its status

    Args:
        url: Base URL of the service (e.g., http://node2:8700)
        service_type: Type of service (llama, xtts, stt, float)

    Returns:
        Service status including loaded model if applicable
    """
    import httpx

    result = {
        "success": False,
        "status": "stopped",
        "url": url,
        "service_type": service_type,
        "model": None,
        "details": {}
    }

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            if service_type == "llama":
                # llama-server uses OpenAI-compatible API
                # Check /v1/models for loaded models
                try:
                    response = await client.get(f"{url}/v1/models")
                    if response.status_code == 200:
                        data = response.json()
                        models = data.get("data", [])
                        if models:
                            # Get the first (usually only) loaded model
                            model_info = models[0]
                            result["model"] = model_info.get("id", "unknown")
                            result["details"]["owned_by"] = model_info.get("owned_by", "")
                        result["status"] = "running"
                        result["success"] = True
                except Exception:
                    # Fallback: try /health endpoint
                    try:
                        response = await client.get(f"{url}/health")
                        if response.status_code == 200:
                            result["status"] = "running"
                            result["success"] = True
                            result["model"] = "unknown"
                    except Exception:
                        pass

            elif service_type == "xtts":
                # XTTS server - check /docs or custom health endpoint
                try:
                    response = await client.get(f"{url}/docs")
                    if response.status_code == 200:
                        result["status"] = "running"
                        result["success"] = True
                        result["model"] = "xtts-v2"
                except Exception:
                    # Try root endpoint
                    try:
                        response = await client.get(f"{url}/")
                        if response.status_code in [200, 307, 404]:
                            result["status"] = "running"
                            result["success"] = True
                            result["model"] = "xtts-v2"
                    except Exception:
                        pass

            elif service_type == "stt":
                # STT/Whisper server
                try:
                    response = await client.get(f"{url}/health")
                    if response.status_code == 200:
                        result["status"] = "running"
                        result["success"] = True
                        result["model"] = "whisper"
                        # Try to get model info from response
                        try:
                            data = response.json()
                            result["model"] = data.get("model", "whisper")
                        except Exception:
                            pass
                except Exception:
                    # Try docs endpoint
                    try:
                        response = await client.get(f"{url}/docs")
                        if response.status_code == 200:
                            result["status"] = "running"
                            result["success"] = True
                            result["model"] = "whisper"
                    except Exception:
                        pass

            elif service_type == "float":
                # FLOAT video generation server
                try:
                    response = await client.get(f"{url}/health")
                    if response.status_code == 200:
                        result["status"] = "running"
                        result["success"] = True
                        result["model"] = "float"
                except Exception:
                    # Try docs endpoint (FastAPI default)
                    try:
                        response = await client.get(f"{url}/docs")
                        if response.status_code == 200:
                            result["status"] = "running"
                            result["success"] = True
                            result["model"] = "float"
                    except Exception:
                        pass
            else:
                # Generic health check
                try:
                    response = await client.get(f"{url}/health")
                    if response.status_code == 200:
                        result["status"] = "running"
                        result["success"] = True
                except Exception:
                    pass

    except Exception as e:
        result["error"] = str(e)

    return result


@router.get("/services/all")
async def check_all_services():
    """
    Check status of all configured services across all nodes

    Returns comprehensive status of:
    - Main inference (localhost)
    - Vision/Freud (node2)
    - STT (node2)
    - XTTS (node2)
    - FLOAT (node2)
    """
    import httpx
    import asyncio

    services = []

    # Define all services to check
    service_configs = [
        {
            "name": "Main Inference",
            "url": config.OLLAMA_BASE_URL,
            "type": "llama",
            "location": "localhost",
            "gpu": "GPU 0 (RTX 5090)",
            "expected_model": "qwen3:32b",
            "icon": "🧠"
        },
        {
            "name": "Vision / Freud",
            "url": getattr(config, 'VISION_OLLAMA_URL', 'http://node2:11435'),
            "type": "llama",
            "location": "node2",
            "gpu": "GPU 0 (RTX 4080 SUPER)",
            "expected_model": "llama3.2-vision:11b / gemma3:4b",
            "icon": "👁️"
        },
        {
            "name": "STT (Whisper)",
            "url": getattr(config, 'STT_SERVER_URL', 'http://node2:8600'),
            "type": "stt",
            "location": "node2",
            "gpu": "GPU 1 (RTX 3060)",
            "expected_model": "whisper",
            "icon": "🎤"
        },
        {
            "name": "XTTS",
            "url": getattr(config, 'XTTS_SERVER_URL', 'http://node2:8700'),
            "type": "xtts",
            "location": "node2",
            "gpu": "GPU 1 (RTX 3060)",
            "expected_model": "xtts-v2",
            "icon": "🔊"
        },
        {
            "name": "FLOAT",
            "url": getattr(config, 'FLOAT_SERVER_URL', 'http://node2:8000'),
            "type": "float",
            "location": "node2",
            "gpu": "GPU 0 (RTX 4080 SUPER)",
            "expected_model": "float",
            "icon": "🎬"
        },
        {
            "name": "Sentiment",
            "url": "http://node2:11437",
            "type": "llama",
            "location": "node2",
            "gpu": "GPU 1 (RTX 3060)",
            "expected_model": "mistral-7b",
            "icon": "💭"
        }
    ]

    async def check_single_service(svc_config):
        """Check a single service and return enriched result"""
        import httpx

        result = {
            "name": svc_config["name"],
            "url": svc_config["url"],
            "location": svc_config["location"],
            "gpu": svc_config["gpu"],
            "expected_model": svc_config["expected_model"],
            "icon": svc_config["icon"],
            "status": "stopped",
            "model": None,
            "success": False
        }

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                svc_type = svc_config["type"]
                url = svc_config["url"]

                if svc_type == "llama":
                    try:
                        response = await client.get(f"{url}/v1/models")
                        if response.status_code == 200:
                            data = response.json()
                            models = data.get("data", [])
                            if models:
                                result["model"] = models[0].get("id", "unknown")
                            result["status"] = "running"
                            result["success"] = True
                    except Exception:
                        try:
                            response = await client.get(f"{url}/health")
                            if response.status_code == 200:
                                result["status"] = "running"
                                result["success"] = True
                        except Exception:
                            pass

                elif svc_type in ["xtts", "stt", "float"]:
                    # Try health, then docs endpoint
                    for endpoint in ["/health", "/docs", "/"]:
                        try:
                            response = await client.get(f"{url}{endpoint}")
                            if response.status_code in [200, 307]:
                                result["status"] = "running"
                                result["success"] = True
                                result["model"] = svc_config["expected_model"]
                                break
                        except Exception:
                            continue

        except Exception as e:
            result["error"] = str(e)

        return result

    # Check all services in parallel
    tasks = [check_single_service(svc) for svc in service_configs]
    services = await asyncio.gather(*tasks)

    # Group by location
    localhost_services = [s for s in services if s["location"] == "localhost"]
    node2_services = [s for s in services if s["location"] == "node2"]

    # Calculate overall health
    all_running = all(s["status"] == "running" for s in services)
    any_running = any(s["status"] == "running" for s in services)

    return {
        "success": True,
        "overall_status": "healthy" if all_running else ("degraded" if any_running else "down"),
        "localhost": localhost_services,
        "node2": node2_services,
        "all_services": services
    }


@router.post("/services/control")
async def control_service(service_name: str, action: str):
    """
    Start or stop a service

    Args:
        service_name: Name of the service (e.g., 'iris-vision', 'iris-llama')
        action: 'start', 'stop', or 'restart'

    Returns:
        Result of the operation
    """
    import asyncio

    # Validate action
    if action not in ['start', 'stop', 'restart']:
        return {"success": False, "error": f"Invalid action: {action}. Must be start, stop, or restart"}

    # Define which services are on which host
    localhost_services = ['iris-llama']
    node2_services = ['iris-vision', 'iris-freud', 'iris-stt', 'iris-xtts', 'iris-float', 'iris-sentiment']

    # Validate service name
    all_services = localhost_services + node2_services
    if service_name not in all_services:
        return {"success": False, "error": f"Unknown service: {service_name}"}

    try:
        if service_name in localhost_services:
            # Local service - use subprocess
            cmd = f"sudo systemctl {action} {service_name}"
            process = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                return {
                    "success": True,
                    "message": f"Service {service_name} {action}ed successfully",
                    "host": "localhost"
                }
            else:
                return {
                    "success": False,
                    "error": stderr.decode().strip() or f"Failed to {action} {service_name}",
                    "host": "localhost"
                }
        else:
            # Node2 service - use SSH
            cmd = f"ssh captain@node2 'sudo systemctl {action} {service_name}'"
            process = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                return {
                    "success": True,
                    "message": f"Service {service_name} {action}ed successfully on node2",
                    "host": "node2"
                }
            else:
                return {
                    "success": False,
                    "error": stderr.decode().strip() or f"Failed to {action} {service_name} on node2",
                    "host": "node2"
                }

    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/services/mcp")
async def get_mcp_status():
    """Get status of MCP servers"""
    try:
        # Check for running MCP server processes
        mcp_servers = []
        seen_pids = set()

        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                pid = proc.info['pid']
                if pid in seen_pids:
                    continue

                cmdline = proc.info['cmdline']
                if cmdline and any('mcp_servers' in str(arg) for arg in cmdline):
                    # Extract server name from the path that contains _server.py
                    server_name = "Unknown"
                    for arg in cmdline:
                        if '_server.py' in str(arg):
                            parts = str(arg).split('/')
                            # Find the directory name before the _server.py file
                            for i, part in enumerate(parts):
                                if '_server.py' in part:
                                    if i > 0:
                                        server_name = parts[i-1].title() + " Server"
                                    break
                            break

                    seen_pids.add(pid)
                    mcp_servers.append({
                        "name": server_name,
                        "pid": pid,
                        "status": "running"
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        # Deduplicate by name (keep first occurrence)
        seen_names = set()
        unique_servers = []
        for server in mcp_servers:
            if server['name'] not in seen_names:
                seen_names.add(server['name'])
                unique_servers.append(server)
        mcp_servers = unique_servers

        # Add known servers that should be running
        known_servers = ["Info Server", "Knowledge Server", "Traits Server", "Protocols Server"]
        found_names = [s['name'] for s in mcp_servers]

        for server in known_servers:
            if server not in found_names:
                mcp_servers.append({
                    "name": server,
                    "pid": None,
                    "status": "unknown"
                })

        return {
            "success": True,
            "servers": mcp_servers
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/stt/config")
async def get_stt_config():
    """Get current STT configuration"""
    try:
        # Get from database or return defaults
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Try to get STT config from system_config table
        stt_config = {
            "vox_threshold": 0.025,
            "vox_silence_ms": 5000,
            "vox_min_speech_ms": 3000,
            "whisper_model": "base",
            "beam_size": 5
        }

        try:
            cursor.execute("""
                SELECT config_key, config_value
                FROM system_config
                WHERE config_key LIKE 'STT_%'
            """)
            rows = cursor.fetchall()
            for row in rows:
                key = row['config_key'].lower().replace('stt_', '')
                value = row['config_value']
                if key in stt_config:
                    # Convert to appropriate type
                    if key in ['vox_threshold']:
                        stt_config[key] = float(value)
                    elif key in ['vox_silence_ms', 'vox_min_speech_ms', 'beam_size']:
                        stt_config[key] = int(value)
                    else:
                        stt_config[key] = value
        except Exception:
            pass  # Table might not exist, use defaults

        cursor.close()
        conn.close()

        return {"success": True, "config": stt_config}

    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/stt/config")
async def update_stt_config(updates: Dict[str, Any]):
    """
    Update STT configuration

    Accepts keys:
    - vox_threshold: float (0.01 - 0.1) - Speech detection sensitivity
    - vox_silence_ms: int (1000 - 10000) - Silence before stopping
    - vox_min_speech_ms: int (500 - 5000) - Minimum speech duration
    - whisper_model: str (tiny/base/small/medium/large-v2/large-v3)
    - beam_size: int (1 - 10)
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Validate and save each setting
        valid_keys = ['vox_threshold', 'vox_silence_ms', 'vox_min_speech_ms', 'whisper_model', 'beam_size']
        saved = []

        for key, value in updates.items():
            if key not in valid_keys:
                continue

            db_key = f"STT_{key.upper()}"

            # Validate ranges
            if key == 'vox_threshold':
                value = max(0.005, min(0.2, float(value)))
            elif key == 'vox_silence_ms':
                value = max(500, min(15000, int(value)))
            elif key == 'vox_min_speech_ms':
                value = max(100, min(5000, int(value)))
            elif key == 'whisper_model':
                if value not in ['tiny', 'base', 'small', 'medium', 'large-v2', 'large-v3']:
                    continue
            elif key == 'beam_size':
                value = max(1, min(10, int(value)))

            # Upsert into system_config
            cursor.execute("""
                INSERT INTO system_config (config_key, config_value, modified_by, modified_at)
                VALUES (%s, %s, 'admin_console', NOW())
                ON CONFLICT (config_key)
                DO UPDATE SET config_value = %s, modified_by = 'admin_console', modified_at = NOW()
            """, (db_key, str(value), str(value)))

            saved.append(key)

        conn.commit()
        cursor.close()
        conn.close()

        return {
            "success": True,
            "saved": saved,
            "message": "STT config updated. Frontend settings apply immediately. Whisper model requires service restart."
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/stt/update-model")
async def update_stt_model(model: str):
    """
    Update the Whisper model on node2's STT service

    This writes to /programs/stt/stt.conf on node2.
    Requires service restart to take effect.
    """
    import asyncio

    valid_models = ['tiny', 'base', 'small', 'medium', 'large-v2', 'large-v3']
    if model not in valid_models:
        return {"success": False, "error": f"Invalid model. Must be one of: {valid_models}"}

    try:
        # Write config file on node2 via SSH
        config_content = f"""# STT Server Configuration
# This file is read by systemd when starting iris-stt service
WHISPER_MODEL={model}
"""
        cmd = f"ssh captain@node2 'echo \"{config_content}\" > /programs/stt/stt.conf'"
        process = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode == 0:
            return {
                "success": True,
                "message": f"STT model set to '{model}'. Restart STT service to apply."
            }
        else:
            return {
                "success": False,
                "error": stderr.decode().strip() or "Failed to update config"
            }

    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/services/face-monitor")
async def get_face_monitor_status():
    """Get face monitoring service status"""
    try:
        # Check if face monitor thread is running
        # This would need to be implemented in face_monitor.py with a status endpoint
        # For now, check if the module is imported and monitoring is enabled

        is_enabled = getattr(config, 'FACE_MONITORING_ENABLED', False)

        return {
            "success": True,
            "enabled": is_enabled,
            "interval_seconds": getattr(config, 'FACE_MONITORING_INTERVAL_SECONDS', 30),
            "greeting_min_absence_minutes": getattr(config, 'FACE_GREETING_MIN_ABSENCE_MINUTES', 5),
            "greeting_cooldown_minutes": getattr(config, 'FACE_GREETING_COOLDOWN_MINUTES', 15)
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================================
# Configuration Endpoints
# ============================================================================

@router.get("/config")
async def get_config():
    """Get current configuration values"""
    try:
        config_values = {
            # Face monitoring
            "FACE_MONITORING_ENABLED": getattr(config, 'FACE_MONITORING_ENABLED', True),
            "FACE_MONITORING_INTERVAL_SECONDS": getattr(config, 'FACE_MONITORING_INTERVAL_SECONDS', 30),
            "FACE_GREETING_MIN_ABSENCE_MINUTES": getattr(config, 'FACE_GREETING_MIN_ABSENCE_MINUTES', 5),
            "FACE_GREETING_COOLDOWN_MINUTES": getattr(config, 'FACE_GREETING_COOLDOWN_MINUTES', 15),

            # Token budgets
            "MAX_CONVERSATION_TURNS": getattr(config, 'MAX_CONVERSATION_TURNS', 30),
            "MAX_CONTEXT_TOKENS": getattr(config, 'MAX_CONTEXT_TOKENS', 12000),
            "RESPONSE_BUDGET_TOKENS": getattr(config, 'RESPONSE_BUDGET_TOKENS', 2500),

            # Session
            "SESSION_TIMEOUT_MINUTES": getattr(config, 'SESSION_TIMEOUT_MINUTES', 30),
            "OLLAMA_CONTEXT_WINDOW": getattr(config, 'OLLAMA_CONTEXT_WINDOW', 32768),
            "VISION_ENABLED": getattr(config, 'VISION_ENABLED', True),

            # System
            "SYSTEM_INSTRUCTIONS": getattr(config, 'SYSTEM_INSTRUCTIONS', True),
            "CHARACTER_TRAITS": getattr(config, 'CHARACTER_TRAITS', True),
            "EPISODIC_MEMORIES": getattr(config, 'EPISODIC_MEMORIES', True),
        }

        return {
            "success": True,
            "config": config_values
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/config/update")
async def update_config(update: ConfigUpdate):
    """
    Update a configuration value in database

    Changes persist across server restarts and are immediately available.
    Some changes may require server restart to take full effect.
    """
    try:
        from database.config_loader import set_config, reload_config

        key = update.key
        value = update.value

        # Update in database
        success = set_config(key, value, modified_by='admin_console')

        if not success:
            raise HTTPException(status_code=400, detail=f"Failed to update config: {key}")

        # Reload config into runtime
        reload_config()

        # Also update the config module for immediate effect
        setattr(config, key, value)

        return {
            "success": True,
            "message": f"Config updated: {key} = {value}",
            "persisted": True
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid value type: {str(e)}")
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/config/reload")
async def reload_config_from_database():
    """
    Force reload configuration from database

    Use this after manual database changes or to refresh config
    without restarting the server.
    """
    try:
        from database.config_loader import reload_config, inject_into_module

        # Reload from database
        success = reload_config()

        if not success:
            return {
                "success": False,
                "error": "Failed to reload from database"
            }

        # Re-inject into config module
        inject_into_module(config)

        return {
            "success": True,
            "message": "Configuration reloaded from database"
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================================
# Quick Actions
# ============================================================================

@router.post("/actions/clear-webcam-cache")
async def clear_webcam_cache():
    """Clear webcam frame cache"""
    try:
        cache_dir = Path("/tmp/iris_webcam_cache")

        if cache_dir.exists():
            # Remove all files in cache
            for file in cache_dir.glob("*"):
                file.unlink()

            return {
                "success": True,
                "message": "Webcam cache cleared"
            }
        else:
            return {
                "success": True,
                "message": "No webcam cache found"
            }

    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/actions/reset-face-presence")
async def reset_face_presence():
    """Reset face presence state (mark all as not present)"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE face_presence_state
            SET is_present = false,
                exited_at = NOW()
            WHERE is_present = true
        """)

        affected = cursor.rowcount
        conn.commit()
        cursor.close()
        conn.close()

        return {
            "success": True,
            "message": f"Reset {affected} presence record(s)"
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/logs/recent")
async def get_recent_logs(lines: int = 100):
    """Get recent log entries from all log files"""
    try:
        log_dir = Path(PROJECT_ROOT) / "logs"

        # Look for log files in logs dir and subdirectories
        log_files = []
        if log_dir.exists():
            # Check top-level logs
            log_files.extend(log_dir.glob("*.log"))
            # Check subdirectories
            log_files.extend(log_dir.glob("*/*.log"))
            log_files.extend(log_dir.glob("*/*.txt"))

            # Sort by modification time (most recent first)
            log_files = sorted(log_files, key=lambda p: p.stat().st_mtime, reverse=True)

        if log_files:
            # Aggregate recent lines from multiple log files
            all_recent_lines = []

            for log_file in log_files[:5]:  # Check up to 5 most recent files
                try:
                    with open(log_file, 'r') as f:
                        file_lines = f.readlines()
                        # Add file identifier to each line
                        file_name = f"{log_file.parent.name}/{log_file.name}"
                        for line in file_lines[-20:]:  # Last 20 lines per file
                            all_recent_lines.append(f"[{file_name}] {line.rstrip()}")
                except Exception:
                    pass

            # Sort by any timestamp in the lines (best effort) and limit
            all_recent_lines = all_recent_lines[-lines:]

            return {
                "success": True,
                "logs": all_recent_lines if all_recent_lines else ["No recent log entries"],
                "files_checked": [str(f.name) for f in log_files[:5]]
            }
        else:
            return {
                "success": True,
                "logs": ["No log files found in logs/ directory"],
                "file": None
            }

    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/logs/service/{service_name}")
async def get_service_logs(service_name: str, lines: int = 100):
    """
    Get journalctl logs for a specific service

    Args:
        service_name: Name of the systemd service (e.g., 'iris-vision', 'iris-llama')
        lines: Number of log lines to retrieve

    Returns:
        Log entries from journalctl
    """
    import asyncio

    # Define which services are on which host
    localhost_services = ['iris-llama']
    node2_services = ['iris-vision', 'iris-freud', 'iris-stt', 'iris-xtts', 'iris-float', 'iris-sentiment']

    # Validate service name
    all_services = localhost_services + node2_services
    if service_name not in all_services:
        return {"success": False, "error": f"Unknown service: {service_name}"}

    try:
        if service_name in localhost_services:
            # Local service
            cmd = f"journalctl -u {service_name} -n {lines} --no-pager"
            process = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                log_lines = stdout.decode().strip().split('\n')
                return {
                    "success": True,
                    "service": service_name,
                    "host": "localhost",
                    "logs": log_lines
                }
            else:
                return {
                    "success": False,
                    "error": stderr.decode().strip() or "Failed to get logs",
                    "host": "localhost"
                }
        else:
            # Node2 service - use SSH
            cmd = f"ssh captain@node2 'journalctl -u {service_name} -n {lines} --no-pager'"
            process = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                log_lines = stdout.decode().strip().split('\n')
                return {
                    "success": True,
                    "service": service_name,
                    "host": "node2",
                    "logs": log_lines
                }
            else:
                return {
                    "success": False,
                    "error": stderr.decode().strip() or "Failed to get logs from node2",
                    "host": "node2"
                }

    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/database/stats")
async def get_database_stats():
    """Get database statistics and table sizes"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Get table sizes
        cursor.execute("""
            SELECT
                schemaname,
                tablename,
                pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size,
                pg_total_relation_size(schemaname||'.'||tablename) AS size_bytes
            FROM pg_tables
            WHERE schemaname = 'public'
            ORDER BY size_bytes DESC
            LIMIT 20
        """)

        tables = cursor.fetchall()

        # Get total database size
        cursor.execute("""
            SELECT pg_size_pretty(pg_database_size(current_database())) as size
        """)
        db_size = cursor.fetchone()['size']

        cursor.close()
        conn.close()

        return {
            "success": True,
            "database_size": db_size,
            "tables": [dict(t) for t in tables]
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================================
# System Control (Use with caution!)
# ============================================================================

@router.post("/system/restart")
async def restart_server():
    """
    Restart the Iris server

    WARNING: This will terminate the current process
    """
    try:
        # This is a placeholder - actual implementation would need
        # to coordinate with the process manager (systemd, supervisor, etc.)

        return {
            "success": False,
            "error": "Server restart not implemented",
            "message": "Please restart manually using: sudo systemctl restart iris"
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================================
# Token Budget Endpoints
# ============================================================================

@router.get("/token-budget")
async def get_token_budget():
    """
    Get comprehensive token budget information

    Returns:
        - Budget allocations and configurable parameters
        - Live usage statistics from actual context assembly
        - Descriptions for all configurable settings
    """
    try:
        # Get configurable parameters from database
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Fetch all token-related config from system_config
        # OLLAMA_CONTEXT_WINDOW is in 'llm' category, rest are in 'tokens'
        cursor.execute("""
            SELECT key, value, description, category
            FROM system_config
            WHERE category = 'tokens'
               OR key = 'OLLAMA_CONTEXT_WINDOW'
            ORDER BY key
        """)
        db_config = {row['key']: {'value': row['value'], 'description': row['description']}
                     for row in cursor.fetchall()}

        cursor.close()
        conn.close()

        # Helper to safely get int value from db_config
        def get_int(key, default):
            try:
                val = db_config.get(key, {}).get('value')
                return int(val) if val is not None else default
            except (ValueError, TypeError):
                return default

        def get_desc(key, default):
            return db_config.get(key, {}).get('description', default)

        # Build configurable dict from database values
        # Map to what the system actually uses (config module attribute names)
        configurable = {
            "OLLAMA_CONTEXT_WINDOW": {
                "value": get_int('OLLAMA_CONTEXT_WINDOW', 32768),
                "description": get_desc('OLLAMA_CONTEXT_WINDOW', "Total context window size")
            },
            "SYSTEM_PROMPT_BASE_BUDGET": {
                "value": get_int('SYSTEM_PROMPT_BASE_BUDGET', 600),
                "description": get_desc('SYSTEM_PROMPT_BASE_BUDGET', "Base identity tokens")
            },
            "CHARACTER_TRAITS_BUDGET": {
                "value": get_int('CHARACTER_TRAITS_BUDGET', 200),
                "description": get_desc('CHARACTER_TRAITS_BUDGET', "Personality traits budget")
            },
            "EPISODIC_MEMORY_BUDGET": {
                "value": get_int('EPISODIC_MEMORY_BUDGET', 2500),
                "description": get_desc('EPISODIC_MEMORY_BUDGET', "Retrieved memories budget")
            },
            "EMOTIONAL_STATE_BUDGET": {
                "value": get_int('EMOTIONAL_STATE_BUDGET', 200),
                "description": get_desc('EMOTIONAL_STATE_BUDGET', "Emotional context budget")
            },
            "TOOL_DEFINITIONS_BUDGET": {
                "value": get_int('TOOL_DEFINITIONS_BUDGET', 1500),
                "description": get_desc('TOOL_DEFINITIONS_BUDGET', "Tool schemas budget")
            },
            "TOOL_RESULTS_BUDGET": {
                "value": get_int('TOOL_RESULTS_BUDGET', 15000),
                "description": get_desc('TOOL_RESULTS_BUDGET', "Recent tool results budget")
            },
            "CONVERSATION_HISTORY_BUDGET": {
                "value": get_int('CONVERSATION_HISTORY_BUDGET', 7000),
                "description": get_desc('CONVERSATION_HISTORY_BUDGET', "Conversation history budget")
            },
            "RESPONSE_GENERATION_BUDGET": {
                "value": get_int('RESPONSE_GENERATION_BUDGET', 2000),
                "description": get_desc('RESPONSE_GENERATION_BUDGET', "Response reserve budget")
            },
            "MAX_TOTAL_MESSAGES": {
                "value": get_int('MAX_TOTAL_MESSAGES', 50),
                "description": get_desc('MAX_TOTAL_MESSAGES', "Safety limit on messages")
            },
            "MAX_SQL_RESULT_TOKENS": {
                "value": get_int('MAX_SQL_RESULT_TOKENS', 3000),
                "description": get_desc('MAX_SQL_RESULT_TOKENS', "SQL query result limit")
            },
            # Tiered context settings
            "VERBOSE_TOKEN_BUDGET": {
                "value": get_int('VERBOSE_TOKEN_BUDGET', 3000),
                "description": get_desc('VERBOSE_TOKEN_BUDGET', "Token budget for recent full messages")
            },
            "SUMMARY_TOKEN_BUDGET": {
                "value": get_int('SUMMARY_TOKEN_BUDGET', 17000),
                "description": get_desc('SUMMARY_TOKEN_BUDGET', "Token budget for older summarized messages")
            },
            "SUMMARY_MIN_LENGTH": {
                "value": get_int('SUMMARY_MIN_LENGTH', 50),
                "description": get_desc('SUMMARY_MIN_LENGTH', "Minimum message length to generate summary")
            },
            # Document handling
            "DOCUMENT_CONTEXT_BUDGET": {
                "value": get_int('DOCUMENT_CONTEXT_BUDGET', 8000),
                "description": get_desc('DOCUMENT_CONTEXT_BUDGET', "Max tokens for uploaded documents (smart truncation)")
            }
        }

        # Get summary statistics
        summary_stats = {"has_summary": 0, "needs_summary": 0, "total": 0}
        try:
            from database.persistence import get_current_chat_table
            conn2 = get_db_connection()
            cursor2 = conn2.cursor()
            chat_table = get_current_chat_table()
            min_length = get_int('SUMMARY_MIN_LENGTH', 50)

            cursor2.execute(f"""
                SELECT
                    COUNT(*) FILTER (WHERE summary IS NOT NULL) as has_summary,
                    COUNT(*) FILTER (WHERE summary IS NULL AND LENGTH(message) >= %s) as needs_summary,
                    COUNT(*) as total
                FROM {chat_table}
                WHERE role IN ('user', 'assistant')
            """, (min_length,))

            row = cursor2.fetchone()
            if row:
                summary_stats = {
                    "has_summary": row[0] or 0,
                    "needs_summary": row[1] or 0,
                    "total": row[2] or 0
                }
            cursor2.close()
            conn2.close()
        except Exception as e:
            print(f"[routes_admin.py] Could not get summary stats: {e}")

        # For allocations, use what the RUNNING system is actually using (config module)
        # This shows the ACTUAL values in effect, not just what's in DB
        context_window = getattr(config, 'OLLAMA_CONTEXT_WINDOW', 32768)
        system_base = getattr(config, 'SYSTEM_PROMPT_BASE_BUDGET', 600)
        traits = getattr(config, 'CHARACTER_TRAITS_BUDGET', 200)
        memories = getattr(config, 'EPISODIC_MEMORY_BUDGET', 2500)
        emotional = getattr(config, 'EMOTIONAL_STATE_BUDGET', 200)
        tool_defs = getattr(config, 'TOOL_DEFINITIONS_BUDGET', 1500)
        tool_results = getattr(config, 'TOOL_RESULTS_BUDGET', 15000)
        conversation = getattr(config, 'CONVERSATION_HISTORY_BUDGET', 7000)
        response = getattr(config, 'RESPONSE_GENERATION_BUDGET', 2000)

        # Calculate safety margin
        total_allocated = (system_base + traits + memories + emotional +
                          tool_defs + tool_results + conversation + response)
        safety_margin = context_window - total_allocated

        # Budget allocations (what's configured)
        allocations = {
            "system_prompt_base": system_base,
            "character_traits": traits,
            "episodic_memories": memories,
            "emotional_state": emotional,
            "tool_definitions": tool_defs,
            "tool_results": tool_results,
            "conversation_history": conversation,
            "response_reserve": response,
            "safety_margin": max(safety_margin, 0)
        }

        # Get live usage statistics
        live_usage = {
            "system_tokens": 0,
            "conversation_tokens": 0,
            "total_tokens": 0,
            "utilization_percent": 0.0,
            "messages_loaded": 0
        }

        try:
            # Import here to avoid circular imports
            from core.system_prompt import assemble_full_context
            from core.conversation import ConversationHistory
            from mcp_servers.tool_manager import get_tool_manager

            # Get active conversation context
            from app.api.routes_context import active_conversation

            if active_conversation:
                # Get tool definitions
                tool_manager = get_tool_manager()
                tool_definitions = tool_manager.get_tool_definitions_for_ollama()

                # Assemble context
                all_messages, budget = assemble_full_context(active_conversation, tool_definitions)

                # Parse stats
                system_msg = all_messages[0] if all_messages else {"content": ""}
                conversation_msgs = all_messages[1:] if len(all_messages) > 1 else []

                from core.token_counter import TokenCounter
                system_tokens = TokenCounter.count_tokens(system_msg.get("content", ""))
                conversation_tokens = TokenCounter.count_message_tokens(conversation_msgs)
                total_tokens = system_tokens + conversation_tokens

                live_usage = {
                    "system_tokens": system_tokens,
                    "conversation_tokens": conversation_tokens,
                    "total_tokens": total_tokens,
                    "utilization_percent": round((total_tokens / context_window) * 100, 1) if context_window > 0 else 0,
                    "messages_loaded": len(conversation_msgs)
                }
        except Exception as e:
            print(f"[routes_admin.py] Could not get live usage: {e}")
            # Keep defaults

        # Check for mismatches between DB and running config
        running_config = {
            "OLLAMA_CONTEXT_WINDOW": context_window,
            "SYSTEM_PROMPT_BASE_BUDGET": system_base,
            "CHARACTER_TRAITS_BUDGET": traits,
            "EPISODIC_MEMORY_BUDGET": memories,
            "EMOTIONAL_STATE_BUDGET": emotional,
            "TOOL_DEFINITIONS_BUDGET": tool_defs,
            "TOOL_RESULTS_BUDGET": tool_results,
            "CONVERSATION_HISTORY_BUDGET": conversation,
            "RESPONSE_GENERATION_BUDGET": response
        }

        mismatches = []
        for key, running_val in running_config.items():
            db_val = configurable.get(key, {}).get('value')
            if db_val is not None and db_val != running_val:
                mismatches.append({
                    "key": key,
                    "database": db_val,
                    "running": running_val
                })

        return {
            "success": True,
            "budget": {
                "context_window": context_window,
                "allocations": allocations,
                "configurable": configurable,
                "live_usage": live_usage,
                "running_config": running_config,
                "mismatches": mismatches if mismatches else None,
                "note": "Restart server to apply database changes" if mismatches else None,
                "summary_stats": summary_stats
            }
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


@router.post("/token-budget/update")
async def update_token_budget(updates: Dict[str, Any]):
    """
    Update token budget configuration values

    Accepts a dict of key-value pairs to update.
    Valid keys are token budget parameters from system_config.
    """
    try:
        from database.config_loader import set_config, reload_config

        valid_keys = [
            'OLLAMA_CONTEXT_WINDOW',
            'SYSTEM_PROMPT_BASE_BUDGET',
            'CHARACTER_TRAITS_BUDGET',
            'EPISODIC_MEMORY_BUDGET',
            'EMOTIONAL_STATE_BUDGET',
            'TOOL_DEFINITIONS_BUDGET',
            'TOOL_RESULTS_BUDGET',
            'CONVERSATION_HISTORY_BUDGET',
            'RESPONSE_GENERATION_BUDGET',
            'MAX_TOTAL_MESSAGES',
            'MAX_SQL_RESULT_TOKENS',
            # Tiered context settings
            'VERBOSE_TOKEN_BUDGET',
            'SUMMARY_TOKEN_BUDGET',
            'SUMMARY_MIN_LENGTH',
            # Document handling
            'DOCUMENT_CONTEXT_BUDGET'
        ]

        saved = []
        errors = []

        for key, value in updates.items():
            if key not in valid_keys:
                errors.append(f"Invalid key: {key}")
                continue

            try:
                # Ensure integer value
                int_value = int(value)

                # Basic validation
                if int_value < 0:
                    errors.append(f"{key}: Value must be non-negative")
                    continue

                # Update in database
                success = set_config(key, int_value, modified_by='admin_console')

                if success:
                    saved.append(key)
                    # Update config module for immediate effect
                    setattr(config, key, int_value)
                else:
                    errors.append(f"{key}: Failed to save to database")

            except ValueError:
                errors.append(f"{key}: Invalid integer value")

        # Reload config to ensure consistency
        if saved:
            reload_config()

        return {
            "success": len(errors) == 0,
            "saved": saved,
            "errors": errors if errors else None,
            "message": f"Updated {len(saved)} token budget setting(s)"
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/summaries/backfill")
async def backfill_summaries(limit: int = 50, batch_size: int = 10):
    """
    Trigger summary backfill for messages that don't have summaries.

    Args:
        limit: Maximum messages to process (default 50)
        batch_size: Messages per batch (default 10)

    Returns:
        Status and count of processed messages
    """
    try:
        from database.persistence import get_messages_needing_summaries, save_summary
        from core.summary_generator import SummaryGenerator

        # Get messages needing summaries
        messages = get_messages_needing_summaries(limit)

        if not messages:
            return {
                "success": True,
                "message": "No messages need summaries",
                "processed": 0,
                "successful": 0,
                "failed": 0
            }

        # Initialize generator
        generator = SummaryGenerator()

        total_success = 0
        total_failed = 0

        # Process in batches
        for i in range(0, len(messages), batch_size):
            batch = messages[i:i + batch_size]

            # Generate summaries for batch
            results = await generator.generate_summaries_batch(batch)

            # Save successful summaries
            for msg_id, summary in results.items():
                if save_summary(msg_id, summary):
                    total_success += 1
                else:
                    total_failed += 1

            # Count failed generations
            total_failed += len(batch) - len(results)

        await generator.close()

        return {
            "success": True,
            "message": f"Backfill complete",
            "processed": len(messages),
            "successful": total_success,
            "failed": total_failed
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


# ============================================================================
# System Config Endpoints (Reusable Config Renderer)
# ============================================================================

@router.get("/system-config")
async def get_all_system_config():
    """
    Get all system configuration grouped by category.

    Returns config items with full metadata for auto-rendering in the UI.
    Used by the reusable config renderer to dynamically build config forms.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cursor.execute("""
            SELECT
                key,
                value,
                value_type,
                default_value,
                description,
                category,
                requires_restart,
                last_modified
            FROM system_config
            ORDER BY category, key
        """)

        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        # Group by category
        categories_dict = {}
        for row in rows:
            category = row['category'] or 'general'
            if category not in categories_dict:
                categories_dict[category] = []

            # Determine if value differs from default
            is_modified = (row['value'] != row['default_value']) if row['default_value'] is not None else False

            categories_dict[category].append({
                'key': row['key'],
                'value': row['value'],
                'value_type': row['value_type'] or 'string',
                'default_value': row['default_value'],
                'description': row['description'],
                'requires_restart': row['requires_restart'] or False,
                'last_modified': row['last_modified'].isoformat() if row['last_modified'] else None,
                'is_modified': is_modified
            })

        # Convert to list format for easier frontend consumption
        categories_list = [
            {'name': name, 'configs': configs}
            for name, configs in sorted(categories_dict.items())
        ]

        return {
            'success': True,
            'categories': categories_list,
            'total_configs': len(rows)
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {'success': False, 'error': str(e)}


class ConfigResetRequest(BaseModel):
    """Model for config reset requests"""
    key: str


@router.post("/system-config/reset")
async def reset_config_to_default(request: ConfigResetRequest):
    """
    Reset a configuration value to its default.

    Args:
        key: The configuration key to reset

    Returns:
        Success status and the default value that was restored
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Get the default value
        cursor.execute("""
            SELECT key, default_value, value
            FROM system_config
            WHERE key = %s
        """, (request.key,))

        row = cursor.fetchone()

        if not row:
            cursor.close()
            conn.close()
            return {'success': False, 'error': f'Config key not found: {request.key}'}

        if row['default_value'] is None:
            cursor.close()
            conn.close()
            return {'success': False, 'error': f'No default value defined for: {request.key}'}

        default_value = row['default_value']

        # Update to default value
        cursor.execute("""
            UPDATE system_config
            SET value = default_value,
                last_modified = NOW()
            WHERE key = %s
        """, (request.key,))

        conn.commit()
        cursor.close()
        conn.close()

        # Also update the config module for immediate effect
        try:
            # Try to convert to appropriate type
            if default_value.lower() in ('true', 'false'):
                typed_value = default_value.lower() == 'true'
            else:
                try:
                    typed_value = int(default_value)
                except ValueError:
                    try:
                        typed_value = float(default_value)
                    except ValueError:
                        typed_value = default_value

            setattr(config, request.key, typed_value)
        except Exception:
            pass  # Non-critical if runtime update fails

        return {
            'success': True,
            'key': request.key,
            'default_value': default_value,
            'message': f'Reset {request.key} to default value'
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {'success': False, 'error': str(e)}


@router.get("/health/detailed")
async def detailed_health_check():
    """Comprehensive health check of all systems"""
    try:
        health = {
            "timestamp": datetime.now().isoformat(),
            "overall_status": "healthy",
            "checks": {}
        }

        # Database check
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.close()
            conn.close()
            health["checks"]["database"] = {"status": "healthy", "message": "Connected"}
        except Exception as e:
            health["checks"]["database"] = {"status": "unhealthy", "message": str(e)}
            health["overall_status"] = "degraded"

        # Check all services using the new endpoint
        try:
            services_result = await check_all_services()
            if services_result.get("success"):
                for service in services_result.get("all_services", []):
                    key = service["name"].lower().replace(" ", "_").replace("/", "_")
                    if service["status"] == "running":
                        health["checks"][key] = {
                            "status": "healthy",
                            "url": service["url"],
                            "model": service.get("model"),
                            "location": service["location"]
                        }
                    else:
                        health["checks"][key] = {
                            "status": "unhealthy",
                            "url": service["url"],
                            "location": service["location"],
                            "error": service.get("error", "Service not responding")
                        }
                        health["overall_status"] = "degraded"
        except Exception as e:
            health["checks"]["services"] = {"status": "unhealthy", "error": str(e)}
            health["overall_status"] = "degraded"

        # Disk space check
        disk = psutil.disk_usage('/')
        health["checks"]["disk_space"] = {
            "status": "healthy" if disk.percent < 90 else "warning",
            "used_percent": disk.percent,
            "free_gb": round(disk.free / (1024**3), 2)
        }

        return {"success": True, "health": health}

    except Exception as e:
        return {"success": False, "error": str(e)}
