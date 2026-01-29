"""
LLM API client for Iris v3
OpenAI-compatible interface with switchable backends (llama-server / SGLang)

Both backends expose /v1/chat/completions (OpenAI-compatible).
The difference is metrics extraction:
- llama.cpp: timings object with cache_n, prompt_n, predicted_n, etc.
- SGLang: usage object with prompt_tokens_details.cached_tokens (RadixAttention)

Backend is selected via INFERENCE_BACKEND config ('llamacpp' or 'sglang').
"""
from colorama import Fore, Back, Style, init
import httpx
from typing import Dict, List, AsyncIterator, Optional, Any
import json
import sys
import os; PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..' if '__file__' in dir() else '.')); sys.path.insert(0, PROJECT_ROOT)
from app import config
from core.token_counter import TokenCounter
import psycopg2

def get_db_connection():
    """Create database connection"""
    password = os.environ.get('IRIS_DB_PASSWORD') or getattr(config, 'DB_PASSWORD', None)

    conn_params = {
        'host': config.DB_HOST,
        'port': config.DB_PORT,
        'database': config.DB_NAME,
        'user': config.DB_USER
    }

    if password:
        conn_params['password'] = password

    return psycopg2.connect(**conn_params)

def kv_cutoff_preview(last_prompt, current_prompt, preview_words=15):
    """
    Approximate KV cache cutoff by comparing prompts word by word.
    Returns percent reused and next words to be re-encoded.
    """
    last_words = str(last_prompt).split()
    current_words = str(current_prompt).split()
    
    # Find first mismatch
    cutoff_index = 0
    for w1, w2 in zip(last_words, current_words):
        if w1 == w2:
            cutoff_index += 1
        else:
            break
    
    reuse_pct = (cutoff_index / len(current_words)) * 100
    
    # Grab next N words for preview
    next_words = current_words[cutoff_index : cutoff_index + preview_words]
    
    return {
        'reuse_pct': reuse_pct,
        'cutoff_index': cutoff_index,
        'next_words': ' '.join(next_words)
    }



def prompt_compare(prompt):
    print (f"[client.py][prompt_compare] kv comparison initializing")
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        #3. Get the existing hash from last turn
        cursor.execute("""SELECT hash FROM prompt_hashes where section = 'prompt' LIMIT 1 """)
        result = cursor.fetchone()
        cursor.close()
    except Exception as e:
        print(f">>> EXCEPTION {e}")

    #print(f"[system_prompt.py][hash_compare] " + Style.BRIGHT + Fore.CYAN + f"dbase hash {result[0]}")
    if result:
            last_prompt = result[0]
            kv_report =  kv_cutoff_preview(last_prompt, prompt)
            print (Style.BRIGHT + Fore.YELLOW + f"~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~")
            print (f"[client.py][prompt_compare] kv comparison results:\n{kv_report}\n")
            print (Style.BRIGHT + Fore.YELLOW + f"~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~")
    else:
        print(f"[client.py][prompt_compare] " + Style.BRIGHT + Fore.YELLOW + f"No prompt found. adding.")

    try: 

        #print(f"[system_prompt.py][hash_compare] " + Style.BRIGHT + Fore.GREEN + f"updating the prompt_hashes")
        cursor = conn.cursor()
        cursor.execute(
                """
                INSERT INTO prompt_hashes (section, hash)
                VALUES (%s, %s)
                ON CONFLICT (section)
                DO UPDATE SET hash = EXCLUDED.hash
                """,
                ("prompt", str(prompt),)
            )
        conn.commit()
        cursor.close()
        conn.close()
         # 3. Return the hexadecimal string
         # return hash_obj.hexdigest()      
    except Exception as e:
        print(f"exception updating ... {e}")




def _get_backend() -> str:
    """Return the active inference backend ('llamacpp' or 'sglang')"""
    return getattr(config, 'INFERENCE_BACKEND', 'llamacpp').lower()


