"""
Input preprocessing: memory retrieval, emotional state, vision, documents.

Extracted from routes_chat.py lines 1426-1676.
"""

import asyncio
import math
import time as _time
from dataclasses import dataclass, field
from typing import Optional, List

from fastapi import WebSocket

from core.node2_check import is_node2_service_enabled
from core.vision_manager import analyze_images_for_conversation
from core.document_processor import process_documents_for_conversation
from core.document_indexer import index_document_to_knowledge_base


@dataclass
class PreprocessResult:
    """Result of preprocessing a user turn."""
    user_message: str
    retrieval_scored: list = field(default_factory=list)
    turn_metrics: dict = field(default_factory=dict)


async def _run_memory_retrieval_inline() -> list:
    """
    Run memory retrieval v2 inline every turn (~200ms with warm model).

    Writes to live_memories table (forensics + prompt assembly reads from it).
    If retrieval fails, live_memories retains last-known-good state.

    Returns:
        List of scored memory dicts with keys: id, final_score, topic_sim,
        emo_congruence, recency, tier (empty list on failure).
    """
    try:
        from backend.memory.memory_retrieval_v2 import run_retrieval_v2, DB_CFG
        t0 = _time.time()
        scored = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: run_retrieval_v2(DB_CFG, top_k=10, insert=True, mode="replace", show=False)
        )
        elapsed = _time.time() - t0
        print(f"[input_processor][memory_retrieval] ✓ Retrieval v2 completed in {elapsed:.3f}s")
        return scored or []
    except Exception as e:
        print(f"[input_processor][memory_retrieval] ✗ Retrieval v2 failed (live_memories unchanged): {e}")
        return []


async def _process_emotional_state(user_message: str, emotional_tracker, turn_metrics: dict):
    """Analyze user message and update Iris's emotional state."""
    if not is_node2_service_enabled('EMOTIONAL_STATE') or not user_message:
        return

    try:
        print(f"[input_processor] ├─ EMOTIONAL STATE PROCESSING ─┤")
        emotional_result = await emotional_tracker.process_message(user_message)
        if emotional_result.get('analysis'):
            dominant = emotional_result.get('dominant_emotions', [])[:3]
            dominant_str = ', '.join([f"{e[0]}:{e[1]:.2f}" for e in dominant])
            print(f"[input_processor] │  Analysis: {emotional_result['analysis'].get('tone', 'unknown')} (intensity: {emotional_result['analysis'].get('intensity', 0):.2f})")
            print(f"[input_processor] │  Dominant emotions: {dominant_str}")
        else:
            print(f"[input_processor] │  No emotional analysis available")

        # Observability: capture emotional state delta
        if emotional_result.get("state_before") and emotional_result.get("state_after"):
            before = emotional_result["state_before"]
            after = emotional_result["state_after"]
            turn_metrics["emotional_state_before"] = before
            turn_metrics["emotional_state_after"] = after
            delta = math.sqrt(sum((after.get(k, 0) - before.get(k, 0)) ** 2 for k in after))
            turn_metrics["emotional_delta"] = round(delta, 4)
            turn_metrics["dominant_emotion"] = max(after, key=after.get) if after else None
    except Exception as e:
        print(f"[input_processor] │  ✗ Emotional state error: {e}")


async def _process_vision(user_images: list, user_message: str,
                          websocket: WebSocket, active_conversation):
    """Process images through the vision model and add analysis to conversation."""
    if not user_images or not is_node2_service_enabled('VISION_ENABLED'):
        return

    print(f"[input_processor] ├─ VISION PROCESSING: {len(user_images)} image(s) ─┤")

    await websocket.send_json({
        "type": "vision_start",
        "image_count": len(user_images)
    })

    try:
        vision_analysis = await analyze_images_for_conversation(
            images=user_images,
            user_message=user_message if user_message else None
        )

        if vision_analysis:
            print(f"[input_processor] │  ✓ Vision analysis complete ({len(vision_analysis)} chars)")

            vision_content = f"[Vision Analysis]\n{vision_analysis}"
            active_conversation.add_tool_message(
                content=vision_content,
                tool_name="vision_analysis"
            )
            active_conversation.append_to_snapshot({
                "role": "tool", "content": vision_content, "tool_name": "vision_analysis"
            })

            await websocket.send_json({
                "type": "vision_complete",
                "success": True
            })
        else:
            print(f"[input_processor] │  ✗ Vision analysis failed")
            await websocket.send_json({
                "type": "vision_complete",
                "success": False,
                "error": "Vision analysis returned no results"
            })

    except Exception as e:
        print(f"[input_processor] │  ✗ Vision error: {e}")
        await websocket.send_json({
            "type": "vision_complete",
            "success": False,
            "error": str(e)
        })


