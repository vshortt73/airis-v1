"""
Test script for attachments.py module
Tests all core functionality independently
"""

import sys
import os
from pathlib import Path

# Add core directory to path so we can import attachments
core_dir = Path(__file__).parent / 'core'
sys.path.insert(0, str(core_dir))

import attachments  # Now Python will find it in core/
from PIL import Image
import io

def create_test_image(color='blue', size=(512, 512)) -> bytes:
    """Create a simple test image in memory"""
    img = Image.new('RGB', size, color=color)
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    return buffer.getvalue()

def test_directory_creation():
    """Test that directories are created properly"""
    print("\n" + "="*60)
    print("TEST 1: Directory Creation")
    print("="*60)
    
    test_session = "test-session-123"
    
    user_dir = attachments.get_user_upload_dir(test_session)
    gen_dir = attachments.get_generated_dir(test_session)
    
    print(f"✓ User upload dir: {user_dir}")
    print(f"✓ Generated dir: {gen_dir}")
    print(f"✓ User dir exists: {user_dir.exists()}")
    print(f"✓ Generated dir exists: {gen_dir.exists()}")
    
    return user_dir.exists() and gen_dir.exists()

def test_save_and_load():
    """Test saving and loading files"""
    print("\n" + "="*60)
    print("TEST 2: Save and Load")
    print("="*60)
    
    test_session = "test-session-456"
    
    # Create test image
    print("\nCreating test image...")
    image_data = create_test_image('blue', (256, 256))
    print(f"✓ Created blue 256x256 image ({len(image_data)} bytes)")
    
    # Save as user upload
    print("\nSaving as user upload...")
    metadata = attachments.save_user_upload(
        session_id=test_session,
        file_data=image_data,
        filename="test_blue.png",
        mime_type="image/png"
    )
    print(f"✓ Saved metadata: {metadata}")
    
    # Load it back
    print("\nLoading file back...")
    loaded_data = attachments.load_file(metadata['path'])
    print(f"✓ Loaded {len(loaded_data)} bytes")
    
    # Verify
    if loaded_data == image_data:
        print("✓ SUCCESS: Data matches!")
        return True
    else:
        print("✗ FAILED: Data mismatch!")
        return False

def test_base64_encoding():
    """Test base64 encoding/decoding"""
    print("\n" + "="*60)
    print("TEST 3: Base64 Encoding")
    print("="*60)
    
    # Create test image
    image_data = create_test_image('red', (128, 128))
    print(f"Original size: {len(image_data)} bytes")
    
    # Encode
    print("\nEncoding to base64...")
    encoded = attachments.encode_to_base64(image_data)
    print(f"✓ Encoded length: {len(encoded)} characters")
    print(f"✓ First 50 chars: {encoded[:50]}...")
    
    # Decode
    print("\nDecoding from base64...")
    decoded = attachments.decode_from_base64(encoded)
    print(f"✓ Decoded size: {len(decoded)} bytes")
    
    # Verify
    if decoded == image_data:
        print("✓ SUCCESS: Encoding/decoding round-trip works!")
        return True
    else:
        print("✗ FAILED: Data corruption during encoding!")
        return False

def test_load_and_encode():
    """Test combined load + encode operation"""
    print("\n" + "="*60)
    print("TEST 4: Load and Encode (Combined)")
    print("="*60)
    
    test_session = "test-session-789"
    
    # Save image
    print("\nSaving test image...")
    image_data = create_test_image('green', (200, 200))
    metadata = attachments.save_generated_file(
        session_id=test_session,
        file_data=image_data,
        filename="test_green.png"
    )
    print(f"✓ Saved: {metadata['path']}")
    
    # Load and encode in one step
    print("\nLoading and encoding...")
    encoded = attachments.load_and_encode(metadata['path'])
    
    if encoded:
        print(f"✓ Got base64 string ({len(encoded)} chars)")
        
        # Verify by decoding
        decoded = attachments.decode_from_base64(encoded)
        if decoded == image_data:
            print("✓ SUCCESS: Load-and-encode works correctly!")
            return True
        else:
            print("✗ FAILED: Data mismatch after decode!")
            return False
    else:
        print("✗ FAILED: load_and_encode returned None!")
        return False

