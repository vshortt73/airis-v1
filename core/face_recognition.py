"""
Face Recognition Core Module

Handles face detection, embedding generation, similarity matching,
and person management using InsightFace (ArcFace) with 512-dim embeddings.

Uses:
- InsightFace for face detection and embedding extraction
- PostgreSQL with pgvector for embedding storage and HNSW similarity search
- OpenCV for camera capture and image processing
"""

import os
import sys
import threading
import hashlib
import json
from typing import List, Dict, Optional, Tuple, Any
from pathlib import Path
import base64
from io import BytesIO

import numpy as np
import cv2
import psycopg2
import psycopg2.extras
from PIL import Image

# InsightFace imports
try:
    import insightface
    from insightface.app import FaceAnalysis
except ImportError as e:
    print(f"[face_recognition.py] ✗ InsightFace not installed: {e}")
    print(f"[face_recognition.py] Install with: pip install insightface onnxruntime-gpu")
    FaceAnalysis = None

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)

from app import config


# ============================================================================
# Global singleton for InsightFace model (thread-safe)
# ============================================================================

_face_model = None
_model_lock = threading.Lock()


def get_face_model() -> Optional[FaceAnalysis]:
    """
    Get or initialize InsightFace model (singleton with thread safety)

    Returns:
        FaceAnalysis instance or None if initialization fails
    """
    global _face_model

    if _face_model is not None:
        return _face_model

    with _model_lock:
        # Double-check after acquiring lock
        if _face_model is not None:
            return _face_model

        try:
            print(f"[face_recognition.py][get_face_model] Initializing InsightFace model '{config.FACE_RECOGNITION_MODEL}'...")

            # Initialize FaceAnalysis with specified model
            app = FaceAnalysis(
                name=config.FACE_RECOGNITION_MODEL,
                providers=['CUDAExecutionProvider', 'CPUExecutionProvider'] if config.FACE_USE_GPU else ['CPUExecutionProvider']
            )

            # Prepare model with detection size
            app.prepare(ctx_id=0 if config.FACE_USE_GPU else -1, det_size=config.FACE_DETECTION_SIZE)

            _face_model = app
            print(f"[face_recognition.py][get_face_model] ✓ Model initialized successfully")
            print(f"[face_recognition.py][get_face_model] GPU: {config.FACE_USE_GPU}, Detection size: {config.FACE_DETECTION_SIZE}")

            return _face_model

        except Exception as e:
            print(f"[face_recognition.py][get_face_model] ✗ Error initializing model: {e}")
            return None


# ============================================================================
# Database Connection
# ============================================================================

def get_db_connection():
    """Get database connection with credentials from config"""
    password = os.environ.get('AIRIS_DB_PASSWORD') or getattr(config, 'DB_PASSWORD', None)
    conn_params = {
        'host': config.DB_HOST,
        'port': config.DB_PORT,
        'database': config.DB_NAME,
        'user': config.DB_USER
    }
    if password:
        conn_params['password'] = password
    return psycopg2.connect(**conn_params)


# ============================================================================
# Image Utilities
# ============================================================================

def load_image_from_path(image_path: str) -> Optional[np.ndarray]:
    """
    Load image from file path

    Args:
        image_path: Path to image file

    Returns:
        Image as numpy array (BGR format) or None if failed
    """
    try:
        img = cv2.imread(image_path)
        if img is None:
            print(f"[face_recognition.py][load_image_from_path] ✗ Failed to load image: {image_path}")
            return None
        return img
    except Exception as e:
        print(f"[face_recognition.py][load_image_from_path] ✗ Error loading image: {e}")
        return None


