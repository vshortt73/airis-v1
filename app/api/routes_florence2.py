"""
Florence2 API Routes for Iris v3
Provides REST endpoints for Florence-2 vision model tasks.
"""

import sys
import os
from pathlib import Path
from typing import Optional, List, Any
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import base64

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from services.florence2_service import get_florence2_service, FLORENCE2_TASKS
from core.node2_check import is_node2_service_enabled

router = APIRouter(prefix="/api/florence2", tags=["florence2"])


# ============================================================================
# Request/Response Models
# ============================================================================

class Florence2Request(BaseModel):
    """Request model for Florence2 analysis."""
    image: str  # Base64 encoded image
    task: str = "caption"  # Task name
    text_input: Optional[str] = None  # Additional text for tasks that need it
    max_new_tokens: int = 1024
    num_beams: int = 3


class BoundingBox(BaseModel):
    """Bounding box model."""
    x1: float
    y1: float
    x2: float
    y2: float
    label: str
    confidence: Optional[float] = None


class Florence2Response(BaseModel):
    """Response model for Florence2 analysis."""
    success: bool
    task: Optional[str] = None
    result: Optional[Any] = None  # Can be dict, string, or list depending on task
    raw_output: Optional[Any] = None
    inference_time: Optional[float] = None
    image_size: Optional[dict] = None
    error: Optional[str] = None


# ============================================================================
# API Endpoints
# ============================================================================

@router.get("/status")
async def get_status():
    """Get Florence2 service status."""
    if not is_node2_service_enabled("FLORENCE2_ENABLED"):
        return {"status": "disabled", "reason": "Florence2 service disabled (Node2 not available)"}
    service = get_florence2_service()
    return service.get_status()


@router.get("/tasks")
async def list_tasks():
    """List all available Florence2 tasks."""
    return {
        "tasks": [
            {
                "name": name,
                "prompt": prompt,
                "requires_text": name in [
                    "phrase_grounding",
                    "open_vocabulary_detection",
                    "referring_expression_segmentation"
                ],
                "requires_region": name in [
                    "region_to_segmentation",
                    "region_to_category",
                    "region_to_description"
                ]
            }
            for name, prompt in FLORENCE2_TASKS.items()
        ]
    }


@router.post("/load")
async def load_model(device: str = "cuda:1"):
    """Load the Florence2 model into memory."""
    service = get_florence2_service()

    if service.is_loaded():
        return {"success": True, "message": "Model already loaded"}

    success = service.load_model(device=device)

    if success:
        return {"success": True, "message": f"Model loaded on {device}"}
    else:
        raise HTTPException(status_code=500, detail="Failed to load model")


@router.post("/unload")
async def unload_model():
    """Unload the Florence2 model from memory."""
    service = get_florence2_service()
    service.unload_model()
    return {"success": True, "message": "Model unloaded"}


@router.post("/analyze", response_model=Florence2Response)
async def analyze_image(request: Florence2Request):
    """
    Analyze an image using Florence2.

    Available tasks:
    - caption, detailed_caption, more_detailed_caption: Image captioning
    - object_detection, dense_region_caption, region_proposal: Object detection
    - ocr, ocr_with_region: Text recognition
    - phrase_grounding: Find objects matching text description
    - open_vocabulary_detection: Detect specific objects by name
    - referring_expression_segmentation: Segment objects matching description
    - region_to_category, region_to_description: Describe specific regions
    """
    if not is_node2_service_enabled("FLORENCE2_ENABLED"):
        return Florence2Response(success=False, error="Florence2 service disabled (Node2 not available)")
    service = get_florence2_service()

    result = service.run_task(
        image=request.image,
        task=request.task,
        text_input=request.text_input,
        max_new_tokens=request.max_new_tokens,
        num_beams=request.num_beams
    )

    return Florence2Response(**result)


