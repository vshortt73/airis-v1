# Vision System Setup - Simple (Ollama-based)

## Overview

Iris uses Ollama's built-in `llava` model for vision. This is **much simpler** than llama.cpp and just works!

## Quick Setup (2 Steps!)

### 1. Pull the LLaVA model

```bash
# Pull llava model (7B - faster, uses ~4GB VRAM)
ollama pull llava:7b

# OR llava 13B (better quality, uses ~7GB VRAM)
ollama pull llava:13b
```

### 2. Set which model to use in config

Edit `app/config.py`:
```python
VISION_MODEL = "llava:7b"  # or "llava:13b"
```

**That's it!** The vision system will now work automatically when users upload images.

## How It Works

- Iris uses the same Ollama instance for both main model (qwen3:32b) and vision (llava)
- When an image is uploaded, Iris automatically calls llava to analyze it
- The analysis is added to conversation context before the main model responds
- No GPU management needed - Ollama handles everything

## Test It

```bash
# Start Iris
export IRIS_DB_PASSWORD='your_password'
./scripts/start.sh

# In another terminal, test vision API
curl -X POST http://localhost:8000/api/vision/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "image": "'"$(base64 -w 0 /path/to/test/image.jpg)"'",
    "prompt": "What is in this image?"
  }' | jq
```

Or just open the web interface, upload an image, and chat!

## Model Comparison

| Model | VRAM | Speed | Quality | Use Case |
|-------|------|-------|---------|----------|
| llava:7b | ~4GB | Fast | Good | General use, quick responses |
| llava:13b | ~7GB | Medium | Better | More detailed analysis |
| llava:34b | ~18GB | Slow | Best | Maximum quality (if you have VRAM) |

## Troubleshooting

### "Model not found"

```bash
ollama pull llava:7b
```

### "Connection refused"

Make sure Ollama is running:
```bash
ollama serve
```

### Vision not working in chat

Check vision is enabled in `app/config.py`:
```python
VISION_ENABLED = True
```

Check vision status:
```bash
curl http://localhost:8000/api/vision/status | jq
```

## Configuration Options

In `app/config.py`:

```python
# Vision System
VISION_ENABLED = True
VISION_MODEL = "llava:7b"  # Which Ollama model to use
VISION_MAX_TOKENS = 1000  # Max response length
VISION_MAX_IMAGE_SIZE_MB = 10  # Max image size
VISION_TIMEOUT_SECONDS = 30  # Request timeout
VISION_DEBUG = False  # Verbose logging
```

## Performance

**llava:7b (recommended):**
- First request: ~2-3 seconds
- Subsequent: ~1-2 seconds
- VRAM: ~4GB

**llava:13b (better quality):**
- First request: ~3-5 seconds
- Subsequent: ~2-3 seconds
- VRAM: ~7GB

## Why Ollama Instead of llama.cpp?

The original plan was to use llama.cpp with manual GPU targeting, but:

1. **Simpler**: No need to download GGUF files, manage CLIP models, or build with CUDA
2. **More Reliable**: Ollama's llava integration is battle-tested and works out of the box
3. **Better Results**: Ollama handles the vision prompting correctly (no gibberish!)
4. **Easier Updates**: Just `ollama pull llava:latest` to update
5. **Same Performance**: Ollama uses llama.cpp under the hood anyway

The only trade-off is you can't explicitly control which GPU it uses, but Ollama's automatic scheduling works fine for most setups.

## Advanced: Multiple Ollama Instances (GPU Control)

If you really need llava on a specific GPU:

1. Run a second Ollama instance:
   ```bash
   # Terminal 1: Main Ollama (GPU 0)
   OLLAMA_HOST=127.0.0.1:11434 ollama serve

   # Terminal 2: Vision Ollama (GPU 1)
   CUDA_VISIBLE_DEVICES=1 OLLAMA_HOST=127.0.0.1:11435 ollama serve
   ```

2. Update config:
   ```python
   OLLAMA_BASE_URL = "http://localhost:11434"  # Main model
   VISION_OLLAMA_URL = "http://localhost:11435"  # Vision model
   ```

3. Update `vision_service.py` to use `VISION_OLLAMA_URL` instead of `OLLAMA_BASE_URL`

But for most cases, single Ollama instance works great!
