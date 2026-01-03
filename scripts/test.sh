#!/bin/bash
# Smart GPU Resource Orchestrator for Nightly Memory Creation
# Manages Ollama ↔ llama.cpp transitions with health checks and error recovery
export IRIS_DB_PASSWORD='yourpassword'

set -o pipefail


# Check sudo access (needed for systemctl)
    if ! sudo -n true 2>/dev/null; then
        printf "Script needs passwordless sudo for systemctl"
        printf "Add to /etc/sudoers: $USER ALL=(ALL) NOPASSWD: /bin/systemctl"
        exit 1
    fi