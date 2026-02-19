#!/bin/bash
# Smart GPU Resource Orchestrator for Nightly Memory Creation
# Manages Ollama ↔ llama.cpp transitions with health checks and error recovery
# Database password — must be set in environment before running
if [ -z "$AIRIS_DB_PASSWORD" ]; then
    echo "ERROR: AIRIS_DB_PASSWORD not set. Export it before running this script."
    exit 1
fi

set -o pipefail


# Check sudo access (needed for systemctl)
    if ! sudo -n true 2>/dev/null; then
        printf "Script needs passwordless sudo for systemctl"
        printf "Add to /etc/sudoers: $USER ALL=(ALL) NOPASSWD: /bin/systemctl"
        exit 1
    fi