def test_attachment_metadata():
    """Test attachment metadata operations"""
    print("\n" + "="*60)
    print("TEST 5: Attachment Metadata")
    print("="*60)
    
    # Create metadata
    print("\nCreating attachment metadata...")
    metadata = attachments.create_attachment_metadata(
        relative_path="user/abc123/image.png",
        mime_type="image/png",
        attachment_type="image"
    )
    print(f"✓ Metadata: {metadata}")
    
    # Serialize
    print("\nSerializing to JSON...")
    json_str = attachments.serialize_attachments([metadata])
    print(f"✓ JSON: {json_str}")
    
    # Parse back
    print("\nParsing JSON...")
    parsed = attachments.parse_attachments_json(json_str)
    print(f"✓ Parsed: {parsed}")
    
    # Verify
    if parsed[0] == metadata:
        print("✓ SUCCESS: Metadata serialization works!")
        return True
    else:
        print("✗ FAILED: Metadata mismatch!")
        return False

def test_token_estimation():
    """Test token estimation"""
    print("\n" + "="*60)
    print("TEST 6: Token Estimation")
    print("="*60)
    
    test_session = "test-session-tokens"
    
    # Create different sized images
    sizes = [(128, 128), (256, 256), (512, 512), (1024, 1024)]
    
    for size in sizes:
        print(f"\nTesting {size[0]}x{size[1]} image...")
        image_data = create_test_image('yellow', size)
        
        # Save it
        metadata = attachments.save_generated_file(
            session_id=test_session,
            file_data=image_data
        )
        
        # Get stats
        stats = attachments.get_attachment_stats(metadata['path'])
        
        print(f"  Size: {stats['size_kb']:.1f} KB")
        print(f"  Estimated tokens: {stats['estimated_tokens']}")
    
    print("\n✓ Token estimation complete (these are rough estimates)")
    return True

def test_base64_with_data_uri():
    """Test handling base64 with data URI prefix"""
    print("\n" + "="*60)
    print("TEST 7: Base64 with Data URI Prefix")
    print("="*60)
    
    test_session = "test-session-uri"
    
    # Create test image
    image_data = create_test_image('purple', (150, 150))
    
    # Encode with data URI prefix (like browser would send)
    plain_base64 = attachments.encode_to_base64(image_data)
    with_uri = f"data:image/png;base64,{plain_base64}"
    
    print(f"Plain base64 length: {len(plain_base64)}")
    print(f"With URI prefix length: {len(with_uri)}")
    print(f"First 60 chars: {with_uri[:60]}...")
    
    # Test save_base64_image function
    print("\nSaving via save_base64_image()...")
    metadata = attachments.save_base64_image(
        session_id=test_session,
        base64_string=with_uri,
        is_user_upload=True
    )
    print(f"✓ Saved: {metadata}")
    
    # Load it back and verify
    loaded = attachments.load_file(metadata['path'])
    
    if loaded == image_data:
        print("✓ SUCCESS: Data URI handling works!")
        return True
    else:
        print("✗ FAILED: Data corruption!")
        return False

def run_all_tests():
    """Run all tests and report results"""
    print("\n" + "#"*60)
    print("# IRIS v3 - ATTACHMENT MODULE TEST SUITE")
    print("#"*60)
    
    tests = [
        ("Directory Creation", test_directory_creation),
        ("Save and Load", test_save_and_load),
        ("Base64 Encoding", test_base64_encoding),
        ("Load and Encode", test_load_and_encode),
        ("Attachment Metadata", test_attachment_metadata),
        ("Token Estimation", test_token_estimation),
        ("Data URI Handling", test_base64_with_data_uri)
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
    print("# TEST SUMMARY")
    print("#"*60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 ALL TESTS PASSED! 🎉")
        print("\nAttachment module is ready for integration!")
    else:
        print(f"\n⚠️  {total - passed} test(s) failed - debug before proceeding")
    
    return passed == total

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
