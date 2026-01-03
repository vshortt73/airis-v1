#!/bin/bash
# Quick test runner for dream system
cd /iris-v3/backend/memory/dreams
/venv/iris-v3/bin/python3 dream_moderator.py --dream-type creative_random "$@"
