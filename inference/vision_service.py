"""
Vision Service for Iris v3
Manages vision model via llama.cpp server on GPU 1

Architecture:
- Main Ollama (GPU 0, port 11434): qwen3:32b for text/tool calling
- llama.cpp (GPU 1, port 11435): llava-phi-3 for image analysis

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
    Manages vision model via llama.cpp server on GPU 1

    Architecture:
    - Main Ollama (GPU 0, port 11434): qwen3:32b for text/tool calling
    - llama.cpp (GPU 1, port 11435): llava-phi-3 for image analysis
    - GPU isolation ensures 32B model has full 5090 VRAM

    Responsibilities:
    - Process vision requests (image + prompt -> text description)
    - Connect to llama.cpp server using OpenAI-compatible API
    - Handle errors and fallbacks
    """

    def __init__(self):
        self.server_url = config.VISION_OLLAMA_URL  # llama.cpp server on GPU 1
        self.is_model_loaded = False
        self.load_time = None
        self.request_count = 0
        self.total_inference_time = 0

        print(f"[vision_service.py][__init__] Vision service initialized")
        print(f"[vision_service.py][__init__] Using llama.cpp server: {self.server_url} (GPU 1)")

    def load_model(self) -> bool:
        """
        Check if llama.cpp vision server is available

        Returns:
            True if successful, False otherwise
        """
        if not config.VISION_ENABLED:
            print("[vision_service.py][load_model] Vision system disabled in config")
            return False

        try:
            print(f"[vision_service.py][load_model] Checking llama.cpp server health...")

            # Check server health
            response = httpx.get(f"{self.server_url}/health", timeout=10.0)

            if response.status_code == 200:
                data = response.json()
                model_name = data.get('model', 'unknown')
                self.is_model_loaded = True
                self.load_time = time.time()
                print(f"[vision_service.py][load_model] ✓ llama.cpp server ready (model: {model_name})")
                return True
            else:
                print(f"[vision_service.py][load_model] ✗ Server returned status {response.status_code}")
                return False

        except Exception as e:
            print(f"[vision_service.py][load_model] ✗ Error connecting to llama.cpp: {e}")
            return False

    def unload_model(self) -> bool:
        """
        Mark model as unloaded (llama.cpp manages actual model lifecycle)

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
        Analyze an image using llama.cpp's OpenAI-compatible vision API

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

            # Ensure we have the data URI format for OpenAI API
            if image_base64.startswith('data:'):
                image_data_url = image_base64
                # Also get raw base64 for size check
                raw_base64 = image_base64.split(',', 1)[1]
            else:
                # Assume JPEG if no prefix (most common)
                image_data_url = f"data:image/jpeg;base64,{image_base64}"
                raw_base64 = image_base64

            # Validate image size
            try:
                image_bytes = base64.b64decode(raw_base64)
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

            # Build OpenAI-compatible vision request
            payload = {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": image_data_url}
                            }
                        ]
                    }
                ],
                "max_tokens": max_tokens or config.VISION_MAX_TOKENS,
                "temperature": 0.7,
                "stream": False
            }

            response = httpx.post(
                f"{self.server_url}/v1/chat/completions",
                json=payload,
                timeout=config.VISION_TIMEOUT_SECONDS
            )
            response.raise_for_status()

            result_data = response.json()

            # Parse OpenAI-format response
            result_text = ""
            if "choices" in result_data and len(result_data["choices"]) > 0:
                result_text = result_data["choices"][0].get("message", {}).get("content", "")

            inference_time = time.time() - start_time

            # Update stats
            self.request_count += 1
            self.total_inference_time += inference_time

            # Get token count from response if available, otherwise estimate
            tokens_used = result_data.get("usage", {}).get("completion_tokens", len(result_text.split()))

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
        except httpx.HTTPStatusError as e:
            # Try to get error details from response
            error_detail = str(e)
            try:
                error_json = e.response.json()
                if "error" in error_json:
                    error_detail = error_json["error"].get("message", str(e))
            except:
                pass
            error_msg = f"Vision API error: {error_detail}"
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
            "server_url": self.server_url,
            "server_type": "llama.cpp",
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

    # Ensure server is available
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

    # Test connection
    print("Checking llama.cpp server...")
    if service.load_model():
        print("✓ Server available\n")
        print(f"Status: {service.get_status()}\n")
    else:
        print("✗ Server not available")
        print("Make sure llama.cpp is running on port 11435 with a vision model")
