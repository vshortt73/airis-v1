#!/usr/bin/env python3
"""
Quick test of dream system components

Architecture:
- Iris: localhost:11434 (local RTX 5090, qwen3-32b)
- Freud: node2:11435 (remote RTX 4080, gemma-3-4b) - swaps with Vision at night
"""
import os
import sys

# Set up paths
PROJECT_ROOT = '/iris-v3'
sys.path.insert(0, PROJECT_ROOT)

print("Importing modules...")
import asyncio

print("Importing conversation manager...")
from backend.memory.dreams.conversation_manager import DreamConversation, DreamModelConfig, call_ollama
from app import config
print("Imports successful!")

async def test_llama_connections():
    """Test basic llama.cpp connectivity"""
    print("=== Testing llama.cpp Connections ===\n")

    messages = [{"role": "user", "content": "Say hello in 5 words"}]

    # Test Iris (local llama.cpp)
    iris_url = config.OLLAMA_BASE_URL
    print(f"Testing Iris ({iris_url})...")
    response = await call_ollama(
        iris_url,
        DreamModelConfig.IRIS_MODEL,
        messages,
        temperature=0.7
    )
    print(f"Iris response received: {len(response)} chars")
    print(f"Iris: {response}\n")

    # Test Freud (remote node2)
    freud_url = DreamModelConfig.FREUD_URL
    print(f"Testing Freud ({freud_url})...")
    print("Note: Freud only available during nightly dreams (swaps with Vision)")
    try:
        response = await call_ollama(
            freud_url,
            DreamModelConfig.FREUD_MODEL,
            messages,
            temperature=0.7
        )
        print(f"Freud: {response}\n")
        print("✓ Both models responding!\n")
    except Exception as e:
        print(f"Freud not available (expected during daytime): {e}\n")
        print("✓ Iris responding! (Freud only available at night)\n")

async def test_single_turn():
    """Test a single dream turn"""
    print("=== Testing Single Dream Turn ===\n")

    conversation = DreamConversation(
        dream_context="Test creative dream",
        dream_type="creative_random"
    )

    conversation._initialize_contexts()

    print("Executing one dream turn...\n")
    freud_msg, iris_response = await conversation.dream_turn()

    print(f"Freud: {freud_msg[:100]}...")
    print(f"Iris: {iris_response[:100]}...\n")

    print("✓ Single turn successful!\n")

async def main():
    try:
        await test_llama_connections()
        await test_single_turn()
        print("✓ All tests passed!")
    except Exception as e:
        print(f"✗ Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
