#!/bin/bash
# Nightly Memory Creation Pipeline
# Uses llama.cpp server on port 11434 (OpenAI-compatible API)
#
# Cron: 0 3 * * * /iris-v3/scripts/nightly_memory_creation.sh
# (runs at 3:00 AM, before semantic consolidation at 3:30 AM)

# Load credentials (set by cron env or /etc/airis/env)
[ -f /etc/airis/env ] && source /etc/airis/env

set -o pipefail

# ============================================
# CONFIGURATION
# ============================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/paths.env"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_PYTHON="$IRIS_VENV/bin/python"

# Paths
TOPIC_SEGMENTATION_SCRIPT="$PROJECT_ROOT/backend/memory/new/topic_segmentation.py"
MEMORY_SCRIPT="$PROJECT_ROOT/backend/memory/new/memory_creation.py"

# Logging
LOG_DIR="$PROJECT_ROOT/logs/memory_creation"
LOG_FILE="$LOG_DIR/nightly_$(date +%Y%m%d_%H%M%S).log"
LOCK_FILE="/tmp/iris_memory_creation.lock"

# llama.cpp server (OpenAI-compatible API)
LLAMA_SERVICE="iris-llama"
LLAMA_PORT=11434
LLAMA_URL="http://localhost:$LLAMA_PORT"

# Timeouts (seconds)
SERVICE_START_TIMEOUT=60
HEALTH_CHECK_RETRIES=10
HEALTH_CHECK_INTERVAL=3

# ============================================
# UTILITIES
# ============================================
mkdir -p "$LOG_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log_error() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $1" | tee -a "$LOG_FILE" >&2
}

# Insert system message into chat history (for Iris awareness)
insert_system_message() {
    local message="$1"

    log "Notifying Iris: $message"

    # Escape single quotes for SQL
    local escaped_message="${message//\'/\'\'}"

    PGPASSWORD="$AIRIS_DB_PASSWORD" psql -h localhost -U "${AIRIS_DB_USER:-airisuser}" -d "${AIRIS_DB_NAME:-airisdb}" -c \
        "INSERT INTO chat_history (role, message, c_timestamp) VALUES ('system', E'$escaped_message', NOW());" \
        >> "$LOG_FILE" 2>&1

    if [ $? -eq 0 ]; then
        log "✓ System message inserted into chat history"
    else
        log_error "Failed to insert system message (non-critical, continuing)"
    fi
}

# Service event logger for gap report system
log_service_event() {
    local event_type="$1"
    local service_name="$2"
    local source="$3"
    local detail="$4"
    PGPASSWORD="$AIRIS_DB_PASSWORD" psql -h localhost -U "${AIRIS_DB_USER:-airisuser}" -d "${AIRIS_DB_NAME:-airisdb}" -c \
        "INSERT INTO service_events (event_type, service_name, source, detail) VALUES ('$event_type', '$service_name', '$source', '$detail');" \
        >> "$LOG_FILE" 2>&1 || true
}

cleanup() {
    log "Cleanup triggered..."

    # Remove lock file
    if [ -f "$LOCK_FILE" ]; then
        rm -f "$LOCK_FILE"
        log "Removed lock file"
    fi
}
trap cleanup EXIT INT TERM

# ============================================
# PRE-FLIGHT CHECKS
# ============================================
preflight_checks() {
    log "=========================================="
    log "PRE-FLIGHT CHECKS"
    log "=========================================="

    # Check lock file
    if [ -f "$LOCK_FILE" ]; then
        log_error "Memory creation already running (lock file exists)"
        log_error "If stale, remove: rm $LOCK_FILE"
        exit 1
    fi
    touch "$LOCK_FILE"

    # Check database password
    if [ -z "$AIRIS_DB_PASSWORD" ]; then
        log_error "AIRIS_DB_PASSWORD not set"
        exit 1
    fi

    # Check Python venv
    if [ ! -f "$VENV_PYTHON" ]; then
        log_error "Python venv not found: $VENV_PYTHON"
        exit 1
    fi

    # Check scripts exist
    if [ ! -f "$TOPIC_SEGMENTATION_SCRIPT" ]; then
        log_error "Topic segmentation script not found: $TOPIC_SEGMENTATION_SCRIPT"
        exit 1
    fi

    if [ ! -f "$MEMORY_SCRIPT" ]; then
        log_error "Memory script not found: $MEMORY_SCRIPT"
        exit 1
    fi

    # Check sudo access (needed for systemctl)
    log "Testing sudo access..."
    if sudo -n systemctl --version >/dev/null 2>&1; then
        log "✓ Passwordless sudo configured for systemctl"
    else
        log_error "Passwordless sudo not configured"
        log_error "Run: sudo bash /tmp/fix-sudoers-captain.sh"
        exit 1
    fi

    log "✓ All pre-flight checks passed"
    log ""
}