def load_image_from_base64(base64_string: str) -> Optional[np.ndarray]:
    """
    Load image from base64 string

    Args:
        base64_string: Base64-encoded image (with or without data URI prefix)

    Returns:
        Image as numpy array (BGR format) or None if failed
    """
    try:
        # Remove data URI prefix if present
        if ',' in base64_string:
            base64_string = base64_string.split(',', 1)[1]

        # Decode base64
        img_data = base64.b64decode(base64_string)

        # Convert to numpy array
        nparr = np.frombuffer(img_data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if img is None:
            print(f"[face_recognition.py][load_image_from_base64] ✗ Failed to decode image")
            return None

        return img
    except Exception as e:
        print(f"[face_recognition.py][load_image_from_base64] ✗ Error loading image: {e}")
        return None


def load_image_from_bytes(image_bytes: bytes) -> Optional[np.ndarray]:
    """
    Load image from bytes

    Args:
        image_bytes: Raw image bytes

    Returns:
        Image as numpy array (BGR format) or None if failed
    """
    try:
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if img is None:
            print(f"[face_recognition.py][load_image_from_bytes] ✗ Failed to decode image")
            return None

        return img
    except Exception as e:
        print(f"[face_recognition.py][load_image_from_bytes] ✗ Error loading image: {e}")
        return None


def compute_image_hash(img: np.ndarray) -> str:
    """
    Compute SHA256 hash of image for deduplication

    Args:
        img: Image as numpy array

    Returns:
        SHA256 hash string
    """
    # Encode image to bytes
    _, buffer = cv2.imencode('.jpg', img)
    img_bytes = buffer.tobytes()

    # Compute hash
    return hashlib.sha256(img_bytes).hexdigest()


# ============================================================================
# Camera Capture
# ============================================================================

def capture_from_camera(camera_identifier: str) -> Optional[np.ndarray]:
    """
    Capture frame from camera (USB device or RTSP stream)

    Args:
        camera_identifier: Device ID (0, 1, ...) or RTSP URL or file path

    Returns:
        Captured frame as numpy array or None if failed
    """
    try:
        # Try to convert to int for USB camera
        try:
            device_id = int(camera_identifier)
            cap = cv2.VideoCapture(device_id)
        except ValueError:
            # Not an int, treat as URL or file path
            cap = cv2.VideoCapture(camera_identifier)

        if not cap.isOpened():
            print(f"[face_recognition.py][capture_from_camera] ✗ Failed to open camera: {camera_identifier}")
            return None

        # Read frame
        ret, frame = cap.read()
        cap.release()

        if not ret or frame is None:
            print(f"[face_recognition.py][capture_from_camera] ✗ Failed to read frame from: {camera_identifier}")
            return None

        return frame

    except Exception as e:
        print(f"[face_recognition.py][capture_from_camera] ✗ Error capturing from camera: {e}")
        return None


# ============================================================================
# Face Detection & Embedding
# ============================================================================

def detect_faces(img: np.ndarray, min_confidence: float = None) -> List[Dict[str, Any]]:
    """
    Detect faces in image and extract embeddings

    Args:
        img: Image as numpy array (BGR format)
        min_confidence: Minimum detection confidence (default from config)

    Returns:
        List of face dictionaries with keys:
            - bbox: [x1, y1, x2, y2]
            - confidence: Detection confidence (0-1)
            - embedding: 512-dim numpy array
            - det_score: Detection score
            - landmark: 5-point facial landmarks
    """
    model = get_face_model()
    if model is None:
        print(f"[face_recognition.py][detect_faces] ✗ Model not initialized")
        return []

    if min_confidence is None:
        min_confidence = config.FACE_DETECTION_CONFIDENCE

    try:
        # Detect faces
        faces = model.get(img)

        if not faces:
            return []

        # Filter by confidence and format results
        results = []
        for face in faces:
            if face.det_score < min_confidence:
                continue

            # Check if bbox exists
            if face.bbox is None:
                print(f"[face_recognition.py][detect_faces] ⚠️ Face detected but bbox is None")
                continue

            # Check if embedding exists (can be None if face too small/blurry)
            if not hasattr(face, 'normed_embedding') or face.normed_embedding is None:
                print(f"[face_recognition.py][detect_faces] ⚠️ Face detected but no embedding (face too small/blurry?)")
                continue

            results.append({
                'bbox': face.bbox.tolist(),  # [x1, y1, x2, y2]
                'confidence': float(face.det_score),
                'embedding': face.normed_embedding.tolist(),  # 512-dim list
                'det_score': float(face.det_score),
                'landmark': face.landmark.tolist() if hasattr(face, 'landmark') and face.landmark is not None else None
            })

        print(f"[face_recognition.py][detect_faces] Detected {len(results)} faces (confidence >= {min_confidence})")
        return results

    except Exception as e:
        print(f"[face_recognition.py][detect_faces] ✗ Error detecting faces: {e}")
        return []


def generate_face_embedding(img: np.ndarray, bbox: Optional[List[float]] = None) -> Optional[List[float]]:
    """
    Generate face embedding for image (optionally from specific bbox)

    Args:
        img: Image as numpy array (BGR format)
        bbox: Optional bounding box [x1, y1, x2, y2] to extract face region

    Returns:
        512-dim embedding as list or None if failed
    """
    # If bbox provided, crop to face region first
    if bbox:
        x1, y1, x2, y2 = [int(coord) for coord in bbox]
        img = img[y1:y2, x1:x2]

    # Detect faces in image
    faces = detect_faces(img)

    if not faces:
        print(f"[face_recognition.py][generate_face_embedding] No faces detected")
        return None

    if len(faces) > 1:
        print(f"[face_recognition.py][generate_face_embedding] Warning: Multiple faces detected, using first")

    return faces[0]['embedding']


# ============================================================================
# Person Management
# ============================================================================

def create_person(name: str, display_name: str = None, relationship: str = None,
                 notes: str = None, tags: List[str] = None) -> Optional[int]:
    """
    Create new person in database

    Args:
        name: Unique person name
        display_name: Optional display name
        relationship: Optional relationship (owner, family, friend, etc.)
        notes: Optional notes
        tags: Optional list of tags

    Returns:
        person_id if successful, None otherwise
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO face_persons (name, display_name, relationship, notes, tags)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING person_id
        """, (name, display_name, relationship, notes, tags))

        person_id = cursor.fetchone()[0]
        conn.commit()
        cursor.close()
        conn.close()

        print(f"[face_recognition.py][create_person] ✓ Created person '{name}' with ID {person_id}")
        return person_id

    except psycopg2.IntegrityError as e:
        print(f"[face_recognition.py][create_person] ✗ Person '{name}' already exists")
        return None
    except Exception as e:
        print(f"[face_recognition.py][create_person] ✗ Error creating person: {e}")
        return None


