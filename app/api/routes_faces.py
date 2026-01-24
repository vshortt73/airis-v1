"""
Face Recognition REST API Routes

Provides HTTP endpoints for:
- Person management (CRUD)
- Training image upload
- Camera registry (CRUD)
- Recognition testing
- Statistics and monitoring

Follows patterns from routes_vision.py and routes_protocols.py
"""

import os
import sys
import json
from typing import List, Optional, Dict, Any
from pathlib import Path
import base64
from datetime import datetime

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, PROJECT_ROOT)

from app import config
from core import face_recognition as fr
from core import attachments


# ============================================================================
# Router Setup
# ============================================================================

router = APIRouter(prefix="/api/faces", tags=["faces"])


# ============================================================================
# Pydantic Models for Request/Response
# ============================================================================

class PersonCreate(BaseModel):
    name: str = Field(..., description="Unique person name")
    display_name: Optional[str] = Field(None, description="Display name")
    relationship: Optional[str] = Field(None, description="Relationship (owner, family, friend, etc.)")
    notes: Optional[str] = Field(None, description="Notes")
    tags: Optional[List[str]] = Field(None, description="Tags")


class PersonUpdate(BaseModel):
    display_name: Optional[str] = None
    relationship: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[List[str]] = None
    enabled: Optional[bool] = None


class CameraCreate(BaseModel):
    name: str = Field(..., description="Unique camera name")
    camera_type: str = Field(..., description="Camera type: usb, rtsp, ip, file")
    connection_string: str = Field(..., description="Device ID or URL")
    username: Optional[str] = None
    password: Optional[str] = None
    location: Optional[str] = None
    description: Optional[str] = None
    enabled: bool = True
    check_interval_seconds: Optional[int] = None


class CameraUpdate(BaseModel):
    camera_type: Optional[str] = None
    connection_string: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    location: Optional[str] = None
    description: Optional[str] = None
    enabled: Optional[bool] = None
    check_interval_seconds: Optional[int] = None


class RecognizeRequest(BaseModel):
    image_data: str = Field(..., description="Base64-encoded image")
    camera_id: Optional[int] = None
    similarity_threshold: Optional[float] = None


# ============================================================================
# Person Management Endpoints
# ============================================================================

@router.get("/persons")
async def list_persons(enabled_only: bool = True):
    """List all persons"""
    try:
        persons = fr.list_persons(enabled_only=enabled_only)
        return {"success": True, "persons": persons}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/persons/{person_id}")
async def get_person(person_id: int):
    """Get person by ID"""
    person = fr.get_person(person_id)
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")
    return {"success": True, "person": person}


@router.post("/persons")
async def create_person(person: PersonCreate):
    """Create new person"""
    person_id = fr.create_person(
        name=person.name,
        display_name=person.display_name,
        relationship=person.relationship,
        notes=person.notes,
        tags=person.tags
    )

    if person_id is None:
        raise HTTPException(status_code=400, detail="Failed to create person (name may already exist)")

    created_person = fr.get_person(person_id)
    return {"success": True, "person": created_person}


@router.put("/persons/{person_id}")
async def update_person(person_id: int, updates: PersonUpdate):
    """Update person"""
    # Filter out None values
    update_data = {k: v for k, v in updates.dict().items() if v is not None}

    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    success = fr.update_person(person_id, **update_data)

    if not success:
        raise HTTPException(status_code=404, detail="Person not found or update failed")

    updated_person = fr.get_person(person_id)
    return {"success": True, "person": updated_person}


@router.delete("/persons/{person_id}")
async def delete_person(person_id: int):
    """Delete person (CASCADE deletes embeddings)"""
    success = fr.delete_person(person_id)

    if not success:
        raise HTTPException(status_code=404, detail="Person not found")

    return {"success": True, "message": f"Person {person_id} deleted"}


# ============================================================================
# Training Image Upload
# ============================================================================

