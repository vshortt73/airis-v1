#!/bin/bash
# Quick test runner for dream system
cd /airis-v1/backend/memory/dreams
/venv/airis/bin/python3 dream_moderator.py --dream-type creative_random "$@"
