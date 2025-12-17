# Vision System Architecture - Iris v3

## Overview

Iris uses a **dual-model architecture** for optimal performance:
- **Primary Model**: qwen3:32b (Ollama on GPU 0 / RTX 5090) - Text, tool calling, reasoning
- **Vision Model**: llava (llama.cpp on GPU 1 / RTX 4080 Super) - Image analysis on demand

This architecture allows Iris to maintain excellent tool calling capabilities while having dedicated vision when needed.

## Design Rationale

### Why Separate Vision Model?

1. **Tool Calling Excellence**: qwen3:32b has superior tool calling, which is critical for Iris
2. **Resource Efficiency**: Vision model loads only when needed, freeing GPU 1 for:
   - ComfyUI image generation
   - XTTS audio synthesis
   - Other tasks
3. **Resolution/Quality**: Dedicated vision model can be optimized for image analysis
4. **Cost**: Smaller vision model (llava) is faster and uses less VRAM

### GPU Allocation Strategy

```
GPU 0 (RTX 5090 - 32GB):
├── Ollama Server (persistent)
│   └── qwen3:32b model
└── [Always loaded]

GPU 1 (RTX 4080 Super - 16GB):
├── XTTS Audio Model (persistent, small footprint ~2GB)
├── Vision Model (on-demand, ~4-6GB)
│   └── llava via llama.cpp
└── ComfyUI (when vision not active, ~8-12GB)
```

## Architecture Components

### 1. Vision Service (`ollama/vision_service.py`)

**Purpose**: Manage llama.cpp vision model lifecycle

**Responsibilities**:
- Load llava model to GPU 1
- Process vision requests
- Unload model when idle
- Handle errors and fallbacks

**Key Methods**:
```python
class VisionService:
    def __init__(self):
        # Initialize llama.cpp with GPU 1

    async def load_model(self) -> bool:
        # Load llava model to GPU 1

    async def analyze_image(self, image_base64: str, prompt: str) -> str:
        # Send image + prompt to llava
        # Return analysis text

    async def unload_model(self) -> bool:
        # Free GPU 1 memory

    def is_loaded(self) -> bool:
        # Check model status
```

### 2. Vision Manager (`core/vision_manager.py`)

**Purpose**: High-level vision request coordination

**Responsibilities**:
- Queue vision requests
- Manage model lifecycle based on usage
- Integrate with conversation flow
- Token counting for vision results

**Key Methods**:
```python
class VisionManager:
    def __init__(self):
        self.service = VisionService()
        self.last_used = None
        self.unload_timer = None

    async def process_images(self, images: List[str], context: str) -> str:
        # Load model if needed
        # Process all images
        # Return consolidated analysis
        # Schedule unload after timeout

    async def ensure_unloaded(self):
        # Unload if idle for N minutes
```

### 3. API Endpoints (`app/api/routes_vision.py`)

**Purpose**: HTTP endpoints for vision services

**Endpoints**:
- `POST /api/vision/analyze` - Analyze single image
- `POST /api/vision/batch` - Analyze multiple images
- `GET /api/vision/status` - Check model status
- `POST /api/vision/unload` - Force unload model

### 4. Chat Integration

**Modified Flow**:
```
User sends message + images
    ↓
Save images to disk (attachments.py)
    ↓
Check: Do we need vision?
    ↓ YES
Load vision model (if not loaded)
    ↓
Send images to VisionService
    ↓
Receive image descriptions
    ↓
Add vision results to conversation context
    ↓
Continue with normal chat flow (qwen3:32b + tools)
    ↓
Schedule vision model unload (5 min timer)
```

## Implementation Details

### llama.cpp Integration

**Library**: `llama-cpp-python` (Python bindings)

**Installation**:
```bash
# Install with CUDA support for GPU 1
CMAKE_ARGS="-DLLAMA_CUBLAS=on" pip install llama-cpp-python
```

**GPU Targeting**:
```python
# Force GPU 1 usage
os.environ['CUDA_VISIBLE_DEVICES'] = '1'

from llama_cpp import Llama
from llama_cpp.llama_chat_format import Llava15ChatHandler

# Initialize
chat_handler = Llava15ChatHandler(clip_model_path="path/to/clip")
llm = Llama(
    model_path="path/to/llava-model.gguf",
    chat_handler=chat_handler,
    n_gpu_layers=-1,  # Offload all layers to GPU
    n_ctx=2048,       # Context window
    verbose=False
)
```

### Model Loading Strategy

**On-Demand Loading**:
- Model loads only when image is received
- First request takes ~3-5 seconds (model load time)
- Subsequent requests are instant

**Auto-Unload**:
- After 5 minutes of no vision requests
- Timer resets on each new request
- Manual unload via API or when ComfyUI needs GPU

**Model Files**:
```
/models/vision/
├── llava-v1.6-mistral-7b.Q4_K_M.gguf  # Main model
└── mmproj-model-f16.gguf               # Vision encoder
```

### Vision Prompt Templates

