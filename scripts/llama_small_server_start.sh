#!/bin/bash

source /venv/iris-v3/bin/activate

/programs/llama.cpp/build/bin/llama-server \
  -m /models/vision/qwen/Qwen2-VL-7B-Instruct-Q4_K_M.gguf\
  --mmproj /models/vision/qwen/mmproj-Qwen2-VL-7B-Instruct-f32.gguf\
  --port 11435 \
  --host 0.0.0.0 \
  --ctx-size 8192 \
  --jinja \
  -fa on\
  -ngl 99 \
  -sm none \
  -mg 0 \
  -b 8192 \
  -ub 2048 \
  -t 16 \
  -v \
  --cache-reuse 0 \
  --slots \
  -np 1 \



