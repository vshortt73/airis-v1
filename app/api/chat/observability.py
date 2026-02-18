"""
Turn metrics, response embedding, memory influence scoring, response finalization.

Extracted from routes_chat.py lines 2692-2813.
"""

import asyncio
import time as _time
from typing import Optional

from fastapi import WebSocket

from core.token_counter import TokenCounter


async def finalize_response(
    full_response: str,
    active_conversation,
    user_message: str,
) -> str:
    """
    Finalize the response: fact reference parsing, repetition scoring, want detection,
    and saving to conversation.

    Args:
        full_response: The complete streamed response
        active_conversation: Active conversation instance
        user_message: Original user message (for want detection context)

    Returns:
        The cleaned response content (after fact reference stripping)
    """
    if not full_response:
        return full_response

    # Parse fact references
    from core.system_prompt import parse_fact_references, update_fact_references
    cleaned_response, fact_ids = parse_fact_references(full_response)

    if fact_ids:
        print(f"[observability] ├─ FACT TRACKING: {len(fact_ids)} fact(s) ─┤")
        print(f"[observability] │  Fact IDs: {fact_ids}")
        update_fact_references(fact_ids)

    final_content = cleaned_response if fact_ids else full_response
    active_conversation.add_assistant_message(final_content)
    print(f"[observability] ✓ Final response saved")

    # Repetition gate — post-generation scoring (observability only)
    try:
        from core.repetition_gate import score_repetition
        rep_score, rep_phrases = score_repetition(final_content, active_conversation.get_messages())
        if rep_score > 0:
            print(f"[observability] Repetition score: {rep_score} ({len(rep_phrases)} shared phrases)")
        if rep_score >= 0.3:
            print(f"[observability] ⚠ HIGH REPETITION: {rep_phrases[:5]}")
    except Exception as e:
        print(f"[observability] Repetition scoring error: {e}")

    # Append final assistant message to snapshot
    active_conversation.append_to_snapshot({"role": "assistant", "content": final_content})

    # Scan for want expressions (fire-and-forget, don't block response)
    from core.want_detector import process_response_async as detect_wants
    user_text = user_message.lower() if user_message else ""
    garden_query_patterns = [
        "garden", "seeds", "seed", "motivation", "motivations",
        "what do you want", "what are your wants",
        "what do you need", "what are your needs",
        "your desires", "your drives", "your goals"
    ]
    is_garden_query = any(p in user_text for p in garden_query_patterns)

    if not is_garden_query:
        asyncio.create_task(detect_wants(full_response, user_message))
    else:
        print(f"[observability] Skipping want detection - user asked about garden/motivations")

    return final_content


async def capture_turn_metrics(
    turn_metrics: dict,
    full_response: str,
    retrieval_scored: list,
    budget: dict,
):
    """
    Embed response, compute memory influence, and persist turn metrics.

    Args:
        turn_metrics: Mutable dict of accumulated turn metrics
        full_response: Complete response text
        retrieval_scored: List of scored memory dicts from retrieval
        budget: Context budget dict from prompt assembly
    """
    try:
        _turn_start = turn_metrics.get("_turn_start", _time.time())
        _turn_elapsed = int((_time.time() - _turn_start) * 1000)
        turn_metrics["response_time_ms"] = _turn_elapsed
        turn_metrics["response_tokens"] = TokenCounter.count_tokens(full_response) if full_response else 0
        turn_metrics["total_context_tokens"] = budget.get("total_tokens", 0)

        # Embed response and compute memory influence (async, ~50ms)
        if full_response and len(full_response) > 20:
            try:
                from core.embeddings import generate_embedding
                import numpy as np
                resp_emb = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: generate_embedding(full_response[:2000])
                )
                if resp_emb:
                    turn_metrics["response_embedding"] = resp_emb
                    resp_arr = np.array(resp_emb, dtype=np.float32)
                    resp_norm = np.linalg.norm(resp_arr)
                    if resp_norm > 0:
                        resp_arr = resp_arr / resp_norm

                    # Compute memory influence scores
                    if retrieval_scored:
                        influence_scores = []
                        for mem in retrieval_scored:
                            mem_emb = mem.get("emb_minilm") or mem.get("emb_takeaway") or mem.get("emb_key_details")
                            if mem_emb:
                                if isinstance(mem_emb, str):
                                    mem_emb = [float(x) for x in mem_emb.strip("[]").split(",")]
                                mem_arr = np.array(mem_emb, dtype=np.float32)
                                mem_norm = np.linalg.norm(mem_arr)
                                if mem_norm > 0:
                                    mem_arr = mem_arr / mem_norm
                                sim = float(np.dot(resp_arr, mem_arr))
                                influence_scores.append(round(sim, 4))
                            else:
                                influence_scores.append(0.0)
                        turn_metrics["memory_influence_scores"] = influence_scores
                        turn_metrics["max_memory_influence"] = max(influence_scores) if influence_scores else None
                        turn_metrics["unexplained_ratio"] = round(1.0 - max(influence_scores), 4) if influence_scores else None
            except Exception as emb_err:
                print(f"[observability] Response embedding failed (non-fatal): {emb_err}")

        # Persist metrics (fire-and-forget)
        from database.metrics import save_turn_metrics
        asyncio.get_event_loop().run_in_executor(None, lambda: save_turn_metrics(turn_metrics))
    except Exception as metrics_err:
        print(f"[observability] Metrics capture failed (non-fatal): {metrics_err}")


