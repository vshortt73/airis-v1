#!/bin/bash
export IRIS_DB_PASSWORD='yourpassword'
cd "$(dirname "$0")/.."

# ============================================
# PREFLIGHT: Check Ollama Services
# ============================================
echo "=== Iris Preflight Checks ==="
echo ""

# Detect which Ollama configuration is active
if systemctl is-active --quiet ollama-unified; then
    # Using unified 70B mode
    echo "Configuration: Unified 70B (dual-GPU)"
    echo -n "Checking ollama-unified service (both GPUs, port 11434)... "
    echo "✓ Running"
elif systemctl is-active --quiet ollama; then
    # Using 72B mode with separate vision service
    echo "Configuration: 72B (both GPUs, main service)"

    # Check main Ollama service (GPUs 0+1, port 11434)
    echo -n "Checking ollama service (GPUs 0+1, port 11434)... "
    if systemctl is-active --quiet ollama; then
        echo "✓ Running"
    else
        echo "✗ Not running"
        echo "Attempting to start ollama service..."
        if sudo systemctl start ollama; then
            echo "✓ Started ollama service"
            sleep 2  # Give it time to initialize
        else
            echo "✗ Failed to start ollama service"
            echo "Please start manually: sudo systemctl start ollama"
            exit 1
        fi
    fi

    # Check vision Ollama service (port 11435, separate instance)
    echo -n "Checking ollama-vision service (port 11435)... "
    if systemctl is-active --quiet ollama-vision; then
        echo "✓ Running"
    else
        echo "✗ Not running"
        echo "Attempting to start ollama-vision service..."
        if sudo systemctl start ollama-vision; then
            echo "✓ Started ollama-vision service"
            sleep 2  # Give it time to initialize
        else
            echo "✗ Failed to start ollama-vision service"
            echo "Please start manually: sudo systemctl start ollama-vision"
            exit 1
        fi
    fi
else
    # Neither configuration is running - start unified by default
    echo "No Ollama services running. Starting unified 70B mode..."
    if sudo systemctl start ollama-unified; then
        echo "✓ Started ollama-unified service"
        sleep 3  # Give 70B model time to load
    else
        echo "✗ Failed to start ollama-unified"
        echo "Please check service status: sudo systemctl status ollama-unified"
        exit 1
    fi
fi

# Verify ports are accessible
echo ""
echo "Verifying Ollama endpoints..."

# Always check main port
echo -n "Testing main Ollama (11434)... "
if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "✓ Accessible"
else
    echo "✗ Not accessible"
    echo "Warning: Main Ollama may not be ready"
fi

# Only check vision port in dual mode
if systemctl is-active --quiet ollama-vision; then
    echo -n "Testing vision Ollama (11435)... "
    if curl -s http://localhost:11435/api/tags > /dev/null 2>&1; then
        echo "✓ Accessible"
    else
        echo "✗ Not accessible"
        echo "Warning: Vision Ollama may not be ready"
    fi
fi

echo ""
echo "=== Starting Iris v3 ==="
echo ""

# ============================================
# START APPLICATION
# ============================================
export PYTHONPATH="$(pwd):$PYTHONPATH"
source /venv/iris-v3/bin/activate
python app/main.py
