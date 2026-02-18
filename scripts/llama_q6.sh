#!/bin/bash

source "$(dirname "$0")/paths.env"
source "$IRIS_VENV/bin/activate"

"$IRIS_LLAMA_SERVER" \
  -m "$IRIS_ALT_MODEL" \
  --port 11434 \
  --host 0.0.0.0 \
  -c 32768 \
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
  --cache-type-k q8_0 \
  --cache-type-v q8_0



