# Vision System Setup Guide

## Overview

Iris v3 uses a **dual-model architecture** for optimal performance:
- **Main Model** (qwen3:32b): Text generation, tool calling, reasoning → GPU 0 (RTX 5090)
- **Vision Model** (llava): Image analysis on demand → GPU 1 (RTX 4080 Super)

This guide walks through setting up the vision system.

## Prerequisites

### Hardware
- **GPU 0**: RTX 5090 (32GB) - Running Ollama with qwen3:32b
- **GPU 1**: RTX 4080 Super (16GB) - Will run llava vision model

### Software
- CUDA Toolkit (11.8 or higher)
- Python 3.11+
- Ollama (already configured on GPU 0)
- CMake (for building llama.cpp with CUDA)

## Installation Steps

### 1. Set Database Password (Required)

Iris requires a PostgreSQL database password to be set as an environment variable:

```bash
# Set permanently in your shell profile (~/.bashrc or ~/.zshrc)
export IRIS_DB_PASSWORD='your_actual_password_here'

# Or set for current session only
export IRIS_DB_PASSWORD='your_actual_password_here'
```

**Verify database connection:**
```bash
python3 tests/test_database.py
```

### 2. Install llama-cpp-python with CUDA Support

The vision system requires `llama-cpp-python` compiled with CUDA support for GPU acceleration.

```bash
# Install with CUDA support (GPU acceleration)
CMAKE_ARGS="-DGGML_CUDA=on" pip install llama-cpp-python
```

**Verify installation:**
```python
python3 -c "from llama_cpp import Llama; print('✓ llama-cpp-python installed successfully')"
```

### 3. Download Vision Model Files

You need two files for the llava vision model:
1. **Main model** (llava-v1.6-mistral-7b quantized)
2. **Vision encoder** (CLIP model projector)

```bash
# Create models directory
mkdir -p /models/vision

# Download llava-v1.6-mistral-7b (Q4_K_M quantization - ~4.5GB)
cd /models/vision
wget https://huggingface.co/cjpais/llava-v1.6-mistral-7b-gguf/resolve/main/llava-v1.6-mistral-7b.Q4_K_M.gguf

# Download vision encoder (mmproj - ~600MB)
wget https://huggingface.co/cjpais/llava-v1.6-mistral-7b-gguf/resolve/main/mmproj-model-f16.gguf
```

**Alternative models** (if you want different quality/size trade-offs):
- **Higher quality**: `llava-v1.6-mistral-7b.Q5_K_M.gguf` (~5.5GB, better quality)
- **Smaller size**: `llava-v1.6-mistral-7b.Q4_0.gguf` (~3.8GB, faster but lower quality)
- **Larger model**: `llava-v1.6-34b.Q4_K_M.gguf` (~19GB, best quality but slower)

### 4. Configure Iris

Edit `app/config.py` to set your model paths:

```python
# Vision System Configuration
VISION_ENABLED = True
VISION_MODEL_PATH = "/models/vision/llava-v1.6-mistral-7b.Q4_K_M.gguf"
VISION_CLIP_PATH = "/models/vision/mmproj-model-f16.gguf"
VISION_GPU_ID = 1  # RTX 4080 Super
```

**Optional tuning parameters:**
```python
VISION_AUTO_UNLOAD_MINUTES = 5  # Unload after idle (free GPU for ComfyUI)
VISION_MAX_TOKENS = 1000  # Max response length per image
VISION_CONTEXT_WINDOW = 2048  # Vision model context
VISION_DEBUG = False  # Set to True for verbose logging
```

### 5. Verify GPU Setup

Check that CUDA can see both GPUs:

```bash
# Check CUDA devices
python3 -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}'); print(f'GPU count: {torch.cuda.device_count()}'); [print(f'GPU {i}: {torch.cuda.get_device_name(i)}') for i in range(torch.cuda.device_count())]"
```

Expected output:
```
CUDA available: True
GPU count: 2
GPU 0: NVIDIA GeForce RTX 5090
GPU 1: NVIDIA GeForce RTX 4080 SUPER
```

### 6. Test Vision Service

Test the vision service independently before using in chat:

```bash
# Test model loading/unloading
python3 ollama/vision_service.py
```

Expected output:
```
=== Vision Service Test ===

Status: {'enabled': True, 'model_loaded': False, ...}

Loading model...
✓ Model loaded

Status: {'enabled': True, 'model_loaded': True, ...}

Unloading model...
✓ Model unloaded
```

### 7. Test Vision Manager

Test the high-level vision manager:

```bash
python3 core/vision_manager.py
```

### 8. Start Iris and Test Integration

```bash
# Start Iris
export IRIS_DB_PASSWORD='your_password'
./scripts/start.sh
```

**Test via API:**
```bash
# Check vision status
curl http://localhost:8000/api/vision/status | jq

# Test image analysis (replace with your base64 image)
curl -X POST http://localhost:8000/api/vision/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "image": "iVBORw0KGgoAAAANSU...",
    "prompt": "Describe this image"
  }' | jq
```

**Test in chat:**
1. Open http://localhost:8000
2. Upload an image
3. Send a message
4. Iris will automatically analyze the image using the vision model

## Usage

### In Chat

When you send images to Iris:
1. Images are saved to disk
2. Vision model loads (if not already loaded) - takes ~3-5 seconds first time
3. Each image is analyzed with context from your message
4. Vision analysis is added to conversation
5. Main model (qwen3:32b) sees the analysis and responds
6. Vision model unloads after 5 minutes of inactivity

### Via API

**Analyze single image:**
```bash
curl -X POST http://localhost:8000/api/vision/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "image": "<base64_encoded_image>",
    "prompt": "What objects are in this image?"
  }'
```

