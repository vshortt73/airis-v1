from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Union
from contextlib import asynccontextmanager
import uvicorn
import psycopg2
from fastapi.responses import StreamingResponse
import emoji
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sentence_transformers import SentenceTransformer
import os

# Force offline mode for HuggingFace models
os.environ["HF_HUB_OFFLINE"] = "1"

# CRITICAL: Make BOTH GPUs visible, then we'll select GPU 1 in model params
os.environ["CUDA_VISIBLE_DEVICES"] = "0"

# Import llama_cpp AFTER setting CUDA environment
from llama_cpp import Llama, LlamaGrammar

app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)


DB_NAME = os.environ.get('AIRIS_DB_NAME', 'airisdb')
DB_USER = os.environ.get('AIRIS_DB_USER', 'airisuser')
DB_PASS = os.environ.get('AIRIS_DB_PASSWORD', '')
DB_HOST = "localhost"

config = {}

# Global variables to hold the LLM instance and embedding model
llm: Optional[Llama] = None
embedding_model: Optional[SentenceTransformer] = None

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

class EmbedRequest(BaseModel):
    text: str

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
    print(f">>>>>>>>>>>>>>>>>>>>>>>>>>>>>API Called. {prompt}")
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

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan event handler for startup and shutdown"""
    global embedding_model

    # Startup
    # You'll need to modify this path to point to your model
    model_path = config['Big-Model']  # Change this to your model path

    # Model initialization parameters - distributed across both GPUs
    model_params = {
        "n_ctx": 8192,          # Context window
        "n_gpu_layers": -1,     # -1 = ALL layers on GPU (auto-distribute across both)
        "main_gpu": 0,          # Primary GPU for compute
        "tensor_split": None,   # Let llama.cpp auto-distribute across GPUs
        "verbose": True,        # Set to True for debugging
        "n_threads": 8,         # CPU threads
    }

    success = initialize_llm(model_path, **model_params)
    if not success:
        print("Warning: Failed to initialize model on startup")
    else:
        print("Model loaded successfully")

    # Load embedding model for memory retrieval
    print("Loading embedding model...")
    try:
        embedding_model = SentenceTransformer(
            os.environ.get('EMBEDDING_MODEL_PATH', '/models/llm_models/huggingface/models/all-mpnet-base-v2/')
        )
        print("✅ Embedding model loaded successfully (all-mpnet-base-v2)")
    except Exception as e:
        print(f"⚠️ Warning: Failed to load embedding model: {e}")
        embedding_model = None

    yield

    # Shutdown (cleanup if needed)
    embedding_model = None
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


def validate_and_clean_json_response(response_text):
    """Validate and clean the JSON response"""
    try:
        data = json.loads(response_text)
        
        # Clean up empty category
        if 'category' in data and not data['category'].strip():
            data['category'] = 'general'
            
        # Clean up shaped_queries
        if 'shaped_queries' in data:
            cleaned_queries = []
            for query in data['shaped_queries']:
                query = str(query).strip()
                if query.startswith('?'):
                    query = query[1:].strip()
                if query and not query.endswith('?'):
                    query += '?'
                if len(query) > 3:
                    cleaned_queries.append(query)
            data['shaped_queries'] = cleaned_queries
            
        # Clean up keywords
        if 'keywords' in data:
            data['keywords'] = [str(kw).strip() for kw in data['keywords'] if str(kw).strip()]
            
        return json.dumps(data)
        
    except:
        return None


@app.post("/v1/completions", response_model=Union[CompletionResponse, dict])
async def create_completion(request: CompletionRequest):
    """Create a text completion"""
    request.prompt = emoji.replace_emoji(request.prompt, replace='')
    print(f"Got prompt: {request.prompt}")
    global llm
    
    if llm is None:
        raise HTTPException(status_code=503, detail="Model not initialized")

    grammar = None
    if request.grammar_file:
        try:
            # Load grammar content manually
            with open(request.grammar_file, 'r', encoding='utf-8') as f:
                grammar_content = f.read().strip()
            
            # Validate no duplicates
            if grammar_content.count('root ::=') > 1:
                raise ValueError("Multiple root definitions found in grammar")
                
            # Create grammar from string instead of file
            grammar = LlamaGrammar.from_string(grammar_content)
            print(f"Grammar loaded from string successfully")
            
        except Exception as e:
            print(f"Grammar error: {e}")
            raise HTTPException(status_code=400, detail=f"Grammar error: {str(e)}")

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
            grammar=grammar
        )
        print(response["choices"][0]["text"])
        return {
            "id": "cmpl-123",
            "object": "text_completion",
            "choices": [
                {"index": 0, "text": response["choices"][0]["text"]}
            ]
        }

       

       # print(f"response received: {response}")
        # If streaming is requested, return the generator
      #  if request.stream:
      #      return response
       
        print("cleaning json...")
        #Clean JSON if grammar was used
        if grammar and response and "choices" in response and response["choices"]:
            original_text = response["choices"][0]["text"]
            cleaned_text = validate_and_clean_json_response(original_text)

        if cleaned_text:
            response["choices"][0]["text"] = cleaned_text
            return {
                "id": "cmpl-123",
                "object": "text_completion",
                "choices": [
                    {"index": 0, "text": cleaned_text}
                ]
            }

        print("json not cleaned for some reason.")
        return response

    # ✅ Fallback return if grammar not used
        return {
            "id": "cmpl-123",
            "object": "text_completion",
            "choices": [
                {"index": 0, "text": response["choices"][0]["text"]}
            ]
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")



@app.post("/v1/completions/stream", response_class=StreamingResponse)
async def create_completion_stream(request: CompletionRequest):
    """Create a streaming text completion"""
    global llm

    if llm is None:
        raise HTTPException(status_code=503, detail="Model not initialized")

    def token_stream():
        try:
            for chunk in llm(
                prompt=request.prompt,
                stream=True,  # force streaming here
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
                mirostat_eta=request.mirostat_eta
            ):
                # each chunk from llama.cpp already looks like {"choices": [{"text": "..."}]}
                if "choices" in chunk and chunk["choices"]:
                    token = chunk["choices"][0]["text"]
                    yield f"data: {json.dumps({'choices': [{'text': token}]})}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(token_stream(), media_type="text/event-stream")




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

@app.get("/model-info")
async def model_info():
    global llm
    if llm is None:
        raise HTTPException(status_code=503, detail="Model not initialized")

    info = {}
    try:
        info["n_ctx"] = getattr(llm, "n_ctx", None) or getattr(llm, "context_params", {}).get("n_ctx", None)
    except Exception:
        pass
    try:
        info["n_threads"] = getattr(llm, "n_threads", None) or getattr(llm, "context_params", {}).get("n_threads", None)
    except Exception:
        pass
    try:
        info["n_gpu_layers"] = getattr(llm, "n_gpu_layers", None) or getattr(llm, "context_params", {}).get("n_gpu_layers", None)
    except Exception:
        pass
    try:
        info["model_path"] = getattr(llm, "model_path", None)
    except Exception:
        pass

    return info



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

@app.post("/embed")
async def embed(req: EmbedRequest):
    """Generate embeddings for memory retrieval and semantic search"""
    global embedding_model

    if embedding_model is None:
        raise HTTPException(
            status_code=503,
            detail="Embedding model not loaded. Check server logs for initialization errors."
        )

    try:
        # Generate embedding vector using SentenceTransformer
        vector = embedding_model.encode(req.text).tolist()
        return {"vector": vector}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Embedding generation failed: {str(e)}"
        )

if __name__ == "__main__":
    # Run the server
    uvicorn.run(
        "llm_engine:app",  # Updated to match your filename
        host="0.0.0.0",
        port=9600,         # Updated to match your port
        log_level="debug",      # Enable debug logging
        access_log=True,        # Log all requests
        use_colors=True,        # Colored output
    )