def get_person(person_id: int) -> Optional[Dict[str, Any]]:
    """
    Get person by ID

    Args:
        person_id: Person ID

    Returns:
        Person dictionary or None if not found
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cursor.execute("""
            SELECT * FROM face_persons WHERE person_id = %s
        """, (person_id,))

        person = cursor.fetchone()
        cursor.close()
        conn.close()

        return dict(person) if person else None

    except Exception as e:
        print(f"[face_recognition.py][get_person] ✗ Error getting person: {e}")
        return None


def get_person_by_name(name: str) -> Optional[Dict[str, Any]]:
    """
    Get person by name

    Args:
        name: Person name

    Returns:
        Person dictionary or None if not found
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cursor.execute("""
            SELECT * FROM face_persons WHERE name = %s
        """, (name,))

        person = cursor.fetchone()
        cursor.close()
        conn.close()

        return dict(person) if person else None

    except Exception as e:
        print(f"[face_recognition.py][get_person_by_name] ✗ Error getting person: {e}")
        return None


def list_persons(enabled_only: bool = True) -> List[Dict[str, Any]]:
    """
    List all persons

    Args:
        enabled_only: Only return enabled persons

    Returns:
        List of person dictionaries
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        query = "SELECT * FROM face_persons"
        if enabled_only:
            query += " WHERE enabled = true"
        query += " ORDER BY name"

        cursor.execute(query)
        persons = cursor.fetchall()
        cursor.close()
        conn.close()

        return [dict(person) for person in persons]

    except Exception as e:
        print(f"[face_recognition.py][list_persons] ✗ Error listing persons: {e}")
        return []


def update_person(person_id: int, **kwargs) -> bool:
    """
    Update person attributes

    Args:
        person_id: Person ID
        **kwargs: Attributes to update (display_name, relationship, notes, tags, enabled)

    Returns:
        True if successful, False otherwise
    """
    if not kwargs:
        return True

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Build UPDATE query
        set_clauses = []
        values = []
        for key, value in kwargs.items():
            if key in ['display_name', 'relationship', 'notes', 'tags', 'enabled']:
                set_clauses.append(f"{key} = %s")
                values.append(value)

        if not set_clauses:
            print(f"[face_recognition.py][update_person] No valid fields to update")
            return False

        query = f"UPDATE face_persons SET {', '.join(set_clauses)} WHERE person_id = %s"
        values.append(person_id)

        cursor.execute(query, values)
        conn.commit()
        cursor.close()
        conn.close()

        print(f"[face_recognition.py][update_person] ✓ Updated person {person_id}")
        return True

    except Exception as e:
        print(f"[face_recognition.py][update_person] ✗ Error updating person: {e}")
        return False


def delete_person(person_id: int) -> bool:
    """
    Delete person (CASCADE deletes embeddings and presence state)

    Args:
        person_id: Person ID

    Returns:
        True if successful, False otherwise
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM face_persons WHERE person_id = %s", (person_id,))
        conn.commit()

        rows_deleted = cursor.rowcount
        cursor.close()
        conn.close()

        if rows_deleted > 0:
            print(f"[face_recognition.py][delete_person] ✓ Deleted person {person_id}")
            return True
        else:
            print(f"[face_recognition.py][delete_person] Person {person_id} not found")
            return False

    except Exception as e:
        print(f"[face_recognition.py][delete_person] ✗ Error deleting person: {e}")
        return False


