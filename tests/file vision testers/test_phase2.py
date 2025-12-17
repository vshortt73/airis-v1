"""
Phase 2 Test: Database Integration with Attachments
Tests that attachments can be saved to and loaded from the database
"""

import sys
import os
from pathlib import Path

# Add paths
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / 'core'))
sys.path.insert(0, str(Path(__file__).parent / 'database'))

import attachments
import persistence_phase2 as persistence
from PIL import Image
import io
import uuid

def create_test_image(color='blue', size=(256, 256)) -> bytes:
    """Create a simple test image"""
    img = Image.new('RGB', size, color=color)
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    return buffer.getvalue()

def test_save_message_with_attachment():
    """Test saving a message with attachment metadata"""
    print("\n" + "="*60)
    print("PHASE 2 TEST 1: Save Message with Attachment")
    print("="*60)
    
    # Create a test session
    session_id = str(uuid.uuid4())
    print(f"Test session: {session_id[:8]}...")
    
    # Save test image using attachments module
    print("\nSaving test image...")
    image_data = create_test_image('red', (200, 200))
    attachment_metadata = attachments.save_user_upload(
        session_id=session_id,
        file_data=image_data,
        filename="test_red.png"
    )
    print(f"✓ Image saved: {attachment_metadata['path']}")
    
    # Save message with attachment to database
    print("\nSaving message with attachment to database...")
    success = persistence.save_message(
        session_id=session_id,
        role="user",
        message="Here's a red square",
        attachments=[attachment_metadata]  # Pass as list
    )
    
    if success:
        print("✓ SUCCESS: Message with attachment saved to database!")
        return True
    else:
        print("✗ FAILED: Could not save message")
        return False

def test_load_message_with_attachment():
    """Test loading messages and their attachments"""
    print("\n" + "="*60)
    print("PHASE 2 TEST 2: Load Message with Attachment")
    print("="*60)
    
    # Create test session
    session_id = str(uuid.uuid4())
    
    # Save image
    print("\nCreating and saving test image...")
    image_data = create_test_image('green', (150, 150))
    attachment_metadata = attachments.save_generated_file(
        session_id=session_id,
        file_data=image_data
    )
    print(f"✓ Image saved: {attachment_metadata['path']}")
    
    # Save message with attachment
    print("\nSaving message to database...")
    persistence.save_message(
        session_id=session_id,
        role="assistant",
        message="I generated this green square",
        attachments=[attachment_metadata]
    )
    print("✓ Message saved")
    
    # Load messages back
    print("\nLoading messages from database...")
    messages = persistence.load_recent_conversation(max_turns=10)
    
    if not messages:
        print("✗ FAILED: No messages loaded")
        return False
    
    # Find our test message
    test_message = None
    for msg in messages:
        if "green square" in msg.get('content', ''):
            test_message = msg
            break
    
    if not test_message:
        print("✗ FAILED: Could not find test message")
        return False
    
    print(f"✓ Found test message: '{test_message['content']}'")
    
    # Check if attachments are present
    if 'attachments' in test_message:
        print(f"✓ Attachments field present: {test_message['attachments'][:100]}...")
        print("✓ SUCCESS: Message loaded with attachment metadata!")
        return True
    else:
        print("✗ FAILED: No attachments in loaded message")
        return False

def test_multiple_attachments():
    """Test saving and loading multiple attachments"""
    print("\n" + "="*60)
    print("PHASE 2 TEST 3: Multiple Attachments")
    print("="*60)
    
    session_id = str(uuid.uuid4())
    
    # Create multiple test images
    print("\nCreating multiple test images...")
    attachments_list = []
    
    for color in ['red', 'blue', 'yellow']:
        image_data = create_test_image(color, (100, 100))
        metadata = attachments.save_user_upload(
            session_id=session_id,
            file_data=image_data,
            filename=f"test_{color}.png"
        )
        attachments_list.append(metadata)
        print(f"✓ Created {color} image: {metadata['path']}")
    
    # Save message with multiple attachments
    print(f"\nSaving message with {len(attachments_list)} attachments...")
    success = persistence.save_message(
        session_id=session_id,
        role="user",
        message="Here are three colored squares",
        attachments=attachments_list
    )
    
    if success:
        print("✓ SUCCESS: Message with multiple attachments saved!")
        
        # Load it back
        messages = persistence.load_recent_conversation(max_turns=10)
        test_msg = None
        for msg in messages:
            if "three colored squares" in msg.get('content', ''):
                test_msg = msg
                break
        
        if test_msg and 'attachments' in test_msg:
            import json
            loaded_attachments = json.loads(test_msg['attachments'])
            print(f"✓ Loaded {len(loaded_attachments)} attachments from database")
            return True
        else:
            print("✗ FAILED: Could not verify loaded attachments")
            return False
    else:
        print("✗ FAILED: Could not save message")
        return False

def run_phase2_tests():
    """Run all Phase 2 tests"""
    print("\n" + "#"*60)
    print("# PHASE 2: DATABASE INTEGRATION WITH ATTACHMENTS")
    print("#"*60)
    
    tests = [
        ("Save Message with Attachment", test_save_message_with_attachment),
        ("Load Message with Attachment", test_load_message_with_attachment),
        ("Multiple Attachments", test_multiple_attachments)
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
    print("# PHASE 2 TEST SUMMARY")
    print("#"*60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 PHASE 2 COMPLETE! 🎉")
        print("\nDatabase integration works!")
        print("Ready for Phase 3: Conversation Layer")
    else:
        print(f"\n⚠️  {total - passed} test(s) failed")
    
    return passed == total

if __name__ == "__main__":
    # Make sure database password is set
    if not os.environ.get('IRIS_DB_PASSWORD'):
        print("ERROR: IRIS_DB_PASSWORD environment variable not set!")
        print("Set it with: export IRIS_DB_PASSWORD='yourpassword'")
        sys.exit(1)
    
    success = run_phase2_tests()
    sys.exit(0 if success else 1)
