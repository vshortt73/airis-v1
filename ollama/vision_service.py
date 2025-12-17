"""
Vision Service for Iris v3
Manages llama.cpp-based vision model (llava) on GPU 1
"""

import os
import sys
import base64
from typing import Optional, Dict
from pathlib import Path
import time

# Path setup
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app import config


class VisionService:
    """
    Manages llava vision model lifecycle on GPU 1

    Responsibilities:
    - Load/unload llava model to GPU 1 (RTX 4080 Super)
    - Process vision requests (image + prompt -> text description)
    - Handle errors and fallbacks
    - Monitor GPU memory usage
    """

    def __init__(self):
        self.model = None
        self.chat_handler = None
        self.is_model_loaded = False
        self.model_path = config.VISION_MODEL_PATH
        self.clip_path = config.VISION_CLIP_PATH
        self.gpu_id = config.VISION_GPU_ID
        self.load_time = None
        self.request_count = 0
        self.total_inference_time = 0

        print(f"[vision_service.py][__init__] Vision service initialized (GPU {self.gpu_id})")
        print(f"[vision_service.py][__init__] Model path: {self.model_path}")
        print(f"[vision_service.py][__init__] CLIP path: {self.clip_path}")

    def _set_gpu_visibility(self):
        """Force GPU 1 visibility for this process"""
        os.environ['CUDA_VISIBLE_DEVICES'] = str(self.gpu_id)
        if config.VISION_DEBUG:
            print(f"[vision_service.py][_set_gpu_visibility] Set CUDA_VISIBLE_DEVICES={self.gpu_id}")

    def load_model(self) -> bool:
        """
        Load llava model to GPU 1

        Returns:
            True if successful, False otherwise
        """
        if self.is_model_loaded:
            print("[vision_service.py][load_model] Model already loaded")
            return True

        if not config.VISION_ENABLED:
            print("[vision_service.py][load_model] Vision system disabled in config")
            return False

        try:
            # Set GPU visibility
            self._set_gpu_visibility()

            # Check if model files exist
            if not Path(self.model_path).exists():
                print(f"[vision_service.py][load_model] ✗ Model file not found: {self.model_path}")
                return False

            if not Path(self.clip_path).exists():
                print(f"[vision_service.py][load_model] ✗ CLIP file not found: {self.clip_path}")
                return False

            print(f"[vision_service.py][load_model] Loading llava model to GPU {self.gpu_id}...")
            start_time = time.time()

            # Import llama-cpp-python (only when needed)
            try:
                from llama_cpp import Llama
                from llama_cpp.llama_chat_format import Llava15ChatHandler
            except ImportError:
                print("[vision_service.py][load_model] ✗ llama-cpp-python not installed")
                print("[vision_service.py][load_model] Install: CMAKE_ARGS='-DGGML_CUDA=on' pip install llama-cpp-python")
                return False

            # Initialize chat handler for vision
            self.chat_handler = Llava15ChatHandler(clip_model_path=self.clip_path)

            # Load model
            self.model = Llama(
                model_path=self.model_path,
                chat_handler=self.chat_handler,
                n_gpu_layers=-1,  # Offload all layers to GPU
                n_ctx=config.VISION_CONTEXT_WINDOW,
                logits_all=True,
                verbose=config.VISION_DEBUG
            )

            self.is_model_loaded = True
            self.load_time = time.time()
            load_duration = time.time() - start_time

            print(f"[vision_service.py][load_model] ✓ Model loaded successfully ({load_duration:.2f}s)")
            return True

        except Exception as e:
            print(f"[vision_service.py][load_model] ✗ Error loading model: {e}")
            self.model = None
            self.chat_handler = None
            self.is_model_loaded = False
            return False

    def unload_model(self) -> bool:
        """
        Unload model and free GPU memory

        Returns:
            True if successful, False otherwise
        """
        if not self.is_model_loaded:
            print("[vision_service.py][unload_model] Model not loaded")
            return True

        try:
            print(f"[vision_service.py][unload_model] Unloading model from GPU {self.gpu_id}...")

            # Delete model objects
            if self.model:
                del self.model
                self.model = None

            if self.chat_handler:
                del self.chat_handler
                self.chat_handler = None

            # Force garbage collection
            import gc
            gc.collect()

            # Try to free CUDA memory
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    if config.VISION_DEBUG:
                        print("[vision_service.py][unload_model] CUDA cache cleared")
            except ImportError:
                pass

            self.is_model_loaded = False
            self.load_time = None

            print("[vision_service.py][unload_model] ✓ Model unloaded successfully")
            return True

        except Exception as e:
            print(f"[vision_service.py][unload_model] ✗ Error unloading model: {e}")
            return False

    def analyze_image(
        self,
        image_base64: str,
        prompt: str = "Describe this image in detail.",
        max_tokens: Optional[int] = None
    ) -> Dict[str, any]:
        """
        Analyze an image using the vision model

        Args:
            image_base64: Base64 encoded image (with or without data URI)
            prompt: Analysis prompt
            max_tokens: Max tokens for response (default from config)

        Returns:
            Dict with:
                - success: bool
                - result: str (analysis text)
                - tokens: int (estimated)
                - inference_time: float (seconds)
                - error: str (if failed)
        """
        if not self.is_model_loaded:
            return {
                "success": False,
                "error": "Vision model not loaded. Call load_model() first.",
                "result": None
            }

        try:
            start_time = time.time()

            # Clean base64 string (remove data URI if present)
            if image_base64.startswith('data:'):
                image_base64 = image_base64.split(',', 1)[1]

            # Decode to validate
            try:
                image_bytes = base64.b64decode(image_base64)
                image_size_mb = len(image_bytes) / (1024 * 1024)

                if image_size_mb > config.VISION_MAX_IMAGE_SIZE_MB:
                    return {
                        "success": False,
                        "error": f"Image too large: {image_size_mb:.2f}MB (max: {config.VISION_MAX_IMAGE_SIZE_MB}MB)",
                        "result": None
                    }
            except Exception as e:
                return {
                    "success": False,
                    "error": f"Invalid base64 image: {e}",
                    "result": None
                }

            if config.VISION_DEBUG:
                print(f"[vision_service.py][analyze_image] Processing image ({image_size_mb:.2f}MB)")
                print(f"[vision_service.py][analyze_image] Prompt: {prompt}")

            # Create chat message with image
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
                        {"type": "text", "text": prompt}
                    ]
                }
            ]

            # Generate response
            max_tokens = max_tokens or config.VISION_MAX_TOKENS
            response = self.model.create_chat_completion(
                messages=messages,
                max_tokens=max_tokens,
                temperature=0.7
            )

            # Extract result
            result_text = response['choices'][0]['message']['content']
            tokens_used = response.get('usage', {}).get('total_tokens', 0)
            inference_time = time.time() - start_time

            # Update stats
            self.request_count += 1
            self.total_inference_time += inference_time

            print(f"[vision_service.py][analyze_image] ✓ Analysis complete ({inference_time:.2f}s, {tokens_used} tokens)")

            return {
                "success": True,
                "result": result_text,
                "tokens": tokens_used,
                "inference_time": inference_time,
                "error": None
            }

        except Exception as e:
            error_msg = f"Vision analysis error: {e}"
            print(f"[vision_service.py][analyze_image] ✗ {error_msg}")
            return {
                "success": False,
                "error": error_msg,
                "result": None
            }

    def get_status(self) -> Dict[str, any]:
        """
        Get current vision service status

        Returns:
            Status dict with model state, stats, etc.
        """
        uptime = None
        if self.load_time:
            uptime = time.time() - self.load_time

        avg_inference_time = None
        if self.request_count > 0:
            avg_inference_time = self.total_inference_time / self.request_count

        return {
            "enabled": config.VISION_ENABLED,
            "model_loaded": self.is_model_loaded,
            "gpu_id": self.gpu_id,
            "model_path": self.model_path,
            "uptime_seconds": uptime,
            "request_count": self.request_count,
            "avg_inference_time": avg_inference_time,
            "config": {
                "max_tokens": config.VISION_MAX_TOKENS,
                "context_window": config.VISION_CONTEXT_WINDOW,
                "max_image_size_mb": config.VISION_MAX_IMAGE_SIZE_MB,
                "auto_unload_minutes": config.VISION_AUTO_UNLOAD_MINUTES
            }
        }

    def is_loaded(self) -> bool:
        """Check if model is currently loaded"""
        return self.is_model_loaded


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

