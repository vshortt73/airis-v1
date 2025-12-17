#!/bin/bash
cd "$(dirname "$0")/.."

# ============================================
# PREFLIGHT: Check Ollama Services
# ============================================
echo "=== Iris Preflight Checks ==="
echo ""

# Check main Ollama service (GPU 0, port 11434)
echo -n "Checking ollama service (GPU 0, port 11434)... "
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

# Check vision Ollama service (GPU 1, port 11435)
echo -n "Checking ollama-vision service (GPU 1, port 11435)... "
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

# Verify ports are accessible
echo ""
echo "Verifying Ollama endpoints..."
echo -n "Testing main Ollama (11434)... "
if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "✓ Accessible"
else
    echo "✗ Not accessible"
    echo "Warning: Main Ollama may not be ready"
fi

echo -n "Testing vision Ollama (11435)... "
if curl -s http://localhost:11435/api/tags > /dev/null 2>&1; then
    echo "✓ Accessible"
else
    echo "✗ Not accessible"
    echo "Warning: Vision Ollama may not be ready"
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
