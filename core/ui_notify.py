"""
Cross-module UI notification system.

Usage:
    from core.ui_notify import ui_msg
    ui_msg("Vision model loaded", "success")
    ui_msg("API rate limit approaching", "warning")
    ui_msg("Failed to connect", "error")

Styles: "info" (gray), "success" (green), "warning" (yellow), "error" (red)

This function can be called from any module (sync or async).
If no UI clients are connected, notifications are silently discarded.
"""
import httpx
import asyncio
import os
import sys
from pathlib import Path

# Setup project path for imports
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Detect SSL configuration (same logic as main.py)
SSL_DIR = PROJECT_ROOT / "ssl"
USE_SSL = (SSL_DIR / "key.pem").exists() and (SSL_DIR / "cert.pem").exists()

# Import config for port
from app import config
PROTOCOL = "https" if USE_SSL else "http"
ACTIVE_PORT = 8443 if USE_SSL else config.PORT
NOTIFY_URL = f"{PROTOCOL}://localhost:{ACTIVE_PORT}/api/ui/notify"


def ui_msg(message: str, style: str = "info") -> bool:
    """
    Send a notification to the UI.

    Args:
        message: Text to display
        style: One of "info", "success", "warning", "error"

    Returns:
        True if sent successfully, False otherwise
    """
    # Validate style
    valid_styles = {"info", "success", "warning", "error"}
    if style not in valid_styles:
        style = "info"

    # Handle both sync and async contexts
    try:
        loop = asyncio.get_running_loop()
        # We're in async context - schedule as task
        asyncio.create_task(_send_notification_async(message, style))
        return True
    except RuntimeError:
        # No running loop - use sync client
        return _send_notification_sync(message, style)


def _send_notification_sync(message: str, style: str) -> bool:
    """Send notification using synchronous HTTP client."""
    try:
        # verify=False for self-signed certs on localhost
        with httpx.Client(timeout=2.0, verify=False) as client:
            response = client.post(NOTIFY_URL, json={"message": message, "style": style})
            return response.status_code == 200
    except Exception:
        # Silently discard if no server or no clients
        return False


async def _send_notification_async(message: str, style: str) -> bool:
    """Send notification using async HTTP client."""
    try:
        # verify=False for self-signed certs on localhost
        async with httpx.AsyncClient(timeout=2.0, verify=False) as client:
            response = await client.post(NOTIFY_URL, json={"message": message, "style": style})
            return response.status_code == 200
    except Exception:
        # Silently discard if no server or no clients
        return False