**Analyze multiple images:**
```bash
curl -X POST http://localhost:8000/api/vision/batch \
  -H "Content-Type: application/json" \
  -d '{
    "images": ["<base64_image_1>", "<base64_image_2>"],
    "context": "Compare these two images"
  }'
```

**Force unload model** (to free GPU for ComfyUI):
```bash
curl -X POST http://localhost:8000/api/vision/unload
```

**Check status:**
```bash
curl http://localhost:8000/api/vision/status
```

## GPU Memory Management

### Memory Usage Estimates
- **llava-7b Q4_K_M**: ~4-6 GB VRAM
- **XTTS audio**: ~2 GB VRAM (always loaded)
- **ComfyUI**: ~8-12 GB VRAM (when active)

### Sharing GPU 1

The vision model automatically unloads after 5 minutes of inactivity, freeing memory for:
- ComfyUI image generation
- Other CUDA tasks

**Manual control:**
```python
from core.vision_manager import get_vision_manager

manager = get_vision_manager()

# Force unload (async)
await manager.force_unload()

# Check status
status = manager.get_status()
print(f"Model loaded: {status['model_loaded']}")
print(f"Idle time: {status['manager']['idle_seconds']}s")
```

## Troubleshooting

### "Model file not found"

Check paths in `app/config.py` match where you downloaded the models:
```bash
ls -lh /models/vision/
```

### "llama-cpp-python not installed"

Reinstall with CUDA support:
```bash
pip uninstall llama-cpp-python
CMAKE_ARGS="-DGGML_CUDA=on" pip install llama-cpp-python --no-cache-dir
```

### "CUDA out of memory"

GPU 1 is full. Options:
1. Unload vision model: `curl -X POST http://localhost:8000/api/vision/unload`
2. Close ComfyUI or other GPU tasks
3. Use smaller vision model (Q4_0 instead of Q4_K_M)
4. Reduce `VISION_CONTEXT_WINDOW` in config

### Vision model on wrong GPU

The service forces GPU 1 using `CUDA_VISIBLE_DEVICES=1`. If you need different GPU:
1. Edit `VISION_GPU_ID` in `app/config.py`
2. Restart Iris

### Slow performance

**First request**: 3-5 seconds (model loading) - this is normal
**Subsequent requests**: 0.5-1.5 seconds

If all requests are slow:
- Check GPU is being used: `nvidia-smi` should show llava process on GPU 1
- Verify CUDA support: Model should say "CUDA" in logs
- Try smaller model or reduce context window

### Model won't unload

Check if requests are still being processed:
```bash
curl http://localhost:8000/api/vision/status | jq '.manager.processing'
```

Force kill if needed (not recommended):
```bash
# This will restart Iris
sudo systemctl restart iris  # Or however you run Iris
```

## Performance Tuning

### Quality vs Speed

**For better quality** (slower, more VRAM):
- Use Q5_K_M or Q6_K quantization
- Increase `VISION_MAX_TOKENS` to 1500-2000
- Increase `VISION_CONTEXT_WINDOW` to 4096

**For faster inference** (lower quality):
- Use Q4_0 quantization
- Decrease `VISION_MAX_TOKENS` to 500
- Decrease `VISION_CONTEXT_WINDOW` to 1024

### Auto-Unload Timing

Adjust based on usage patterns:
```python
# Unload quickly (more for ComfyUI)
VISION_AUTO_UNLOAD_MINUTES = 2

# Keep loaded longer (less loading overhead)
VISION_AUTO_UNLOAD_MINUTES = 10
```

### Batch Processing

When analyzing multiple images, use the batch endpoint for better efficiency:
```python
# Efficient (one model load)
await manager.process_images(images=[img1, img2, img3])

# Inefficient (loads model 3 times if unloaded)
await manager.process_images(images=[img1])
await manager.process_images(images=[img2])
await manager.process_images(images=[img3])
```

## Advanced Configuration

### Custom Prompts

Tailor prompts for specific use cases:

```python
# OCR focus
prompt = "Extract all visible text from this image verbatim."

# Object detection
prompt = "List all objects in this image with their approximate positions."

# Detailed scene description
prompt = "Describe this scene in detail, including the setting, lighting, mood, and any notable artistic elements."
```

### Integration with Other Services

**Use vision analysis in tools:**
```python
# In your MCP tool
from core.vision_manager import get_vision_manager

async def my_tool(image_url: str):
    # Download image
    image_base64 = download_and_encode(image_url)

    # Analyze
    manager = get_vision_manager()
    result = await manager.process_images([image_base64])

    return result['results'][0]
```

## Model Information

### LLaVA 1.6

- **Base**: Mistral-7B (text) + CLIP (vision)
- **Training**: ~1.2M image-text pairs
- **Strengths**: General vision understanding, good OCR, reasoning about images
- **Weaknesses**: Less accurate than larger models, struggles with fine details

### Quantization Levels

| Quantization | Size | Quality | Speed |
|--------------|------|---------|-------|
| Q4_0         | 3.8 GB | Good    | Fast  |
| Q4_K_M       | 4.5 GB | Better  | Medium |
| Q5_K_M       | 5.5 GB | Great   | Slower |
| Q6_K         | 6.7 GB | Excellent | Slowest |

## Next Steps

1. ✓ Install and test vision system
2. Try different models/quantizations for your needs
3. Tune auto-unload timing for your workflow
4. Integrate vision analysis into custom MCP tools
5. Experiment with prompt engineering for specific tasks

## Support

For issues or questions:
- Check logs: Iris outputs detailed vision logs
- Test components individually: `vision_service.py`, `vision_manager.py`
- Review VISION_ARCHITECTURE.md for design details