# ============================================================================
# Training & Embedding Management
# ============================================================================

def add_training_embedding(person_id: int, img: np.ndarray, image_path: str = None,
                          is_primary: bool = False) -> Optional[int]:
    """
    Add training embedding for person

    Args:
        person_id: Person ID
        img: Image as numpy array
        image_path: Optional path to source image
        is_primary: Mark as primary embedding

    Returns:
        embedding_id if successful, None otherwise
    """
    try:
        # Detect faces and extract embedding
        faces = detect_faces(img)

        if not faces:
            print(f"[face_recognition.py][add_training_embedding] ✗ No faces detected in image")
            return None

        if len(faces) > 1:
            print(f"[face_recognition.py][add_training_embedding] Warning: Multiple faces detected, using first")

        face = faces[0]
        embedding = face['embedding']
        confidence = face['confidence']
        bbox = face['bbox']

        # Compute image hash
        img_hash = compute_image_hash(img)

        # Insert into database
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO face_embeddings
            (person_id, embedding, image_path, image_hash, face_confidence, face_bbox, is_primary)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING embedding_id
        """, (person_id, embedding, image_path, img_hash, confidence, json.dumps(bbox), is_primary))

        embedding_id = cursor.fetchone()[0]

        # Update person's training_image_count
        cursor.execute("""
            UPDATE face_persons
            SET training_image_count = (
                SELECT COUNT(*) FROM face_embeddings WHERE person_id = %s
            )
            WHERE person_id = %s
        """, (person_id, person_id))

        conn.commit()
        cursor.close()
        conn.close()

        print(f"[face_recognition.py][add_training_embedding] ✓ Added embedding {embedding_id} for person {person_id}")
        return embedding_id

    except psycopg2.IntegrityError as e:
        print(f"[face_recognition.py][add_training_embedding] ✗ Duplicate image (hash already exists)")
        return None
    except Exception as e:
        print(f"[face_recognition.py][add_training_embedding] ✗ Error adding embedding: {e}")
        return None


def get_person_embeddings(person_id: int) -> List[List[float]]:
    """
    Get all embeddings for person

    Args:
        person_id: Person ID

    Returns:
        List of 512-dim embeddings
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT embedding FROM face_embeddings
            WHERE person_id = %s
            ORDER BY is_primary DESC, face_confidence DESC
        """, (person_id,))

        embeddings = [row[0] for row in cursor.fetchall()]
        cursor.close()
        conn.close()

        return embeddings

    except Exception as e:
        print(f"[face_recognition.py][get_person_embeddings] ✗ Error getting embeddings: {e}")
        return []


def compute_average_embedding(person_id: int) -> Optional[np.ndarray]:
    """
    Compute average embedding for person (improves matching accuracy)

    Args:
        person_id: Person ID

    Returns:
        Average embedding as numpy array or None if no embeddings
    """
    embeddings = get_person_embeddings(person_id)

    if not embeddings:
        return None

    # Convert to numpy and compute mean
    emb_array = np.array(embeddings)
    avg_embedding = np.mean(emb_array, axis=0)

    # Normalize (important for cosine similarity)
    avg_embedding = avg_embedding / np.linalg.norm(avg_embedding)

    return avg_embedding


# ============================================================================
# Face Recognition & Matching
# ============================================================================

def find_best_match(face_embedding: List[float], similarity_threshold: float = None,
                   top_k: int = 5) -> List[Dict[str, Any]]:
    """
    Find best matching persons for face embedding using HNSW similarity search

    Args:
        face_embedding: 512-dim embedding to match
        similarity_threshold: Minimum similarity (default from config)
        top_k: Number of top matches to return

    Returns:
        List of match dictionaries with keys:
            - person_id
            - name
            - display_name
            - similarity: Cosine similarity (0-1, higher is better)
            - avg_similarity: Average similarity across all person's embeddings
    """
    if similarity_threshold is None:
        similarity_threshold = config.FACE_SIMILARITY_THRESHOLD

    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Multi-stage matching strategy:
        # 1. Find candidate persons using HNSW index (fast, approximate)
        # 2. Compute average similarity across all person's embeddings (accurate)
        # 3. Filter by threshold and sort

        # Query: Find top matches per person using HNSW index
        cursor.execute("""
            WITH embedding_matches AS (
                SELECT
                    e.person_id,
                    e.embedding_id,
                    (1 - (e.embedding <=> %s::vector))::float AS similarity
                FROM face_embeddings e
                JOIN face_persons p ON e.person_id = p.person_id
                WHERE p.enabled = true
                ORDER BY e.embedding <=> %s::vector
                LIMIT %s
            ),
            person_avg_similarity AS (
                SELECT
                    person_id,
                    AVG(similarity) AS avg_similarity,
                    MAX(similarity) AS max_similarity,
                    COUNT(*) AS embedding_count
                FROM embedding_matches
                GROUP BY person_id
            )
            SELECT
                p.person_id,
                p.name,
                p.display_name,
                p.relationship,
                p.training_image_count,
                pas.avg_similarity,
                pas.max_similarity,
                pas.embedding_count
            FROM person_avg_similarity pas
            JOIN face_persons p ON pas.person_id = p.person_id
            WHERE pas.avg_similarity >= %s
            ORDER BY pas.avg_similarity DESC
            LIMIT %s
        """, (face_embedding, face_embedding, top_k * 10, similarity_threshold, top_k))

        matches = cursor.fetchall()
        cursor.close()
        conn.close()

        results = [dict(match) for match in matches]

        if results:
            print(f"[face_recognition.py][find_best_match] Found {len(results)} matches (threshold: {similarity_threshold})")
            for match in results:
                print(f"  - {match['name']}: {match['avg_similarity']:.3f} avg, {match['max_similarity']:.3f} max")
        else:
            print(f"[face_recognition.py][find_best_match] No matches found (threshold: {similarity_threshold})")

        return results

    except Exception as e:
        print(f"[face_recognition.py][find_best_match] ✗ Error finding match: {e}")
        return []


def recognize_face(img: np.ndarray, similarity_threshold: float = None) -> List[Dict[str, Any]]:
    """
    Detect and recognize faces in image

    Args:
        img: Image as numpy array
        similarity_threshold: Minimum similarity for match

    Returns:
        List of recognition results with keys:
            - bbox: Face bounding box [x1, y1, x2, y2]
            - confidence: Detection confidence
            - embedding: 512-dim embedding
            - matches: List of person matches (sorted by similarity)
            - best_match: Best matching person (if any)
    """
    # Detect faces
    faces = detect_faces(img)

    if not faces:
        print(f"[face_recognition.py][recognize_face] No faces detected")
        return []

    results = []
    for face in faces:
        # Find matches for this face
        matches = find_best_match(face['embedding'], similarity_threshold)

        result = {
            'bbox': face['bbox'],
            'confidence': face['confidence'],
            'embedding': face['embedding'],
            'matches': matches,
            'best_match': matches[0] if matches else None
        }

        results.append(result)

    print(f"[face_recognition.py][recognize_face] Recognized {len([r for r in results if r['best_match']])} / {len(results)} faces")

    return results


# ============================================================================
# Camera Management
# ============================================================================

def get_camera(camera_id: int) -> Optional[Dict[str, Any]]:
    """Get camera by ID"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cursor.execute("SELECT * FROM face_cameras WHERE camera_id = %s", (camera_id,))
        camera = cursor.fetchone()
        cursor.close()
        conn.close()

        return dict(camera) if camera else None

    except Exception as e:
        print(f"[face_recognition.py][get_camera] ✗ Error: {e}")
        return None


