#!/bin/bash
# ============================================================================
# Nightly Dream Script for Iris
# ============================================================================
# Runs automatically via cron at 4:00 AM to create a dream for the previous day
#
# Cron setup:
#   0 4 * * * /iris-v3/scripts/nightly_dream.sh >> /iris-v3/logs/dreams/cron.log 2>&1
# ============================================================================

set -e  # Exit on error
export IRIS_DB_PASSWORD='yourpassword'

# ============================================================================
# CONFIGURATION
# ============================================================================

PROJECT_ROOT="/iris-v3"
VENV_PATH="/venv/iris-v3"
DREAM_MODERATOR="$PROJECT_ROOT/backend/memory/dreams/dream_moderator.py"
LOG_DIR="$PROJECT_ROOT/logs/dreams"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="$LOG_DIR/dream_$TIMESTAMP.log"

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
if [ -z "$IRIS_DB_PASSWORD" ]; then
    echo "⚠ Warning: IRIS_DB_PASSWORD not set in environment" | tee -a "$LOG_FILE"
    echo "  Dream creation may fail if database requires authentication" | tee -a "$LOG_FILE"
fi

echo "" | tee -a "$LOG_FILE"

# ============================================================================
# CHECK OLLAMA SERVICES
# ============================================================================

echo "[2/4] Checking Ollama services..." | tee -a "$LOG_FILE"

# Check Freud Ollama (CPU - gemma2:9b)
if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "⚠ Main Ollama (port 11434) not responding - attempting to start..." | tee -a "$LOG_FILE"
    sudo systemctl start ollama-vision
    sleep 5

    if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        echo "✗ Failed to start main Ollama" | tee -a "$LOG_FILE"
        exit 1
    fi
fi
echo "✓ Freud Ollama running" | tee -a "$LOG_FILE"

# Check main Ollama (Iris - 72B both GPUs)
if ! curl -s http://localhost:11435/api/tags > /dev/null 2>&1; then
    echo "⚠ Vision Ollama (port 11435) not responding - attempting to start..." | tee -a "$LOG_FILE"
    sudo systemctl start ollama
    sleep 5

    if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        echo "✗ Failed to start Ollama" | tee -a "$LOG_FILE"
        exit 1
    fi
fi
echo "✓ Main Ollama running (Iris)" | tee -a "$LOG_FILE"

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

echo "" | tee -a "$LOG_FILE"

# ============================================================================
# CLEANUP & SUMMARY
# ============================================================================

echo "[4/4] Cleanup..." | tee -a "$LOG_FILE"

# Deactivate virtual environment
deactivate 2>/dev/null || true

# Log completion
echo "" | tee -a "$LOG_FILE"
echo "============================================================================" | tee -a "$LOG_FILE"
echo "Dream Script Complete - $(date)" | tee -a "$LOG_FILE"
echo "Exit Code: $EXIT_CODE" | tee -a "$LOG_FILE"
echo "============================================================================" | tee -a "$LOG_FILE"

exit $EXIT_CODE
