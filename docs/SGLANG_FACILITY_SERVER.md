# sglang Facility Server — Architecture & Test Results

**Date:** 2026-02-18
**Target hardware:** NVIDIA L40S 48GB (enterprise) or equivalent
**Dev/test hardware:** RTX 5090 32GB (consumer — used for all measurements below)
**Model:** Qwen3-32B-Q4_K_M.gguf (Q4_K_M quantization)
**sglang:** v0.5.8.post1 + sgl_kernel 0.3.21+cu130
**Context:** 40,960 tokens

---

## Why sglang

The DAD Foundation deploys one companion box per resident. Each box runs a lightweight client that sends the full prompt (system instructions, traits, facts, memories, dreams, tools, conversation history) to a **facility inference server**. That server must handle many residents concurrently.

**llama.cpp** (current Iris backend) is single-slot: one request at a time, first-come-first-served. With 10 residents, request #10 waits for requests 1-9 to complete.

**sglang** uses RadixAttention — a radix tree of cached KV states — plus continuous batching. Multiple residents' requests are processed in the same GPU forward pass, and overlapping token prefixes are computed once and shared.

---

## The DAD Template Discovery

### Problem

Every resident has a **unique** system prompt (their traits, facts, memories, dreams). With the stock Qwen3 chat template, the token stream looks like:

```
<|im_start|>system
[UNIQUE: resident's personality, memories, facts, dreams]    ← breaks prefix matching
[IDENTICAL: tool definitions across all residents]
<|im_end|>
```

Because the unique content comes first, RadixAttention finds **zero** shared prefix between residents. Each resident's request is computed from scratch.

### Solution

The **DAD template** (`inference/dad_qwen3_template.jinja`) flips the order:

```
<|im_start|>system
[IDENTICAL: tool definitions — ~13,759 tokens with full 41-tool set]   ← shared prefix!
[UNIQUE: resident's personality, memories, facts, dreams]
<|im_end|>
```

This is a one-line structural change in the Jinja2 chat template. The model doesn't care about order within the system block — it processes the full context regardless. But RadixAttention now sees a common prefix across all residents.

### Measured Impact

**Cross-resident cache sharing (2 residents, 8 tools):**

| Template | Jimmy's 1st turn (after Margaret) | Latency |
|----------|----------------------------------|---------|
| Stock Qwen3 | 5 tokens cached (0.3%) | 6.4s |
| DAD template | 1,154 tokens cached (77.8%) | 3.1s |

**Result: 230x more cache sharing, 2x faster first request from a new resident.**

With the full 41-tool production set (13,759 tokens), the shared prefix represents ~33% of the 40K context window — cached once, reused for every resident.

### File

```
inference/dad_qwen3_template.jinja
```

Usage:
```bash
python -m sglang.launch_server \
  --model-path /path/to/Qwen3-32B-Q4_K_M.gguf \
  --chat-template inference/dad_qwen3_template.jinja \
  --tool-call-parser qwen \
  --enable-cache-report \
  --sleep-on-idle \
  --mem-fraction-static 0.90 \
  --context-length 40960 \
  --port 11435
```

---

## Test Results (RTX 5090, dev hardware)

All measurements below taken on a consumer RTX 5090 32GB. Enterprise hardware (L40S 48GB, A100 80GB) will match or exceed these numbers due to larger KV cache pools and higher memory bandwidth.

### 1. Basic Prefix Caching (Single User)

Three sequential requests with the same system prompt:

| Request | Prompt Tokens | Cached | Hit % | Notes |
|---------|--------------|--------|-------|-------|
| Cold start | 450 | 0 | 0% | First request ever |
| Same prefix, new question | 491 | 407 | 82% | System prompt cached |
| Exact repeat | 450 | 441 | 97% | Near-perfect reuse |

### 2. Tool Calling

sglang 0.5.8.post1 with `--tool-call-parser qwen` handles Qwen3 tool calls correctly:

- Single tool calls: model emits proper `tool_calls` array with `finish_reason: "tool_calls"`
- Tool result round-trips: tool call → tool result → follow-up response works
- Multi-tool turns: multiple tool calls in a single assistant response work
- Tool calling verified with both stock and DAD templates

### 3. KV Cache During Tool Loops (Single User, 5 Turns)

Simulated Iris-style conversation with tool use:

| Turn | Prompt Tokens | Cached | Hit % | Notes |
|------|--------------|--------|-------|-------|
| 1 | 450 | 5 | 1% | Cold |
| 2 | 531 | 451 | 85% | Warm |
| 3 | 573 | 533 | 93% | Growing conversation |
| 4 | 829 | 574 | 69% | Tool result insertion |
| 5 | 1,109 | 574 | 52% | Cache eviction starting |

Tool result insertion causes partial cache invalidation (the inserted content shifts subsequent tokens). Cache recovers on the next same-prefix turn.

### 4. Cross-Resident Cache Sharing

See "The DAD Template Discovery" above. Full results:

**Default template:**
| Label | Prompt | Cached | Hit% | Time |
|-------|--------|--------|------|------|
| Margaret Turn 1 (cold) | 1,469 | 5 | 0.3% | 6.4s |
| Margaret Turn 2 (warm) | 1,470 | 1,455 | 99.0% | 2.0s |
| Jimmy Turn 1 (cross-resident) | 1,483 | 5 | **0.3%** | 6.4s |
| Jimmy Turn 2 (warm) | 1,482 | 1,468 | 99.1% | 2.0s |
| Margaret Turn 3 (return) | 1,475 | 1,455 | 98.6% | 2.0s |

**DAD template:**
| Label | Prompt | Cached | Hit% | Time |
|-------|--------|--------|------|------|
| Margaret Turn 1 (cold) | 1,469 | 1,468 | 99.9% | 4.8s |
| Margaret Turn 2 (warm) | 1,470 | 1,455 | 99.0% | 2.1s |
| Jimmy Turn 1 (cross-resident) | 1,483 | 1,154 | **77.8%** | 3.1s |
| Jimmy Turn 2 (warm) | 1,482 | 1,468 | 99.1% | 2.1s |
| Margaret Turn 3 (return) | 1,475 | 1,455 | 98.6% | 2.1s |

### 5. Concurrent Multi-Resident Inference

**5 simulated residents** (Margaret, Jimmy, Dorothy, Frank, Evelyn), each with unique system prompts, personality traits, backstories, and conversation patterns. All sharing the same 8-tool set via DAD template.

#### Sequential Baseline (one at a time)

| Resident | Prompt Tokens | Cached | Hit% | Time |
|----------|--------------|--------|------|------|
| Margaret (cold) | 999 | 0 | 0.0% | 6.0s |
| Jimmy | 1,021 | 817 | 80.0% | 3.5s |
| Dorothy | 1,025 | 817 | 79.7% | 3.6s |
| Frank | 1,038 | 817 | 78.7% | 3.6s |
| Evelyn | 1,025 | 817 | 79.7% | 3.5s |

Total: 20.2s sequential

#### Concurrent Burst (all 5 at once)

| Resident | Prompt Tokens | Cached | Hit% | Time |
|----------|--------------|--------|------|------|
| All 5 residents | ~1,000 each | ~1,000 | 99.9% | 7.2s |

Wall time: **7.2s** for 5 simultaneous requests (2.8x speedup vs sequential)

#### Interleaved Round-Robin (3 turns each, sequential)

| Round | Avg Cache Hit | Avg Latency |
|-------|--------------|-------------|
| Round 1 | 99.9% | 2.9s |
| Round 2 | 98.2% | 3.0s |
| Round 3 | 98.1% | 3.0s |

All 5 residents maintain 98%+ cache hits across 3 rounds of interleaved conversation. RadixAttention retains each resident's branch in the tree.

#### Concurrent Rounds (3 rounds × 5 concurrent)

| Round | Wall Time | Avg Cache Hit |
|-------|-----------|--------------|
| Round 1 | 6.6s | 99.9% |
| Round 2 | 7.0s | 99.9% |
| Round 3 | 6.6s | 99.9% |

**15 total requests in 20.2s wall time. Throughput: 0.74 req/s. 2.2x speedup over sequential.**

---

## Architecture Summary

```
┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│  Margaret's  │  │   Jimmy's   │  │  Dorothy's  │  ... more boxes
│     Box      │  │     Box     │  │     Box     │
│  (client)    │  │  (client)   │  │  (client)   │
└──────┬───────┘  └──────┬───────┘  └──────┬───────┘
       │                 │                 │
       │    Full prompt  │    Full prompt  │
       │    (unique per  │    (unique per  │
       │     resident)   │     resident)   │
       │                 │                 │
       └────────┬────────┴────────┬────────┘
                │                 │
                ▼                 ▼
       ┌──────────────────────────────┐
       │    Facility Inference Server  │
       │    sglang + DAD Template      │
       │    L40S 48GB (enterprise)     │
       │                              │
       │  RadixAttention Cache:       │
       │  ┌─ tools (shared prefix) ─┐ │
       │  │  13,759 tokens CACHED   │ │
       │  │  computed ONCE          │ │
       │  └────────┬────────────────┘ │
       │     ┌─────┼─────┐           │
       │     ▼     ▼     ▼           │
       │   [Marg] [Jim] [Dor] ...   │
       │   unique  unique unique     │
       │   branch  branch branch     │
       └──────────────────────────────┘
```

