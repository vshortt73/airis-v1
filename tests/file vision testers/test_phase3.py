"""
Phase 3 Test: Conversation Layer with Image Support
Tests that conversation.py can handle images properly
"""

import sys
import os
from pathlib import Path

# Add paths
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / 'core'))
sys.path.insert(0, str(Path(__file__).parent / 'database'))

from conversation_phase3 import ConversationHistory
import attachments
from PIL import Image
import io

def create_test_image(color='blue', size=(256, 256)) -> str:
    """Create test image and return as base64"""
    img = Image.new('RGB', size, color=color)
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    image_bytes = buffer.getvalue()
    return attachments.encode_to_base64(image_bytes)

def test_user_message_with_image():
    """Test adding user message with image attachment"""
    print("\n" + "="*60)
    print("PHASE 3 TEST 1: User Message with Image")
    print("="*60)
    
    # Create conversation
    print("\nCreating conversation...")
    conv = ConversationHistory(enable_persistence=True)
    print(f"✓ Conversation created, session: {conv.get_session_id()[:8]}...")
    
    # Create test image
    print("\nCreating test image...")
    image_base64 = create_test_image('purple', (200, 200))
    print(f"✓ Created base64 image ({len(image_base64)} chars)")
    
    # Add user message with image
    print("\nAdding user message with image...")
    conv.add_user_message(
        content="Here's a purple square",
        images=[image_base64]
    )
    
    # Check in-memory message
    messages = conv.get_messages()
    last_msg = messages[-1]
    
    print(f"\n✓ Message added to conversation")
    print(f"  Role: {last_msg['role']}")
    print(f"  Content: {last_msg['content']}")
    
    if 'attachments' in last_msg:
        import json
        atts = json.loads(last_msg['attachments'])
        print(f"  Attachments: {len(atts)} file(s)")
        print(f"  Path: {atts[0]['path']}")
        print("✓ SUCCESS: User message with image handled correctly!")
        return True
    else:
        print("✗ FAILED: No attachments in message")
        return False

def test_assistant_message_with_image():
    """Test adding assistant message with generated image"""
    print("\n" + "="*60)
    print("PHASE 3 TEST 2: Assistant Message with Generated Image")
    print("="*60)
    
    conv = ConversationHistory(enable_persistence=True)
    
    # Create generated image
    print("\nCreating generated image...")
    image_base64 = create_test_image('orange', (300, 300))
    
    # Add assistant message with image
    print("\nAdding assistant message with generated image...")
    conv.add_assistant_message(
        content="I generated this orange square",
        images=[image_base64]
    )
    
    messages = conv.get_messages()
    last_msg = messages[-1]
    
    print(f"\n✓ Message added")
    print(f"  Role: {last_msg['role']}")
    
    if 'attachments' in last_msg:
        import json
        atts = json.loads(last_msg['attachments'])
        # Check it was saved to generated/ directory
        if 'generated/' in atts[0]['path']:
            print(f"  ✓ Saved to generated directory: {atts[0]['path']}")
            print("✓ SUCCESS: Assistant message with generated image!")
            return True
        else:
            print(f"  ✗ Wrong directory: {atts[0]['path']}")
            return False
    else:
        print("✗ FAILED: No attachments")
        return False

def test_tool_message_with_images():
    """Test adding tool message with multiple output images"""
    print("\n" + "="*60)
    print("PHASE 3 TEST 3: Tool Message with Multiple Images")
    print("="*60)
    
    conv = ConversationHistory(enable_persistence=True)
    
    # Create multiple tool output images
    print("\nCreating 3 tool output images...")
    images = [
        create_test_image('red', (150, 150)),
        create_test_image('green', (150, 150)),
        create_test_image('blue', (150, 150))
    ]
    print(f"✓ Created {len(images)} images")
    
    # Add tool message with images
    print("\nAdding tool message with images...")
    conv.add_tool_message(
        content="ComfyUI generated 3 images",
        tool_name="comfyui_render",
        images=images
    )
    
    messages = conv.get_messages()
    last_msg = messages[-1]
    
    print(f"\n✓ Message added")
    print(f"  Tool: {last_msg['tool_name']}")
    
    if 'attachments' in last_msg:
        import json
        atts = json.loads(last_msg['attachments'])
        if len(atts) == 3:
            print(f"  ✓ All {len(atts)} images saved")
            for att in atts:
                print(f"    - {att['path']}")
            print("✓ SUCCESS: Tool message with multiple images!")
            return True
        else:
            print(f"  ✗ Wrong number of attachments: {len(atts)}")
            return False
    else:
        print("✗ FAILED: No attachments")
        return False

def test_reload_with_attachments():
    """Test that attachments persist across reload"""
    print("\n" + "="*60)
    print("PHASE 3 TEST 4: Reload Conversation with Attachments")
    print("="*60)
    
    # Create conversation and add message with image
    print("\nCreating conversation with image...")
    conv1 = ConversationHistory(enable_persistence=True)
    session_id = conv1.get_session_id()
    
    image_base64 = create_test_image('cyan', (100, 100))
    conv1.add_user_message("Test image", images=[image_base64])
    
    print(f"✓ Added message to session {session_id[:8]}...")
    print(f"  Messages in conv1: {conv1.get_message_count()}")
    
    # Create NEW conversation instance (simulates reload)
    print("\nCreating new conversation instance (reload simulation)...")
    conv2 = ConversationHistory(enable_persistence=True)
    
    print(f"✓ New conversation created")
    print(f"  Session: {conv2.get_session_id()[:8]}...")
    print(f"  Messages loaded: {conv2.get_message_count()}")
    
    # Check if our test message is there with attachments
    messages = conv2.get_messages()
    found = False
    for msg in messages:
        if "Test image" in msg.get('content', ''):
            print(f"\n✓ Found test message in reloaded conversation")
            if 'attachments' in msg:
                print(f"  ✓ Attachments present: {msg['attachments'][:50]}...")
                found = True
                break
            else:
                print(f"  ✗ No attachments in reloaded message")
                return False
    
    if found:
        print("✓ SUCCESS: Attachments persist across reload!")
        return True
    else:
        print("✗ FAILED: Test message not found in reload")
        return False

def run_phase3_tests():
    """Run all Phase 3 tests"""
    print("\n" + "#"*60)
    print("# PHASE 3: CONVERSATION LAYER WITH IMAGE SUPPORT")
    print("#"*60)
    
    tests = [
        ("User Message with Image", test_user_message_with_image),
        ("Assistant Message with Generated Image", test_assistant_message_with_image),
        ("Tool Message with Multiple Images", test_tool_message_with_images),
        ("Reload Conversation with Attachments", test_reload_with_attachments)
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n✗ ERROR in {name}: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))
    
    # Summary
    print("\n" + "#"*60)
    print("# PHASE 3 TEST SUMMARY")
    print("#"*60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 PHASE 3 COMPLETE! 🎉")
        print("\nConversation layer handles images!")
        print("Ready for Phase 4: Ollama Integration")
    else:
        print(f"\n⚠️  {total - passed} test(s) failed")
    
    return passed == total

if __name__ == "__main__":
    # Make sure database password is set
    if not os.environ.get('IRIS_DB_PASSWORD'):
        print("ERROR: IRIS_DB_PASSWORD environment variable not set!")
        print("Set it with: export IRIS_DB_PASSWORD='yourpassword'")
        sys.exit(1)
    
    success = run_phase3_tests()
    sys.exit(0 if success else 1)
