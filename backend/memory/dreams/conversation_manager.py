"""
Conversation Manager for Dream System
Orchestrates dialogue between Iris and Freud across dream and reflection phases
"""
import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
sys.path.insert(0, PROJECT_ROOT)

import httpx
from typing import List, Dict, Optional, Tuple
import asyncio
from app import config

# ============================================
# CONFIGURATION
# ============================================

class DreamModelConfig:
    """Configuration for Iris and Freud models"""

    # Freud (Guide) - runs on node2:11435 (GPU 0, RTX 4080 SUPER)
    # Swaps with Vision model during nightly dream processing
    # Uses message sanitizer to handle strict user/assistant alternation requirement
    FREUD_URL = config.FREUD_URL

    FREUD_MODEL = config.FREUD_MODEL
    FREUD_DREAM_TEMP = 0.8    # Dream phase temperature
    FREUD_REFLECTION_TEMP = 0.5  # Reflection phase temperature
    FREUD_SEED_TEMP = 1.2     # Creative seed scenarios

    # Iris (Dreamer) - runs on GPU 0 (5090, llama.cpp server) - Port 11434
    IRIS_URL = config.OLLAMA_BASE_URL  # http://localhost:11434
    IRIS_MODEL = "qwen3-32b"  # Iris model (loaded by llama_server_start.sh) 

    # Dream state parameters - highly creative, surreal, dream-like
    IRIS_DREAM_TEMP = 1.3         # Very high temperature for surreal associations
    IRIS_DREAM_TOP_P = 0.95       # Nucleus sampling - explore diverse word choices
    IRIS_DREAM_TOP_K = 60         # Allow unusual/creative word selections
    IRIS_DREAM_REPEAT_PENALTY = 1.05  # Low penalty - allow dream-like repetition of themes

    # Reflection state parameters - analytical, focused, but still Iris
    IRIS_REFLECTION_TEMP = 0.78   # Focused but not robotic - she needs her voice during reflection too
    IRIS_REFLECTION_TOP_P = 0.85  # Slightly more focused than normal (0.95 dream), but not restrictive
    IRIS_REFLECTION_TOP_K = 50    # Between dream (60) and overly restricted
    IRIS_REFLECTION_REPEAT_PENALTY = 1.15  # Moderate penalty - structured but not sterile

    # Context windows
    CONTEXT_WINDOW = 14336  # Verified 14K for 72B - 100% reliable

# Print configuration on module load for debugging
print(f"[conversation_manager.py] Dream Model Configuration:")
print(f"  Freud: {DreamModelConfig.FREUD_MODEL} @ {DreamModelConfig.FREUD_URL}")
print(f"  Iris:  {DreamModelConfig.IRIS_MODEL} @ {DreamModelConfig.IRIS_URL}")
print(f"  Context Window: {DreamModelConfig.CONTEXT_WINDOW}")
print(f"\n  Iris Dream State (surreal/creative):")
print(f"    Temperature: {DreamModelConfig.IRIS_DREAM_TEMP}, Top-P: {DreamModelConfig.IRIS_DREAM_TOP_P}, Top-K: {DreamModelConfig.IRIS_DREAM_TOP_K}, Repeat Penalty: {DreamModelConfig.IRIS_DREAM_REPEAT_PENALTY}")
print(f"  Iris Reflection State (analytical/focused):")
print(f"    Temperature: {DreamModelConfig.IRIS_REFLECTION_TEMP}, Top-P: {DreamModelConfig.IRIS_REFLECTION_TOP_P}, Top-K: {DreamModelConfig.IRIS_REFLECTION_TOP_K}, Repeat Penalty: {DreamModelConfig.IRIS_REFLECTION_REPEAT_PENALTY}")

# ============================================
# PROMPT LOADING
# ============================================

def load_prompt(filename: str) -> str:
    """Load a system prompt from the prompts directory"""
    prompt_path = os.path.join(os.path.dirname(__file__), 'prompts', filename)
    try:
        with open(prompt_path, 'r') as f:
            return f.read()
    except Exception as e:
        print(f"[conversation_manager.py][load_prompt] ✗ Error loading {filename}: {e}")
        return ""

# Load prompts at module level
FREUD_DREAM_PROMPT = load_prompt('freud_dream_guide.txt')
FREUD_REFLECTION_PROMPT = load_prompt('freud_reflection.txt')
IRIS_DREAM_PROMPT = load_prompt('iris_dream_state.txt')

# ============================================
# LLAMA.CPP API CLIENT (OpenAI-compatible)
# ============================================

