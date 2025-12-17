"""
Chat WebSocket API route with comprehensive logging
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, PROJECT_ROOT)
from core.system_prompt import assemble_full_context
from ollama.client import chat_completion_stream

router = APIRouter(tags=["chat"])

active_conversation = None

def set_active_conversation(conv):
    """Set the active conversation instance"""
    global active_conversation
    active_conversation = conv

@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """WebSocket endpoint for chat with comprehensive logging"""
    await websocket.accept()
    
    print(f"[routes_chat.py][websocket_chat] WebSocket connected, Conversation History now has {active_conversation.get_message_count()} messages")
    
    try:
        while True:
            # Receive message from client (may include images)
            data = await websocket.receive_json()
            user_message = data.get("message", "").strip()
            user_images = data.get("images", [])  # List of base64 images
            
            if not user_message and not user_images:
                await websocket.send_json({
                    "type": "error",
                    "content": "Empty message"
                })
                continue
            
            print(f"[routes_chat.py][websocket_chat] ━━━━━━ NEW TURN ━━━━━━")
            print(f"[routes_chat.py][websocket_chat] User message: '{user_message[:50]}...'")
            if user_images:
                print(f"[routes_chat.py][websocket_chat] User attached {len(user_images)} image(s)")
            
            # Add user message with images to history (triggers save to DB)
            active_conversation.add_user_message(
                user_message,
                images=user_images if user_images else None
            )
            
            # Assemble full context with image loading
            all_messages, budget = assemble_full_context(active_conversation)
            
            print(f"[routes_chat.py][websocket_chat] ━━ CONTEXT READY ━━")
            print(f"[routes_chat.py][websocket_chat] Messages: {budget['message_count']}, Images: {budget['image_count']}")
            
            # Send acknowledgment
            await websocket.send_json({
                "type": "start",
                "message_count": active_conversation.get_message_count()
            })
            
            print(f"[routes_chat.py][websocket_chat] ━━ STREAMING TO UI ━━")
            
            # Stream response from Ollama
            full_response = ""
            async for chunk in chat_completion_stream(all_messages):
                full_response += chunk
                await websocket.send_json({
                    "type": "chunk",
                    "content": chunk
                })
            
            print(f"[routes_chat.py][websocket_chat] ✓ Streaming complete ({len(full_response)} chars)")
            
            # Add complete response to history (triggers save to DB)
            active_conversation.add_assistant_message(full_response)
            
            # Send completion signal
            await websocket.send_json({
                "type": "done",
                "message_count": active_conversation.get_message_count()
            })
            
            print(f"[routes_chat.py][websocket_chat] ━━ TURN COMPLETE ━━")
            print(f"[routes_chat.py][websocket_chat] Conversation History now has {active_conversation.get_message_count()} messages")
            print(f"[routes_chat.py][websocket_chat] ━━━━━━━━━━━━━━━━━━━━━━")
            
    except WebSocketDisconnect:
        print("[routes_chat.py][websocket_chat] Client disconnected")
    except Exception as e:
        print(f"[routes_chat.py][websocket_chat] ✗ Error: {e}")
        try:
            await websocket.send_json({
                "type": "error",
                "content": str(e)
            })
        except:
            pass