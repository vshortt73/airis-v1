"""
Iris Creative Server - MCP Server for Image Generation
Provides unified image generation via ComfyUI on node2
"""

import sys
import os
import json
import base64
import asyncio
import random
from pathlib import Path
from typing import Dict, Any, Optional

import aiohttp

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from mcp_servers.base.base_server import IrisMCPServer

# ============================================================================
# CONFIGURATION
# ============================================================================

COMFYUI_URL = "http://node2:8189"
COMFYUI_OUTPUT_DIR = "/home/captain/node2-mount/programs/ComfyUI/output"
WORKFLOW_DIR = Path(__file__).parent / "workflows"

# Style configurations
STYLE_CONFIGS = {
    "general": {
        "workflow": "non-iris",
        "width": 1080,
        "height": 1080,
        "steps": 23,
        "cfg": 8,
        "max_wait": 180.0,
        "negative_prompt": "blurry, bad quality, distorted, ugly"
    },
    "self": {
        "workflow": "iris",
        "width": 768,
        "height": 1080,
        "steps": 25,
        "cfg": 8,
        "max_wait": 300.0,  # Longer for FaceID processing
        "negative_prompt": "text, watermark, blurry, poor composure, bad lighting, poor composition, unprofessional, washed out, no color"
    }
}

# ============================================================================
# COMFYUI CLIENT
# ============================================================================

