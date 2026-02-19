#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.."

# ============================================
# PREFLIGHT: Check inference backend
# ============================================
echo "=== Airis Preflight Checks ==="
echo ""

# Database credentials — from environment
DB_NAME="${AIRIS_DB_NAME:-airisdb}"
DB_USER="${AIRIS_DB_USER:-airisuser}"
DB_HOST="${AIRIS_DB_HOST:-localhost}"

# Database password — must be set in environment before running
if [ -z "$AIRIS_DB_PASSWORD" ]; then
    echo "ERROR: AIRIS_DB_PASSWORD not set. Export it before running this script."
    echo "  export AIRIS_DB_PASSWORD='yourpassword'"
    exit 1
fi
export PGPASSWORD="$AIRIS_DB_PASSWORD"



# Detect backend from database (default: llamacpp)
BACKEND=$(psql -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" -t -A -c \
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
        echo "  sudo systemctl start airis-sglang"
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
echo "=== Starting Airis ==="
echo ""

# ============================================
# START APPLICATION
# ============================================
export PYTHONPATH="$(pwd):$PYTHONPATH"
source "$SCRIPT_DIR/paths.env"
source "$IRIS_VENV/bin/activate"
python app/main.py