# ============================================
# LLAMA.CPP SERVICE CHECK
# ============================================
check_and_start_llama() {
    log "=========================================="
    log "CHECKING LLAMA.CPP SERVICE"
    log "=========================================="

    # Check if llama service is running
    if systemctl is-active --quiet "$LLAMA_SERVICE"; then
        log "✓ $LLAMA_SERVICE already running"

        # Verify API is responding (OpenAI-compatible endpoint)
        if curl -sf "$LLAMA_URL/v1/models" >/dev/null 2>&1; then
            log "✓ llama.cpp API responding on port $LLAMA_PORT"
            log ""
            return 0
        else
            log "⚠ Service running but API not responding - restarting..."
            sudo systemctl restart "$LLAMA_SERVICE"
        fi
    else
        log "$LLAMA_SERVICE not running - starting..."
        sudo systemctl start "$LLAMA_SERVICE"
    fi

    # Wait for service to start
    for i in $(seq 1 $SERVICE_START_TIMEOUT); do
        if systemctl is-active --quiet "$LLAMA_SERVICE"; then
            log "✓ $LLAMA_SERVICE started"
            break
        fi
        sleep 1
    done

    if ! systemctl is-active --quiet "$LLAMA_SERVICE"; then
        log_error "$LLAMA_SERVICE failed to start after ${SERVICE_START_TIMEOUT}s"
        return 1
    fi

    # Health check with retries (OpenAI-compatible endpoint)
    log "Waiting for llama.cpp API to become ready..."
    for i in $(seq 1 $HEALTH_CHECK_RETRIES); do
        if curl -sf "$LLAMA_URL/v1/models" >/dev/null 2>&1; then
            log "✓ llama.cpp API ready (check $i)"
            log ""
            return 0
        fi
        log "Health check $i/$HEALTH_CHECK_RETRIES..."
        sleep $HEALTH_CHECK_INTERVAL
    done

    log_error "llama.cpp API failed health checks after $((HEALTH_CHECK_RETRIES * HEALTH_CHECK_INTERVAL))s"
    return 1
}


# ============================================
# TOPIC SEGMENTATION & MEMORY CREATION
# ============================================
run_topic_segmentation() {
    log "=========================================="
    log "STEP 1/2: RUNNING TOPIC SEGMENTATION"
    log "=========================================="

    cd "$PROJECT_ROOT" || return 1
    export PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH"

    log "Executing: $VENV_PYTHON $TOPIC_SEGMENTATION_SCRIPT"
    log ""

    "$VENV_PYTHON" "$TOPIC_SEGMENTATION_SCRIPT" 2>&1 | tee -a "$LOG_FILE"
    EXIT_CODE=${PIPESTATUS[0]}

    log ""
    if [ $EXIT_CODE -eq 0 ]; then
        log "✓ Topic segmentation completed successfully"
    else
        log_error "Topic segmentation failed (exit code: $EXIT_CODE)"
    fi

    log ""
    return $EXIT_CODE
}

run_memory_creation() {
    log "=========================================="
    log "STEP 2/2: RUNNING MEMORY CREATION"
    log "=========================================="

    cd "$PROJECT_ROOT" || return 1
    export PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH"

    log "Executing: $VENV_PYTHON $MEMORY_SCRIPT"
    log ""

    "$VENV_PYTHON" "$MEMORY_SCRIPT" 2>&1 | tee -a "$LOG_FILE"
    EXIT_CODE=${PIPESTATUS[0]}

    log ""
    if [ $EXIT_CODE -eq 0 ]; then
        log "✓ Memory creation completed successfully"
    else
        log_error "Memory creation failed (exit code: $EXIT_CODE)"
    fi

    log ""
    return $EXIT_CODE
}