def _extract_timings_from_response(response_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract unified timing metrics from a non-streaming response.

    llama.cpp: top-level 'timings' object or __verbose.timings
    SGLang: 'usage' object with prompt_tokens_details.cached_tokens
    """
    backend = _get_backend()

    if backend == 'sglang':
        usage = response_data.get("usage", {})
        prompt_total = usage.get("prompt_tokens", 0)
        cached = 0
        details = usage.get("prompt_tokens_details", {})
        if details:
            cached = details.get("cached_tokens", 0)
        return {
            "cache_n": cached,
            "prompt_n": prompt_total - cached,
            "predicted_n": usage.get("completion_tokens", 0),
            "predicted_ms": 0,
            "prompt_ms": 0,
            "predicted_per_second": 0,
            "prompt_per_second": 0,
        }
    else:
        # llama.cpp: try top-level timings first, then __verbose.timings
        timings = response_data.get("timings", {})
        if not timings:
            timings = response_data.get("__verbose", {}).get("timings", {})
        return {
            "cache_n": timings.get("cache_n", 0),
            "prompt_n": timings.get("prompt_n", 0),
            "predicted_n": timings.get("predicted_n", 0),
            "predicted_ms": timings.get("predicted_ms", 0),
            "prompt_ms": timings.get("prompt_ms", 0),
            "predicted_per_second": timings.get("predicted_per_second", 0),
            "prompt_per_second": timings.get("prompt_per_second", 0),
        }


def _extract_timings_from_stream_chunk(chunk: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Extract unified timing metrics from a streaming SSE chunk.
    Returns a timings dict on the final chunk, or None otherwise.

    llama.cpp: 'timings' key on the final chunk (with finish_reason)
    SGLang: 'usage' key on the final chunk (when stream_options.include_usage is set)
    """
    backend = _get_backend()

    if backend == 'sglang':
        usage = chunk.get("usage")
        if not usage:
            return None
        prompt_total = usage.get("prompt_tokens", 0)
        cached = 0
        details = usage.get("prompt_tokens_details", {})
        if details:
            cached = details.get("cached_tokens", 0)
        return {
            "cache_n": cached,
            "prompt_n": prompt_total - cached,
            "predicted_n": usage.get("completion_tokens", 0),
            "predicted_ms": 0,
            "prompt_ms": 0,
            "predicted_per_second": 0,
            "prompt_per_second": 0,
        }
    else:
        timings = chunk.get("timings")
        if not timings:
            return None
        return timings


class ToolCallResponse:
    """Response object that may contain tool calls (OpenAI-compatible format)"""

    def __init__(self, response_data: Dict[str, Any]):
        self.raw_response = response_data
        # OpenAI format: choices[0].message instead of message
        choices = response_data.get("choices", [])
        self.message = choices[0].get("message", {}) if choices else {}
        self.tool_calls = self.message.get("tool_calls", [])
        # Extract KV cache metrics via backend-aware helper
        timings = _extract_timings_from_response(response_data)
        self.cache_tokens = timings.get("cache_n", 0)
        self.prompt_tokens = timings.get("prompt_n", 0)
        self.predicted_tokens = timings.get("predicted_n", 0)

        # Calculate cache efficiency
        total_prompt = self.cache_tokens + self.prompt_tokens
        self.cache_efficiency = (self.cache_tokens / total_prompt * 100) if total_prompt > 0 else 0

    def has_tool_calls(self) -> bool:
        """Check if response contains tool calls"""
        return len(self.tool_calls) > 0

    def get_content(self) -> str:
        """Get text content from response"""
        return self.message.get("content", "")

    def log_cache_metrics(self):
        """Log detailed cache metrics for Phase 2 monitoring"""
        total_prompt = self.cache_tokens + self.prompt_tokens
        efficiency = self.cache_efficiency

        print(f"[client.py][cache_metrics] " + Style.BRIGHT + Fore.CYAN +
              f"┌── KV CACHE METRICS ──┐")
        print(f"[client.py][cache_metrics] │ Cached:     {self.cache_tokens:,} tokens")
        print(f"[client.py][cache_metrics] │ New:        {self.prompt_tokens:,} tokens")
        print(f"[client.py][cache_metrics] │ Total:      {total_prompt:,} tokens")
        print(f"[client.py][cache_metrics] │ Efficiency: {efficiency:.1f}%")

        # Color-coded efficiency indicator
        if efficiency >= 80:
            status = Fore.GREEN + "✓ EXCELLENT" + Style.RESET_ALL
        elif efficiency >= 65:
            status = Fore.YELLOW + "○ GOOD" + Style.RESET_ALL
        elif efficiency >= 50:
            status = Fore.YELLOW + "△ FAIR" + Style.RESET_ALL
        else:
            status = Fore.RED + "✗ POOR" + Style.RESET_ALL

        print(f"[client.py][cache_metrics] │ Status:     {status}")
        print(f"[client.py][cache_metrics] └──────────────────────┘")


async def chat_completion_with_tools(
    messages: List[Dict[str, str]],
    tools: Optional[List[Dict[str, Any]]] = None
) -> ToolCallResponse:
    """
    Send chat completion request to llama-server with tool definitions (non-streaming)

    This is used for the FIRST call when tools are available - the model will
    decide whether to call a tool or respond directly.

    Args:
        messages: List of message dicts with "role" and "content" keys
        tools: Optional list of tool definitions in OpenAI format:
               [{
                   "type": "function",
                   "function": {
                       "name": "weather_get",
                       "description": "...",
                       "parameters": {...}
                   }
               }]

    Returns:
        ToolCallResponse object containing either tool calls or text response
    """

    # OpenAI-compatible endpoint
    url = f"{config.OLLAMA_TOOL_EVAL_URL}/v1/chat/completions"

    # Minimal context for tool evaluation
    # Tool definitions are in the 'tools' parameter, not system message
    truncated_messages = []

    minimal_system = {
        'role': 'system',
        'content': 'You are Iris, an AI assistant. Analyze the conversation and call appropriate tools when needed.'
    }
    truncated_messages.append(minimal_system)

    # Keep conversation messages only (skip system messages from original)
    conversation_only = [msg for msg in messages if msg.get('role') != 'system']

    # Keep last 20 messages for good context
    truncated_messages.extend(conversation_only[-20:])

    print(f"[client.py][chat_completion_with_tools] ⚡ Minimal context for tool eval: {len(messages)} → {len(truncated_messages)} messages")

    # OpenAI-compatible payload (flat params, no 'options' wrapper)
    payload = {
        "messages": truncated_messages,
        "stream": False,
        "max_tokens": 2048,
        "temperature": 0.95,
        "top_p": 0.95,
    }

    # Add tools if provided
    if tools:
        payload["tools"] = tools
        payload["parallel_tool_calls"] = True
        print(f"[client.py][chat_completion_with_tools] Sending {len(tools)} tools to llama-server (parallel_tool_calls=True)")
        print(json.dumps(payload['tools'][0], indent=2))
        print(f"[client.py][chat_completion_with_tools] Tool count: {len(payload['tools'])}")

    print(f"[client.py][chat_completion_with_tools] ⚡ POST {url}")

    async with httpx.AsyncClient(timeout=600.0) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()

        response_data = response.json()
        tool_response = ToolCallResponse(response_data)

        # Log KV cache metrics (Phase 2 detailed monitoring)
        if tool_response.cache_tokens > 0 or tool_response.prompt_tokens > 0:
            tool_response.log_cache_metrics()

        if tool_response.has_tool_calls():
            print(f"[client.py][chat_completion_with_tools] ✓ Model returned {len(tool_response.tool_calls)} tool call(s)")
            for tool_call in tool_response.tool_calls:
                print(f"  - {tool_call.get('function', {}).get('name')}")
        else:
            print(f"[client.py][chat_completion_with_tools] Model responded directly (no tool calls)")

        return tool_response


def preflight_check(messages: List[Dict], tools: Optional[List[Dict]] = None) -> tuple:
    """
    Final safety check before sending to LLM.
    If total tokens exceed context window minus response budget, trim oldest
    conversation messages until it fits.

    Returns:
        (messages, was_trimmed) — possibly trimmed message list and flag
    """
    max_context = getattr(config, 'OLLAMA_CONTEXT_WINDOW', 32768)
    response_budget = getattr(config, 'RESPONSE_GENERATION_BUDGET', 2000)
    limit = max_context - response_budget

    total = TokenCounter.count_message_tokens(messages)
    if tools:
        total += TokenCounter.count_tokens(json.dumps(tools))

    if total <= limit:
        return messages, False

    # Over budget — trim non-system messages from the front (oldest conversation first)
    print(f"[client.py] ⚠ PREFLIGHT: {total:,} tokens exceeds limit {limit:,}. Trimming oldest messages...")
    trimmed = list(messages)
    while total > limit and len(trimmed) > 2:
        # Keep first message (system) and last message (current user/tool)
        removed = trimmed.pop(1)
        removed_role = removed.get('role', '?')
        total = TokenCounter.count_message_tokens(trimmed)
        if tools:
            total += TokenCounter.count_tokens(json.dumps(tools))
        print(f"[client.py]   Dropped {removed_role} message, now {total:,} tokens ({len(trimmed)} msgs)")

    print(f"[client.py] ⚠ PREFLIGHT: Trimmed to {total:,} tokens, {len(trimmed)} messages")
    return trimmed, True


async def chat_completion_stream(
    messages: List[Dict[str, str]]
) -> AsyncIterator[str]:
    """
    Send chat completion request to llama-server and stream response (SSE format)

    This is used for:
    1. Regular chat without tools
    2. SECOND call after tool results are added to conversation

    Args:
        messages: List of message dicts with "role" and "content" keys

    Yields:
        Chunks of response text as they arrive
    """

    # Preflight: ensure we don't overflow the context window
    messages, was_trimmed = preflight_check(messages)
    if was_trimmed:
        print(f"[client.py][chat_completion_stream] ⚠ Context was trimmed by preflight check")

    url = f"{config.OLLAMA_BASE_URL}/v1/chat/completions"
    prompt_compare(messages)

    # OpenAI-compatible payload
    payload = {
        "messages": messages,
        "stream": True,
        "max_tokens": 4096,
        "temperature": 0.95,
        "top_p": 0.95,
    }

    # SGLang needs stream_options to include usage in final chunk
    if _get_backend() == 'sglang':
        payload["stream_options"] = {"include_usage": True}

    print(f"[client.py][chat_completion_stream] POST {url} (backend: {_get_backend()})")
    print(f"[client.py][chat_completion_stream] Sending {len(messages)} messages")

    try:
        async with httpx.AsyncClient(timeout=600.0) as client:
            async with client.stream("POST", url, json=payload) as response:
                print(f"[client.py][chat_completion_stream] Response status: {response.status_code}")
                response.raise_for_status()

                chunk_count = 0
                final_timings = None
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue

                    # SSE format: lines start with "data: "
                    if line.startswith("data: "):
                        json_str = line[6:]  # Remove "data: " prefix

                        # Handle stream end marker
                        if json_str == "[DONE]":
                            break

                        try:
                            chunk = json.loads(json_str)
                            # OpenAI streaming format: choices[0].delta.content
                            choices = chunk.get("choices", [])
                            if choices:
                                delta = choices[0].get("delta", {})
                                # Yield reasoning content (thinking)
                                reasoning = delta.get("reasoning_content")
                                if reasoning:
                                    chunk_count += 1
                                    yield (reasoning, True)  # (text, is_thinking)
                                content = delta.get("content")
                                if content:
                                    chunk_count += 1
                                    yield (content, False)
                                # Capture timings from final chunk (has finish_reason)
                                if choices[0].get("finish_reason"):
                                    extracted = _extract_timings_from_stream_chunk(chunk)
                                    if extracted:
                                        final_timings = extracted
                            # SGLang may send usage in a separate final chunk (no choices)
                            if not choices:
                                extracted = _extract_timings_from_stream_chunk(chunk)
                                if extracted:
                                    final_timings = extracted
                        except json.JSONDecodeError as e:
                            print(f"[client.py][chat_completion_stream] JSON decode error: {e}")
                            continue

                # Yield timings as special dict at end (caller checks type)
                if final_timings:
                    cache_n = final_timings.get("cache_n", 0)
                    prompt_n = final_timings.get("prompt_n", 0)
                    total = cache_n + prompt_n
                    efficiency = (cache_n / total * 100) if total > 0 else 0
                    print(f"[client.py][chat_completion_stream] KV Cache: {cache_n:,} cached + {prompt_n:,} new = {total:,} tokens ({efficiency:.1f}%)")
                    yield {"__timings__": final_timings, "cache_n": cache_n, "prompt_n": prompt_n, "efficiency": efficiency}

                print(f"[client.py][chat_completion_stream] ✓ Streaming complete: {chunk_count} chunks")
    except httpx.HTTPStatusError as e:
        print(f"[client.py][chat_completion_stream] ✗ HTTP error: {e}")
        print(f"[client.py][chat_completion_stream] Response: {e.response.text if hasattr(e, 'response') else 'N/A'}")
        raise
    except Exception as e:
        print(f"[client.py][chat_completion_stream] ✗ Unexpected error: {e}")
        raise


class StreamingToolResponse:
    """Response from streaming chat that may contain tool calls (OpenAI-compatible)"""

    def __init__(self):
        self.content = ""
        self.tool_calls = []
        self.raw_message = {}
        self.cache_tokens = 0
        self.prompt_tokens = 0
        self.cache_efficiency = 0.0
        # Additional timing metrics for performance monitoring
        self.predicted_n = 0       # Generated tokens count
        self.predicted_ms = 0      # Generation time in ms
        self.prompt_ms = 0         # Prompt eval time in ms
        self.gen_tok_per_sec = 0.0 # Generation speed
        self.prompt_tok_per_sec = 0.0  # Prompt processing speed

    def has_tool_calls(self) -> bool:
        """Check if response contains tool calls"""
        return len(self.tool_calls) > 0

    def get_content(self) -> str:
        """Get accumulated text content"""
        return self.content


async def chat_completion_stream_with_tools(
    messages: List[Dict[str, str]],
    tools: Optional[List[Dict[str, Any]]] = None
) -> AsyncIterator[tuple[str, Optional[StreamingToolResponse]]]:
    """
    Send chat completion request to llama-server with tools and stream response (SSE)

    This enables INTERLEAVED tool calling - Iris can stream text, then decide
    to call tools, then stream more text based on tool results.

    Args:
        messages: List of message dicts with "role" and "content" keys
        tools: Optional list of tool definitions in OpenAI format

    Yields:
        Tuples of (text_chunk, final_response)
        - During streaming: (chunk, None)
        - At end: ("", StreamingToolResponse with tool_calls if any)
    """

    # Preflight: ensure we don't overflow the context window
    messages, was_trimmed = preflight_check(messages, tools)
    if was_trimmed:
        print(f"[client.py][chat_completion_stream_with_tools] ⚠ Context was trimmed by preflight check")

    url = f"{config.OLLAMA_BASE_URL}/v1/chat/completions"
    prompt_compare(messages)

    # OpenAI-compatible payload
    payload = {
        "messages": messages,
        "stream": True,
        "max_tokens": 4096,
        "temperature": 0.7,
    }

    # SGLang needs stream_options to include usage in final chunk
    if _get_backend() == 'sglang':
        payload["stream_options"] = {"include_usage": True}

    # Add tools if provided
    if tools:
        payload["tools"] = tools
        payload["parallel_tool_calls"] = True
        print(f"[client.py][chat_completion_stream_with_tools] Sending {len(tools)} tools (streaming, parallel_tool_calls=True)")

    print(f"[client.py][chat_completion_stream_with_tools] POST {url} (backend: {_get_backend()})")

    response_obj = StreamingToolResponse()
    chunk_count = 0
    content_chunks = 0
    final_timings = None

    async with httpx.AsyncClient(timeout=600.0) as client:
        async with client.stream("POST", url, json=payload) as response:
            response.raise_for_status()

            async for line in response.aiter_lines():
                line = line.strip()
                if not line:
                    continue

                # SSE format: lines start with "data: "
                if line.startswith("data: "):
                    json_str = line[6:]

                    if json_str == "[DONE]":
                        break

                    try:
                        chunk = json.loads(json_str)
                        chunk_count += 1

                        choices = chunk.get("choices", [])
                        if choices:
                            choice = choices[0]
                            delta = choice.get("delta", {})

                            # DEBUG: Log first few chunks
                            if chunk_count <= 3:
                                print(f"[client.py][DEBUG] Chunk {chunk_count}: {json.dumps(chunk)[:200]}")

                            # Stream reasoning content (thinking) as it arrives
                            reasoning = delta.get("reasoning_content")
                            if reasoning:
                                yield (reasoning, None, True)  # 3rd element = is_thinking

                            # Stream text content as it arrives
                            content = delta.get("content")
                            if content:
                                response_obj.content += content
                                content_chunks += 1
                                yield (content, None, False)

                            # Check for tool_calls in delta (streaming tool calls)
                            if "tool_calls" in delta:
                                # Accumulate tool calls from streaming chunks
                                for tc in delta["tool_calls"]:
                                    idx = tc.get("index", 0)
                                    # Extend list if needed
                                    while len(response_obj.tool_calls) <= idx:
                                        response_obj.tool_calls.append({"function": {"name": "", "arguments": ""}})
                                    # Merge data
                                    if "id" in tc:
                                        response_obj.tool_calls[idx]["id"] = tc["id"]
                                    if "type" in tc:
                                        response_obj.tool_calls[idx]["type"] = tc["type"]
                                    if "function" in tc:
                                        if "name" in tc["function"]:
                                            response_obj.tool_calls[idx]["function"]["name"] += tc["function"]["name"]
                                        if "arguments" in tc["function"]:
                                            response_obj.tool_calls[idx]["function"]["arguments"] += tc["function"]["arguments"]

                            # Store finish_reason and capture timings from final chunk
                            finish_reason = choice.get("finish_reason")
                            if finish_reason:
                                response_obj.raw_message["finish_reason"] = finish_reason
                                extracted = _extract_timings_from_stream_chunk(chunk)
                                if extracted:
                                    final_timings = extracted

                        # SGLang may send usage in a separate final chunk (no choices)
                        if not chunk.get("choices"):
                            extracted = _extract_timings_from_stream_chunk(chunk)
                            if extracted:
                                final_timings = extracted

                    except json.JSONDecodeError:
                        continue

    # Filter out incomplete tool calls
    response_obj.tool_calls = [tc for tc in response_obj.tool_calls if tc.get("function", {}).get("name")]

    # Store KV cache and timing metrics in response object
    if final_timings:

        response_obj.cache_tokens = final_timings.get("cache_n", 0)
        response_obj.prompt_tokens = final_timings.get("prompt_n", 0)
        total = response_obj.cache_tokens + response_obj.prompt_tokens
        response_obj.cache_efficiency = (response_obj.cache_tokens / total * 100) if total > 0 else 0

        # Additional timing metrics
        response_obj.predicted_n = final_timings.get("predicted_n", 0)
        response_obj.predicted_ms = final_timings.get("predicted_ms", 0)
        response_obj.prompt_ms = final_timings.get("prompt_ms", 0)

        # Calculate tokens/second - use direct values if available, otherwise calculate
        response_obj.gen_tok_per_sec = final_timings.get("predicted_per_second", 0)
        response_obj.prompt_tok_per_sec = final_timings.get("prompt_per_second", 0)

        # Fallback: calculate from ms if direct values not available
        if response_obj.gen_tok_per_sec == 0 and response_obj.predicted_ms > 0:
            response_obj.gen_tok_per_sec = response_obj.predicted_n / (response_obj.predicted_ms / 1000)
        if response_obj.prompt_tok_per_sec == 0 and response_obj.prompt_ms > 0:
            response_obj.prompt_tok_per_sec = response_obj.prompt_tokens / (response_obj.prompt_ms / 1000)

        print(f"[client.py][chat_completion_stream_with_tools] KV Cache: {response_obj.cache_tokens:,} cached + {response_obj.prompt_tokens:,} new = {total:,} tokens ({response_obj.cache_efficiency:.1f}%)")
        print(f"[client.py][chat_completion_stream_with_tools] Speed: {response_obj.gen_tok_per_sec:.1f} tok/s gen, {response_obj.prompt_tok_per_sec:.1f} tok/s prompt")

    print(f"[client.py][chat_completion_stream_with_tools] ✓ Stream complete: {chunk_count} chunks, {content_chunks} with content")

    if response_obj.tool_calls:
        print(f"[client.py][chat_completion_stream_with_tools] Detected {len(response_obj.tool_calls)} tool call(s)")
        for tc in response_obj.tool_calls:
            print(f"  - {tc.get('function', {}).get('name')}")

    # Yield final response object with tool calls (if any)
    yield ("", response_obj, False)

async def chat_completions(
    messages: List[Dict[str, str]],
    grammar_file: Optional[str] = None
) -> str:
    """
    Send chat completion request to llama-server - non-streaming bulk response

    This is used for:
    1. Memory tools and non-UI functions

    Args:
        messages: List of message dicts with "role" and "content" keys
        grammar_file: Optional path to GBNF grammar file for constrained output
                     (Note: grammar support depends on llama-server configuration)

    Returns:
        Complete text response
    """

    url = f"{config.OLLAMA_BASE_URL}/v1/chat/completions"
    prompt_compare(messages)

    # OpenAI-compatible payload
    payload = {
        "messages": messages,
        "stream": False,
        "max_tokens": 2048,
        "temperature": 0.1,
    }

    # Add grammar if provided (llama-server only; SGLang doesn't support GBNF)
    if grammar_file and _get_backend() != 'sglang':
        with open(grammar_file, 'r') as f:
            payload["grammar"] = f.read()

    print(f"[client.py][chat_completions] POST {url} (backend: {_get_backend()})")

    async with httpx.AsyncClient(timeout=600.0) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()

        data = response.json()

        # Log KV cache metrics via backend-aware extraction
        timings = _extract_timings_from_response(data)
        cache_n = timings.get("cache_n", 0)
        if cache_n > 0:
            print(f"[client.py][chat_completions] " + Style.BRIGHT + Fore.GREEN +
                  f"KV Cache: {cache_n} tokens reused" + Style.RESET_ALL)

        # OpenAI format: choices[0].message.content
        choices = data.get("choices", [])
        if choices:
            return choices[0].get("message", {}).get("content", "")
        return ""