**Default Analysis Prompt**:
```
"Describe this image in detail. Focus on key objects, people, actions,
text, colors, and any notable features. Be concise but thorough."
```

**Context-Aware Prompts**:
- If user asks specific question: Use that as prompt
- If continuing conversation: "Describe what you see in this image to help answer: {last_user_message}"
- If multiple images: Number them and describe each

### Token Budget

**Vision Results Allocation**:
- Reserve 500-1000 tokens for vision analysis per image
- Truncate long descriptions if needed
- Store in conversation as "tool" message:

```python
{
    "role": "tool",
    "tool_name": "vision_analysis",
    "content": "Image 1: [description]..."
}
```

## Configuration (`app/config.py`)

```python
# ============================================
# VISION SYSTEM CONFIGURATION
# ============================================
VISION_ENABLED = True
VISION_MODEL_PATH = "/models/vision/llava-v1.6-mistral-7b.Q4_K_M.gguf"
VISION_CLIP_PATH = "/models/vision/mmproj-model-f16.gguf"
VISION_GPU_ID = 1  # RTX 4080 Super
VISION_AUTO_UNLOAD_MINUTES = 5
VISION_MAX_TOKENS = 1000  # Per image analysis
VISION_CONTEXT_WINDOW = 2048
```

## Error Handling & Fallbacks

### Model Load Failure
- Log error clearly
- Return message to user: "Vision system unavailable"
- Continue conversation without vision

### GPU Memory Error
- Attempt to free memory
- Try lower context window
- Fall back to CPU (slow but works)
- Notify user of degraded performance

### Image Processing Errors
- Validate image format
- Check file size (max 10MB)
- Resize if too large
- Return error message if corrupt

## Performance Expectations

### Latency
- **Cold start** (model not loaded): ~3-5 seconds
- **Warm start** (model loaded): ~0.5-1.5 seconds per image
- **Model load time**: ~2-3 seconds
- **Model unload time**: ~1 second

### Memory Usage
- **llava-7b Q4**: ~4-6 GB VRAM
- **XTTS**: ~2 GB VRAM
- **Available for ComfyUI**: ~8-10 GB (when vision unloaded)

### Throughput
- **Single image**: ~1-2 seconds
- **Batch (3 images)**: ~3-5 seconds
- **Concurrent requests**: Queued (no parallel)

## Testing Strategy

### Unit Tests
- Model loading/unloading
- Image encoding/decoding
- GPU targeting verification
- Error handling paths

### Integration Tests
- End-to-end image analysis via API
- Chat flow with images
- Auto-unload timer functionality
- GPU 1 isolation (not interfering with GPU 0)

### Performance Tests
- Cold vs warm start latency
- Memory leak detection
- Concurrent request handling
- VRAM usage monitoring

## Migration Path

### Phase 1: Foundation ✓ (Current)
- Vision service module
- llama.cpp integration
- Basic API endpoints

### Phase 2: Integration
- Connect to chat flow
- Auto-unload system
- Token counting

### Phase 3: Optimization
- Prompt tuning
- Batch processing
- Caching strategies

### Phase 4: Advanced Features
- Image comparison
- OCR optimization
- Multi-modal reasoning

## Monitoring & Debugging

### Logging
```python
print(f"[vision_service.py][load_model] Loading llava to GPU {config.VISION_GPU_ID}")
print(f"[vision_service.py][analyze_image] Processing image ({len(image_data)} bytes)")
print(f"[vision_manager.py][process_images] Vision analysis: {tokens} tokens")
```

### Health Checks
- `/api/vision/status` - Model loaded? GPU memory? Last used?
- `/api/vision/stats` - Request count, avg latency, error rate

### Debug Mode
```python
VISION_DEBUG = True  # Verbose logging
VISION_SAVE_INPUTS = True  # Save images for debugging
```

## Security Considerations

### Input Validation
- Max image size: 10 MB
- Allowed formats: PNG, JPG, JPEG, WebP
- Validate base64 encoding
- Check for malicious payloads

### Resource Limits
- Max concurrent requests: 1 (queue others)
- Max images per request: 5
- Timeout per image: 30 seconds
- GPU memory monitoring

### Privacy
- Images stored locally only
- No external API calls
- Auto-delete old images (optional)

## Future Enhancements

1. **Model Selection**: Allow user to choose vision model (llava, cogvlm, etc.)
2. **Image Generation**: Integrate FLUX via ComfyUI on same GPU
3. **Video Analysis**: Frame extraction + batch processing
4. **OCR Pipeline**: Dedicated text extraction path
5. **Embeddings**: Image embeddings for episodic memory
6. **Comparison Mode**: "Compare these two images..."
7. **Annotated Output**: Return bounding boxes, labels

## References

- llama.cpp: https://github.com/ggerganov/llama.cpp
- llama-cpp-python: https://github.com/abetlen/llama-cpp-python
- LLaVA: https://llava-vl.github.io/
- Ollama Tool Calling: https://ollama.ai/blog/tool-support