class ComfyUIClient:
    """Client for interacting with ComfyUI API"""

    def __init__(self, base_url: str = COMFYUI_URL):
        self.base_url = base_url
        self.timeout = aiohttp.ClientTimeout(total=300)

    async def queue_prompt(self, workflow: Dict) -> Optional[str]:
        """Queue a workflow for execution"""
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(
                    f"{self.base_url}/prompt",
                    json={"prompt": workflow}
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("prompt_id")
                    else:
                        error = await resp.text()
                        print(f"[creative] ComfyUI error: {error}")
                        return None
        except Exception as e:
            print(f"[creative] Failed to queue prompt: {e}")
            return None

    async def get_history(self, prompt_id: str) -> Optional[Dict]:
        """Get execution history for a prompt"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.base_url}/history/{prompt_id}") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get(prompt_id)
                    return None
        except Exception as e:
            print(f"[creative] Failed to get history: {e}")
            return None

    async def wait_for_completion(
        self,
        prompt_id: str,
        poll_interval: float = 1.0,
        max_wait: float = 180.0
    ) -> Optional[Dict]:
        """Poll history until generation completes"""
        elapsed = 0.0
        while elapsed < max_wait:
            history = await self.get_history(prompt_id)
            if history:
                status = history.get("status", {})
                if status.get("status_str") == "success":
                    return history
                elif status.get("status_str") == "error":
                    print(f"[creative] Generation failed: {status.get('messages', [])}")
                    return None

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            if int(elapsed) % 10 == 0 and elapsed > 0:
                print(f"[creative] Still generating... ({int(elapsed)}s)")

        print(f"[creative] Generation timed out after {max_wait}s")
        return None


# ============================================================================
# WORKFLOW HELPERS
# ============================================================================

def load_workflow(name: str) -> Optional[Dict]:
    """Load a workflow template from the workflows directory"""
    workflow_path = WORKFLOW_DIR / f"{name}.json"
    if not workflow_path.exists():
        print(f"[creative] Workflow not found: {workflow_path}")
        return None
    try:
        with open(workflow_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"[creative] Failed to load workflow: {e}")
        return None


def inject_prompt(
    workflow: Dict,
    prompt: str,
    negative_prompt: str,
    width: int,
    height: int,
    seed: int,
    steps: int,
    cfg: float
) -> Dict:
    """Inject generation parameters into workflow"""
    workflow = json.loads(json.dumps(workflow))  # Deep copy

    if "6" in workflow:
        workflow["6"]["inputs"]["text"] = prompt
    if "7" in workflow:
        workflow["7"]["inputs"]["text"] = negative_prompt
    if "5" in workflow:
        workflow["5"]["inputs"]["width"] = width
        workflow["5"]["inputs"]["height"] = height
    if "3" in workflow:
        workflow["3"]["inputs"]["seed"] = seed
        workflow["3"]["inputs"]["steps"] = steps
        workflow["3"]["inputs"]["cfg"] = cfg

    print(f"[creative] Injected: '{prompt[:50]}...', {width}x{height}, seed={seed}")
    return workflow


def extract_output_filename(history: Dict) -> Optional[str]:
    """Extract the output image filename from completion history"""
    try:
        outputs = history.get("outputs", {})
        for node_id, node_output in outputs.items():
            images = node_output.get("images", [])
            if images:
                return images[0].get("filename")
        return None
    except Exception as e:
        print(f"[creative] Failed to extract filename: {e}")
        return None


# ============================================================================
# SERVER INITIALIZATION
# ============================================================================

server = IrisMCPServer(
    name="Iris Creative Server",
    description="Unified image generation via ComfyUI"
)

comfyui = ComfyUIClient()


# ============================================================================
# UNIFIED IMAGE TOOL
# ============================================================================

@server.register_tool
async def image(
    action: str,
    prompt: str,
    negative_prompt: Optional[str] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    seed: Optional[int] = None,
    steps: Optional[int] = None,
    cfg: Optional[float] = None
) -> Dict[str, Any]:
    """
    Unified image generation tool.

    Actions:
        - "generate": Create a general image (any subject)
        - "self": Generate an image of yourself (Iris) using face preservation

    Args:
        action: "generate" for general images, "self" for self-portraits
        prompt: Detailed description of the image. For "generate": describe subject,
                style, lighting, composition. For "self": describe scene, pose,
                clothing, mood (face is handled automatically).
        negative_prompt: Things to avoid (optional, has smart defaults)
        width: Image width in pixels (optional, defaults vary by action)
        height: Image height in pixels (optional, defaults vary by action)
        seed: Random seed for reproducibility (optional)
        steps: Diffusion steps (optional, defaults vary by action)
        cfg: CFG scale 1-20 (optional, default: 8)

    Returns:
        dict with success, image_base64, filename, seed, dimensions

    Examples:
        image(action="generate", prompt="A serene mountain at sunset, photorealistic")
        image(action="self", prompt="Sitting at a cozy coffee shop, warm lighting")
    """
    # Map action to style config
    action = action.lower().strip()
    if action in ("generate", "general"):
        style = "general"
    elif action in ("self", "iris", "selfie", "me"):
        style = "self"
    else:
        return {
            "success": False,
            "error": f"Unknown action: {action}",
            "valid_actions": ["generate", "self"]
        }

    config = STYLE_CONFIGS[style]
    print(f"[creative][image] Action: {action} (style: {style})")
    print(f"[creative][image] Prompt: {prompt[:100]}...")

    # Request GPU
    try:
        from core.gpu_manager import request_gpu
        print(f"[creative][image] Requesting GPU for ComfyUI...")
        success, error = await request_gpu("comfyui")
        if not success:
            return {"success": False, "error": f"GPU unavailable: {error}"}
        print(f"[creative][image] GPU acquired")
    except ImportError as e:
        print(f"[creative][image] Warning: GPU manager not available: {e}")

    # Load workflow
    workflow = load_workflow(config["workflow"])
    if not workflow:
        return {"success": False, "error": f"Workflow '{config['workflow']}' not found"}

    # Apply defaults from style config, override with provided values
    final_width = width if width is not None else config["width"]
    final_height = height if height is not None else config["height"]
    final_steps = steps if steps is not None else config["steps"]
    final_cfg = cfg if cfg is not None else config["cfg"]
    final_negative = negative_prompt if negative_prompt else config["negative_prompt"]
    final_seed = seed if seed is not None else random.randint(0, 2**32 - 1)

    # Clamp dimensions
    max_dim = 1536 if style == "self" else 2048
    final_width = min(max(final_width, 512), max_dim)
    final_height = min(max(final_height, 512), max_dim)

    # Inject parameters
    workflow = inject_prompt(
        workflow,
        prompt=prompt,
        negative_prompt=final_negative,
        width=final_width,
        height=final_height,
        seed=final_seed,
        steps=final_steps,
        cfg=final_cfg
    )

    # Queue prompt
    print(f"[creative][image] Queueing to ComfyUI...")
    prompt_id = await comfyui.queue_prompt(workflow)
    if not prompt_id:
        return {"success": False, "error": "Failed to queue prompt"}

    print(f"[creative][image] Queued: {prompt_id}")

    # Wait for completion
    print(f"[creative][image] Generating{'(FaceID)' if style == 'self' else ''}...")
    history = await comfyui.wait_for_completion(prompt_id, max_wait=config["max_wait"])
    if not history:
        return {"success": False, "error": "Generation timed out or failed"}

    # Extract output
    filename = extract_output_filename(history)
    if not filename:
        return {"success": False, "error": "No output image found"}

    print(f"[creative][image] Output: {filename}")

    # Read and encode
    image_path = Path(COMFYUI_OUTPUT_DIR) / filename
    if not image_path.exists():
        return {"success": False, "error": f"Output not found at {image_path}"}

    try:
        with open(image_path, 'rb') as f:
            image_data = f.read()
        image_base64 = base64.b64encode(image_data).decode('utf-8')

        print(f"[creative][image] Success ({len(image_data)} bytes)")

        return {
            "success": True,
            "image_base64": image_base64,
            "filename": filename,
            "seed": final_seed,
            "width": final_width,
            "height": final_height,
            "style": style,
            "prompt": prompt[:200]
        }

    except Exception as e:
        return {"success": False, "error": f"Failed to read image: {e}"}


# ============================================================================
# SERVER STARTUP
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("IRIS CREATIVE SERVER (Unified)")
    print("=" * 60)
    print(f"ComfyUI URL: {COMFYUI_URL}")
    print("Tool: image(action, prompt, ...)")
    print("Actions: generate, self")
    print("Starting server...")
    print("=" * 60)
    server.run()
