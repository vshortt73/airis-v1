"""
Florence2 Vision Service for Iris v3
Provides image analysis capabilities using Microsoft's Florence-2 model.

Supports two modes:
1. LOCAL: Load model directly (requires compatible GPU)
2. REMOTE: Call Florence2 server on node2 over HTTP

Supports tasks:
- Captioning: CAPTION, DETAILED_CAPTION, MORE_DETAILED_CAPTION
- Object Detection: OD, DENSE_REGION_CAPTION, REGION_PROPOSAL
- OCR: OCR, OCR_WITH_REGION
- Grounding: CAPTION_TO_PHRASE_GROUNDING, OPEN_VOCABULARY_DETECTION
- Segmentation: REFERRING_EXPRESSION_SEGMENTATION, REGION_TO_SEGMENTATION
- Region Understanding: REGION_TO_CATEGORY, REGION_TO_DESCRIPTION
"""

import sys
import os
from pathlib import Path
from typing import Optional, Dict, Any, List, Union
import threading
import time
import base64
from io import BytesIO
import httpx

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Configuration - try to load from app config, fall back to defaults
try:
    from app import config as app_config
    FLORENCE2_REMOTE_URL = getattr(app_config, 'FLORENCE2_SERVER_URL', "http://node2:5100")
    FLORENCE2_MODE = getattr(app_config, 'FLORENCE2_MODE', "remote")
except ImportError:
    FLORENCE2_REMOTE_URL = os.environ.get("FLORENCE2_REMOTE_URL", "http://node2:5100")
    FLORENCE2_MODE = os.environ.get("FLORENCE2_MODE", "remote")

FLORENCE2_MODEL_PATH = "/models/vision/florence2"

# Available tasks
FLORENCE2_TASKS = {
    # Captioning tasks (no additional input)
    "caption": "<CAPTION>",
    "detailed_caption": "<DETAILED_CAPTION>",
    "more_detailed_caption": "<MORE_DETAILED_CAPTION>",

    # Object detection tasks (no additional input)
    "object_detection": "<OD>",
    "dense_region_caption": "<DENSE_REGION_CAPTION>",
    "region_proposal": "<REGION_PROPOSAL>",

    # OCR tasks (no additional input)
    "ocr": "<OCR>",
    "ocr_with_region": "<OCR_WITH_REGION>",

    # Tasks requiring text input
    "phrase_grounding": "<CAPTION_TO_PHRASE_GROUNDING>",
    "open_vocabulary_detection": "<OPEN_VOCABULARY_DETECTION>",
    "referring_expression_segmentation": "<REFERRING_EXPRESSION_SEGMENTATION>",

    # Tasks requiring region input (format: <loc_x1><loc_y1><loc_x2><loc_y2>)
    "region_to_segmentation": "<REGION_TO_SEGMENTATION>",
    "region_to_category": "<REGION_TO_CATEGORY>",
    "region_to_description": "<REGION_TO_DESCRIPTION>",
}


