#!/usr/bin/env python3
"""
PaddleOCR Standalone Server for Node2

High-quality OCR service optimized for deck plans and floor maps.
Returns text detections with bounding boxes for spatial analysis.

Usage:
    python paddleocr_server_standalone.py --host 0.0.0.0 --port 5200 --device gpu

Requirements:
    pip install paddlepaddle-gpu  # or paddlepaddle for CPU
    pip install paddleocr
    pip install fastapi uvicorn pillow
"""

import argparse
import base64
import time
from io import BytesIO
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# ============================================================================
# Global State
# ============================================================================

ocr_engine = None
ocr_loaded = False
use_gpu = True


def load_ocr(use_gpu_flag: bool = True, lang: str = "en"):
    """Load PaddleOCR engine."""
    global ocr_engine, ocr_loaded, use_gpu

    if ocr_loaded:
        print("[PaddleOCR] Already loaded")
        return True

    try:
        from paddleocr import PaddleOCR

        print(f"[PaddleOCR] Loading OCR engine (GPU: {use_gpu_flag}, lang: {lang})...")
        start_time = time.time()

        use_gpu = use_gpu_flag

        # Initialize PaddleOCR (2.x API)
        # use_angle_cls=True for rotated text (common in deck plans)
        # det_db_thresh lowered for better detection of small text
        # det_limit_side_len increased for high-res deck plans (default 960)
        ocr_engine = PaddleOCR(
            use_angle_cls=True,
            lang=lang,
            use_gpu=use_gpu_flag,
            show_log=False,
            det_db_thresh=0.3,  # Lower threshold for better detection
            det_db_box_thresh=0.5,
            det_db_unclip_ratio=1.6,  # Slightly larger boxes
            rec_batch_num=16,
            det_limit_side_len=2560,  # Higher res for deck plans (default 960)
            det_limit_type='max',
        )

        ocr_loaded = True
        load_time = time.time() - start_time
        print(f"[PaddleOCR] Loaded in {load_time:.2f}s")

        return True

    except Exception as e:
        print(f"[PaddleOCR] Failed to load: {e}")
        import traceback
        traceback.print_exc()
        return False


def unload_ocr():
    """Unload OCR engine."""
    global ocr_engine, ocr_loaded

    if not ocr_loaded:
        return

    print("[PaddleOCR] Unloading...")
    ocr_engine = None
    ocr_loaded = False
    print("[PaddleOCR] Unloaded")


def decode_image(image_data: str):
    """Decode base64 image to numpy array."""
    from PIL import Image
    import numpy as np

    if "base64," in image_data:
        image_data = image_data.split("base64,")[1]

    image_bytes = base64.b64decode(image_data)
    pil_image = Image.open(BytesIO(image_bytes)).convert("RGB")

    return np.array(pil_image), pil_image.size