async def _process_documents(user_documents: list, user_message: str,
                             websocket: WebSocket, active_conversation):
    """Extract text from uploaded documents and add to conversation context."""
    if not user_documents:
        return

    print(f"[input_processor] ├─ DOCUMENT PROCESSING: {len(user_documents)} document(s) ─┤")

    await websocket.send_json({
        "type": "document_start",
        "document_count": len(user_documents)
    })

    try:
        document_text, full_documents = await process_documents_for_conversation(
            documents=user_documents,
            user_message=user_message if user_message else None
        )

        if document_text:
            print(f"[input_processor] │  ✓ Document extraction complete ({len(document_text):,} chars)")

            # Launch background indexing for each full document
            for full_doc in full_documents:
                asyncio.create_task(
                    index_document_to_knowledge_base(
                        title=full_doc["title"],
                        full_text=full_doc["full_text"],
                        file_type=full_doc["file_type"],
                        category="uploaded_documents"
                    )
                )
                print(f"[input_processor] │  → Queued '{full_doc['title']}' for knowledge base indexing")

            # Add document content to conversation as tool message
            kb_note = ""
            if full_documents:
                kb_note = "\n[Note: This document has been automatically saved to the knowledge base.]"
            doc_content = f"[Document Content]\n{document_text}{kb_note}"
            active_conversation.add_tool_message(
                content=doc_content,
                tool_name="document_extraction"
            )
            active_conversation.append_to_snapshot({
                "role": "tool", "content": doc_content, "tool_name": "document_extraction"
            })

            await websocket.send_json({
                "type": "document_complete",
                "success": True,
                "chars_extracted": len(document_text)
            })
        else:
            print(f"[input_processor] │  ✗ Document extraction failed")
            await websocket.send_json({
                "type": "document_complete",
                "success": False,
                "error": "Document extraction returned no results"
            })

    except Exception as e:
        print(f"[input_processor] │  ✗ Document error: {e}")
        await websocket.send_json({
            "type": "document_complete",
            "success": False,
            "error": str(e)
        })


async def preprocess_user_turn(
    data: dict,
    active_conversation,
    emotional_tracker,
    websocket: WebSocket,
) -> PreprocessResult:
    """
    Orchestrate all input preprocessing for a user turn.

    Steps:
        1. Extract message/images/documents from data
        2. Add user message to conversation history
        3. Run memory retrieval
        4. Process emotional state
        5. Process vision input (if images)
        6. Process documents (if documents)

    Args:
        data: Raw WebSocket message data
        active_conversation: Active conversation instance
        emotional_tracker: Emotional state tracker
        websocket: WebSocket connection

    Returns:
        PreprocessResult with all computed state
    """
    user_message = data.get("message", "").strip()
    user_images = data.get("images", [])
    user_documents = data.get("documents", [])
    sender = data.get("sender", "user")

    # Add user message with images to history
    active_conversation.add_user_message(
        user_message,
        images=user_images if user_images else None,
        sender=sender
    )

    # Append user message to prompt snapshot (if active)
    active_conversation.append_to_snapshot({"role": "user", "content": user_message})

    # Init turn metrics
    _turn_start = _time.time()
    _turn_metrics = {
        "session_id": str(active_conversation.get_session_id()) if active_conversation.get_session_id() else None
    }

    # Memory retrieval (inline, ~200ms)
    retrieval_scored = await _run_memory_retrieval_inline()

    # Capture memory retrieval provenance
    if retrieval_scored:
        _turn_metrics["memories_in_context"] = len(retrieval_scored)
        _turn_metrics["memory_ids"] = [s["id"] for s in retrieval_scored]
        _turn_metrics["memory_tiers"] = [s["tier"] for s in retrieval_scored]
        _turn_metrics["memory_scores"] = [round(s["final_score"], 4) for s in retrieval_scored]
        _turn_metrics["avg_topic_similarity"] = round(sum(s["topic_sim"] for s in retrieval_scored) / len(retrieval_scored), 4)
        _turn_metrics["avg_emotional_congruence"] = round(sum(s["emo_congruence"] for s in retrieval_scored) / len(retrieval_scored), 4)
        _turn_metrics["avg_recency"] = round(sum(s["recency"] for s in retrieval_scored) / len(retrieval_scored), 4)
    else:
        _turn_metrics["memories_in_context"] = 0

    # Emotional state processing
    await _process_emotional_state(user_message, emotional_tracker, _turn_metrics)

    # Vision processing
    await _process_vision(user_images, user_message, websocket, active_conversation)

    # Document processing
    await _process_documents(user_documents, user_message, websocket, active_conversation)

    # Store turn start time in metrics for later use
    _turn_metrics["_turn_start"] = _turn_start

    return PreprocessResult(
        user_message=user_message,
        retrieval_scored=retrieval_scored,
        turn_metrics=_turn_metrics,
    )
