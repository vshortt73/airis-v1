from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Union
from contextlib import asynccontextmanager
import uvicorn
from llama_cpp import Llama
import psycopg2
from sentence_transformers import SentenceTransformer
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import os


DB_NAME = "irisdb"
DB_USER = "irisuser"
DB_PASS = "yourpassword"
DB_HOST = "localhost"

# Force offline mode
os.environ["HF_HUB_OFFLINE"] = "1"

#model = SentenceTransformer("/models/llm_models/huggingface/models/all-mpnet-base-v2/", local_files_only=True)
#model = SentenceTransformer("/models/llm_models/huggingface/models/all-mpnet-base-v2/", model_kwargs={"local_files_only": True})
model = SentenceTransformer("/models/llm_models/huggingface/models/all-mpnet-base-v2/")

config = {}

class CompletionRequest(BaseModel):
    prompt: str
    stream: bool = False
    max_tokens: int = 1024
    top_k: int = 2
    temperature: float = 0.2
    repeat_penalty: float = 2.2
    stop: Optional[List[str]] = [
        "<|im_start|>user",
        "<|im_start|>system",
        "<|im_end|>",
        "<|end_of_turn|>"
    ]
    top_p: float = 0.95
    min_p: float = 0.05
    typical_p: float = 1.0
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    tfs_z: float = 1.0
    mirostat_mode: int = 0
    mirostat_tau: float = 5.0
    mirostat_eta: float = 0.1

    # 🔥 Add grammar support
    grammar_file: Optional[str] = None
    grammar_str: Optional[str] = None


class CompletionResponse(BaseModel):
    id: str
    object: str = "text_completion"
    created: int
    model: str
    choices: List[dict]
    usage: dict

# Global variable to hold the LLM instance
llm: Optional[Llama] = None

conn= psycopg2.connect(
    dbname=DB_NAME,
    user=DB_USER,
    password=DB_PASS,  # or leave blank if using peer auth
    host=DB_HOST
)

cursor = conn.cursor()
cursor.execute("""SELECT name, Value FROM variables""")
rows = cursor.fetchall()
conn.close()

for name, value in rows:
    config[name] = value

# Pydantic models for request/response
class CompletionRequest(BaseModel):
    prompt: str
    stream: bool = False
    max_tokens: int = 1024
    top_k: int = 2
    temperature: float = 0.2
    repeat_penalty: float = 2.2
    stop: Optional[List[str]] = ["<|im_start|>user", "<|im_start|>system", "<|im_end|>", "<|end_of_turn|>"]
    top_p: float = 0.95
    min_p: float = 0.05
    typical_p: float = 1.0
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    tfs_z: float = 1.0
    mirostat_mode: int = 0
    mirostat_tau: float = 5.0
    mirostat_eta: float = 0.1
    grammar_file: Optional[str] = None
    grammar_str: Optional[str] = None

class CompletionResponse(BaseModel):
    id: str
    object: str = "text_completion"
    created: int
    model: str
    choices: List[dict]
    usage: dict

class TokenizeRequest(BaseModel):
    text: str
    add_bos: bool = True
    special: bool = True

class TokenizeResponse(BaseModel):
    tokens: List[int]

# Global variable to hold the LLM instance
llm: Optional[Llama] = None

def initialize_llm(model_path: str, **kwargs):
    """Initialize the Llama model"""
    global llm
    try:
        llm = Llama(model_path=model_path, **kwargs)
        return True
    except Exception as e:
        print(f"Error initializing model: {e}")
        return False

import requests
import json

