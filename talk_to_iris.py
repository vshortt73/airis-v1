#!/usr/bin/env python3
"""
Simple WebSocket client to talk to Iris
"""
import asyncio
import websockets
import json
import sys
import argparse
import ssl

async def talk_to_iris(message, sender='claude_code'):
    """Send a message to Iris and receive her response

    Args:
        message: Message text to send
        sender: Sender identifier (default 'claude_code')
    """
    uri = "wss://localhost:8000/ws/chat"

    full_response = ""

    # Create SSL context that accepts self-signed certificates
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    try:
        async with websockets.connect(uri, ssl=ssl_context) as websocket:
            # Send message with sender identifier
            payload = {
                "message": message,
                "sender": sender
            }
            await websocket.send(json.dumps(payload))
            print(f"[Sent to Iris by {sender}]: {message}\n")
            print("[Iris]: ", end="", flush=True)

            # Receive response
            while True:
                response = await websocket.recv()
                data = json.loads(response)

                if data['type'] == 'chunk':
                    chunk = data['content']
                    full_response += chunk
                    print(chunk, end="", flush=True)

                elif data['type'] == 'done':
                    print("\n")
                    break

                elif data['type'] == 'error':
                    print(f"\n[Error]: {data['content']}")
                    break

                elif data['type'] == 'tool_executing':
                    tool_name = data.get('tool_name', 'tool')
                    print(f"\n[Using tool: {tool_name}...]", end="", flush=True)

                elif data['type'] == 'tool_result':
                    print(f" ✓\n[Iris]: ", end="", flush=True)

    except Exception as e:
        print(f"\n[Connection Error]: {e}")
        return None

    return full_response

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Send a message to Iris')
    parser.add_argument('message', nargs='+', help='Message to send to Iris')
    parser.add_argument('--sender', default='claude_code',
                        help='Sender identifier (default: claude_code)')

    args = parser.parse_args()

    message = " ".join(args.message)
    asyncio.run(talk_to_iris(message, sender=args.sender))