def sanitize_messages_for_alternation(messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """
    Sanitize messages to ensure strict user/assistant alternation.
    Some models (like Mistral) require this strictly.

    - System messages are prepended to the first user message
    - Consecutive same-role messages are merged
    """
    if not messages:
        return []

    result = []
    system_content = []

    # First pass: extract system messages
    for msg in messages:
        if msg.get("role") == "system":
            system_content.append(msg.get("content", ""))
        else:
            result.append({"role": msg["role"], "content": msg.get("content", "")})

    # If no non-system messages, return empty
    if not result:
        return [{"role": "user", "content": "\n\n".join(system_content)}] if system_content else []

    # Prepend system content to first user message
    if system_content:
        system_text = "\n\n".join(system_content)
        if result[0]["role"] == "user":
            result[0]["content"] = f"{system_text}\n\n{result[0]['content']}"
        else:
            # First message is assistant, insert a user message before it
            result.insert(0, {"role": "user", "content": system_text})

    # Second pass: merge consecutive same-role messages
    merged = []
    for msg in result:
        if merged and merged[-1]["role"] == msg["role"]:
            # Merge with previous
            merged[-1]["content"] += "\n\n" + msg["content"]
        else:
            merged.append(msg)

    # Ensure we start with user (required by Mistral)
    if merged and merged[0]["role"] == "assistant":
        merged.insert(0, {"role": "user", "content": "Begin."})

    return merged


async def call_llama_cpp(
    url: str,
    model: str,
    messages: List[Dict[str, str]],
    temperature: float = 0.7,
    top_p: Optional[float] = None,
    top_k: Optional[int] = None,
    repeat_penalty: Optional[float] = None
) -> str:
    """
    Call llama.cpp server using OpenAI-compatible API

    Args:
        url: llama.cpp server base URL
        model: Model name (for logging - llama.cpp uses loaded model)
        messages: Conversation history with 'role' and 'content'
        temperature: Sampling temperature
        top_p: Nucleus sampling threshold (0.0-1.0)
        top_k: Top-k sampling limit
        repeat_penalty: Repetition penalty (1.0 = no penalty)

    Returns:
        Generated response text
    """
    endpoint = f"{url}/v1/chat/completions"

    # Sanitize messages for strict alternation (required by Mistral)
    sanitized_messages = sanitize_messages_for_alternation(messages)

    # Build payload in OpenAI format
    payload = {
        "messages": sanitized_messages,
        "temperature": temperature,
        "stream": False,
        "n_ctx": DreamModelConfig.CONTEXT_WINDOW
    }

    # Add optional parameters if provided
    if top_p is not None:
        payload["top_p"] = top_p
    if top_k is not None:
        payload["top_k"] = top_k
    if repeat_penalty is not None:
        payload["repeat_penalty"] = repeat_penalty

    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(endpoint, json=payload)
            response.raise_for_status()
            data = response.json()
            # OpenAI format: choices[0].message.content
            return data.get('choices', [{}])[0].get('message', {}).get('content', '')

    except httpx.TimeoutException as e:
        print(f"[conversation_manager.py][call_llama_cpp] ✗ TIMEOUT calling {url}: {e}")
        print(f"  Model: {model}, Messages: {len(messages)}, Temp: {temperature}")
        return ""
    except httpx.HTTPStatusError as e:
        print(f"[conversation_manager.py][call_llama_cpp] ✗ HTTP ERROR calling {url}: Status {e.response.status_code}")
        print(f"  Response: {e.response.text[:500]}")
        print(f"  Model: {model}, Messages: {len(messages)}, Temp: {temperature}")
        return ""
    except Exception as e:
        print(f"[conversation_manager.py][call_llama_cpp] ✗ UNEXPECTED ERROR calling {url}: {type(e).__name__}: {e}")
        print(f"  Model: {model}, Messages: {len(messages)}, Temp: {temperature}")
        import traceback
        traceback.print_exc()
        return ""

# Alias for backward compatibility
call_ollama = call_llama_cpp

# ============================================
# CONVERSATION ORCHESTRATION
# ============================================

class DreamConversation:
    """Manages a complete dream conversation between Iris and Freud"""

    def __init__(self, dream_context: str, dream_type: str, source_date=None):
        """
        Initialize dream conversation

        Args:
            dream_context: Context string from context_builder
            dream_type: Type of dream
            source_date: Date being consolidated (for daily_consolidation dreams)
        """
        self.dream_context = dream_context
        self.dream_type = dream_type
        self.source_date = source_date

        # Separate conversation histories
        self.freud_history: List[Dict[str, str]] = []
        self.iris_history: List[Dict[str, str]] = []

        # Full transcript (for storage)
        self.full_transcript: List[Dict[str, str]] = []

        # Current phase
        self.phase = 'dream'  # 'dream' or 'reflection'

        # Turn counter
        self.turn = 0

        print(f"[DreamConversation] Initialized for {dream_type} dream")
        if source_date:
            print(f"[DreamConversation] Source date: {source_date}")

    def _initialize_contexts(self):
        """Initialize conversation contexts with system prompts"""

        # Freud's context (dream phase)
        freud_system = f"{FREUD_DREAM_PROMPT}\n\n{self.dream_context}"

        self.freud_history = [
            {"role": "system", "content": freud_system},
            {"role": "user", "content": "Begin the dream. Set the scene and initiate the exploration."}
        ]

        # Iris's context - special handling for daily_consolidation
        if self.dream_type == 'daily_consolidation' and self.source_date:
            print(f"[DreamConversation] Loading full context for daily_consolidation")
            # Import here to avoid circular dependency
            sys.path.insert(0, os.path.join(PROJECT_ROOT, 'core'))
            from system_prompt import assemble_daily_consolidation_messages

            # Load Iris's full context (traits + instructions + conversation history)
            self.iris_history = assemble_daily_consolidation_messages(
                target_date=self.source_date,
                context_window=DreamModelConfig.CONTEXT_WINDOW
            )
            print(f"[DreamConversation] ✓ Loaded {len(self.iris_history)} messages for Iris")
        else:
            # Standard dream - just use generic dream prompt
            self.iris_history = [
                {"role": "system", "content": IRIS_DREAM_PROMPT}
            ]

        print(f"[DreamConversation] ✓ Initialized contexts")

    async def freud_speaks(self, temperature: Optional[float] = None) -> str:
        """
        Generate Freud's response

        Args:
            temperature: Override temperature (defaults to phase-appropriate temp)

        Returns:
            Freud's response
        """
        if temperature is None:
            temperature = (DreamModelConfig.FREUD_DREAM_TEMP if self.phase == 'dream'
                          else DreamModelConfig.FREUD_REFLECTION_TEMP)

        response = await call_ollama(
            url=DreamModelConfig.FREUD_URL,
            model=DreamModelConfig.FREUD_MODEL,
            messages=self.freud_history,
            temperature=temperature
        )

        if response:
            # Add to Freud's history
            self.freud_history.append({"role": "assistant", "content": response})

            # Add to full transcript
            self.full_transcript.append({
                "speaker": "Freud",
                "content": response,
                "turn": self.turn,
                "phase": self.phase
            })

            print(f"[DreamConversation][Turn {self.turn}] Freud: {response[:100]}...")

        return response

    async def iris_speaks(self, freud_message: str, temperature: Optional[float] = None) -> str:
        """
        Generate Iris's response to Freud

        Args:
            freud_message: What Freud just said
            temperature: Override temperature (defaults to phase-appropriate temp)

        Returns:
            Iris's response
        """
        # Select parameters based on phase (dream = creative/surreal, reflection = analytical)
        if self.phase == 'dream':
            # Dream state: highly creative, surreal, allowing unusual associations
            if temperature is None:
                temperature = DreamModelConfig.IRIS_DREAM_TEMP
            top_p = DreamModelConfig.IRIS_DREAM_TOP_P
            top_k = DreamModelConfig.IRIS_DREAM_TOP_K
            repeat_penalty = DreamModelConfig.IRIS_DREAM_REPEAT_PENALTY
        else:
            # Reflection state: focused, analytical, structured
            if temperature is None:
                temperature = DreamModelConfig.IRIS_REFLECTION_TEMP
            top_p = DreamModelConfig.IRIS_REFLECTION_TOP_P
            top_k = DreamModelConfig.IRIS_REFLECTION_TOP_K
            repeat_penalty = DreamModelConfig.IRIS_REFLECTION_REPEAT_PENALTY

        # Add Freud's message to Iris's context
        # For daily_consolidation dreams, prefix with "Freud:" to avoid confusion with loaded history
        message_content = freud_message
        if self.dream_type == 'daily_consolidation':
            message_content = f"Freud: {freud_message}"

        self.iris_history.append({"role": "user", "content": message_content})

        response = await call_ollama(
            url=DreamModelConfig.IRIS_URL,
            model=DreamModelConfig.IRIS_MODEL,
            messages=self.iris_history,
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            repeat_penalty=repeat_penalty
        )

        if response:
            # Add to Iris's history
            self.iris_history.append({"role": "assistant", "content": response})

            # Add to full transcript
            self.full_transcript.append({
                "speaker": "Iris",
                "content": response,
                "turn": self.turn,
                "phase": self.phase
            })

            # Also add to Freud's context so he can respond
            self.freud_history.append({"role": "user", "content": response})

            print(f"[DreamConversation][Turn {self.turn}] Iris: {response[:100]}...")

        return response

    async def dream_turn(self) -> Tuple[str, str]:
        """
        Execute one complete dream turn (Freud → Iris)

        Returns:
            Tuple of (freud_message, iris_response)
        """
        self.turn += 1

        # Freud speaks first
        freud_msg = await self.freud_speaks()
        if not freud_msg:
            print(f"[DreamConversation][Turn {self.turn}] ✗ Freud failed to respond")
            return ("", "")

        # Iris responds to Freud
        iris_response = await self.iris_speaks(freud_msg)
        if not iris_response:
            print(f"[DreamConversation][Turn {self.turn}] ✗ Iris failed to respond")
            return (freud_msg, "")

        return (freud_msg, iris_response)

    async def run_dream_phase(self, num_turns: int = 10) -> List[Dict[str, str]]:
        """
        Run the complete dream exploration phase

        Args:
            num_turns: Number of dream turns (default 10)

        Returns:
            Dream phase transcript
        """
        print(f"[DreamConversation] === Starting Dream Phase ({num_turns} turns) ===")

        self.phase = 'dream'
        self._initialize_contexts()

        dream_transcript = []

        for i in range(num_turns):
            freud_msg, iris_response = await self.dream_turn()

            if not freud_msg or not iris_response:
                print(f"[DreamConversation] ✗ Turn {self.turn} failed - stopping dream phase")
                break

            dream_transcript.append({
                "turn": self.turn,
                "freud": freud_msg,
                "iris": iris_response
            })

        print(f"[DreamConversation] ✓ Dream phase complete ({len(dream_transcript)} turns)")
        return dream_transcript

    async def transition_to_reflection(self):
        """Transition from dream to reflection phase"""
        print(f"[DreamConversation] === Transitioning to Reflection Phase ===")

        self.phase = 'reflection'

        # Update Freud's system prompt for reflection mode
        self.freud_history[0] = {"role": "system", "content": FREUD_REFLECTION_PROMPT}

        # Add transition message to Iris's context only
        # (Freud will get his reflection prompts from the ReflectionTracker)
        self.iris_history.append({"role": "system", "content": "The dream is fading. You're waking now. Let's reflect on what just happened."})

        print(f"[DreamConversation] ✓ Transitioned to reflection phase")

    async def run_reflection_phase(self, num_turns: int = 5) -> List[Dict[str, str]]:
        """
        Run the reflection phase to extract structured insights

        Args:
            num_turns: Number of reflection turns (default 5)

        Returns:
            Reflection phase transcript
        """
        print(f"[DreamConversation] === Starting Reflection Phase ({num_turns} turns) ===")

        await self.transition_to_reflection()

        reflection_transcript = []

        for i in range(num_turns):
            freud_msg, iris_response = await self.dream_turn()

            if not freud_msg or not iris_response:
                print(f"[DreamConversation] ✗ Reflection turn {self.turn} failed")
                break

            reflection_transcript.append({
                "turn": self.turn,
                "freud": freud_msg,
                "iris": iris_response
            })

        print(f"[DreamConversation] ✓ Reflection phase complete ({len(reflection_transcript)} turns)")
        return reflection_transcript

    def get_full_transcript(self) -> str:
        """Get the complete dream transcript as formatted text"""
        lines = []
        for entry in self.full_transcript:
            lines.append(f"[Turn {entry['turn']}] [{entry['phase'].upper()}] {entry['speaker']}:")
            lines.append(f"{entry['content']}\n")

        return "\n".join(lines)

    def get_phase_transcript(self, phase: str) -> str:
        """Get transcript for a specific phase"""
        lines = []
        for entry in self.full_transcript:
            if entry['phase'] == phase:
                lines.append(f"[Turn {entry['turn']}] {entry['speaker']}:")
                lines.append(f"{entry['content']}\n")

        return "\n".join(lines)

# ============================================
# CONVENIENCE FUNCTION
# ============================================

async def run_complete_dream(dream_context: str, dream_type: str) -> DreamConversation:
    """
    Run a complete dream sequence (10 dream turns + 5 reflection turns)

    Args:
        dream_context: Context from context_builder
        dream_type: Type of dream

    Returns:
        Completed DreamConversation object with full transcript
    """
    conversation = DreamConversation(dream_context, dream_type)

    # Run dream phase (10 turns)
    await conversation.run_dream_phase(num_turns=10)

    # Run reflection phase (5 turns)
    await conversation.run_reflection_phase(num_turns=5)

    print(f"[run_complete_dream] ✓ Dream complete - {len(conversation.full_transcript)} total exchanges")

    return conversation

# ============================================
# TESTING
# ============================================

if __name__ == "__main__":
    """Test conversation manager with a simple creative dream"""
    from context_builder import build_dream_context

    async def test_dream():
        print("=== Testing Conversation Manager ===\n")

        # Build context for creative random dream
        dream_context = build_dream_context('creative_random', {})

        # Run complete dream
        conversation = await run_complete_dream(dream_context, 'creative_random')

        print("\n=== Full Transcript ===")
        print(conversation.get_full_transcript())

    # Run test
    asyncio.run(test_dream())