**Key principle:** One box = one person. The box IS that person's data. No multi-tenant, no resident_id columns. Each box sends its entire unique prompt. The facility server handles concurrency — the boxes don't know about each other.

---

## Hardware Considerations

**Development/testing** was performed on a consumer RTX 5090 (32GB VRAM). Production deployments target enterprise GPUs:

| GPU | VRAM | Est. Concurrent Residents | Notes |
|-----|------|--------------------------|-------|
| RTX 5090 | 32GB | 5-10 | Dev/test only. Consumer card, no ECC. |
| L40S | 48GB | 15-25 | Primary deployment target. 48GB = 50% more KV cache pool. ECC memory, enterprise support. |
| A100 80GB | 80GB | 30-50 | High-capacity facilities. 2.5x the cache pool of 5090. |

The L40S's extra 16GB VRAM over the 5090 directly translates to more concurrent resident cache entries before LRU eviction kicks in. With `--mem-fraction-static 0.90`, that's ~43GB of KV cache pool vs ~29GB on the 5090 — roughly 50% more residents sustained at full cache hit rates.

All test numbers below were measured on the RTX 5090. Enterprise hardware will perform equal or better.

## Configuration Reference

| Flag | Value | Notes |
|------|-------|-------|
| `--model-path` | GGUF file path | Q4_K_M recommended; L40S can run higher quants |
| `--chat-template` | `inference/dad_qwen3_template.jinja` | **Required for cross-resident caching** |
| `--tool-call-parser` | `qwen` | Required for Qwen3 tool calling |
| `--enable-cache-report` | (flag) | Adds `prompt_tokens_details.cached_tokens` to responses |
| `--sleep-on-idle` | (flag) | Reduces CPU from 100% to ~50% when idle |
| `--mem-fraction-static` | `0.90` | More VRAM for KV cache = more concurrent residents |
| `--context-length` | `40960` | Match Iris/Airis context window |
| `--max-running-requests` | (default: auto) | Tune for max concurrent residents |
| `--schedule-policy` | `fcfs` (default) | First-come-first-served; `lpm` for longest-prefix-match |

### sglang Installation

```bash
python -m venv /venv/sglang
source /venv/sglang/bin/activate

# PyTorch (use appropriate CUDA index for your hardware)
pip install torch --index-url https://download.pytorch.org/whl/cu126  # L40S (Ada/Hopper)
# pip install torch --index-url https://download.pytorch.org/whl/cu130  # RTX 5090 (Blackwell)

# sglang
pip install "sglang[all]>=0.5.8"

# sgl_kernel — match your CUDA version
# L40S / A100 / enterprise (cu124):
pip install sgl-kernel
# RTX 5090 / Blackwell (cu130 — needs wheel from GitHub):
# pip install --force-reinstall \
#   "https://github.com/sgl-project/whl/releases/download/v0.3.21/sgl_kernel-0.3.21+cu130-cp310-abi3-manylinux2014_x86_64.whl"
```

---

## Known Issues & Notes

1. **CPU usage**: sglang's scheduler uses busy-polling by default → 100% CPU. Use `--sleep-on-idle` to reduce to ~50%.
2. **GGUF support**: sglang warns "gguf quantization is not fully optimized yet." Works correctly but may have optimization headroom.
3. **Cache eviction under load**: With many residents and long conversations, LRU eviction will start dropping per-resident cache entries. Monitor `cached_tokens` in responses.
4. **Tool list stability**: The DAD template's advantage depends on tools being identical across residents. If tools change, the shared prefix is invalidated. In practice, tools change rarely (deployment-time, not per-turn).

---

*This document records empirical measurements from 2026-02-18 testing on consumer RTX 5090 32GB. Production deployment targets the NVIDIA L40S 48GB. Results will vary with models, quantizations, VRAM capacity, and memory bandwidth — enterprise hardware should match or exceed these numbers.*