class Florence2Service:
    """
    Service for running Florence-2 vision model inference.

    Supports two modes:
    - LOCAL: Load model directly on this machine
    - REMOTE: Call Florence2 server on node2 over HTTP

    Set FLORENCE2_MODE environment variable to "local" or "remote" (default: remote)
    Set FLORENCE2_REMOTE_URL for the node2 server address (default: http://node2:5100)
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        """Singleton pattern for shared model access."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self.model = None
        self.processor = None
        self.device = None
        self.torch_dtype = None
        self._model_loaded = False
        self._last_used = 0
        self._load_lock = threading.Lock()
        self._initialized = True

        # Remote mode settings
        self.mode = FLORENCE2_MODE
        self.remote_url = FLORENCE2_REMOTE_URL
        self._http_client = None

        print(f"[Florence2Service] Initialized in {self.mode.upper()} mode")
        if self.mode == "remote":
            print(f"[Florence2Service] Remote URL: {self.remote_url}")

    def is_loaded(self) -> bool:
        """Check if model is currently loaded (local) or server is available (remote)."""
        if self.mode == "remote":
            return self._check_remote_status()
        return self._model_loaded and self.model is not None

    def _check_remote_status(self) -> bool:
        """Check if remote Florence2 server is available and has model loaded."""
        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.get(f"{self.remote_url}/status")
                if response.status_code == 200:
                    data = response.json()
                    return data.get("loaded", False)
        except Exception as e:
            print(f"[Florence2Service] Remote status check failed: {e}")
        return False

    def _get_http_client(self) -> httpx.Client:
        """Get or create HTTP client for remote calls."""
        if self._http_client is None:
            self._http_client = httpx.Client(timeout=120.0)  # Long timeout for inference
        return self._http_client

    def load_model(self, device: str = "cuda:0") -> bool:
        """
        Load the Florence-2 model into memory.

        In REMOTE mode, this triggers model loading on the remote server.
        In LOCAL mode, this loads the model on this machine.

        Args:
            device: Device to load model on (default: cuda:0)

        Returns:
            True if loaded successfully
        """
        # Remote mode - tell server to load model
        if self.mode == "remote":
            try:
                print(f"[Florence2Service] Requesting remote server to load model...")
                client = self._get_http_client()
                response = client.post(
                    f"{self.remote_url}/load",
                    params={"device": device},
                    timeout=300.0  # Long timeout for model loading
                )
                if response.status_code == 200:
                    print("[Florence2Service] Remote model loaded successfully")
                    return True
                else:
                    print(f"[Florence2Service] Remote load failed: {response.text}")
                    return False
            except Exception as e:
                print(f"[Florence2Service] Remote load error: {e}")
                return False

        # Local mode - load model here
        with self._load_lock:
            if self._model_loaded:
                print("[Florence2Service] Model already loaded")
                return True

            try:
                import torch
                from transformers import AutoProcessor, AutoModelForCausalLM

                print(f"[Florence2Service] Loading model from {FLORENCE2_MODEL_PATH}...")
                start_time = time.time()

                # Set device and dtype
                self.device = device if torch.cuda.is_available() else "cpu"
                self.torch_dtype = torch.float16 if torch.cuda.is_available() else torch.float32

                # Load processor and model
                self.processor = AutoProcessor.from_pretrained(
                    FLORENCE2_MODEL_PATH,
                    trust_remote_code=True
                )

                self.model = AutoModelForCausalLM.from_pretrained(
                    FLORENCE2_MODEL_PATH,
                    torch_dtype=self.torch_dtype,
                    trust_remote_code=True,
                    attn_implementation="eager"  # Fix for newer transformers versions
                ).to(self.device)

                self.model.eval()
                self._model_loaded = True
                self._last_used = time.time()

                load_time = time.time() - start_time
                print(f"[Florence2Service] Model loaded on {self.device} in {load_time:.2f}s")

                return True

            except Exception as e:
                print(f"[Florence2Service] Failed to load model: {e}")
                import traceback
                traceback.print_exc()
                return False

    def unload_model(self):
        """Unload model from memory to free GPU resources."""
        # Remote mode - tell server to unload
        if self.mode == "remote":
            try:
                client = self._get_http_client()
                response = client.post(f"{self.remote_url}/unload")
                if response.status_code == 200:
                    print("[Florence2Service] Remote model unloaded")
                else:
                    print(f"[Florence2Service] Remote unload failed: {response.text}")
            except Exception as e:
                print(f"[Florence2Service] Remote unload error: {e}")
            return

        # Local mode - unload here
        with self._load_lock:
            if not self._model_loaded:
                return

            try:
                import torch

                print("[Florence2Service] Unloading model...")

                del self.model
                del self.processor
                self.model = None
                self.processor = None
                self._model_loaded = False

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()

                print("[Florence2Service] Model unloaded")

            except Exception as e:
                print(f"[Florence2Service] Error unloading model: {e}")

    def _decode_image(self, image_data: Union[str, bytes]) -> "Image":
        """
        Decode image from base64 string or bytes.

        Args:
            image_data: Base64 encoded string or raw bytes

        Returns:
            PIL Image object
        """
        from PIL import Image

        if isinstance(image_data, str):
            # Remove data URI prefix if present
            if "base64," in image_data:
                image_data = image_data.split("base64,")[1]
            image_bytes = base64.b64decode(image_data)
        else:
            image_bytes = image_data

        return Image.open(BytesIO(image_bytes)).convert("RGB")

    def run_task(
        self,
        image: Union[str, bytes, "Image"],
        task: str,
        text_input: Optional[str] = None,
        max_new_tokens: int = 1024,
        num_beams: int = 3
    ) -> Dict[str, Any]:
        """
        Run a Florence-2 task on an image.

        Args:
            image: Image as base64 string, bytes, or PIL Image
            task: Task name (e.g., "caption", "object_detection", "ocr")
            text_input: Additional text input for tasks that require it
            max_new_tokens: Maximum tokens to generate
            num_beams: Number of beams for beam search

        Returns:
            Dict with success status and results
        """
        # Convert image to base64 if needed (for remote mode)
        if self.mode == "remote":
            image_b64 = self._ensure_base64(image)
            return self._run_remote_task(image_b64, task, text_input, max_new_tokens, num_beams)

        # Local mode
        return self._run_local_task(image, task, text_input, max_new_tokens, num_beams)

    def _ensure_base64(self, image: Union[str, bytes, "Image"]) -> str:
        """Ensure image is in base64 string format."""
        if isinstance(image, str):
            # Already base64 (or has data URI prefix)
            if "base64," in image:
                return image.split("base64,")[1]
            return image
        elif isinstance(image, bytes):
            return base64.b64encode(image).decode("utf-8")
        else:
            # PIL Image - convert to base64
            from PIL import Image as PILImage
            buffer = BytesIO()
            image.save(buffer, format="PNG")
            return base64.b64encode(buffer.getvalue()).decode("utf-8")

    def _run_remote_task(
        self,
        image_b64: str,
        task: str,
        text_input: Optional[str],
        max_new_tokens: int,
        num_beams: int
    ) -> Dict[str, Any]:
        """Run task on remote Florence2 server."""
        try:
            print(f"[Florence2Service] Running remote task: {task}")
            start_time = time.time()

            client = self._get_http_client()
            response = client.post(
                f"{self.remote_url}/analyze",
                json={
                    "image": image_b64,
                    "task": task,
                    "text_input": text_input,
                    "max_new_tokens": max_new_tokens,
                    "num_beams": num_beams
                }
            )

            if response.status_code == 200:
                result = response.json()
                total_time = time.time() - start_time
                print(f"[Florence2Service] Remote task completed in {total_time:.2f}s (inference: {result.get('inference_time', 0):.2f}s)")
                return result
            elif response.status_code == 503:
                return {"success": False, "error": "Remote model not loaded. Call load_model() first."}
            else:
                return {"success": False, "error": f"Remote error: {response.text}"}

        except httpx.TimeoutException:
            return {"success": False, "error": "Remote server timeout"}
        except Exception as e:
            print(f"[Florence2Service] Remote task error: {e}")
            return {"success": False, "error": str(e)}

    def _run_local_task(
        self,
        image: Union[str, bytes, "Image"],
        task: str,
        text_input: Optional[str],
        max_new_tokens: int,
        num_beams: int
    ) -> Dict[str, Any]:
        """Run task locally on this machine."""
        import torch
        from PIL import Image as PILImage

        # Ensure model is loaded
        if not self.is_loaded():
            if not self.load_model():
                return {"success": False, "error": "Failed to load model"}

        self._last_used = time.time()

        try:
            # Get task prompt
            task_lower = task.lower().replace("-", "_").replace(" ", "_")
            if task_lower not in FLORENCE2_TASKS:
                # Check if it's a raw task prompt
                if task.startswith("<") and task.endswith(">"):
                    task_prompt = task
                else:
                    return {
                        "success": False,
                        "error": f"Unknown task: {task}. Available: {list(FLORENCE2_TASKS.keys())}"
                    }
            else:
                task_prompt = FLORENCE2_TASKS[task_lower]

            # Decode image if needed
            if isinstance(image, (str, bytes)):
                pil_image = self._decode_image(image)
            else:
                pil_image = image

            # Build prompt
            if text_input:
                prompt = task_prompt + text_input
            else:
                prompt = task_prompt

            print(f"[Florence2Service] Running task: {task_prompt}")
            start_time = time.time()

            # Process inputs
            inputs = self.processor(
                text=prompt,
                images=pil_image,
                return_tensors="pt"
            ).to(self.device, self.torch_dtype)

            # Generate (use greedy decoding to avoid beam search compatibility issues)
            with torch.no_grad():
                generated_ids = self.model.generate(
                    input_ids=inputs["input_ids"],
                    pixel_values=inputs["pixel_values"],
                    max_new_tokens=max_new_tokens,
                    num_beams=1,  # Force greedy decoding - beam search has compatibility issues
                    do_sample=False,
                    use_cache=True
                )

            # Decode output
            generated_text = self.processor.batch_decode(
                generated_ids,
                skip_special_tokens=False
            )[0]

            # Post-process
            parsed_answer = self.processor.post_process_generation(
                generated_text,
                task=task_prompt,
                image_size=(pil_image.width, pil_image.height)
            )

            inference_time = time.time() - start_time
            print(f"[Florence2Service] Task completed in {inference_time:.2f}s")

            return {
                "success": True,
                "task": task_prompt,
                "result": parsed_answer.get(task_prompt, parsed_answer),
                "raw_output": parsed_answer,
                "inference_time": inference_time,
                "image_size": {"width": pil_image.width, "height": pil_image.height}
            }

        except Exception as e:
            print(f"[Florence2Service] Error running task: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}

    def get_status(self) -> Dict[str, Any]:
        """Get current service status."""
        status = {
            "mode": self.mode,
            "available_tasks": list(FLORENCE2_TASKS.keys())
        }

        if self.mode == "remote":
            status["remote_url"] = self.remote_url
            # Try to get remote status
            try:
                client = self._get_http_client()
                response = client.get(f"{self.remote_url}/status", timeout=5.0)
                if response.status_code == 200:
                    remote_status = response.json()
                    status["loaded"] = remote_status.get("loaded", False)
                    status["remote_status"] = remote_status
                else:
                    status["loaded"] = False
                    status["remote_error"] = f"Status code: {response.status_code}"
            except Exception as e:
                status["loaded"] = False
                status["remote_error"] = str(e)
        else:
            status["loaded"] = self._model_loaded
            status["device"] = str(self.device) if self.device else None
            status["last_used"] = self._last_used
            status["model_path"] = FLORENCE2_MODEL_PATH

        return status


# Singleton instance
_service_instance = None

def get_florence2_service() -> Florence2Service:
    """Get the Florence2 service singleton instance."""
    global _service_instance
    if _service_instance is None:
        _service_instance = Florence2Service()
    return _service_instance


# CLI test
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Florence2 Service Test")
    parser.add_argument("--image", type=str, help="Path to test image")
    parser.add_argument("--task", type=str, default="caption", help="Task to run")
    parser.add_argument("--text", type=str, help="Text input for task")
    args = parser.parse_args()

    service = get_florence2_service()

    print("\nFlorence2 Service Status:")
    print(service.get_status())

    if args.image:
        from PIL import Image

        print(f"\nLoading image: {args.image}")
        image = Image.open(args.image).convert("RGB")

        print(f"Running task: {args.task}")
        result = service.run_task(image, args.task, args.text)

        print("\nResult:")
        import json
        print(json.dumps(result, indent=2, default=str))
    else:
        print("\nAvailable tasks:")
        for name, prompt in FLORENCE2_TASKS.items():
            print(f"  {name}: {prompt}")