def llm_api(prompt, stream=False, api_url="http://localhost:9500", **kwargs):
    """
    Unified API client that handles both streaming and non-streaming responses
    Returns either a generator (streaming) or a dict (non-streaming)
    """
    payload = {
        "prompt": prompt,
        "stream": stream,
        **kwargs
    }
    steam=False
    if stream:
        print(f"handling streaming response...{payload}")
        # Handle streaming response
        response = requests.post(f"{api_url}/generate", json=payload, stream=True)
        response.raise_for_status()
        
        def stream_generator():
            for line in response.iter_lines():
                if line:
                    line = line.decode('utf-8')
                    if line.startswith('data: '):
                        data = line[6:]  # Remove 'data: ' prefix
                        if data == '[DONE]':
                            break
                        try:
                            chunk = json.loads(data)
                            yield chunk
                        except json.JSONDecodeError:
                            continue
        
        return stream_generator()
    
    else:
        # Handle non-streaming response
        response = requests.post(f"{api_url}/generate", json=payload)
    #    response.raise_for_status()
        result = response.json()
        return {
            "choices": [{"text": result["text"]}],
            "usage": {"total_tokens": len(result["text"].split())}
        }

# # Usage examples:

# # 1. Streaming usage (your current pattern works unchanged)
# print("=== Streaming ===")
# for chunk in llm_api(
#     prompt="Tell me a story about a robot",
#     stream=True,
#     max_tokens=15000,
#     top_p=0.4,  
#     top_k=30,
#     temperature=1.4,
#     repeat_penalty=2.2,
#     stop=["<|im_start|>user", "<|im_start|>system", "<|im_end|>", "<|end_of_turn|>"]
# ):
#     # Extract text - your existing code works
#     text = chunk.get("choices", [{}])[0].get("text", "") if isinstance(chunk, dict) else str(chunk)
#     print(text, end="", flush=True)

# print("\n\n=== Non-streaming ===")
# # 2. Non-streaming usage
# response = llm_api(
#     prompt="What is 2+2?",
#     stream=False,
#     max_tokens=100,
#     temperature=0.2
# )

# # Extract text from non-streaming response
# text = response["choices"][0]["text"]
# print(f"Response: {text}")

# # 3. Generic handler that works with both
# def handle_llm_response(prompt, use_streaming=True, **kwargs):
#     """Handle both streaming and non-streaming in one function"""
    
#     if use_streaming:
#         print("Streaming response:")
#         full_text = ""
#         for chunk in llm_api(prompt=prompt, stream=True, **kwargs):
#             text = chunk.get("choices", [{}])[0].get("text", "")
#             print(text, end="", flush=True)
#             full_text += text
#         print()  # New line after streaming
#         return full_text
#     else:
#         print("Non-streaming response:")
#         response = llm_api(prompt=prompt, stream=False, **kwargs)
#         text = response["choices"][0]["text"]
#         print(text)
#         return text

# # Test both modes with same function
# prompt = "Explain quantum computing in simple terms"

# streaming_result = handle_llm_response(prompt, use_streaming=True, max_tokens=200)
# non_streaming_result = handle_llm_response(prompt, use_streaming=False, max_tokens=200)