def run_ocr(
    image_data: str,
    det_only: bool = False,
    min_confidence: float = 0.5,
) -> Dict[str, Any]:
    """
    Run OCR on an image.

    Args:
        image_data: Base64 encoded image
        det_only: If True, only run detection (no recognition)
        min_confidence: Minimum confidence threshold for results

    Returns:
        Dict with detections including text, bounding boxes, confidence
    """
    global ocr_engine, ocr_loaded

    if not ocr_loaded:
        return {"success": False, "error": "OCR engine not loaded"}

    try:
        print("[PaddleOCR] Processing image...")
        start_time = time.time()

        # Decode image
        img_array, (width, height) = decode_image(image_data)

        # Run OCR
        if det_only:
            # Detection only
            result = ocr_engine.ocr(img_array, det=True, rec=False, cls=False)
        else:
            # Full OCR (detection + recognition)
            result = ocr_engine.ocr(img_array, cls=True)

        inference_time = time.time() - start_time
        print(f"[PaddleOCR] Completed in {inference_time:.2f}s")

        # Parse results
        detections = []

        if result and result[0]:
            for item in result[0]:
                if det_only:
                    # Detection only returns bounding box
                    bbox = item
                    text = None
                    confidence = 1.0
                else:
                    # Full OCR returns (bbox, (text, confidence))
                    bbox = item[0]
                    text = item[1][0]
                    confidence = float(item[1][1])

                # Skip low confidence results
                if confidence < min_confidence:
                    continue

                # Convert bbox to simple format [x1, y1, x2, y2]
                # PaddleOCR returns 4 corner points
                x_coords = [p[0] for p in bbox]
                y_coords = [p[1] for p in bbox]
                simple_bbox = [
                    min(x_coords),  # x1
                    min(y_coords),  # y1
                    max(x_coords),  # x2
                    max(y_coords),  # y2
                ]

                detection = {
                    "bbox": simple_bbox,
                    "quad": bbox,  # Original 4-point polygon
                    "confidence": round(confidence, 4),
                }

                if text is not None:
                    detection["text"] = text

                # Calculate center point (useful for spatial analysis)
                detection["center"] = [
                    (simple_bbox[0] + simple_bbox[2]) / 2,
                    (simple_bbox[1] + simple_bbox[3]) / 2,
                ]

                detections.append(detection)

        # Sort by vertical position (top to bottom), then horizontal (left to right)
        detections.sort(key=lambda d: (d["center"][1], d["center"][0]))

        return {
            "success": True,
            "detections": detections,
            "count": len(detections),
            "image_size": {"width": width, "height": height},
            "inference_time": inference_time,
        }

    except Exception as e:
        print(f"[PaddleOCR] Error: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


# ============================================================================
# FastAPI Application
# ============================================================================

app = FastAPI(
    title="PaddleOCR Server",
    description="High-quality OCR service for deck plans and floor maps",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class OCRRequest(BaseModel):
    image: str  # Base64 encoded
    det_only: bool = False  # Detection only (no text recognition)
    min_confidence: float = 0.5  # Minimum confidence threshold
    lang: str = "en"  # Language (not used after initial load)


class BatchOCRRequest(BaseModel):
    images: List[str]  # List of base64 encoded images
    min_confidence: float = 0.5


@app.get("/")
async def root():
    return {"service": "PaddleOCR Server", "status": "running"}


@app.get("/status")
async def status():
    return {
        "loaded": ocr_loaded,
        "use_gpu": use_gpu,
    }


@app.post("/load")
async def api_load(use_gpu: bool = True, lang: str = "en"):
    success = load_ocr(use_gpu_flag=use_gpu, lang=lang)
    if success:
        return {"success": True, "message": f"OCR loaded (GPU: {use_gpu})"}
    raise HTTPException(status_code=500, detail="Failed to load OCR engine")


@app.post("/unload")
async def api_unload():
    unload_ocr()
    return {"success": True, "message": "OCR unloaded"}


@app.post("/ocr")
async def api_ocr(request: OCRRequest):
    """
    Run OCR on an image.

    Returns list of text detections with bounding boxes.
    Each detection includes:
    - text: The recognized text
    - bbox: [x1, y1, x2, y2] bounding box
    - quad: 4-corner polygon points
    - confidence: Recognition confidence (0-1)
    - center: [x, y] center point of detection
    """
    if not ocr_loaded:
        # Auto-load if not loaded
        if not load_ocr():
            raise HTTPException(status_code=503, detail="OCR engine not loaded")

    result = run_ocr(
        image_data=request.image,
        det_only=request.det_only,
        min_confidence=request.min_confidence,
    )

    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "OCR failed"))

    return result


@app.post("/ocr/detect")
async def api_detect(request: OCRRequest):
    """
    Run text detection only (no recognition).

    Faster than full OCR, useful for finding text regions.
    """
    request.det_only = True
    return await api_ocr(request)


@app.post("/ocr/batch")
async def api_batch_ocr(request: BatchOCRRequest):
    """
    Run OCR on multiple images.
    """
    if not ocr_loaded:
        if not load_ocr():
            raise HTTPException(status_code=503, detail="OCR engine not loaded")

    results = []
    total_time = 0

    for i, image in enumerate(request.images):
        result = run_ocr(
            image_data=image,
            min_confidence=request.min_confidence,
        )
        results.append(result)
        if result["success"]:
            total_time += result.get("inference_time", 0)

    return {
        "success": True,
        "results": results,
        "total_images": len(request.images),
        "total_inference_time": total_time,
    }


@app.get("/health")
async def health():
    return {"status": "ok", "ocr_loaded": ocr_loaded}


# ============================================================================
# Main
# ============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PaddleOCR Server")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host to bind")
    parser.add_argument("--port", type=int, default=5200, help="Port to listen on")
    parser.add_argument("--device", type=str, default="gpu", choices=["gpu", "cpu"],
                        help="Device to use")
    parser.add_argument("--lang", type=str, default="en", help="OCR language")
    parser.add_argument("--preload", action="store_true", help="Load OCR on startup")
    args = parser.parse_args()

    print("=" * 60)
    print("PADDLEOCR SERVER")
    print("=" * 60)
    print(f"Host: {args.host}")
    print(f"Port: {args.port}")
    print(f"Device: {args.device}")
    print(f"Language: {args.lang}")
    print("=" * 60)

    if args.preload:
        print("Preloading OCR engine...")
        load_ocr(use_gpu_flag=(args.device == "gpu"), lang=args.lang)

    uvicorn.run(app, host=args.host, port=args.port)
