#!/bin/bash

source /venv/iris-v3/bin/activate

/programs/llama.cpp/build/bin/llama-server \
  -m /models/llm_models/qwen/Qwen_Qwen3-32B-Q6_K.gguf\
  --port 11434 \
  --host 0.0.0.0 \
  --ctx-size 26000 \
  --jinja \
  -fa on\
  -ngl 99 \
  -sm none \
  -mg 0 \
  -b 8192 \
  -ub 2048 \
  -t 8 \
  -v \
  --cache-reuse 0 \
  --slots \
  -np 1 \
  --cache-type-k q8_0 \
  --cache-type-v q8_0



