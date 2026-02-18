#!/usr/bin/env python3
"""
Quick test to verify llama.cpp services for dream system

Architecture:
- Iris: localhost:11434 (local RTX 5090, qwen3-32b)
- Freud: node2:11435 (remote RTX 4080, gemma-3-4b) - swaps with Vision at night
"""
import asyncio
import httpx
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
sys.path.insert(0, PROJECT_ROOT)

from app import config

async def test_llama_server(url, test_name):
    """Test if a llama.cpp server is responding (OpenAI-compatible API)"""
    print(f"\n=== Testing {test_name} ===")
    print(f"URL: {url}")

    endpoint = f"{url}/v1/chat/completions"
    payload = {
        "messages": [
            {"role": "user", "content": "Say 'test successful' and nothing else."}
        ],
        "temperature": 0.1,
        "stream": False
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            print("Sending request...")
            response = await client.post(endpoint, json=payload)
            response.raise_for_status()
            data = response.json()
            content = data.get('choices', [{}])[0].get('message', {}).get('content', '')

            print(f"✓ Response received: {content[:100]}")
            return True

    except httpx.TimeoutException as e:
        print(f"✗ TIMEOUT: {e}")
        return False
    except httpx.HTTPStatusError as e:
        print(f"✗ HTTP ERROR: Status {e.response.status_code}")
        print(f"  Response: {e.response.text[:500]}")
        return False
    except Exception as e:
        print(f"✗ ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    print("=" * 60)
    print("Dream System llama.cpp Connection Test")
    print("=" * 60)

    # Get URLs from config
    iris_url = config.OLLAMA_BASE_URL  # localhost:11434
    freud_url = config.FREUD_URL

    print(f"\nConfiguration:")
    print(f"  Iris URL: {iris_url}")
    print(f"  Freud URL: {freud_url}")

    # Test Iris (local RTX 5090)
    iris_ok = await test_llama_server(
        url=iris_url,
        test_name="Iris (local RTX 5090, qwen3-32b)"
    )

    # Test Freud (remote node2 RTX 4080)
    freud_ok = await test_llama_server(
        url=freud_url,
        test_name="Freud (node2 RTX 4080, gemma-3-4b)"
    )

    print("\n" + "=" * 60)
    print("Test Results:")
    print("=" * 60)
    print(f"Iris (localhost:11434):  {'✓ PASS' if iris_ok else '✗ FAIL'}")
    print(f"Freud (node2:11435):     {'✓ PASS' if freud_ok else '✗ FAIL'}")

    if iris_ok and freud_ok:
        print("\n✓ All services ready for dream creation!")
        return 0
    else:
        print("\n✗ Some services failed - check errors above")
        if not freud_ok:
            print("  Note: Freud only runs during nightly dreams (swaps with Vision)")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
