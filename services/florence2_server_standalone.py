#!/usr/bin/env python3
"""
Florence2 Standalone Server for Node2

Run this on node2 (with RTX 4080 Super / RTX 3060) to serve Florence2 inference.
Main Iris instance will call this API over the network.

Usage:
    python florence2_server_standalone.py --host 0.0.0.0 --port 5100 --device cuda:0

The model path should be accessible on node2 (either copied or via NFS mount).
"""

import argparse
import base64
import time
from io import BytesIO
from pathlib import Path
from typing import Optional, Dict, Any, List

import torch
from PIL import Image
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# ============================================================================
# Configuration
# ============================================================================

# Default model path - adjust for node2's filesystem
MODEL_PATH = "/models/vision/florence2"

# Available tasks
FLORENCE2_TASKS = {
    "caption": "<CAPTION>",
    "detailed_caption": "<DETAILED_CAPTION>",
    "more_detailed_caption": "<MORE_DETAILED_CAPTION>",
    "object_detection": "<OD>",
    "dense_region_caption": "<DENSE_REGION_CAPTION>",
    "region_proposal": "<REGION_PROPOSAL>",
    "ocr": "<OCR>",
    "ocr_with_region": "<OCR_WITH_REGION>",
    "phrase_grounding": "<CAPTION_TO_PHRASE_GROUNDING>",
    "open_vocabulary_detection": "<OPEN_VOCABULARY_DETECTION>",
    "referring_expression_segmentation": "<REFERRING_EXPRESSION_SEGMENTATION>",
    "region_to_segmentation": "<REGION_TO_SEGMENTATION>",
    "region_to_category": "<REGION_TO_CATEGORY>",
    "region_to_description": "<REGION_TO_DESCRIPTION>",
}

# ============================================================================
# Global Model State
# ============================================================================

model = None
processor = None
device = None
torch_dtype = None
model_loaded = False


def load_model(model_path: str, target_device: str = "cuda:0"):
    """Load Florence2 model into memory."""
    global model, processor, device, torch_dtype, model_loaded

    if model_loaded:
        print("[Florence2] Model already loaded")
        return True

    try:
        from transformers import AutoProcessor, AutoModelForCausalLM

        print(f"[Florence2] Loading model from {model_path}...")
        print(f"[Florence2] Target device: {target_device}")
        start_time = time.time()

        device = target_device if torch.cuda.is_available() else "cpu"
        torch_dtype = torch.float16 if torch.cuda.is_available() else torch.float32

        print(f"[Florence2] Using device: {device}, dtype: {torch_dtype}")

        # Load processor
        processor = AutoProcessor.from_pretrained(
            model_path,
            trust_remote_code=True
        )

        # Load model with eager attention to avoid SDPA issues
        model = AutoModelForCausalLM.from_pretrained(
            model_path,
            torch_dtype=torch_dtype,
            trust_remote_code=True,
            attn_implementation="eager"
        ).to(device)

        model.eval()
        model_loaded = True

        load_time = time.time() - start_time
        print(f"[Florence2] Model loaded in {load_time:.2f}s")

        # Print GPU memory usage
        if torch.cuda.is_available():
            mem_allocated = torch.cuda.memory_allocated(device) / 1024**3
            mem_reserved = torch.cuda.memory_reserved(device) / 1024**3
            print(f"[Florence2] GPU memory: {mem_allocated:.2f}GB allocated, {mem_reserved:.2f}GB reserved")

        return True

    except Exception as e:
        print(f"[Florence2] Failed to load model: {e}")
        import traceback
        traceback.print_exc()
        return False


def unload_model():
    """Unload model from memory."""
    global model, processor, model_loaded

    if not model_loaded:
        return

    print("[Florence2] Unloading model...")
    del model
    del processor
    model = None
    processor = None
    model_loaded = False

    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    print("[Florence2] Model unloaded")


def decode_image(image_data: str) -> Image.Image:
    """Decode base64 image string to PIL Image."""
    if "base64," in image_data:
        image_data = image_data.split("base64,")[1]
    image_bytes = base64.b64decode(image_data)
    return Image.open(BytesIO(image_bytes)).convert("RGB")


