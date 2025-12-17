"""
Attachment handling for Iris v3
Manages file storage, loading, and encoding for images and other attachments
"""

import os
import base64
import json
from typing import Optional, List, Dict
from datetime import datetime
from pathlib import Path
import mimetypes

# ============================================================================
# CONFIGURATION
# ============================================================================

# Base directory for all attachments (relative to project root)
ATTACHMENTS_BASE = "attachments"

# Subdirectories
USER_UPLOADS_DIR = "user"
GENERATED_DIR = "generated"

# Supported image types
SUPPORTED_IMAGE_TYPES = {
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.gif': 'image/gif',
    '.webp': 'image/webp'
}

# ============================================================================
# PATH MANAGEMENT
# ============================================================================

def get_attachments_root() -> Path:
    """Get the root attachments directory path"""
    # Assumes this is called from /iris-v3/core/attachments.py
    # So project root is two levels up
    current_file = Path(__file__).resolve()
    project_root = current_file.parent.parent if current_file.parent.name == 'core' else current_file.parent
    return project_root / ATTACHMENTS_BASE

def ensure_directory_exists(path: Path) -> None:
    """Create directory if it doesn't exist"""
    path.mkdir(parents=True, exist_ok=True)

def get_user_upload_dir(session_id: str) -> Path:
    """Get directory for user uploads for a specific session"""
    path = get_attachments_root() / USER_UPLOADS_DIR / session_id
    ensure_directory_exists(path)
    return path

def get_generated_dir(session_id: str) -> Path:
    """Get directory for generated content for a specific session"""
    path = get_attachments_root() / GENERATED_DIR / session_id
    ensure_directory_exists(path)
    return path

