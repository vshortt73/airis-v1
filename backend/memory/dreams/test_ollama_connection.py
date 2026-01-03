#!/usr/bin/env python3
"""
Quick test to verify Ollama services for dream system
"""
import asyncio
import httpx
import json

async def test_ollama(url, model_name, test_name):
    """Test if an Ollama service is responding"""
    print(f"\n=== Testing {test_name} ===")
    print(f"URL: {url}")
    print(f"Model: {model_name}")

    endpoint = f"{url}/api/chat"
    payload = {
        "model": model_name,
        "messages": [
            {"role": "user", "content": "Say 'test successful' and nothing else."}
        ],
        "stream": False,
        "options": {
            "num_ctx": 8192,
            "temperature": 0.1
        }
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            print("Sending request...")
            response = await client.post(endpoint, json=payload)
            response.raise_for_status()
            data = response.json()
            content = data.get('message', {}).get('content', '')

            print(f"✓ Response received: {content[:100]}")

            # Check response metrics
            total_duration = data.get('total_duration', 0) / 1e9  # nanoseconds to seconds
            load_duration = data.get('load_duration', 0) / 1e9
            prompt_eval_count = data.get('prompt_eval_count', 0)
            eval_count = data.get('eval_count', 0)

            print(f"  Total time: {total_duration:.2f}s")
            print(f"  Load time: {load_duration:.2f}s")
            print(f"  Prompt tokens: {prompt_eval_count}")
            print(f"  Response tokens: {eval_count}")

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
    print("Dream System Ollama Connection Test")
    print("=" * 60)

    # Test Freud (GPU 0)
    freud_ok = await test_ollama(
        url="http://localhost:11434",
        model_name="qwen2.5:14b",
        test_name="Freud (GPU 0)"
    )

    # Test Iris (GPU 1)
    iris_ok = await test_ollama(
        url="http://localhost:11435",
        model_name="qwen3:32b",
        test_name="Iris (GPU 1)"
    )

    print("\n" + "=" * 60)
    print("Test Results:")
    print("=" * 60)
    print(f"Freud (GPU 0): {'✓ PASS' if freud_ok else '✗ FAIL'}")
    print(f"Iris (GPU 1):  {'✓ PASS' if iris_ok else '✗ FAIL'}")

    if freud_ok and iris_ok:
        print("\n✓ All services ready for dream creation!")
        return 0
    else:
        print("\n✗ Some services failed - check errors above")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
