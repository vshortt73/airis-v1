"""
PaddleOCR API Routes for Iris v3.

Provides REST endpoints for high-quality OCR with bounding boxes.
Designed for spatial analysis of deck plans and floor maps.
"""

import sys
from pathlib import Path
from typing import Optional, List
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
import base64

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from services.paddleocr_service import get_paddleocr_service
from core.node2_check import is_node2_service_enabled

router = APIRouter(prefix="/api/ocr", tags=["ocr"])


# ============================================================================
# Request/Response Models
# ============================================================================

class OCRRequest(BaseModel):
    """Request model for OCR analysis."""
    image: str  # Base64 encoded image
    det_only: bool = False  # Detection only (no text recognition)
    min_confidence: float = 0.5  # Minimum confidence threshold
    lang: str = "en"  # Language


class BatchOCRRequest(BaseModel):
    """Request model for batch OCR."""
    images: List[str]  # List of base64 encoded images
    min_confidence: float = 0.5


class TextDetection(BaseModel):
    """Single text detection result."""
    text: Optional[str] = None
    bbox: List[float]  # [x1, y1, x2, y2]
    quad: List[List[float]]  # 4 corner points
    center: List[float]  # [x, y]
    confidence: float


# ============================================================================
# API Endpoints
# ============================================================================

@router.get("/status")
async def get_status():
    """Get PaddleOCR service status."""
    if not is_node2_service_enabled("PADDLEOCR_ENABLED"):
        return {"status": "disabled", "reason": "PaddleOCR service disabled (Node2 not available)"}
    service = get_paddleocr_service()
    return service.get_status()


@router.post("/load")
async def load_engine(use_gpu: bool = True, lang: str = "en"):
    """Load the OCR engine on the remote server."""
    service = get_paddleocr_service()

    if service.is_loaded():
        return {"success": True, "message": "OCR engine already loaded"}

    success = service.load_engine(use_gpu=use_gpu, lang=lang)

    if success:
        return {"success": True, "message": f"OCR engine loaded (GPU: {use_gpu})"}
    raise HTTPException(status_code=500, detail="Failed to load OCR engine")


@router.post("/unload")
async def unload_engine():
    """Unload the OCR engine."""
    service = get_paddleocr_service()
    service.unload_engine()
    return {"success": True, "message": "OCR engine unloaded"}


@router.post("/analyze")
async def analyze_image(request: OCRRequest):
    """
    Run OCR on an image.

    Returns list of text detections with bounding boxes.
    Each detection includes:
    - text: The recognized text
    - bbox: [x1, y1, x2, y2] bounding box
    - quad: 4-corner polygon points
    - center: [x, y] center point
    - confidence: Recognition confidence (0-1)
    """
    if not is_node2_service_enabled("PADDLEOCR_ENABLED"):
        raise HTTPException(status_code=503, detail="PaddleOCR service disabled (Node2 not available)")
    service = get_paddleocr_service()

    result = service.run_ocr(
        image=request.image,
        det_only=request.det_only,
        min_confidence=request.min_confidence,
        lang=request.lang
    )

    if not result.get("success"):
        raise HTTPException(
            status_code=500,
            detail=result.get("error", "OCR failed")
        )

    return result


@router.post("/analyze/upload")
async def analyze_uploaded_image(
    file: UploadFile = File(...),
    det_only: bool = Form(False),
    min_confidence: float = Form(0.5)
):
    """
    Analyze an uploaded image file.

    Accepts image uploads directly without base64 encoding.
    """
    service = get_paddleocr_service()

    # Read and encode image
    contents = await file.read()
    image_base64 = base64.b64encode(contents).decode("utf-8")

    result = service.run_ocr(
        image=image_base64,
        det_only=det_only,
        min_confidence=min_confidence
    )

    if not result.get("success"):
        raise HTTPException(
            status_code=500,
            detail=result.get("error", "OCR failed")
        )

    return result


@router.post("/detect")
async def detect_text_regions(request: OCRRequest):
    """
    Detect text regions only (no recognition).

    Faster than full OCR, useful for finding text locations.
    """
    service = get_paddleocr_service()
    return service.run_detection(
        image=request.image,
        min_confidence=request.min_confidence
    )


@router.post("/batch")
async def batch_analyze(request: BatchOCRRequest):
    """
    Run OCR on multiple images.

    Returns results for each image.
    """
    service = get_paddleocr_service()
    return service.run_batch_ocr(
        images=request.images,
        min_confidence=request.min_confidence
    )


@router.post("/text")
async def extract_text(request: OCRRequest):
    """
    Extract just the text content from an image.

    Returns a simple text string instead of full detection data.
    """
    service = get_paddleocr_service()
    text = service.extract_text_only(
        image=request.image,
        min_confidence=request.min_confidence
    )
    return {"success": True, "text": text}


@router.post("/spatial")
async def get_spatial_map(request: OCRRequest):
    """
    Get text with spatial layout information.

    Returns text organized by rows with position data.
    Useful for deck plans, floor maps, and layout analysis.

    Response includes:
    - rows: List of rows, each containing detections sorted left-to-right
    - row_count: Number of detected rows
    - total_detections: Total number of text detections
    """
    service = get_paddleocr_service()
    result = service.get_spatial_text_map(
        image=request.image,
        min_confidence=request.min_confidence
    )

    if not result.get("success"):
        raise HTTPException(
            status_code=500,
            detail=result.get("error", "OCR failed")
        )

    return result


@router.get("/health")
async def health():
    """Health check endpoint."""
    if not is_node2_service_enabled("PADDLEOCR_ENABLED"):
        return {"status": "disabled", "reason": "PaddleOCR service disabled (Node2 not available)"}
    service = get_paddleocr_service()
    status = service.get_status()
    return {
        "status": "ok",
        "ocr_loaded": status.get("loaded", False),
        "remote_url": status.get("url")
    }
