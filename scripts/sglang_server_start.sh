#!/bin/bash

source "$(dirname "$0")/paths.env"
source "$IRIS_VENV/bin/activate"
export CUDA_VISIBLE_DEVICES=0
python -m sglang.launch_server \
  --model-path "$IRIS_MAIN_MODEL" \
  --port 11434 \
  --host 0.0.0.0 \
  --context-length 40960 \
  --mem-fraction-static 0.95 \
  2>&1 | tee ~/sglang_server.log
