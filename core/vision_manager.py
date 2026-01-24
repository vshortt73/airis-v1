"""
Vision Manager for Iris v3
High-level coordination of vision requests via llama.cpp
"""

import os
import sys
from typing import List, Dict, Optional
import asyncio
from datetime import datetime
from pathlib import Path

# Path setup
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app import config
from inference.vision_service import get_vision_service


class VisionManager:
    """
    Manages vision request lifecycle via llama.cpp server

    Responsibilities:
    - Check server availability on first request
    - Process single/batch image analysis
    - Queue management for concurrent requests
    - Integration with conversation flow
    """

    def __init__(self):
        self.service = get_vision_service()
        self.last_used = None
        self.processing = False

        print("[vision_manager.py][__init__] Vision manager initialized")

    async def process_images(
        self,
        images: List[str],
        context: Optional[str] = None,
        custom_prompt: Optional[str] = None
    ) -> Dict[str, any]:
        """
        Process one or more images

        Args:
            images: List of base64 encoded images
            context: Conversation context for prompt generation
            custom_prompt: Override default prompt

        Returns:
            Dict with:
                - success: bool
                - results: List[str] - Analysis for each image
                - total_tokens: int
                - total_time: float
                - error: Optional[str]
        """
        if not config.VISION_ENABLED:
            return {
                "success": False,
                "error": "Vision system disabled in configuration",
                "results": []
            }

        if not images:
            return {
                "success": False,
                "error": "No images provided",
                "results": []
            }

        if len(images) > config.VISION_MAX_IMAGES_PER_REQUEST:
            return {
                "success": False,
                "error": f"Too many images ({len(images)}). Max: {config.VISION_MAX_IMAGES_PER_REQUEST}",
                "results": []
            }

        # Wait if already processing
        while self.processing:
            await asyncio.sleep(0.1)

        self.processing = True

        try:
            # Check if llama.cpp server is available
            if not self.service.is_loaded():
                print("[vision_manager.py][process_images] Checking llama.cpp vision server...")
                success = await asyncio.to_thread(self.service.load_model)
                if not success:
                    return {
                        "success": False,
                        "error": "Vision server not available. Is llama.cpp running on port 11435?",
                        "results": []
                    }
                print("[vision_manager.py][process_images] ✓ Vision server ready")

            # Update last used time
            self.last_used = datetime.now()

            # Process each image
            results = []
            total_tokens = 0
            total_time = 0

            for i, image in enumerate(images):
                # Generate prompt
                if custom_prompt:
                    prompt = custom_prompt
                elif len(images) > 1:
                    prompt = f"Describe image {i + 1}. "
                    if context:
                        prompt += f"Context: {context}"
                    else:
                        prompt += "Focus on key objects, people, actions, and notable features."
                else:
                    if context:
                        prompt = f"Describe this image to help answer: {context}"
                    else:
                        prompt = "Describe this image in detail. Focus on key objects, people, actions, text, colors, and any notable features."

                # Analyze image
                print(f"[vision_manager.py][process_images] Analyzing image {i + 1}/{len(images)}...")
                result = await asyncio.to_thread(
                    self.service.analyze_image,
                    image,
                    prompt
                )

                if result['success']:
                    results.append(result['result'])
                    total_tokens += result.get('tokens', 0)
                    total_time += result.get('inference_time', 0)
                    print(f"[vision_manager.py][process_images] ✓ Image {i + 1} analyzed ({result.get('tokens', 0)} tokens)")
                else:
                    error_msg = result.get('error', 'Unknown error')
                    print(f"[vision_manager.py][process_images] ✗ Image {i + 1} failed: {error_msg}")
                    results.append(f"[Error analyzing image {i + 1}: {error_msg}]")

            print(f"[vision_manager.py][process_images] ✓ Processed {len(images)} image(s) - {total_tokens} tokens, {total_time:.2f}s")

            return {
                "success": True,
                "results": results,
                "total_tokens": total_tokens,
                "total_time": total_time,
                "error": None
            }

        except Exception as e:
            error_msg = f"Vision processing error: {e}"
            print(f"[vision_manager.py][process_images] ✗ {error_msg}")
            return {
                "success": False,
                "error": error_msg,
                "results": []
            }

        finally:
            self.processing = False

    async def force_unload(self) -> bool:
        """
        Reset vision service state

        Returns:
            True if successful
        """
        # Wait for any active processing
        while self.processing:
            await asyncio.sleep(0.1)

        print("[vision_manager.py][force_unload] Resetting vision service state...")
        success = await asyncio.to_thread(self.service.unload_model)

        if success:
            self.last_used = None
            print("[vision_manager.py][force_unload] ✓ State reset")
        else:
            print("[vision_manager.py][force_unload] ✗ Reset failed")

        return success

    def get_status(self) -> Dict[str, any]:
        """
        Get vision system status

        Returns:
            Status dict with service info and manager state
        """
        service_status = self.service.get_status()

        idle_time = None
        if self.last_used:
            idle_time = (datetime.now() - self.last_used).total_seconds()

        return {
            **service_status,
            "manager": {
                "processing": self.processing,
                "last_used": self.last_used.isoformat() if self.last_used else None,
                "idle_seconds": idle_time
            }
        }


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_vision_manager_instance = None

def get_vision_manager() -> VisionManager:
    """
    Get or create global vision manager instance

    Returns:
        VisionManager singleton
    """
    global _vision_manager_instance
    if _vision_manager_instance is None:
        _vision_manager_instance = VisionManager()
    return _vision_manager_instance


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

async def analyze_images_for_conversation(
    images: List[str],
    user_message: Optional[str] = None
) -> Optional[str]:
    """
    Analyze images in conversation context

    Args:
        images: List of base64 encoded images
        user_message: User's message for context

    Returns:
        Formatted analysis text or None if failed
    """
    # Request GPU for vision service
    from core.gpu_manager import request_gpu, get_gpu_manager

    success, error = await request_gpu("vision")
    if not success:
        print(f"[vision_manager.py][analyze_images_for_conversation] GPU unavailable: {error}")
        return f"Vision unavailable: {error}"

    # Mark GPU as busy during processing
    gpu = get_gpu_manager()
    gpu.mark_busy()

    try:
        manager = get_vision_manager()

        result = await manager.process_images(
            images=images,
            context=user_message
        )

        if result['success']:
            analyses = result['results']

            # Format output
            if len(analyses) == 1:
                return analyses[0]
            else:
                formatted = []
                for i, analysis in enumerate(analyses):
                    formatted.append(f"Image {i + 1}: {analysis}")
                return "\n\n".join(formatted)
        else:
            print(f"[vision_manager.py][analyze_images_for_conversation] Error: {result.get('error')}")
            return None
    finally:
        gpu.mark_idle()


# ============================================================================
# TESTING
# ============================================================================

if __name__ == "__main__":
    """Test vision manager"""
    import asyncio

    async def test():
        print("=== Vision Manager Test ===\n")

        manager = get_vision_manager()

        # Status
        print("Initial status:")
        print(manager.get_status())
        print()

        # Test force unload (should do nothing if not loaded)
        print("Testing force unload...")
        await manager.force_unload()
        print()

        print("Test complete")

    asyncio.run(test())