def run_inference(
    image: Image.Image,
    task: str,
    text_input: Optional[str] = None,
    max_new_tokens: int = 1024,
    num_beams: int = 3
) -> Dict[str, Any]:
    """Run Florence2 inference on an image."""
    global model, processor, device, torch_dtype, model_loaded

    if not model_loaded:
        return {"success": False, "error": "Model not loaded"}

    try:
        # Get task prompt
        task_lower = task.lower().replace("-", "_").replace(" ", "_")
        if task_lower in FLORENCE2_TASKS:
            task_prompt = FLORENCE2_TASKS[task_lower]
        elif task.startswith("<") and task.endswith(">"):
            task_prompt = task
        else:
            return {"success": False, "error": f"Unknown task: {task}"}

        # Build prompt
        prompt = task_prompt + text_input if text_input else task_prompt

        print(f"[Florence2] Running: {task_prompt}")
        start_time = time.time()

        # Process inputs
        inputs = processor(
            text=prompt,
            images=image,
            return_tensors="pt"
        ).to(device, torch_dtype)

        # Generate (disable cache to avoid past_key_values compatibility issues)
        with torch.no_grad():
            generated_ids = model.generate(
                input_ids=inputs["input_ids"],
                pixel_values=inputs["pixel_values"],
                max_new_tokens=max_new_tokens,
                num_beams=1,
                do_sample=False,
                use_cache=False  # Disable KV cache to avoid compatibility issues
            )

        # Decode
        generated_text = processor.batch_decode(
            generated_ids,
            skip_special_tokens=False
        )[0]

        # Post-process
        parsed_answer = processor.post_process_generation(
            generated_text,
            task=task_prompt,
            image_size=(image.width, image.height)
        )

        inference_time = time.time() - start_time
        print(f"[Florence2] Completed in {inference_time:.2f}s")

        return {
            "success": True,
            "task": task_prompt,
            "result": parsed_answer.get(task_prompt, parsed_answer),
            "raw_output": parsed_answer,
            "inference_time": inference_time,
            "image_size": {"width": image.width, "height": image.height}
        }

    except Exception as e:
        print(f"[Florence2] Inference error: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


# ============================================================================
# FastAPI Application
# ============================================================================

app = FastAPI(
    title="Florence2 Server",
    description="Remote Florence2 inference server for Iris",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnalyzeRequest(BaseModel):
    image: str  # Base64 encoded
    task: str = "caption"
    text_input: Optional[str] = None
    max_new_tokens: int = 1024
    num_beams: int = 3


class BatchRequest(BaseModel):
    image: str
    tasks: List[str]


@app.get("/")
async def root():
    return {"service": "Florence2 Server", "status": "running"}


@app.get("/status")
async def status():
    gpu_info = None
    if torch.cuda.is_available() and model_loaded:
        gpu_info = {
            "device": str(device),
            "memory_allocated_gb": torch.cuda.memory_allocated(device) / 1024**3,
            "memory_reserved_gb": torch.cuda.memory_reserved(device) / 1024**3,
        }
    return {
        "loaded": model_loaded,
        "device": str(device) if device else None,
        "gpu_info": gpu_info,
        "available_tasks": list(FLORENCE2_TASKS.keys())
    }


@app.get("/tasks")
async def list_tasks():
    return {"tasks": FLORENCE2_TASKS}


@app.post("/load")
async def api_load_model(device: str = "cuda:0"):
    success = load_model(MODEL_PATH, device)
    if success:
        return {"success": True, "message": f"Model loaded on {device}"}
    raise HTTPException(status_code=500, detail="Failed to load model")


@app.post("/unload")
async def api_unload_model():
    unload_model()
    return {"success": True, "message": "Model unloaded"}


@app.post("/analyze")
async def analyze(request: AnalyzeRequest):
    if not model_loaded:
        raise HTTPException(status_code=503, detail="Model not loaded")

    try:
        image = decode_image(request.image)
        result = run_inference(
            image=image,
            task=request.task,
            text_input=request.text_input,
            max_new_tokens=request.max_new_tokens,
            num_beams=request.num_beams
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/batch")
async def batch_analyze(request: BatchRequest):
    if not model_loaded:
        raise HTTPException(status_code=503, detail="Model not loaded")

    try:
        image = decode_image(request.image)
        results = {}
        total_time = 0

        for task in request.tasks:
            result = run_inference(image=image, task=task)
            results[task] = result
            if result.get("success"):
                total_time += result.get("inference_time", 0)

        return {
            "success": True,
            "results": results,
            "total_inference_time": total_time
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    return {"status": "ok", "model_loaded": model_loaded}


# ============================================================================
# Main
# ============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Florence2 Standalone Server")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=5100, help="Port to listen on")
    parser.add_argument("--device", type=str, default="cuda:0", help="CUDA device (cuda:0, cuda:1, cpu)")
    parser.add_argument("--model-path", type=str, default=MODEL_PATH, help="Path to Florence2 model")
    parser.add_argument("--preload", action="store_true", help="Load model on startup")
    args = parser.parse_args()

    # Update model path if specified
    MODEL_PATH = args.model_path

    print("=" * 60)
    print("FLORENCE2 STANDALONE SERVER")
    print("=" * 60)
    print(f"Host: {args.host}")
    print(f"Port: {args.port}")
    print(f"Device: {args.device}")
    print(f"Model path: {MODEL_PATH}")
    print("=" * 60)

    # Preload model if requested
    if args.preload:
        print("Preloading model...")
        load_model(MODEL_PATH, args.device)

    # Run server
    uvicorn.run(app, host=args.host, port=args.port)
