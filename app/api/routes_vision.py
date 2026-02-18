"""
Vision API Routes for Iris v3
HTTP endpoints for vision system management and analysis
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import sys
import os
from pathlib import Path

# Path setup
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.vision_manager import get_vision_manager
from app import config
from core.node2_check import is_node2_service_enabled

router = APIRouter()


# ============================================================================
# REQUEST/RESPONSE MODELS
# ============================================================================

class AnalyzeImageRequest(BaseModel):
    """Request model for single image analysis"""
    image: str  # Base64 encoded image
    prompt: Optional[str] = "Describe this image in detail."


class AnalyzeBatchRequest(BaseModel):
    """Request model for batch image analysis"""
    images: List[str]  # List of base64 encoded images
    context: Optional[str] = None  # Conversation context
    custom_prompt: Optional[str] = None  # Override default prompt


class AnalyzeImageResponse(BaseModel):
    """Response model for image analysis"""
    success: bool
    result: Optional[str] = None
    tokens: Optional[int] = None
    inference_time: Optional[float] = None
    error: Optional[str] = None


class AnalyzeBatchResponse(BaseModel):
    """Response model for batch analysis"""
    success: bool
    results: List[str]
    total_tokens: int = 0
    total_time: float = 0
    error: Optional[str] = None


# ============================================================================
# ENDPOINTS
# ============================================================================

@router.post("/analyze", response_model=AnalyzeImageResponse)
async def analyze_single_image(request: AnalyzeImageRequest):
    """
    Analyze a single image

    **Request Body:**
    - `image`: Base64 encoded image (required)
    - `prompt`: Analysis prompt (optional, default: "Describe this image in detail.")

    **Response:**
    - `success`: Whether analysis succeeded
    - `result`: Analysis text
    - `tokens`: Token count
    - `inference_time`: Processing time in seconds
    - `error`: Error message if failed

    **Example:**
    ```json
    {
        "image": "iVBORw0KGgoAAAANSUhEUgAA...",
        "prompt": "What objects are in this image?"
    }
    ```
    """
    if not is_node2_service_enabled("VISION_ENABLED"):
        raise HTTPException(status_code=503, detail="Vision system disabled (Node2 not available)")

    try:
        manager = get_vision_manager()

        result = await manager.process_images(
            images=[request.image],
            custom_prompt=request.prompt
        )

        if result['success']:
            return AnalyzeImageResponse(
                success=True,
                result=result['results'][0],
                tokens=result['total_tokens'],
                inference_time=result['total_time'],
                error=None
            )
        else:
            return AnalyzeImageResponse(
                success=False,
                result=None,
                error=result.get('error', 'Unknown error')
            )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Vision analysis failed: {str(e)}")


@router.post("/batch", response_model=AnalyzeBatchResponse)
async def analyze_batch_images(request: AnalyzeBatchRequest):
    """
    Analyze multiple images in batch

    **Request Body:**
    - `images`: List of base64 encoded images (required, max 5)
    - `context`: Conversation context for prompt generation (optional)
    - `custom_prompt`: Custom prompt to use for all images (optional)

    **Response:**
    - `success`: Whether analysis succeeded
    - `results`: List of analysis texts (one per image)
    - `total_tokens`: Total tokens used
    - `total_time`: Total processing time in seconds
    - `error`: Error message if failed

    **Example:**
    ```json
    {
        "images": ["iVBORw0KGgoA...", "iVBORw0KGgoB..."],
        "context": "What are the differences between these images?"
    }
    ```
    """
    if not is_node2_service_enabled("VISION_ENABLED"):
        raise HTTPException(status_code=503, detail="Vision system disabled (Node2 not available)")

    if not request.images:
        raise HTTPException(status_code=400, detail="No images provided")

    if len(request.images) > config.VISION_MAX_IMAGES_PER_REQUEST:
        raise HTTPException(
            status_code=400,
            detail=f"Too many images ({len(request.images)}). Max: {config.VISION_MAX_IMAGES_PER_REQUEST}"
        )

    try:
        manager = get_vision_manager()

        result = await manager.process_images(
            images=request.images,
            context=request.context,
            custom_prompt=request.custom_prompt
        )

        if result['success']:
            return AnalyzeBatchResponse(
                success=True,
                results=result['results'],
                total_tokens=result['total_tokens'],
                total_time=result['total_time'],
                error=None
            )
        else:
            return AnalyzeBatchResponse(
                success=False,
                results=[],
                error=result.get('error', 'Unknown error')
            )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Batch vision analysis failed: {str(e)}")


@router.get("/status")
async def get_vision_status():
    """
    Get vision system status

    **Response:**
    - Vision system configuration
    - Model load status
    - Performance statistics
    - Manager state (idle time, auto-unload status)

    **Example Response:**
    ```json
    {
        "enabled": true,
        "model_loaded": true,
        "gpu_id": 1,
        "request_count": 42,
        "avg_inference_time": 1.23,
        "manager": {
            "processing": false,
            "idle_seconds": 120.5,
            "auto_unload_scheduled": true
        }
    }
    ```
    """
    try:
        manager = get_vision_manager()
        return manager.get_status()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get status: {str(e)}")


@router.post("/unload")
async def force_unload_model():
    """
    Force immediate model unload

    Useful when you need to free GPU 1 memory for other tasks (e.g., ComfyUI).

    **Response:**
    - `success`: Whether unload succeeded
    - `message`: Status message

    **Example Response:**
    ```json
    {
        "success": true,
        "message": "Vision model unloaded successfully"
    }
    ```
    """
    if not is_node2_service_enabled("VISION_ENABLED"):
        raise HTTPException(status_code=503, detail="Vision system disabled (Node2 not available)")

    try:
        manager = get_vision_manager()
        success = await manager.force_unload()

        if success:
            return {
                "success": True,
                "message": "Vision model unloaded successfully"
            }
        else:
            return {
                "success": False,
                "message": "Failed to unload model"
            }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Force unload failed: {str(e)}")


@router.get("/config")
async def get_vision_config():
    """
    Get vision system configuration

    **Response:**
    - All vision-related config settings

    **Example Response:**
    ```json
    {
        "enabled": true,
        "model_path": "/models/vision/llava-v1.6-mistral-7b.Q4_K_M.gguf",
        "gpu_id": 1,
        "max_tokens": 1000,
        "auto_unload_minutes": 5
    }
    ```
    """
    return {
        "enabled": config.VISION_ENABLED,
        "model_path": config.VISION_MODEL_PATH,
        "clip_path": config.VISION_CLIP_PATH,
        "gpu_id": config.VISION_GPU_ID,
        "auto_unload_minutes": config.VISION_AUTO_UNLOAD_MINUTES,
        "max_tokens": config.VISION_MAX_TOKENS,
        "context_window": config.VISION_CONTEXT_WINDOW,
        "max_image_size_mb": config.VISION_MAX_IMAGE_SIZE_MB,
        "max_images_per_request": config.VISION_MAX_IMAGES_PER_REQUEST,
        "timeout_seconds": config.VISION_TIMEOUT_SECONDS,
        "debug": config.VISION_DEBUG
    }
