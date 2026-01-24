"""
GPU Management API - Status and control endpoints for Node2 GPU resource manager

Endpoints:
- GET /api/gpu/status - Get current GPU status
- POST /api/gpu/request/{service} - Request a specific service
- POST /api/gpu/detect - Re-detect current service
"""

from fastapi import APIRouter, HTTPException
from typing import Optional
import sys
from pathlib import Path

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.gpu_manager import get_gpu_manager, request_gpu, GPU0_SERVICES

router = APIRouter(tags=["gpu"])


@router.get("/api/gpu/status")
async def gpu_status():
    """
    Get current GPU status.

    Returns:
        - current_service: Currently loaded service name or null
        - state: Current state (idle, busy, switching, unknown)
        - active_requests: Number of active API requests
        - services: List of available services
    """
    manager = get_gpu_manager()
    status = manager.get_status()

    # Add service descriptions
    services_with_info = {}
    for name, info in GPU0_SERVICES.items():
        services_with_info[name] = {
            "description": info["description"],
            "port": info["port"],
            "health_url": info["health_url"]
        }

    status["services_info"] = services_with_info
    return status


@router.post("/api/gpu/request/{service}")
async def gpu_request(service: str):
    """
    Request GPU for a specific service.

    This will:
    1. Stop the currently running service (if different)
    2. Start the requested service
    3. Wait for health check to pass

    Args:
        service: Service name (vision, float, freud)

    Returns:
        - success: Whether the service is now ready
        - error: Error message if failed
        - current_service: The service that is now loaded
    """
    if service not in GPU0_SERVICES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown service: {service}. Available: {list(GPU0_SERVICES.keys())}"
        )

    success, error = await request_gpu(service)

    manager = get_gpu_manager()
    return {
        "success": success,
        "error": error,
        "current_service": manager.get_status()["current_service"],
        "state": manager.get_status()["state"]
    }


@router.post("/api/gpu/detect")
async def gpu_detect():
    """
    Re-detect which service is currently running on Node2 GPU 0.

    Useful if the service state is out of sync (e.g., after manual
    systemctl commands or service crashes).

    Returns:
        - detected_service: The service found running, or null
        - state: Current state after detection
    """
    manager = get_gpu_manager()
    detected = await manager.detect_current_service()

    return {
        "detected_service": detected,
        "state": manager.get_status()["state"]
    }


@router.get("/api/gpu/services")
async def list_services():
    """
    List all available GPU services with their configuration.

    Returns:
        Dictionary of service configurations
    """
    services = {}
    for name, info in GPU0_SERVICES.items():
        services[name] = {
            "description": info["description"],
            "unit": info["unit"],
            "port": info["port"],
            "health_url": info["health_url"],
            "startup_delay": info["startup_delay"]
        }

    return {"services": services}