# Global vision service instance
_vision_service_instance = None

def get_vision_service() -> VisionService:
    """
    Get or create global vision service instance

    Returns:
        VisionService singleton
    """
    global _vision_service_instance
    if _vision_service_instance is None:
        _vision_service_instance = VisionService()
    return _vision_service_instance


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def analyze_image_simple(image_base64: str, prompt: str = "Describe this image.") -> Optional[str]:
    """
    Simple wrapper for image analysis

    Args:
        image_base64: Base64 encoded image
        prompt: Analysis prompt

    Returns:
        Analysis text or None if failed
    """
    service = get_vision_service()

    # Ensure model is loaded
    if not service.is_loaded():
        if not service.load_model():
            return None

    # Analyze
    result = service.analyze_image(image_base64, prompt)

    if result['success']:
        return result['result']
    else:
        print(f"[vision_service.py][analyze_image_simple] Error: {result['error']}")
        return None


# ============================================================================
# TESTING
# ============================================================================

if __name__ == "__main__":
    """Test vision service"""
    print("=== Vision Service Test ===\n")

    # Initialize
    service = get_vision_service()
    print(f"Status: {service.get_status()}\n")

    # Test load
    print("Loading model...")
    if service.load_model():
        print("✓ Model loaded\n")
        print(f"Status: {service.get_status()}\n")

        # Test unload
        print("Unloading model...")
        if service.unload_model():
            print("✓ Model unloaded\n")
            print(f"Status: {service.get_status()}\n")
    else:
        print("✗ Failed to load model")