@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan event handler for startup and shutdown"""
    # Startup
    # You'll need to modify this path to point to your model
    model_path = config['Mini-Model']  # Change this to your model path
    
    # Model initialization parameters - adjust as needed
    model_params = {
        "n_ctx": 4096,           # Context length
        "n_gpu_layers": 35,      # Use GPU if available (-1 = all layers)
        "verbose": True,        # Set to True for debugging
        "n_threads": None,       # Number of threads (None = auto)
    }
    
    success = initialize_llm(model_path, **model_params)
    if not success:
        print("Warning: Failed to initialize model on startup")
    else:
        print("Model loa ded successfully")
    yield
    
    # Shutdown (cleanup if needed)
    pass

# Initialize FastAPI app with lifespan
app = FastAPI(
    title="LLama-CPP API", 
    description="API wrapper for llama-cpp-python",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from llama_cpp import Llama, LlamaGrammar
from sentence_transformers import SentenceTransformer
@app.post("/v1/completions", response_model=Union[CompletionResponse, dict])
async def create_completion(request: CompletionRequest):
    """Create a text completion"""

    global llm
    
    grammar = None
    if request.grammar_file:
        grammar = LlamaGrammar.from_file(request.grammar_file)
    elif request.grammar_str:
        grammar = LlamaGrammar(request.grammar_str)
    if llm is None:
        raise HTTPException(status_code=503, detail="Model not initialized")
    
    try:
        # Call the llama-cpp model with your exact parameters
        response = llm(
            prompt=request.prompt,
            stream=request.stream,
            max_tokens=request.max_tokens,
            top_k=request.top_k,
            temperature=request.temperature,
            repeat_penalty=request.repeat_penalty,
            stop=request.stop,
            top_p=request.top_p,
            min_p=request.min_p,
            typical_p=request.typical_p,
            frequency_penalty=request.frequency_penalty,
            presence_penalty=request.presence_penalty,
            tfs_z=request.tfs_z,
            mirostat_mode=request.mirostat_mode,
            mirostat_tau=request.mirostat_tau,
            mirostat_eta=request.mirostat_eta,
            grammar=grammar, 
        )
        print(f"response is {response}")
        # If streaming is requested, return the generator
        if request.stream:
            return response
        
        # Otherwise return the complete response
        return response
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")

# Convenience endpoint that matches your exact interface
@app.post("/generate")
async def generate_text(request: CompletionRequest):
    """Simple generation endpoint that returns just the text"""
    global llm
    
    if llm is None:
        raise HTTPException(status_code=503, detail="Model not initialized")
    
    try:
        response = llm(
            prompt=request.prompt,
            stream=request.stream,
            max_tokens=request.max_tokens,
            top_k=request.top_k,
            temperature=request.temperature,
            repeat_penalty=request.repeat_penalty,
            stop=request.stop
        )
        
        if request.stream:
            return response
        else:
            # Extract just the generated text
            return {"text": response["choices"][0]["text"]}
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")

@app.post("/token-count")
async def get_token_count(request: TokenizeRequest):
    """Get just the token count"""
    result = await tokenize_text(request)
    return {"count": len(result.tokens)}

@app.post("/tokenize", response_model=TokenizeResponse)
async def tokenize_text(request: TokenizeRequest):
    """Tokenize text using the loaded model"""
    global llm
    
    if llm is None:
        raise HTTPException(status_code=503, detail="Model not initialized")
    
    try:
        # Handle both string and bytes input
        text = request.text
        if isinstance(text, str):
            text_bytes = text.encode("utf-8")
        else:
            text_bytes = text
            
        tokens = llm.tokenize(
            text_bytes,
            add_bos=request.add_bos,
            special=request.special
        )
        
        return TokenizeResponse(tokens=tokens)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Tokenization failed: {str(e)}")

@app.post("/detokenize")
async def detokenize_tokens(tokens: List[int]):
    """Convert tokens back to text"""
    global llm
    
    if llm is None:
        raise HTTPException(status_code=503, detail="Model not initialized")
    
    try:
        text_bytes = llm.detokenize(tokens)
        text = text_bytes.decode("utf-8", errors="ignore")
        return {"text": text}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Detokenization failed: {str(e)}")

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy" if llm is not None else "model_not_loaded",
        "model_loaded": llm is not None
    }

@app.post("/load_model")
async def load_model(model_path: str, **kwargs):
    """Endpoint to load a different model"""
    success = initialize_llm(model_path, **kwargs)
    if success:
        return {"status": "success", "message": f"Model loaded from {model_path}"}
    else:
      

        raise HTTPException(status_code=500, detail="Failed to load model")


class EmbedRequest(BaseModel):
    text: str

@app.post("/embed")
def embed(req: EmbedRequest):
    vector = model.encode(req.text).tolist()
    return {"vector": vector}
    
if __name__ == "__main__":
    # Run the server
    uvicorn.run(
        "small_llm_api:app",  # Updated to match your filename
        host="0.0.0.0",
        port=9500,         # Updated to match your port
        log_level="debug",      # Enable debug logging
        access_log=True,        # Log all requests
        use_colors=True,        # Colored output
    )