@router.post("/persons/{person_id}/train")
async def upload_training_images(
    person_id: int,
    files: List[UploadFile] = File(...),
    is_primary: bool = Form(False)
):
    """
    Upload training images for person

    Args:
        person_id: Person ID
        files: List of image files
        is_primary: Mark first image as primary embedding
    """
    print(f"[upload_training_images] Received request for person_id={person_id}, files={len(files)}, is_primary={is_primary}")

    # Verify person exists
    person = fr.get_person(person_id)
    if not person:
        print(f"[upload_training_images] ✗ Person {person_id} not found")
        raise HTTPException(status_code=404, detail="Person not found")

    print(f"[upload_training_images] Person '{person['name']}' has {person['training_image_count']} existing images")

    # Check training image limit
    if person['training_image_count'] + len(files) > config.FACE_MAX_TRAINING_IMAGES:
        print(f"[upload_training_images] ✗ Would exceed max training images")
        raise HTTPException(
            status_code=400,
            detail=f"Would exceed maximum training images ({config.FACE_MAX_TRAINING_IMAGES})"
        )

    results = []
    for idx, file in enumerate(files):
        print(f"[upload_training_images] Processing file {idx+1}/{len(files)}: {file.filename}")
        try:
            # Read image
            image_bytes = await file.read()

            # Load with OpenCV
            img = fr.load_image_from_bytes(image_bytes)
            if img is None:
                results.append({
                    "filename": file.filename,
                    "success": False,
                    "error": "Failed to load image"
                })
                continue

            # Save image to disk
            image_filename = f"{person['name']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{idx}.jpg"
            image_path = os.path.join(config.FACE_TRAINING_IMAGE_PATH, str(person_id), image_filename)

            # Create directory if needed
            os.makedirs(os.path.dirname(image_path), exist_ok=True)

            # Save image
            import cv2
            cv2.imwrite(image_path, img)

            # Add training embedding
            is_first_primary = is_primary and idx == 0
            embedding_id = fr.add_training_embedding(
                person_id=person_id,
                img=img,
                image_path=image_path,
                is_primary=is_first_primary
            )

            if embedding_id:
                results.append({
                    "filename": file.filename,
                    "success": True,
                    "embedding_id": embedding_id,
                    "image_path": image_path
                })
            else:
                results.append({
                    "filename": file.filename,
                    "success": False,
                    "error": "No face detected or duplicate image"
                })

        except Exception as e:
            results.append({
                "filename": file.filename,
                "success": False,
                "error": str(e)
            })

    # Get updated person
    updated_person = fr.get_person(person_id)

    success_count = sum(1 for r in results if r['success'])

    response = {
        "success": True,
        "uploaded": success_count,
        "total": len(files),
        "results": results,
        "person": updated_person
    }

    print(f"[upload_training_images] ✓ Complete: {success_count}/{len(files)} successful")
    return response


@router.get("/persons/{person_id}/embeddings")
async def get_person_embeddings(person_id: int):
    """Get embeddings for person (for debugging/inspection)"""
    embeddings = fr.get_person_embeddings(person_id)
    return {
        "success": True,
        "person_id": person_id,
        "embedding_count": len(embeddings),
        "embeddings": embeddings
    }


# ============================================================================
# Camera Management Endpoints
# ============================================================================

@router.get("/cameras")
async def list_cameras(enabled_only: bool = True):
    """List all cameras"""
    try:
        cameras = fr.list_cameras(enabled_only=enabled_only)
        return {"success": True, "cameras": cameras}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cameras/{camera_id}")