async def send_kv_metrics(websocket: WebSocket, kv_metrics: Optional[dict], turn_metrics: dict):
    """
    Format and send KV cache / performance metrics to the UI.

    Args:
        websocket: WebSocket connection
        kv_metrics: KV cache metrics dict (or None)
        turn_metrics: Mutable turn metrics dict to update
    """
    if not kv_metrics:
        return

    total_tokens = kv_metrics["cache_n"] + kv_metrics["prompt_n"]
    gen_tps = kv_metrics.get("gen_tok_per_sec", 0)
    prompt_tps = kv_metrics.get("prompt_tok_per_sec", 0)
    print(f"[observability] ├─ PERFORMANCE METRICS ─┤")
    print(f"[observability] │  KV: {kv_metrics['cache_n']:,} cached + {kv_metrics['prompt_n']:,} new = {total_tokens:,} tokens ({kv_metrics['efficiency']:.1f}%)")
    print(f"[observability] │  Speed: {gen_tps:.1f} tok/s gen, {prompt_tps:.1f} tok/s prompt")
    await websocket.send_json({
        "type": "kv_cache_metrics",
        "cache_tokens": kv_metrics["cache_n"],
        "prompt_tokens": kv_metrics["prompt_n"],
        "total_tokens": total_tokens,
        "efficiency": round(kv_metrics["efficiency"], 1),
        "gen_tok_per_sec": round(gen_tps, 1),
        "prompt_tok_per_sec": round(prompt_tps, 1),
        "predicted_n": kv_metrics.get("predicted_n", 0),
        "total_ms": kv_metrics.get("predicted_ms", 0) + kv_metrics.get("prompt_ms", 0)
    })

    # Observability: capture KV cache / LLM performance
    turn_metrics["kv_cache_tokens"] = kv_metrics["cache_n"]
    turn_metrics["kv_prompt_tokens"] = kv_metrics["prompt_n"]
    turn_metrics["kv_cache_efficiency"] = round(kv_metrics["efficiency"], 2)
    turn_metrics["gen_tokens_per_sec"] = round(gen_tps, 1)


async def send_completion(
    websocket: WebSocket,
    active_conversation,
    budget: dict,
    full_response: str,
    context_level: str = "FULL",
):
    """
    Send the 'done' message with token counts to the UI.

    Args:
        websocket: WebSocket connection
        active_conversation: Active conversation instance
        budget: Context budget dict
        full_response: Complete response for token counting
        context_level: Context tier string for the UI
    """
    response_tokens = TokenCounter.count_tokens(full_response) if full_response else 0
    final_total_tokens = budget.get('total_tokens', 0) + response_tokens
    max_tokens = budget.get('max_tokens', 32768)

    await websocket.send_json({
        "type": "done",
        "message_count": active_conversation.get_message_count(),
        "context_level": context_level,
        "tokens": {
            "total": final_total_tokens,
            "max": max_tokens,
            "percentage": round((final_total_tokens / max_tokens * 100), 1) if max_tokens > 0 else 0
        }
    })
