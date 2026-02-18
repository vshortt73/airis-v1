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
from datetime import datetime, timedelta
from enum import Enum
import httpx

from app import config


class GPUState(Enum):
    IDLE = "idle"           # Service loaded, no active request
    BUSY = "busy"           # Active request in progress
    SWITCHING = "switching" # Service swap in progress
    UNKNOWN = "unknown"     # State uncertain


def _build_gpu0_services() -> Dict[str, Dict[str, Any]]:
    """Build service registry from config (database source of truth)"""
    return {
        "vision": {
            "unit": "iris-vision.service",
            "health_url": f"{config.VISION_OLLAMA_URL}/health",
            "port": 11435,
            "startup_delay": 8,
            "description": "Vision model"
        },
        "float": {
            "unit": "iris-float.service",
            "health_url": f"{config.FLOAT_SERVER_URL}/",  # FLOAT serves HTML at root, no /health endpoint
            "port": 8000,
            "startup_delay": 12,
            "description": "Video generation"
        },
        "freud": {
            "unit": "iris-freud.service",
            "health_url": f"{config.FREUD_URL}/health",
            "port": 11435,
            "startup_delay": 8,
            "description": "Dream processor"
        },
        "comfyui": {
            "unit": "comfyui.service",
            "health_url": f"{config.COMFYUI_SERVER_URL}/system_stats",
            "port": 8189,
            "startup_delay": 30,
            "description": "Image generation"
        },
        "transcribe": {
            "unit": "iris-transcribe.service",
            "health_url": f"http://{getattr(config, 'NODE2_HOST', 'node2')}:8500/health",
            "port": 8500,
            "startup_delay": 15,
            "description": "Meeting transcription (WhisperX)"
        }
    }


GPU0_SERVICES = _build_gpu0_services()

def _get_node2_ssh():
    """Build SSH target from config (database source of truth)."""
    return f"{getattr(config, 'NODE2_SSH_USER', 'captain')}@{getattr(config, 'NODE2_HOST', 'node2')}"