async def get_camera(camera_id: int):
    """Get camera by ID"""
    camera = fr.get_camera(camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    return {"success": True, "camera": camera}


@router.post("/cameras")
async def create_camera(camera: CameraCreate):
    """Create new camera"""
    try:
        import psycopg2
        conn = fr.get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO face_cameras
            (name, camera_type, connection_string, username, password,
             location, description, enabled, check_interval_seconds)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING camera_id
        """, (camera.name, camera.camera_type, camera.connection_string,
              camera.username, camera.password, camera.location,
              camera.description, camera.enabled, camera.check_interval_seconds))

        camera_id = cursor.fetchone()[0]
        conn.commit()
        cursor.close()
        conn.close()

        created_camera = fr.get_camera(camera_id)
        return {"success": True, "camera": created_camera}

    except psycopg2.IntegrityError:
        raise HTTPException(status_code=400, detail="Camera with this name already exists")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/cameras/{camera_id}")
async def update_camera(camera_id: int, updates: CameraUpdate):
    """Update camera"""
    try:
        # Filter out None values
        update_data = {k: v for k, v in updates.dict().items() if v is not None}

        if not update_data:
            raise HTTPException(status_code=400, detail="No fields to update")

        conn = fr.get_db_connection()
        cursor = conn.cursor()

        # Build UPDATE query
        set_clauses = []
        values = []
        for key, value in update_data.items():
            set_clauses.append(f"{key} = %s")
            values.append(value)

        query = f"UPDATE face_cameras SET {', '.join(set_clauses)} WHERE camera_id = %s"
        values.append(camera_id)

        cursor.execute(query, values)
        conn.commit()
        cursor.close()
        conn.close()

        updated_camera = fr.get_camera(camera_id)
        if not updated_camera:
            raise HTTPException(status_code=404, detail="Camera not found")

        return {"success": True, "camera": updated_camera}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/cameras/{camera_id}")
async def delete_camera(camera_id: int):
    """Delete camera"""
    try:
        conn = fr.get_db_connection()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM face_cameras WHERE camera_id = %s", (camera_id,))
        rows_deleted = cursor.rowcount
        conn.commit()
        cursor.close()
        conn.close()

        if rows_deleted == 0:
            raise HTTPException(status_code=404, detail="Camera not found")

        return {"success": True, "message": f"Camera {camera_id} deleted"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cameras/{camera_id}/test")
async def test_camera(camera_id: int):
    """Test camera connection"""
    camera = fr.get_camera(camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    success = fr.test_camera_connection(camera['connection_string'])

    return {
        "success": success,
        "camera_id": camera_id,
        "name": camera['name'],
        "message": "Camera connection successful" if success else "Camera connection failed"
    }


# ============================================================================
# Recognition Endpoints
# ============================================================================

@router.post("/recognize")
async def recognize_face_api(request: RecognizeRequest):
    """
    Recognize faces in uploaded image

    Args:
        request: Recognition request with base64-encoded image

    Returns:
        Recognition results with detected faces and matches
    """
    try:
        # Load image from base64
        img = fr.load_image_from_base64(request.image_data)
        if img is None:
            raise HTTPException(status_code=400, detail="Failed to load image")

        # Recognize faces
        results = fr.recognize_face(img, similarity_threshold=request.similarity_threshold)

        # Log recognitions
        if request.camera_id:
            for result in results:
                if result['best_match']:
                    fr.log_recognition(
                        person_id=result['best_match']['person_id'],
                        camera_id=request.camera_id,
                        confidence=result['best_match']['avg_similarity'],
                        face_embedding=result['embedding'],
                        face_bbox=result['bbox'],
                        trigger_type='api_test',
                        is_unknown=False
                    )
                else:
                    fr.log_recognition(
                        person_id=None,
                        camera_id=request.camera_id,
                        confidence=0.0,
                        face_embedding=result['embedding'],
                        face_bbox=result['bbox'],
                        trigger_type='api_test',
                        is_unknown=True
                    )

        return {
            "success": True,
            "faces_detected": len(results),
            "faces_recognized": len([r for r in results if r['best_match']]),
            "results": results
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/recognize/camera/{camera_id}")
async def recognize_from_camera(camera_id: int, similarity_threshold: Optional[float] = None):
    """
    Capture from camera and recognize faces

    Args:
        camera_id: Camera ID to capture from
        similarity_threshold: Optional custom threshold

    Returns:
        Recognition results
    """
    camera = fr.get_camera(camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    # Capture frame
    img = fr.capture_from_camera(camera['connection_string'])
    if img is None:
        raise HTTPException(status_code=500, detail="Failed to capture from camera")

    # Recognize faces
    results = fr.recognize_face(img, similarity_threshold=similarity_threshold)

    # Log recognitions
    for result in results:
        if result['best_match']:
            fr.log_recognition(
                person_id=result['best_match']['person_id'],
                camera_id=camera_id,
                confidence=result['best_match']['avg_similarity'],
                face_embedding=result['embedding'],
                face_bbox=result['bbox'],
                trigger_type='api_capture',
                is_unknown=False
            )
        else:
            fr.log_recognition(
                person_id=None,
                camera_id=camera_id,
                confidence=0.0,
                face_embedding=result['embedding'],
                face_bbox=result['bbox'],
                trigger_type='api_capture',
                is_unknown=True
            )

    return {
        "success": True,
        "camera": camera['name'],
        "faces_detected": len(results),
        "faces_recognized": len([r for r in results if r['best_match']]),
        "results": results
    }


# ============================================================================
# Presence & Statistics Endpoints
# ============================================================================

@router.get("/presence")
async def get_presence():
    """Get current presence state (who is currently detected)"""
    try:
        import psycopg2.extras
        conn = fr.get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cursor.execute("""
            SELECT * FROM face_presence_current
            ORDER BY entered_at DESC
        """)

        presence = cursor.fetchall()
        cursor.close()
        conn.close()

        return {
            "success": True,
            "count": len(presence),
            "presence": [dict(p) for p in presence]
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_statistics():
    """Get system statistics"""
    try:
        stats = fr.get_statistics()
        return {"success": True, "stats": stats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/monitoring/status")
async def get_monitoring_status():
    """Get background monitoring status"""
    try:
        import psycopg2.extras
        conn = fr.get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Get config
        cursor.execute("SELECT * FROM face_recognition_config WHERE config_id = 1")
        config_row = cursor.fetchone()

        # Get camera status
        cursor.execute("""
            SELECT
                COUNT(*) FILTER (WHERE enabled = true) as enabled_count,
                COUNT(*) FILTER (WHERE enabled = false) as disabled_count,
                COUNT(*) FILTER (WHERE last_checked > NOW() - INTERVAL '5 minutes') as recently_active,
                COUNT(*) FILTER (WHERE error_count > 5) as error_count
            FROM face_cameras
        """)

        camera_stats = cursor.fetchone()

        cursor.close()
        conn.close()

        return {
            "success": True,
            "monitoring_enabled": config_row['monitoring_enabled'] if config_row else False,
            "monitoring_interval_seconds": config_row['monitoring_interval_seconds'] if config_row else 60,
            "cameras": dict(camera_stats) if camera_stats else {}
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Webcam Frame Caching (for browser-pushed frames)
# ============================================================================

# File-based cache for webcam frames (simpler than HTTP between processes)
WEBCAM_CACHE_DIR = "/tmp/iris_webcam_cache"

@router.post("/webcam_frame")
async def cache_webcam_frame(request: dict):
    """
    Cache webcam frame pushed from browser

    Browser captures frames and POSTs them here every 2-3 seconds.
    The webcam_recognize tool reads the latest frame from disk.
    """
    from datetime import datetime
    import base64
    import cv2
    import numpy as np

    try:
        frame_data = request.get('frame')
        if not frame_data:
            raise HTTPException(status_code=400, detail="No frame data provided")

        # Create cache directory if needed
        os.makedirs(WEBCAM_CACHE_DIR, exist_ok=True)

        # Remove data URI prefix if present
        if ',' in frame_data:
            frame_data = frame_data.split(',', 1)[1]

        # Decode base64 to image
        img_bytes = base64.b64decode(frame_data)
        nparr = np.frombuffer(img_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if img is None:
            raise HTTPException(status_code=400, detail="Failed to decode image")

        # Save to disk (overwrite latest)
        timestamp = datetime.now()
        latest_path = os.path.join(WEBCAM_CACHE_DIR, "frame_latest.jpg")
        cv2.imwrite(latest_path, img)

        # Also save with timestamp (keep last 5)
        timestamped_path = os.path.join(WEBCAM_CACHE_DIR, f"frame_{timestamp.strftime('%Y%m%d_%H%M%S')}.jpg")
        cv2.imwrite(timestamped_path, img)

        # Clean up old frames (keep only last 5)
        import glob
        all_frames = sorted(glob.glob(os.path.join(WEBCAM_CACHE_DIR, "frame_*.jpg")))
        if len(all_frames) > 5:
            for old_frame in all_frames[:-5]:
                if 'latest' not in old_frame:  # Don't delete the latest symlink
                    os.remove(old_frame)

        return {"success": True, "cached_at": str(timestamp), "path": latest_path}

    except Exception as e:
        print(f"[cache_webcam_frame] ✗ Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/webcam_frame/status")
async def get_webcam_frame_status():
    """Check if webcam frame is available"""
    from datetime import datetime, timedelta

    latest_path = os.path.join(WEBCAM_CACHE_DIR, "frame_latest.jpg")

    if not os.path.exists(latest_path):
        return {
            "available": False,
            "message": "No webcam frame cached. Enable webcam in chat interface."
        }

    # Check if frame is stale (older than 10 seconds)
    file_mtime = datetime.fromtimestamp(os.path.getmtime(latest_path))
    age = datetime.now() - file_mtime
    stale = age > timedelta(seconds=10)

    return {
        "available": True,
        "stale": stale,
        "age_seconds": age.total_seconds(),
        "cached_at": str(file_mtime),
        "path": latest_path
    }


# ============================================================================
# Health Check
# ============================================================================

@router.get("/health")
async def health_check():
    """Check if face recognition system is operational"""
    try:
        # Test model initialization
        model = fr.get_face_model()
        model_ok = model is not None

        # Test database connection
        conn = fr.get_db_connection()
        conn.close()
        db_ok = True

    except Exception as e:
        return {
            "success": False,
            "model": False,
            "database": False,
            "error": str(e)
        }

    return {
        "success": model_ok and db_ok,
        "model": model_ok,
        "database": db_ok,
        "embedding_dim": config.FACE_EMBEDDING_DIM,
        "gpu_enabled": config.FACE_USE_GPU
    }