def generate_filename(original_filename: Optional[str] = None, extension: str = ".png") -> str:
    """
    Generate unique filename with timestamp
    
    Args:
        original_filename: Original name (optional)
        extension: File extension (default .png)
    
    Returns:
        Timestamped filename
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    
    if original_filename:
        # Clean the original filename (remove path, keep extension)
        name = Path(original_filename).stem
        ext = Path(original_filename).suffix or extension
        return f"{timestamp}_{name}{ext}"
    else:
        return f"{timestamp}{extension}"

# ============================================================================
# FILE OPERATIONS
# ============================================================================

def save_user_upload(
    session_id: str,
    file_data: bytes,
    filename: Optional[str] = None,
    mime_type: Optional[str] = None
) -> Dict[str, str]:
    """
    Save user-uploaded file
    
    Args:
        session_id: Current session ID
        file_data: Raw file bytes
        filename: Original filename (optional)
        mime_type: MIME type (optional, will detect from extension)
    
    Returns:
        Attachment metadata dict
    """
    # Determine extension and mime type
    if filename:
        ext = Path(filename).suffix.lower()
    else:
        ext = ".png"  # Default
    
    if not mime_type:
        mime_type = SUPPORTED_IMAGE_TYPES.get(ext, "application/octet-stream")
    
    # Generate unique filename
    unique_filename = generate_filename(filename, ext)
    
    # Get upload directory
    upload_dir = get_user_upload_dir(session_id)
    file_path = upload_dir / unique_filename
    
    # Write file
    with open(file_path, 'wb') as f:
        f.write(file_data)
    
    # Calculate relative path from attachments root
    relative_path = f"{USER_UPLOADS_DIR}/{session_id}/{unique_filename}"
    
    print(f"[attachments.py][save_user_upload] Saved: {relative_path} ({len(file_data)} bytes)")
    
    return {
        "type": "image",
        "path": relative_path,
        "mime_type": mime_type,
        "size": len(file_data)
    }

def save_generated_file(
    session_id: str,
    file_data: bytes,
    filename: Optional[str] = None,
    mime_type: str = "image/png"
) -> Dict[str, str]:
    """
    Save tool-generated file
    
    Args:
        session_id: Current session ID
        file_data: Raw file bytes
        filename: Filename (optional)
        mime_type: MIME type
    
    Returns:
        Attachment metadata dict
    """
    # Generate unique filename
    unique_filename = generate_filename(filename)
    
    # Get generated directory
    gen_dir = get_generated_dir(session_id)
    file_path = gen_dir / unique_filename
    
    # Write file
    with open(file_path, 'wb') as f:
        f.write(file_data)
    
    # Calculate relative path
    relative_path = f"{GENERATED_DIR}/{session_id}/{unique_filename}"
    
    print(f"[attachments.py][save_generated_file] Saved: {relative_path} ({len(file_data)} bytes)")
    
    return {
        "type": "image",
        "path": relative_path,
        "mime_type": mime_type,
        "size": len(file_data)
    }

def load_file(relative_path: str) -> Optional[bytes]:
    """
    Load file from disk by relative path
    
    Args:
        relative_path: Path relative to attachments root
    
    Returns:
        File bytes or None if not found
    """
    try:
        full_path = get_attachments_root() / relative_path
        
        if not full_path.exists():
            print(f"[attachments.py][load_file] File not found: {relative_path}")
            return None
        
        with open(full_path, 'rb') as f:
            data = f.read()
        
      #  print(f"[attachments.py][load_file] Loaded: {relative_path} ({len(data)} bytes)")
        return data
        
    except Exception as e:
        print(f"[attachments.py][load_file] Error loading {relative_path}: {e}")
        return None

# ============================================================================
# ENCODING
# ============================================================================

def encode_to_base64(file_data: bytes) -> str:
    """
    Encode file bytes to base64 string
    
    Args:
        file_data: Raw file bytes
    
    Returns:
        Base64 encoded string (no data URI prefix)
    """
    return base64.b64encode(file_data).decode('utf-8')

def decode_from_base64(base64_string: str) -> bytes:
    """
    Decode base64 string to bytes
    
    Args:
        base64_string: Base64 encoded string
    
    Returns:
        Raw file bytes
    """
    # Remove data URI prefix if present
    if base64_string.startswith('data:'):
        base64_string = base64_string.split(',', 1)[1]
    
    return base64.b64decode(base64_string)

def load_and_encode(relative_path: str) -> Optional[str]:
    """
    Load file and encode to base64 in one step
    
    Args:
        relative_path: Path relative to attachments root
    
    Returns:
        Base64 encoded string or None if file not found
    """
    file_data = load_file(relative_path)
    if file_data:
        return encode_to_base64(file_data)
    return None

# ============================================================================
# ATTACHMENT METADATA
# ============================================================================

def create_attachment_metadata(
    relative_path: str,
    mime_type: str = "image/png",
    attachment_type: str = "image"
) -> Dict[str, str]:
    """
    Create attachment metadata dict
    
    Args:
        relative_path: Path relative to attachments root
        mime_type: MIME type
        attachment_type: Type of attachment
    
    Returns:
        Metadata dict
    """
    return {
        "type": attachment_type,
        "path": relative_path,
        "mime_type": mime_type
    }

def parse_attachments_json(attachments_json: Optional[str]) -> List[Dict[str, str]]:
    """
    Parse attachments JSON from database
    
    Args:
        attachments_json: JSON string from database
    
    Returns:
        List of attachment metadata dicts
    """
    if not attachments_json:
        return []
    
    try:
        return json.loads(attachments_json)
    except json.JSONDecodeError as e:
        print(f"[attachments.py][parse_attachments_json] Error parsing JSON: {e}")
        return []

def serialize_attachments(attachments: List[Dict[str, str]]) -> str:
    """
    Serialize attachments list to JSON string
    
    Args:
        attachments: List of attachment metadata dicts
    
    Returns:
        JSON string
    """
    return json.dumps(attachments)

# ============================================================================
# HIGH-LEVEL OPERATIONS
# ============================================================================

def save_base64_image(
    session_id: str,
    base64_string: str,
    is_user_upload: bool = True,
    filename: Optional[str] = None
) -> Dict[str, str]:
    """
    Save base64-encoded image to disk
    
    Args:
        session_id: Current session ID
        base64_string: Base64 encoded image (with or without data URI)
        is_user_upload: True for user uploads, False for generated
        filename: Original filename (optional)
    
    Returns:
        Attachment metadata dict
    """
    # Decode base64
    file_data = decode_from_base64(base64_string)
    
    # Detect mime type from data URI if present
    mime_type = "image/png"  # Default
    if base64_string.startswith('data:'):
        mime_type = base64_string.split(';')[0].split(':')[1]
    
    # Save to appropriate directory
    if is_user_upload:
        return save_user_upload(session_id, file_data, filename, mime_type)
    else:
        return save_generated_file(session_id, file_data, filename, mime_type)

def load_attachments_for_message(attachments_json: Optional[str]) -> List[str]:
    """
    Load and encode all attachments for a message
    
    Args:
        attachments_json: JSON string from database
    
    Returns:
        List of base64 encoded images
    """
    attachments = parse_attachments_json(attachments_json)
    
    encoded_images = []
    for attachment in attachments:
        if attachment.get('type') == 'image':
            base64_string = load_and_encode(attachment['path'])
            if base64_string:
                encoded_images.append(base64_string)
    
    return encoded_images

# ============================================================================
# UTILITY
# ============================================================================

def estimate_tokens_from_image_size(file_size_bytes: int) -> int:
    """
    Rough estimate of token cost for an image
    
    Vision models typically use ~256-1024 tokens per image depending on resolution.
    This is a rough heuristic.
    
    Args:
        file_size_bytes: Size of image file in bytes
    
    Returns:
        Estimated token count
    """
    # Very rough heuristic: ~1 token per 1KB for images
    # Actual token usage depends on image resolution and model encoding
    return max(256, file_size_bytes // 1024)

def get_attachment_stats(relative_path: str) -> Optional[Dict]:
    """
    Get statistics about an attachment
    
    Args:
        relative_path: Path relative to attachments root
    
    Returns:
        Dict with size, estimated tokens, etc.
    """
    file_data = load_file(relative_path)
    if not file_data:
        return None
    
    return {
        "size_bytes": len(file_data),
        "size_kb": len(file_data) / 1024,
        "estimated_tokens": estimate_tokens_from_image_size(len(file_data))
    }