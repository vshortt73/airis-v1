#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.."

# ============================================
# PREFLIGHT: Check inference backend
# ============================================
echo "=== Airis Preflight Checks ==="
echo ""

# Load config from /etc/airis/env (written by bootstrap)
ENV_FILE="/etc/airis/env"
if [ -r "$ENV_FILE" ]; then
    # shellcheck source=/dev/null
    source "$ENV_FILE"
elif [ -f "$ENV_FILE" ]; then
    echo "WARNING: $ENV_FILE exists but is not readable. Run: sudo chmod 640 $ENV_FILE && sudo chown root:$(id -gn) $ENV_FILE"
fi

# Database credentials
DB_NAME="${AIRIS_DB_NAME:-airisdb}"
DB_USER="${AIRIS_DB_USER:-airisuser}"
DB_HOST="${AIRIS_DB_HOST:-localhost}"

if [ -z "$AIRIS_DB_PASSWORD" ]; then
    echo "ERROR: AIRIS_DB_PASSWORD not set."
    echo "  Run ./scripts/bootstrap_airisdb.sh first, or export AIRIS_DB_PASSWORD."
    exit 1
fi
export PGPASSWORD="$AIRIS_DB_PASSWORD"



# Inference server URL (from /etc/airis/env or environment)
INFERENCE_URL="${AIRIS_INFERENCE_URL:-http://localhost:11434}"
echo "Inference server: $INFERENCE_URL"

# Health check
echo -n "Checking inference server... "
if curl -s "${INFERENCE_URL}/v1/models" 2>/dev/null | grep -q '"data"'; then
    echo "✓ Online"
elif curl -s "${INFERENCE_URL}/health" 2>/dev/null | grep -q '"status"'; then
    echo "✓ Online"
else
    echo "✗ Not reachable"
    echo ""
    echo "Inference server is not responding at $INFERENCE_URL"
    echo "Check that the facility server is running and reachable."
    exit 1
fi

# Quick API test
echo -n "Testing chat completions... "
RESPONSE=$(curl -s -X POST "${INFERENCE_URL}/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -d '{"messages":[{"role":"user","content":"hi"}],"max_tokens":1}' 2>/dev/null)

if echo "$RESPONSE" | grep -q '"choices"'; then
    echo "✓ OK"
else
    echo "✗ API not responding"
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
source "$AIRIS_VENV/bin/activate"
python app/main.py
