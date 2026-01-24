"""
Node2 GPU Resource Manager
Coordinates mutually-exclusive GPU services via SSH + systemctl

Services on GPU 0 (RTX 4080 Super) are mutually exclusive:
- vision (iris-vision.service) - llava-phi-3 for image analysis
- float (iris-float.service) - FLOAT video generation
- freud (iris-freud.service) - gemma-3-4b for dream processing

Services on GPU 1 (XTTS/STT) can coexist and don't need management.

Usage:
    from core.gpu_manager import request_gpu

    success, error = await request_gpu("vision")
    if success:
        # Service is ready, make your API call
        result = await vision_service.analyze(image)
    else:
        # GPU busy or swap failed
        ui_msg(f"Vision unavailable: {error}", "error")
"""
import asyncio
import subprocess
from typing import Optional, Tuple, Dict, Any
from datetime import datetime
from enum import Enum
import httpx


class GPUState(Enum):
    IDLE = "idle"           # Service loaded, no active request
    BUSY = "busy"           # Active request in progress
    SWITCHING = "switching" # Service swap in progress
    UNKNOWN = "unknown"     # State uncertain


# Service registry - GPU 0 services only
# Note: Vision and Freud share port 11435 (Freud has Conflicts=iris-vision.service)
GPU0_SERVICES = {
    "vision": {
        "unit": "iris-vision.service",
        "health_url": "http://node2:11435/health",
        "port": 11435,
        "startup_delay": 8,
        "description": "Vision model"
    },
    "float": {
        "unit": "iris-float.service",
        "health_url": "http://node2:8000/",  # FLOAT serves HTML at root, no /health endpoint
        "port": 8000,
        "startup_delay": 12,
        "description": "Video generation"
    },
    "freud": {
        "unit": "iris-freud.service",
        "health_url": "http://node2:11435/health",
        "port": 11435,
        "startup_delay": 8,
        "description": "Dream processor"
    },
    "comfyui": {
        "unit": "comfyui.service",
        "health_url": "http://node2:8189/system_stats",
        "port": 8189,
        "startup_delay": 30,
        "description": "Image generation"
    }
}

NODE2_SSH = "captain@node2"