def get_camera_by_name(name: str) -> Optional[Dict[str, Any]]:
    """Get camera by name"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cursor.execute("SELECT * FROM face_cameras WHERE name = %s", (name,))
        camera = cursor.fetchone()
        cursor.close()
        conn.close()

        return dict(camera) if camera else None

    except Exception as e:
        print(f"[face_recognition.py][get_camera_by_name] ✗ Error: {e}")
        return None


def list_cameras(enabled_only: bool = True) -> List[Dict[str, Any]]:
    """List all cameras"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        query = "SELECT * FROM face_cameras"
        if enabled_only:
            query += " WHERE enabled = true"
        query += " ORDER BY name"

        cursor.execute(query)
        cameras = cursor.fetchall()
        cursor.close()
        conn.close()

        return [dict(camera) for camera in cameras]

    except Exception as e:
        print(f"[face_recognition.py][list_cameras] ✗ Error: {e}")
        return []


# ============================================================================
# Statistics & Logging
# ============================================================================

def log_recognition(person_id: Optional[int], camera_id: Optional[int],
                   confidence: float, face_embedding: List[float],
                   face_bbox: List[float], trigger_type: str = 'manual',
                   session_id: str = None, is_unknown: bool = False) -> Optional[int]:
    """
    Log recognition event to database

    Args:
        person_id: Matched person ID (None if unknown)
        camera_id: Camera ID
        confidence: Recognition confidence
        face_embedding: 512-dim embedding
        face_bbox: Bounding box [x1, y1, x2, y2]
        trigger_type: Type of trigger (background_monitor, manual, mcp_tool)
        session_id: Chat session ID (if applicable)
        is_unknown: True if unknown face

    Returns:
        log_id if successful, None otherwise
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO face_recognition_log
            (person_id, camera_id, confidence, face_embedding, face_bbox,
             trigger_type, session_id, is_unknown)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING log_id
        """, (person_id, camera_id, confidence, face_embedding, json.dumps(face_bbox),
              trigger_type, session_id, is_unknown))

        log_id = cursor.fetchone()[0]

        # Update person statistics if recognized
        if person_id:
            cursor.execute("""
                UPDATE face_persons
                SET recognition_count = recognition_count + 1,
                    last_seen = NOW()
                WHERE person_id = %s
            """, (person_id,))

        conn.commit()
        cursor.close()
        conn.close()

        return log_id

    except Exception as e:
        print(f"[face_recognition.py][log_recognition] ✗ Error logging recognition: {e}")
        return None