class Node2GPUManager:
    """Singleton GPU manager for Node2 GPU 0"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    # Circuit breaker thresholds
    CIRCUIT_FAILURE_THRESHOLD = 3   # Open after 3 consecutive failures
    CIRCUIT_RESET_SECONDS = 120     # Try again after 2 minutes

    def __init__(self):
        if self._initialized:
            return
        self._current_service: Optional[str] = None
        self._state = GPUState.UNKNOWN
        self._active_requests = 0
        self._lock = asyncio.Lock()
        # Circuit breaker state
        self._consecutive_failures: int = 0
        self._circuit_open_until: Optional[datetime] = None
        self._initialized = True
        print("[gpu_manager.py] Node2GPUManager initialized")

    def _check_circuit(self) -> Optional[str]:
        """Returns error message if circuit is open, None if OK to proceed."""
        if self._circuit_open_until and datetime.now() < self._circuit_open_until:
            remaining = int((self._circuit_open_until - datetime.now()).total_seconds())
            return f"Node2 circuit breaker open ({remaining}s remaining after {self._consecutive_failures} failures)"
        return None

    def _record_success(self):
        """Reset circuit breaker on success."""
        if self._consecutive_failures > 0:
            print(f"[gpu_manager.py] Circuit breaker reset (was {self._consecutive_failures} failures)")
        self._consecutive_failures = 0
        self._circuit_open_until = None

    def _record_failure(self):
        """Record failure, potentially open circuit."""
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.CIRCUIT_FAILURE_THRESHOLD:
            self._circuit_open_until = datetime.now() + timedelta(seconds=self.CIRCUIT_RESET_SECONDS)
            print(f"[gpu_manager.py] Circuit breaker OPEN — Node2 unreachable after {self._consecutive_failures} failures. Retry in {self.CIRCUIT_RESET_SECONDS}s")

    def is_node2_healthy(self) -> bool:
        """Quick check: is the circuit breaker closed? Used by other modules to fail fast."""
        return self._check_circuit() is None

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

        # Check circuit breaker before acquiring lock
        circuit_error = self._check_circuit()
        if circuit_error:
            print(f"[gpu_manager.py] {circuit_error}")
            return (False, circuit_error)

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
                prev_service = self._current_service
                success = await self._swap_service(service)
                if success:
                    self._current_service = service
                    self._state = GPUState.IDLE
                    svc = GPU0_SERVICES[service]
                    ui_msg(f"{svc['description']} ready", "success")
                    print(f"[gpu_manager.py] ✓ {service} ready")
                    await self._update_status_file()
                    # Log GPU swap for gap report
                    try:
                        from database.service_events import log_service_event
                        swap_name = f"{prev_service or 'none'}→{service}"
                        log_service_event("service_swap", swap_name, "gpu_manager")
                    except Exception:
                        pass
                    return (True, None)
                else:
                    self._state = GPUState.UNKNOWN
                    ui_msg(f"Failed to start {service}", "error")
                    print(f"[gpu_manager.py] ✗ Failed to start {service}")
                    await self._update_status_file()
                    return (False, f"Failed to start {service}")
            except Exception as e:
                self._state = GPUState.UNKNOWN
                ui_msg(f"GPU error: {e}", "error")
                print(f"[gpu_manager.py] ✗ GPU error: {e}")
                await self._update_status_file()
                return (False, str(e))

    async def _swap_service(self, target: str) -> bool:
        """Stop ALL GPU 0 services, start target, verify health."""
        # Stop ALL GPU 0 services (not just tracked one) to ensure clean state
        # This handles cases where services were started outside GPU Manager
        print(f"[gpu_manager.py] Stopping ALL GPU 0 services before starting {target}...")
        for service_name, service_info in GPU0_SERVICES.items():
            if service_name != target:  # Don't stop the one we're about to start
                await self._ssh_systemctl("stop", service_info["unit"])
        await asyncio.sleep(3)  # Give services time to release GPU memory

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
            self._record_success()
        else:
            print(f"[gpu_manager.py] ✗ Health check failed: {target_info['health_url']}")
            self._record_failure()
        return healthy

    async def _ssh_systemctl(self, action: str, unit: str, max_retries: int = 3) -> bool:
        """
        Execute systemctl on Node2 via SSH with retry and backoff.

        Retries up to max_retries times with exponential backoff (2s, 4s).
        Auth errors (password/terminal prompts) fail immediately — retrying won't help.

        Requires passwordless sudo on Node2. Add to /etc/sudoers.d/iris:
            captain ALL=(ALL) NOPASSWD: /usr/bin/systemctl start iris-*
            captain ALL=(ALL) NOPASSWD: /usr/bin/systemctl stop iris-*
            captain ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart iris-*
            captain ALL=(ALL) NOPASSWD: /usr/bin/systemctl status iris-*
            captain ALL=(ALL) NOPASSWD: /usr/bin/systemctl start comfyui.service
            captain ALL=(ALL) NOPASSWD: /usr/bin/systemctl stop comfyui.service
            captain ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart comfyui.service
            captain ALL=(ALL) NOPASSWD: /usr/bin/systemctl status comfyui.service
        """
        cmd = f"ssh -o ConnectTimeout=10 -o BatchMode=yes {_get_node2_ssh()} 'sudo /bin/systemctl {action} {unit}'"
        for attempt in range(max_retries):
            try:
                result = await asyncio.to_thread(
                    subprocess.run, cmd, shell=True,
                    capture_output=True, timeout=30
                )
                if result.returncode == 0:
                    return True
                stderr = result.stderr.decode() if result.stderr else ""
                if "password" in stderr.lower() or "terminal" in stderr.lower():
                    print(f"[gpu_manager.py] SSH sudo requires NOPASSWD config on Node2")
                    print(f"[gpu_manager.py] Add to /etc/sudoers.d/iris on Node2:")
                    print(f"[gpu_manager.py]   captain ALL=(ALL) NOPASSWD: /bin/systemctl * iris-*.service")
                    return False  # Auth misconfiguration — don't retry
                if attempt < max_retries - 1:
                    delay = 2 ** (attempt + 1)  # 2s, 4s
                    print(f"[gpu_manager.py] SSH attempt {attempt+1} failed ({action} {unit}), retrying in {delay}s...")
                    await asyncio.sleep(delay)
                else:
                    print(f"[gpu_manager.py] SSH command failed after {max_retries} attempts: {stderr}")
            except subprocess.TimeoutExpired:
                if attempt < max_retries - 1:
                    delay = 2 ** (attempt + 1)
                    print(f"[gpu_manager.py] SSH timeout ({action} {unit}), retrying in {delay}s...")
                    await asyncio.sleep(delay)
                else:
                    print(f"[gpu_manager.py] SSH timed out after {max_retries} attempts")
                    return False
            except Exception as e:
                print(f"[gpu_manager.py] SSH error: {e}")
                return False  # Non-transient errors don't retry
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

    async def _update_status_file(self):
        """Fire-and-forget update of the service status file."""
        try:
            from core.service_status import write_service_status
            await write_service_status()
        except Exception as e:
            print(f"[gpu_manager.py] Status file update failed: {e}")

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

    async def reconcile_state(self) -> Optional[str]:
        """Re-detect current service and fix internal state if mismatched."""
        if self._state == GPUState.SWITCHING:
            return self._current_service  # Don't interfere with active swap

        detected = await self.detect_current_service()
        if detected != self._current_service:
            old = self._current_service
            self._current_service = detected
            self._state = GPUState.IDLE if detected else GPUState.UNKNOWN
            print(f"[gpu_manager.py] State reconciled: {old} -> {detected}")
        return detected

    def get_status(self) -> Dict[str, Any]:
        """Get current status."""
        return {
            "current_service": self._current_service,
            "state": self._state.value,
            "active_requests": self._active_requests,
            "services": list(GPU0_SERVICES.keys()),
            "circuit_open": self._check_circuit() is not None,
            "consecutive_failures": self._consecutive_failures,
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
