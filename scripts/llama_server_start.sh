#!/bin/bash

source /venv/iris-v3/bin/activate
export CUDA_VISIBLE_DEVICES=0
/programs/llama.cpp/build/bin/llama-server \
  -m /localmodels/qwen/Qwen3-32B-Q4_K_M.gguf \
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