def get_statistics() -> Dict[str, Any]:
    """Get face recognition system statistics"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Get various statistics
        cursor.execute("""
            SELECT
                (SELECT COUNT(*) FROM face_persons WHERE enabled = true) AS persons_count,
                (SELECT COUNT(*) FROM face_embeddings) AS embeddings_count,
                (SELECT COUNT(*) FROM face_cameras WHERE enabled = true) AS cameras_count,
                (SELECT COUNT(*) FROM face_recognition_log
                 WHERE recognized_at > NOW() - INTERVAL '24 hours') AS recognitions_24h,
                (SELECT COUNT(*) FROM face_recognition_log
                 WHERE recognized_at > NOW() - INTERVAL '7 days') AS recognitions_7d,
                (SELECT COUNT(*) FROM face_presence_state WHERE is_present = true) AS currently_present
        """)

        stats = cursor.fetchone()
        cursor.close()
        conn.close()

        return dict(stats)

    except Exception as e:
        print(f"[face_recognition.py][get_statistics] ✗ Error: {e}")
        return {}


# ============================================================================
# Utility Functions
# ============================================================================

def test_camera_connection(camera_identifier: str) -> bool:
    """
    Test if camera connection works

    Args:
        camera_identifier: Device ID or RTSP URL

    Returns:
        True if successful, False otherwise
    """
    frame = capture_from_camera(camera_identifier)
    return frame is not None


if __name__ == "__main__":
    # Quick test
    print(f"[face_recognition.py] Face Recognition Module")
    print(f"  Model: {config.FACE_RECOGNITION_MODEL}")
    print(f"  Embedding dim: {config.FACE_EMBEDDING_DIM}")
    print(f"  GPU: {config.FACE_USE_GPU}")

    # Test model initialization
    model = get_face_model()
    if model:
        print(f"✓ Model initialized successfully")
    else:
        print(f"✗ Model initialization failed")
