#!/bin/bash
# Freud server for dream system - gemma-3-4b on GPU 1 (port 11435)

source /venv/iris-v3/bin/activate

export CUDA_VISIBLE_DEVICES=1

/programs/llama.cpp/build/bin/llama-server \
  -m /localmodels/gemma/gemma-3-4b-it-Q5_K_M.gguf \
  --port 11435 \
  --host 0.0.0.0 \
  --ctx-size 16384 \
  --jinja \
  -fa on \
  -ngl 99 \
  -sm none \
  -mg 0 \
  -b 4096 \
  -ub 2048 \
  -t 16 \
  -v \
  --cache-reuse 0 \
  --slots \
  -np 1
