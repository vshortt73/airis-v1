"""
Vision Service for Iris v3
Manages vision model (llava) via separate Ollama instance on GPU 1

Dual Ollama Architecture:
- Main Ollama (GPU 0, port 11434): qwen3:32b for text/tool calling
- Vision Ollama (GPU 1, port 11435): llava:7b for image analysis

This ensures the 32B model has full access to the 5090's 32GB VRAM.
"""

import os
import sys
import base64
from typing import Optional, Dict
from pathlib import Path
import time
import httpx

# Path setup
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app import config


class VisionService:
    """
    Manages llava vision model via separate Ollama instance on GPU 1

    Architecture:
    - Main Ollama (GPU 0, port 11434): qwen3:32b for text/tool calling
    - Vision Ollama (GPU 1, port 11435): llava:7b for image analysis
    - GPU isolation ensures 32B model has full 5090 VRAM

    Responsibilities:
    - Process vision requests (image + prompt -> text description)
    - Connect to dedicated vision Ollama instance
    - Handle errors and fallbacks
    """

    def __init__(self):
        self.ollama_url = config.VISION_OLLAMA_URL  # Separate Ollama instance on GPU 1
        self.model_name = config.VISION_MODEL  # From config
        self.is_model_loaded = False
        self.load_time = None
        self.request_count = 0
        self.total_inference_time = 0

        print(f"[vision_service.py][__init__] Vision service initialized")
        print(f"[vision_service.py][__init__] Using Ollama model: {self.model_name}")
        print(f"[vision_service.py][__init__] Vision Ollama URL: {self.ollama_url} (GPU 1)")

    def load_model(self) -> bool:
        """
        Ensure vision model is available in Ollama

        Returns:
            True if successful, False otherwise
        """
        if not config.VISION_ENABLED:
            print("[vision_service.py][load_model] Vision system disabled in config")
            return False

        try:
            print(f"[vision_service.py][load_model] Checking if {self.model_name} is available...")

            # Check if model exists in Ollama
            response = httpx.get(f"{self.ollama_url}/api/tags", timeout=10.0)
            response.raise_for_status()

            models = response.json().get('models', [])
            model_names = [m['name'] for m in models]

            if self.model_name not in model_names and not any(self.model_name in name for name in model_names):
                print(f"[vision_service.py][load_model] ✗ Model {self.model_name} not found in Ollama")
                print(f"[vision_service.py][load_model] Available models: {model_names}")
                print(f"[vision_service.py][load_model] Run: ollama pull {self.model_name}")
                return False

            self.is_model_loaded = True
            self.load_time = time.time()
            print(f"[vision_service.py][load_model] ✓ Model {self.model_name} available")
            return True

        except Exception as e:
            print(f"[vision_service.py][load_model] ✗ Error checking model: {e}")
            return False

    def unload_model(self) -> bool:
        """
        Unload model (Ollama manages this automatically)

        Returns:
            True
        """
        self.is_model_loaded = False
        self.load_time = None
        print("[vision_service.py][unload_model] ✓ Model marked as unloaded")
        return True

    def analyze_image(
        self,
        image_base64: str,
        prompt: str = "Describe this image in detail.",
        max_tokens: Optional[int] = None
    ) -> Dict[str, any]:
        """
        Analyze an image using Ollama's vision model

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
        try:
            start_time = time.time()

            # Clean base64 string (remove data URI if present)
            if image_base64.startswith('data:'):
                image_base64 = image_base64.split(',', 1)[1]

            # Validate image
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

            # Call Ollama API
            payload = {
                "model": self.model_name,
                "prompt": prompt,
                "images": [image_base64],
                "stream": False,
                "options": {
                    "num_predict": max_tokens or config.VISION_MAX_TOKENS,
                    "temperature": 0.7
                }
            }

            response = httpx.post(
                f"{self.ollama_url}/api/generate",
                json=payload,
                timeout=config.VISION_TIMEOUT_SECONDS
            )
            response.raise_for_status()

            result_data = response.json()
            result_text = result_data.get('response', '')
            inference_time = time.time() - start_time

            # Update stats
            self.request_count += 1
            self.total_inference_time += inference_time

            # Estimate tokens (Ollama doesn't always return exact count)
            tokens_used = len(result_text.split())  # Rough estimate

            print(f"[vision_service.py][analyze_image] ✓ Analysis complete ({inference_time:.2f}s, ~{tokens_used} tokens)")

            return {
                "success": True,
                "result": result_text,
                "tokens": tokens_used,
                "inference_time": inference_time,
                "error": None
            }

        except httpx.TimeoutException:
            error_msg = f"Vision analysis timed out after {config.VISION_TIMEOUT_SECONDS}s"
            print(f"[vision_service.py][analyze_image] ✗ {error_msg}")
            return {
                "success": False,
                "error": error_msg,
                "result": None
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
            "model_name": self.model_name,
            "ollama_url": self.ollama_url,
            "uptime_seconds": uptime,
            "request_count": self.request_count,
            "avg_inference_time": avg_inference_time,
            "config": {
                "max_tokens": config.VISION_MAX_TOKENS,
                "max_image_size_mb": config.VISION_MAX_IMAGE_SIZE_MB,
                "timeout_seconds": config.VISION_TIMEOUT_SECONDS,
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
    print("Checking model availability...")
    if service.load_model():
        print("✓ Model available\n")
        print(f"Status: {service.get_status()}\n")
    else:
        print("✗ Model not available")
        print("Run: ollama pull llava:13b")
