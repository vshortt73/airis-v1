#!/bin/bash
export IRIS_DB_PASSWORD='yourpassword'
cd "$(dirname "$0")/.."

# ============================================
# PREFLIGHT: Check inference backend
# ============================================
echo "=== Iris Preflight Checks ==="
echo ""

# Detect backend from database (default: llamacpp)
BACKEND=$(psql -h localhost -U irisuser -d irisdb -t -A -c \
    "SELECT value FROM system_config WHERE key = 'INFERENCE_BACKEND'" 2>/dev/null)
BACKEND=${BACKEND:-llamacpp}
echo "Inference backend: $BACKEND"

if [ "$BACKEND" = "sglang" ]; then
    # SGLang health check
    echo -n "Checking SGLang server (port 11434)... "
    if curl -s http://localhost:11434/v1/models 2>/dev/null | grep -q '"data"'; then
        echo "✓ Running"
    elif curl -s http://localhost:11434/health 2>/dev/null | grep -q '"status"'; then
        echo "✓ Running"
    else
        echo "✗ Not accessible"
        echo ""
        echo "SGLang server is not running on port 11434."
        echo "Start it with:"
        echo "  sudo systemctl start iris-sglang"
        echo "  # or: ./scripts/sglang_server_start.sh"
        echo ""
        exit 1
    fi
else
    # llama-server health check (existing behavior)
    echo -n "Checking llama-server (port 11434)... "
    if curl -s http://localhost:11434/health 2>/dev/null | grep -q '"status":"ok"'; then
        echo "✓ Running"
    else
        echo "✗ Not accessible"
        echo ""
        echo "llama-server is not running on port 11434."
        echo "Please start it manually:"
        echo "  llama-server -m /path/to/model.gguf --port 11434 --ctx-size 32768"
        echo ""
        exit 1
    fi
fi

# Quick API test
echo -n "Testing chat completions endpoint... "
RESPONSE=$(curl -s -X POST http://localhost:11434/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d '{"messages":[{"role":"user","content":"hi"}],"max_tokens":1}' 2>/dev/null)

if echo "$RESPONSE" | grep -q '"choices"'; then
    echo "✓ Accessible"
else
    echo "✗ API not responding correctly"
    echo "Response: $RESPONSE"
    exit 1
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
