"""
Service Status File Writer

Writes /tmp/iris/services.json atomically whenever service state changes.
The GTK monitor watches this file via inotify instead of polling HTTP.

Writers:
    - main.py startup (initial state)
    - gpu_manager.py (after GPU swap)
    - routes_admin.py (after service control)
    - Background task (every 60s, catches undetected crashes)
"""

import asyncio
import json
import os
import tempfile
from datetime import datetime, timezone

STATUS_FILE = "/tmp/iris/services.json"


def ensure_status_dir():
    """Create /tmp/iris/ if it doesn't exist."""
    status_dir = os.path.dirname(STATUS_FILE)
    try:
        os.makedirs(status_dir, mode=0o755, exist_ok=True)
    except OSError as e:
        print(f"[service_status.py] Could not create {status_dir}: {e}")


async def write_service_status():
    """
    Check all services and write status to STATUS_FILE atomically.

    Uses check_all_services() from routes_admin — same data the admin
    console and the old monitor already consume.
    """
    try:
        from app.api.routes_admin import check_all_services

        result = await check_all_services()
        if not result.get("success"):
            print("[service_status.py] check_all_services() failed, skipping write")
            return

        data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "services": result.get("all_services", []),
        }

        ensure_status_dir()

        # Atomic write: write to temp file, then rename
        status_dir = os.path.dirname(STATUS_FILE)
        fd, tmp = tempfile.mkstemp(dir=status_dir, prefix=".svc.", suffix=".json")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f)
            os.replace(tmp, STATUS_FILE)
        except Exception:
            # Clean up temp file on failure
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    except Exception as e:
        print(f"[service_status.py] Failed to write status: {e}")


_refresh_task = None
_previous_service_states = {}  # name -> status string


def _detect_crashes(current_services):
    """
    Compare current service states against previous states.
    If a service was "running" and is now not "running", log a crash_detected
    event (unless a GPU swap is in progress).
    """
    global _previous_service_states

    if not _previous_service_states:
        # First run — seed state, don't report
        _previous_service_states = {
            svc.get("name", ""): svc.get("status", "unknown")
            for svc in current_services
        }
        return

    # Check if GPU manager is currently switching (skip crash detection during swaps)
    gpu_switching = False
    try:
        from core.gpu_manager import get_gpu_manager, GPUState
        gpu = get_gpu_manager()
        gpu_switching = gpu._state == GPUState.SWITCHING
    except Exception:
        pass

    for svc in current_services:
        name = svc.get("name", "")
        current_status = svc.get("status", "unknown")
        previous_status = _previous_service_states.get(name)

        if previous_status == "running" and current_status != "running" and not gpu_switching:
            try:
                from database.service_events import log_service_event
                service_key = name.lower().replace(" ", "_").replace("/", "_")
                log_service_event("crash_detected", service_key, "background_health",
                                  f"Transitioned from running to {current_status}")
                print(f"[service_status.py] Crash detected: {name} ({previous_status} -> {current_status})")
            except Exception:
                pass

            # Reconcile GPU manager state if a GPU0 service crashed
            _GPU0_SERVICE_MAP = {
                "iris_vision": "vision", "iris_float": "float",
                "iris_freud": "freud", "iris_transcribe": "transcribe",
                "comfyui": "comfyui",
            }
            gpu_name = _GPU0_SERVICE_MAP.get(service_key)
            if gpu_name:
                try:
                    from core.gpu_manager import get_gpu_manager, GPUState
                    gpu = get_gpu_manager()
                    if gpu._current_service == gpu_name:
                        gpu._current_service = None
                        gpu._state = GPUState.UNKNOWN
                        print(f"[service_status.py] GPU manager state reconciled: {gpu_name} crashed, state -> UNKNOWN")
                except Exception:
                    pass

    # Update stored states
    _previous_service_states = {
        svc.get("name", ""): svc.get("status", "unknown")
        for svc in current_services
    }


def start_background_refresh(interval: int = 60):
    """Start an asyncio task that rewrites the status file periodically."""
    global _refresh_task

    async def _loop():
        while True:
            await asyncio.sleep(interval)
            try:
                # Run crash detection before writing status
                try:
                    from app.api.routes_admin import check_all_services
                    result = await check_all_services()
                    if result.get("success"):
                        _detect_crashes(result.get("all_services", []))
                except Exception:
                    pass

                await write_service_status()
            except Exception as e:
                print(f"[service_status.py] Background refresh error: {e}")

    _refresh_task = asyncio.create_task(_loop())
    print(f"[service_status.py] Background refresh started (every {interval}s)")
