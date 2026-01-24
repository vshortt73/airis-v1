"""
PaddleOCR Service for Iris v3.

Remote service that connects to PaddleOCR server on node2.
Provides high-quality OCR with bounding boxes for spatial analysis.
"""

import sys
from pathlib import Path

# Add project root for config import
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import httpx
import base64
from typing import Dict, Any, Optional, List

try:
    from app import config
    PADDLEOCR_REMOTE_URL = getattr(config, 'PADDLEOCR_SERVER_URL', 'http://node2:5200')
except ImportError:
    PADDLEOCR_REMOTE_URL = "http://node2:5200"

PADDLEOCR_TIMEOUT = 60.0  # seconds


class PaddleOCRService:
    """Service wrapper for remote PaddleOCR server."""

    def __init__(self, remote_url: str = PADDLEOCR_REMOTE_URL):
        self.remote_url = remote_url
        self._client = None

    def _get_client(self) -> httpx.Client:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.Client(timeout=PADDLEOCR_TIMEOUT)
        return self._client

    def get_status(self) -> Dict[str, Any]:
        """Get service status."""
        try:
            client = self._get_client()
            response = client.get(f"{self.remote_url}/status")
            response.raise_for_status()
            data = response.json()
            data["mode"] = "remote"
            data["url"] = self.remote_url
            return data
        except Exception as e:
            return {
                "loaded": False,
                "error": str(e),
                "mode": "remote",
                "url": self.remote_url
            }

    def is_loaded(self) -> bool:
        """Check if OCR engine is loaded."""
        status = self.get_status()
        return status.get("loaded", False)

    def load_engine(self, use_gpu: bool = True, lang: str = "en") -> bool:
        """Load OCR engine on remote server."""
        try:
            client = self._get_client()
            response = client.post(
                f"{self.remote_url}/load",
                params={"use_gpu": use_gpu, "lang": lang}
            )
            response.raise_for_status()
            return True
        except Exception as e:
            print(f"[PaddleOCRService] Failed to load: {e}")
            return False

    def unload_engine(self) -> None:
        """Unload OCR engine on remote server."""
        try:
            client = self._get_client()
            client.post(f"{self.remote_url}/unload")
        except Exception as e:
            print(f"[PaddleOCRService] Failed to unload: {e}")

    def run_ocr(
        self,
        image: str,
        det_only: bool = False,
        min_confidence: float = 0.5,
        lang: str = "en"
    ) -> Dict[str, Any]:
        """
        Run OCR on an image.

        Args:
            image: Base64 encoded image
            det_only: If True, only detect text regions (no recognition)
            min_confidence: Minimum confidence threshold
            lang: Language code (not used after engine load)

        Returns:
            Dict with:
            - success: bool
            - detections: List of detected text with bounding boxes
            - count: Number of detections
            - image_size: {width, height}
            - inference_time: Processing time in seconds
        """
        try:
            client = self._get_client()

            payload = {
                "image": image,
                "det_only": det_only,
                "min_confidence": min_confidence,
                "lang": lang
            }

            response = client.post(
                f"{self.remote_url}/ocr",
                json=payload
            )
            response.raise_for_status()
            return response.json()

        except httpx.HTTPStatusError as e:
            return {
                "success": False,
                "error": f"HTTP {e.response.status_code}: {e.response.text}"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def run_detection(
        self,
        image: str,
        min_confidence: float = 0.5
    ) -> Dict[str, Any]:
        """
        Run text detection only (no recognition).

        Faster than full OCR, useful for finding text regions.
        """
        return self.run_ocr(
            image=image,
            det_only=True,
            min_confidence=min_confidence
        )

    def run_batch_ocr(
        self,
        images: List[str],
        min_confidence: float = 0.5
    ) -> Dict[str, Any]:
        """
        Run OCR on multiple images.

        Args:
            images: List of base64 encoded images
            min_confidence: Minimum confidence threshold

        Returns:
            Dict with results for each image.
        """
        try:
            client = self._get_client()

            payload = {
                "images": images,
                "min_confidence": min_confidence
            }

            response = client.post(
                f"{self.remote_url}/ocr/batch",
                json=payload
            )
            response.raise_for_status()
            return response.json()

        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def extract_text_only(
        self,
        image: str,
        min_confidence: float = 0.5,
        sort_by: str = "position"
    ) -> str:
        """
        Extract just the text from an image as a string.

        Args:
            image: Base64 encoded image
            min_confidence: Minimum confidence threshold
            sort_by: How to sort results - "position" (top-to-bottom, left-to-right)
                     or "confidence" (highest first)

        Returns:
            Extracted text as a single string with newlines.
        """
        result = self.run_ocr(image=image, min_confidence=min_confidence)

        if not result.get("success"):
            return ""

        detections = result.get("detections", [])

        if sort_by == "confidence":
            detections = sorted(detections, key=lambda d: d.get("confidence", 0), reverse=True)
        # Default is already sorted by position in the server

        texts = [d.get("text", "") for d in detections if d.get("text")]
        return "\n".join(texts)

    def get_spatial_text_map(
        self,
        image: str,
        min_confidence: float = 0.5
    ) -> Dict[str, Any]:
        """
        Get text with spatial information for mapping/layout analysis.

        Returns text organized by approximate rows with position data.
        Useful for deck plans, floor maps, etc.
        """
        result = self.run_ocr(image=image, min_confidence=min_confidence)

        if not result.get("success"):
            return result

        detections = result.get("detections", [])
        image_size = result.get("image_size", {})

        # Group by approximate rows (similar Y positions)
        row_threshold = image_size.get("height", 1000) * 0.03  # 3% of image height

        rows = []
        current_row = []
        current_y = None

        for det in detections:
            center_y = det.get("center", [0, 0])[1]

            if current_y is None or abs(center_y - current_y) < row_threshold:
                current_row.append(det)
                if current_y is None:
                    current_y = center_y
            else:
                if current_row:
                    # Sort row by X position
                    current_row.sort(key=lambda d: d.get("center", [0, 0])[0])
                    rows.append(current_row)
                current_row = [det]
                current_y = center_y

        if current_row:
            current_row.sort(key=lambda d: d.get("center", [0, 0])[0])
            rows.append(current_row)

        return {
            "success": True,
            "rows": rows,
            "row_count": len(rows),
            "total_detections": len(detections),
            "image_size": image_size,
            "inference_time": result.get("inference_time")
        }


# Singleton instance
_paddleocr_service: Optional[PaddleOCRService] = None


def get_paddleocr_service() -> PaddleOCRService:
    """Get the singleton PaddleOCR service instance."""
    global _paddleocr_service
    if _paddleocr_service is None:
        _paddleocr_service = PaddleOCRService()
    return _paddleocr_service
