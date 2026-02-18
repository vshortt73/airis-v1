#!/bin/bash

source "$(dirname "$0")/paths.env"
source "$IRIS_VENV/bin/activate"
export CUDA_VISIBLE_DEVICES=0
"$IRIS_LLAMA_SERVER" \
  -m "$IRIS_MAIN_MODEL" \
  --port 11434 \
  --host 0.0.0.0 \
  -c 40960 \
  --jinja \
  -fa on\
  -ngl 99 \
  -sm none \
  -mg 0 \
  -b 4096 \
  -ub 2048 \
  -t 4\
  -v \
  --cache-reuse 0 \
  --slots \
  -np 1 \
  --log-file ~/llama_server.log



