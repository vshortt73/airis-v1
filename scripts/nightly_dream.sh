#!/bin/bash
# ============================================================================
# Nightly Dream Script for Iris
# ============================================================================
# Runs automatically via cron at 4:00 AM to create a dream for the previous day
#
# Cron setup:
#   0 4 * * * /iris-v3/scripts/nightly_dream.sh >> /iris-v3/logs/dreams/cron.log 2>&1
# ============================================================================

export AIRIS_DB_PASSWORD='yourpassword'

# ============================================================================
# CONFIGURATION
# ============================================================================

PROJECT_ROOT="/iris-v3"
VENV_PATH="/venv/iris-v3"
DREAM_MODERATOR="$PROJECT_ROOT/backend/memory/dreams/dream_moderator.py"
LOG_DIR="$PROJECT_ROOT/logs/dreams"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="$LOG_DIR/dream_$TIMESTAMP.log"

# Node2 configuration
NODE2_HOST="node2"
NODE2_USER="captain"
SSH_OPTS="-o ConnectTimeout=10 -o BatchMode=yes"

# Track whether we swapped to Freud (cleanup only needed if we did)
FREUD_STARTED=false

# ============================================================================
# CLEANUP TRAP — runs on ANY exit (success, failure, signal)
# ============================================================================

cleanup() {
    if [ "$FREUD_STARTED" = false ]; then
        return 0  # Never swapped, nothing to restore
    fi

    echo "" | tee -a "$LOG_FILE"
    echo "[4/4] Cleanup - restoring vision service on node2..." | tee -a "$LOG_FILE"

    for attempt in 1 2 3; do
        echo "Stopping Freud service on node2 (attempt $attempt)..." | tee -a "$LOG_FILE"
        ssh $SSH_OPTS ${NODE2_USER}@${NODE2_HOST} \
            "sudo systemctl stop iris-freud" 2>&1 | tee -a "$LOG_FILE" || true
        sleep 2

        echo "Starting Vision service on node2 (attempt $attempt)..." | tee -a "$LOG_FILE"
        ssh $SSH_OPTS ${NODE2_USER}@${NODE2_HOST} \
            "sudo systemctl start iris-vision" 2>&1 | tee -a "$LOG_FILE" || true
        sleep 8

        if curl -sf http://${NODE2_HOST}:11435/health > /dev/null 2>&1; then
            echo "✓ Vision service restored on node2 (port 11435)" | tee -a "$LOG_FILE"
            # Deactivate virtual environment
            deactivate 2>/dev/null || true
            return 0
        fi
        echo "⚠ Vision health check failed (attempt $attempt)" | tee -a "$LOG_FILE"
    done

    echo "✗ CRITICAL: Vision service could not be restored after 3 attempts" | tee -a "$LOG_FILE"
    # Deactivate virtual environment
    deactivate 2>/dev/null || true
    return 1
}

trap cleanup EXIT

# ============================================================================
# SETUP
# ============================================================================

# Create log directory if it doesn't exist
mkdir -p "$LOG_DIR"

# Log start
echo "============================================================================" | tee -a "$LOG_FILE"
echo "Nightly Dream Script - $(date)" | tee -a "$LOG_FILE"
echo "============================================================================" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

# ============================================================================
# ENVIRONMENT SETUP
# ============================================================================

echo "[1/4] Setting up environment..." | tee -a "$LOG_FILE"

# Activate virtual environment
if [ -f "$VENV_PATH/bin/activate" ]; then
    source "$VENV_PATH/bin/activate"
    echo "✓ Virtual environment activated" | tee -a "$LOG_FILE"
else
    echo "✗ Virtual environment not found at $VENV_PATH" | tee -a "$LOG_FILE"
    exit 1
fi

# Set PYTHONPATH
export PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH"
echo "✓ PYTHONPATH set" | tee -a "$LOG_FILE"

# Check for database password
if [ -z "$AIRIS_DB_PASSWORD" ]; then
    echo "⚠ Warning: AIRIS_DB_PASSWORD not set in environment" | tee -a "$LOG_FILE"
    echo "  Dream creation may fail if database requires authentication" | tee -a "$LOG_FILE"
