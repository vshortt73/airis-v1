#!/bin/bash

source /venv/iris-v3/bin/activate
export CUDA_VISIBLE_DEVICES=0
python -m sglang.launch_server \
  --model-path /localmodels/qwen/Qwen3-32B-Q4_K_M.gguf \
  --port 11434 \
  --host 0.0.0.0 \
  --context-length 40960 \
  --mem-fraction-static 0.95 \
  2>&1 | tee ~/sglang_server.log
