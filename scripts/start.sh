#!/bin/bash
export IRIS_DB_PASSWORD='yourpassword'
cd "$(dirname "$0")/.."

# ============================================
# PREFLIGHT: Check llama-server
# ============================================
echo "=== Iris Preflight Checks ==="
echo ""

# Check llama-server health endpoint
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