# ============================================
# MAIN ORCHESTRATION
# ============================================
main() {
    local start_time=$(date +%s)
    local memories_created=0

    log "=========================================="
    log "NIGHTLY MEMORY CREATION - llama.cpp"
    log "=========================================="
    log "Start time: $(date)"
    log "Log file: $LOG_FILE"
    log ""

    # Pre-flight checks
    preflight_checks || exit 1

    # Ensure llama.cpp is running
    if ! check_and_start_llama; then
        log_error "Failed to ensure llama.cpp is running - ABORTING"
        insert_system_message "Memory processing cancelled - llama.cpp service unavailable."
        exit 1
    fi

    # Notify that memory creation is starting
    insert_system_message "Background memory processing started. Iris remains available during processing."
    log_service_event "memory_start" "nightly_memory" "nightly_memory" "Memory creation started"

    # Run topic segmentation
    SEGMENTATION_EXIT_CODE=0
    if ! run_topic_segmentation; then
        SEGMENTATION_EXIT_CODE=$?
        log_error "Topic segmentation failed - ABORTING memory creation"
        insert_system_message "Memory processing failed during topic segmentation."
        exit 1
    fi

    # Run memory creation (capture output for statistics)
    MEMORY_OUTPUT=$(mktemp)
    "$VENV_PYTHON" "$MEMORY_SCRIPT" > "$MEMORY_OUTPUT" 2>&1
    MEMORY_EXIT_CODE=$?
    cat "$MEMORY_OUTPUT" >> "$LOG_FILE"

    # Extract statistics from Python output
    memories_created=$(grep -oP "Created: \K\d+" "$MEMORY_OUTPUT" 2>/dev/null || echo "0")
    topics_segmented=$(grep -oP "Topics identified: \K\d+" "$LOG_FILE" 2>/dev/null | tail -1 || echo "0")
    error_topics=$(grep -oP "Errors: \K\d+" "$MEMORY_OUTPUT" 2>/dev/null || echo "0")
    rm -f "$MEMORY_OUTPUT"

    # Calculate duration
    local end_time=$(date +%s)
    local duration_seconds=$((end_time - start_time))
    local duration_minutes=$((duration_seconds / 60))

    # Notify completion with accurate error detection
    if [ "$error_topics" -gt 0 ]; then
        insert_system_message "Memory processing encountered errors: $error_topics topics could not be evaluated (LLM unavailable). They will be retried next run. Created $memories_created memories. Duration: ${duration_minutes} minutes."
        log_service_event "memory_end" "nightly_memory" "nightly_memory" "$memories_created created, $error_topics errors (LLM unavailable), ${duration_minutes}m"
    elif [ "$memories_created" -gt 0 ]; then
        insert_system_message "Memory processing completed: $memories_created new memories created from $topics_segmented topics. Duration: ${duration_minutes} minutes."
        log_service_event "memory_end" "nightly_memory" "nightly_memory" "$memories_created created from $topics_segmented topics in ${duration_minutes}m"
    else
        insert_system_message "Memory processing completed: no new memories needed. Duration: ${duration_minutes} minutes."
        log_service_event "memory_end" "nightly_memory" "nightly_memory" "No new memories, ${duration_minutes}m"
    fi

    # Final status
    log "=========================================="
    if [ $MEMORY_EXIT_CODE -eq 0 ] && [ "$error_topics" -eq 0 ]; then
        log "✓ NIGHTLY MEMORY CREATION COMPLETED SUCCESSFULLY"
    else
        log "⚠ NIGHTLY MEMORY CREATION COMPLETED WITH ISSUES"
    fi
    log "  Topics segmented: $topics_segmented"
    log "  Memories created: $memories_created"
    log "  Errors (will retry): $error_topics"
    log "  Duration: ${duration_minutes} minutes (${duration_seconds} seconds)"
    log "End time: $(date)"
    log "=========================================="

    # Cleanup old logs (keep 30 days)
    find "$LOG_DIR" -name "nightly_*.log" -mtime +30 -delete 2>/dev/null

    exit $MEMORY_EXIT_CODE
}

main "$@"
