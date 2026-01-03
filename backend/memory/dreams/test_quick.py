#!/usr/bin/env python3
"""Quick test of dream system components"""
import os
import sys

# Set up paths
PROJECT_ROOT = '/iris-v3'
sys.path.insert(0, PROJECT_ROOT)

print("Importing modules...")
import asyncio

print("Importing conversation manager...")
from backend.memory.dreams.conversation_manager import DreamConversation, call_ollama
print("Imports successful!")

async def test_ollama_connection():
    """Test basic Ollama connectivity"""
    print("=== Testing Ollama Connections ===\n")

    # Test Freud (main Ollama)
    print("Testing Freud (http://localhost:11434 - qwen2.5:14b)...")
    print("Creating messages...")
    messages = [{"role": "user", "content": "Say hello in 5 words"}]
    print("Calling Ollama...")
    response = await call_ollama(
        "http://localhost:11434",
        "qwen2.5:14b",
        messages,
        temperature=0.7
    )
    print(f"Freud response received: {len(response)} chars")
    print(f"Freud: {response}\n")

    # Test Iris (vision Ollama)
    print("Testing Iris (http://localhost:11435 - qwen3:32b)...")
    response = await call_ollama(
        "http://localhost:11435",
        "qwen3:32b",
        messages,
        temperature=0.7
    )
    print(f"Iris: {response}\n")

    print("✓ Both models responding!\n")

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
        await test_ollama_connection()
        await test_single_turn()
        print("✓ All tests passed!")
    except Exception as e:
        print(f"✗ Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