class Node2GPUManager:
    """Singleton GPU manager for Node2 GPU 0"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._current_service: Optional[str] = None
        self._state = GPUState.UNKNOWN
        self._active_requests = 0
        self._lock = asyncio.Lock()
        self._initialized = True
        print("[gpu_manager.py] Node2GPUManager initialized")

    async def request_gpu(self, service: str) -> Tuple[bool, Optional[str]]:
        """
        Request GPU for a service.

        Args:
            service: Service name ("vision", "float", "freud")

        Returns:
            (True, None) - Service ready
            (False, "error message") - Failed
        """
        from core.ui_notify import ui_msg

        if service not in GPU0_SERVICES:
            return (False, f"Unknown service: {service}")

        async with self._lock:
            # Already loaded and idle
            if self._current_service == service and self._state == GPUState.IDLE:
                print(f"[gpu_manager.py] {service} already loaded and idle")
                return (True, None)

            # GPU busy with active request
            if self._state == GPUState.BUSY:
                msg = f"GPU busy: {self._current_service} is processing"
                print(f"[gpu_manager.py] {msg}")
                return (False, msg)

            # Currently switching
            if self._state == GPUState.SWITCHING:
                msg = "GPU is switching services"
                print(f"[gpu_manager.py] {msg}")
                return (False, msg)

            # Need to swap or start
            new_desc = GPU0_SERVICES[service]["description"]
            startup_time = GPU0_SERVICES[service]["startup_delay"]

            if self._current_service and self._current_service != service:
                print(f"[gpu_manager.py] Switching from {self._current_service} to {service}")
                ui_msg(f"Switching to {new_desc} (~{startup_time}s)...", "info")
            elif not self._current_service:
                print(f"[gpu_manager.py] Starting {service} (no service currently running)")
                ui_msg(f"Starting {new_desc} (~{startup_time}s)...", "info")

            self._state = GPUState.SWITCHING

            try:
                success = await self._swap_service(service)
                if success:
                    self._current_service = service
                    self._state = GPUState.IDLE
                    svc = GPU0_SERVICES[service]
                    ui_msg(f"{svc['description']} ready", "success")
                    print(f"[gpu_manager.py] ✓ {service} ready")
                    return (True, None)
                else:
                    self._state = GPUState.UNKNOWN
                    ui_msg(f"Failed to start {service}", "error")
                    print(f"[gpu_manager.py] ✗ Failed to start {service}")
                    return (False, f"Failed to start {service}")
            except Exception as e:
                self._state = GPUState.UNKNOWN
                ui_msg(f"GPU error: {e}", "error")
                print(f"[gpu_manager.py] ✗ GPU error: {e}")
                return (False, str(e))

    async def _swap_service(self, target: str) -> bool:
        """Stop current service, start target, verify health."""
        # Stop current
        if self._current_service:
            current_unit = GPU0_SERVICES[self._current_service]["unit"]
            print(f"[gpu_manager.py] Stopping {current_unit}...")
            await self._ssh_systemctl("stop", current_unit)
            await asyncio.sleep(2)

        # Start target
        target_info = GPU0_SERVICES[target]
        print(f"[gpu_manager.py] Starting {target_info['unit']}...")
        await self._ssh_systemctl("start", target_info["unit"])

        # Wait for startup
        print(f"[gpu_manager.py] Waiting {target_info['startup_delay']}s for startup...")
        await asyncio.sleep(target_info["startup_delay"])

        # Verify health
        healthy = await self._check_health(target_info["health_url"])
        if healthy:
            print(f"[gpu_manager.py] ✓ Health check passed: {target_info['health_url']}")
        else:
            print(f"[gpu_manager.py] ✗ Health check failed: {target_info['health_url']}")
        return healthy

    async def _ssh_systemctl(self, action: str, unit: str) -> bool:
        """
        Execute systemctl on Node2 via SSH.

        Requires passwordless sudo on Node2. Add to /etc/sudoers.d/iris:
            captain ALL=(ALL) NOPASSWD: /bin/systemctl start iris-*.service
            captain ALL=(ALL) NOPASSWD: /bin/systemctl stop iris-*.service
            captain ALL=(ALL) NOPASSWD: /bin/systemctl restart iris-*.service
            captain ALL=(ALL) NOPASSWD: /bin/systemctl status iris-*.service
        """
        # Use -t to allocate pseudo-terminal, but sudo still needs NOPASSWD config
        cmd = f"ssh -o BatchMode=yes {NODE2_SSH} 'sudo systemctl {action} {unit}'"
        try:
            result = await asyncio.to_thread(
                subprocess.run, cmd, shell=True,
                capture_output=True, timeout=30
            )
            if result.returncode != 0:
                stderr = result.stderr.decode() if result.stderr else ""
                if "password" in stderr.lower() or "terminal" in stderr.lower():
                    print(f"[gpu_manager.py] SSH sudo requires NOPASSWD config on Node2")
                    print(f"[gpu_manager.py] Add to /etc/sudoers.d/iris on Node2:")
                    print(f"[gpu_manager.py]   captain ALL=(ALL) NOPASSWD: /bin/systemctl * iris-*.service")
                else:
                    print(f"[gpu_manager.py] SSH command failed: {stderr}")
            return result.returncode == 0
        except subprocess.TimeoutExpired:
            print(f"[gpu_manager.py] SSH command timed out")
            return False
        except Exception as e:
            print(f"[gpu_manager.py] SSH error: {e}")
            return False

    async def _check_health(self, url: str, retries: int = 3) -> bool:
        """Check service health endpoint with retries."""
        for attempt in range(retries):
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    r = await client.get(url)
                    if r.status_code == 200:
                        return True
            except Exception as e:
                if attempt < retries - 1:
                    print(f"[gpu_manager.py] Health check attempt {attempt + 1} failed: {e}, retrying...")
                    await asyncio.sleep(2)
        return False

    def mark_busy(self):
        """Mark GPU as busy (call before API request)."""
        self._active_requests += 1
        self._state = GPUState.BUSY
        print(f"[gpu_manager.py] GPU marked busy (active_requests: {self._active_requests})")

    def mark_idle(self):
        """Mark GPU as idle (call after API request)."""
        self._active_requests = max(0, self._active_requests - 1)
        if self._active_requests == 0:
            self._state = GPUState.IDLE
            print(f"[gpu_manager.py] GPU marked idle")
        else:
            print(f"[gpu_manager.py] Active requests remaining: {self._active_requests}")

    async def detect_current_service(self) -> Optional[str]:
        """Detect which service is running (call on startup)."""
        print("[gpu_manager.py] Detecting current GPU service on Node2...")

        for name, info in GPU0_SERVICES.items():
            if await self._check_health(info["health_url"], retries=1):
                self._current_service = name
                self._state = GPUState.IDLE
                print(f"[gpu_manager.py] ✓ Detected running service: {name}")
                return name

        self._state = GPUState.UNKNOWN
        print("[gpu_manager.py] No GPU 0 service detected on Node2")
        return None

    def get_status(self) -> Dict[str, Any]:
        """Get current status."""
        return {
            "current_service": self._current_service,
            "state": self._state.value,
            "active_requests": self._active_requests,
            "services": list(GPU0_SERVICES.keys())
        }


# ============================================================================
# SINGLETON ACCESSOR
# ============================================================================

_manager: Optional[Node2GPUManager] = None


def get_gpu_manager() -> Node2GPUManager:
    """Get or create the GPU manager singleton."""
    global _manager
    if _manager is None:
        _manager = Node2GPUManager()
    return _manager


async def request_gpu(service: str) -> Tuple[bool, Optional[str]]:
    """Convenience function for requesting GPU."""
    return await get_gpu_manager().request_gpu(service)


# ============================================================================
# TESTING
# ============================================================================

if __name__ == "__main__":
    async def test():
        print("=== GPU Manager Test ===\n")

        manager = get_gpu_manager()

        # Detect current service
        print("1. Detecting current service...")
        current = await manager.detect_current_service()
        print(f"   Current: {current}\n")

        # Get status
        print("2. Status:")
        status = manager.get_status()
        for k, v in status.items():
            print(f"   {k}: {v}")
        print()

        # Test request
        print("3. Requesting vision...")
        success, error = await request_gpu("vision")
        print(f"   Success: {success}, Error: {error}\n")

        print("Test complete")

    asyncio.run(test())