@router.post("/analyze/upload")
async def analyze_uploaded_image(
    file: UploadFile = File(...),
    task: str = Form("caption"),
    text_input: Optional[str] = Form(None)
):
    """
    Analyze an uploaded image file.

    Accepts image uploads directly without base64 encoding.
    """
    if not is_node2_service_enabled("FLORENCE2_ENABLED"):
        raise HTTPException(status_code=503, detail="Florence2 service disabled (Node2 not available)")
    service = get_florence2_service()

    # Read and encode image
    contents = await file.read()
    image_base64 = base64.b64encode(contents).decode("utf-8")

    result = service.run_task(
        image=image_base64,
        task=task,
        text_input=text_input
    )

    return result


@router.post("/caption")
async def caption_image(request: Florence2Request):
    """Generate a caption for an image (shortcut endpoint)."""
    request.task = request.task if request.task in ["caption", "detailed_caption", "more_detailed_caption"] else "caption"
    service = get_florence2_service()
    return service.run_task(image=request.image, task=request.task)


@router.post("/detect")
async def detect_objects(request: Florence2Request):
    """Detect objects in an image (shortcut endpoint)."""
    service = get_florence2_service()
    return service.run_task(image=request.image, task="object_detection")


@router.post("/ocr")
async def extract_text(request: Florence2Request):
    """Extract text from an image using OCR (shortcut endpoint)."""
    service = get_florence2_service()
    task = "ocr_with_region" if request.task == "ocr_with_region" else "ocr"
    return service.run_task(image=request.image, task=task)


@router.post("/ground")
async def ground_phrase(request: Florence2Request):
    """
    Find objects in image matching a text description.

    Requires text_input with the description to ground.
    Example: text_input="a red car" will find and locate red cars in the image.
    """
    if not request.text_input:
        raise HTTPException(
            status_code=400,
            detail="text_input is required for phrase grounding"
        )

    service = get_florence2_service()
    return service.run_task(
        image=request.image,
        task="phrase_grounding",
        text_input=request.text_input
    )


@router.post("/segment")
async def segment_object(request: Florence2Request):
    """
    Segment objects matching a text description.

    Requires text_input with the description of what to segment.
    Example: text_input="the car" will segment the car in the image.
    """
    if not request.text_input:
        raise HTTPException(
            status_code=400,
            detail="text_input is required for segmentation"
        )

    service = get_florence2_service()
    return service.run_task(
        image=request.image,
        task="referring_expression_segmentation",
        text_input=request.text_input
    )


# ============================================================================
# Batch Processing
# ============================================================================

class BatchRequest(BaseModel):
    """Request model for batch processing."""
    image: str  # Base64 encoded image
    tasks: List[str]  # List of tasks to run


@router.post("/batch")
async def batch_analyze(request: BatchRequest):
    """
    Run multiple tasks on a single image.

    Useful for getting caption + object detection + OCR in one request.
    """
    service = get_florence2_service()

    results = {}
    total_time = 0

    for task in request.tasks:
        result = service.run_task(image=request.image, task=task)
        results[task] = result
        if result.get("success"):
            total_time += result.get("inference_time", 0)

    return {
        "success": True,
        "results": results,
        "total_inference_time": total_time
    }


# ============================================================================
# Cascaded Tasks (Caption -> Grounding)
# ============================================================================

@router.post("/cascade/caption-ground")
async def cascade_caption_and_ground(request: Florence2Request):
    """
    Generate a caption and then ground all phrases in it.

    This runs captioning first, then uses the caption for phrase grounding.
    Returns both the caption and bounding boxes for mentioned objects.
    """
    service = get_florence2_service()

    # Get caption
    caption_task = request.task if request.task in ["caption", "detailed_caption", "more_detailed_caption"] else "detailed_caption"
    caption_result = service.run_task(image=request.image, task=caption_task)

    if not caption_result.get("success"):
        return caption_result

    caption_text = caption_result.get("result", "")

    # Ground the caption
    ground_result = service.run_task(
        image=request.image,
        task="phrase_grounding",
        text_input=caption_text
    )

    return {
        "success": True,
        "caption": caption_text,
        "grounding": ground_result.get("result") if ground_result.get("success") else None,
        "total_inference_time": (
            caption_result.get("inference_time", 0) +
            ground_result.get("inference_time", 0)
        )
    }
