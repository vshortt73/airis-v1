#!/bin/bash
cd "$(dirname "$0")/.."
export PYTHONPATH="$(pwd):$PYTHONPATH"
source /venv/iris-v3/bin/activate
python app/main.py