fi

echo "" | tee -a "$LOG_FILE"

# ============================================================================
# CHECK LLAMA.CPP SERVERS & SWAP VISION FOR FREUD ON NODE2
# ============================================================================

echo "[2/4] Setting up llama.cpp servers for dreaming..." | tee -a "$LOG_FILE"

# Check Iris server (port 11434 - Qwen 32B on local GPU 0)
if ! curl -s http://localhost:11434/health > /dev/null 2>&1; then
    echo "⚠ Iris server (port 11434) not responding - attempting to start via systemctl..." | tee -a "$LOG_FILE"
    sudo systemctl start iris-llama
    sleep 15  # Give the large model time to load

    if ! curl -s http://localhost:11434/health > /dev/null 2>&1; then
        echo "✗ Failed to start Iris llama.cpp server" | tee -a "$LOG_FILE"
        exit 1
    fi
fi
echo "✓ Iris llama.cpp server running (port 11434)" | tee -a "$LOG_FILE"

# Swap Vision -> Freud on node2 using systemctl
echo "Stopping Vision service on node2..." | tee -a "$LOG_FILE"
if ! ssh $SSH_OPTS ${NODE2_USER}@${NODE2_HOST} "sudo systemctl stop iris-vision" 2>&1 | tee -a "$LOG_FILE"; then
    echo "⚠ Failed to stop vision (may not be running)" | tee -a "$LOG_FILE"
fi
sleep 2
echo "✓ Vision service stopped on node2" | tee -a "$LOG_FILE"

# Start Freud service on node2 (gemma-3-4b on GPU 0, port 11435)
echo "Starting Freud service on node2 (gemma-3-4b)..." | tee -a "$LOG_FILE"
if ! ssh $SSH_OPTS ${NODE2_USER}@${NODE2_HOST} "sudo systemctl start iris-freud" 2>&1 | tee -a "$LOG_FILE"; then
    echo "✗ SSH failed to start Freud service on node2" | tee -a "$LOG_FILE"
    exit 1
fi
FREUD_STARTED=true
sleep 10  # Give Freud time to load

if ! curl -sf http://${NODE2_HOST}:11435/health > /dev/null 2>&1; then
    echo "✗ Failed to start Freud service on node2 (health check failed)" | tee -a "$LOG_FILE"
    exit 1  # trap will restore vision
fi
echo "✓ Freud service running on node2 (port 11435)" | tee -a "$LOG_FILE"

echo "" | tee -a "$LOG_FILE"

# ============================================================================
# RUN DREAM MODERATOR
# ============================================================================

echo "[3/4] Running dream moderator..." | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

# Run dream moderator for yesterday's conversations
# (Run at 4 AM, so process previous day)
YESTERDAY=$(date -d "yesterday" +%Y-%m-%d)

echo "Processing dreams for: $YESTERDAY" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

# Run with timeout (max 30 minutes)
if timeout 1800 python3 "$DREAM_MODERATOR" --date "$YESTERDAY" 2>&1 | tee -a "$LOG_FILE"; then
    echo "" | tee -a "$LOG_FILE"
    echo "✓ Dream creation successful" | tee -a "$LOG_FILE"
    EXIT_CODE=0
else
    EXIT_CODE=$?
    echo "" | tee -a "$LOG_FILE"
    if [ $EXIT_CODE -eq 124 ]; then
        echo "✗ Dream creation timed out (30 minutes)" | tee -a "$LOG_FILE"
    else
        echo "✗ Dream creation failed with exit code $EXIT_CODE" | tee -a "$LOG_FILE"
    fi
fi

# ============================================================================
# COMPLETION (cleanup runs via trap EXIT)
# ============================================================================

echo "" | tee -a "$LOG_FILE"
echo "============================================================================" | tee -a "$LOG_FILE"
echo "Dream Script Complete - $(date)" | tee -a "$LOG_FILE"
echo "Exit Code: $EXIT_CODE" | tee -a "$LOG_FILE"
echo "============================================================================" | tee -a "$LOG_FILE"

exit $EXIT_CODE
