#!/bin/bash
# Nightly Semantic Memory Consolidation Pipeline
# Clusters episodic memories, consolidates via LLM, saves semantic memories
# Uses llama.cpp server on port 11434 (OpenAI-compatible API)
#
# Cron: 30 3 * * * /iris-v3/scripts/nightly_semantic_consolidation.sh
# (runs 30 min after memory creation at 3:00 AM)

export IRIS_DB_PASSWORD='yourpassword'
export PGPASSWORD='yourpassword'

set -o pipefail

# ============================================
# CONFIGURATION
# ============================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/paths.env"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_PYTHON="$IRIS_VENV/bin/python"

# Paths
SEMANTIC_SCRIPT="$PROJECT_ROOT/backend/memory/new/semantic_consolidation.py"

# Logging
LOG_DIR="$PROJECT_ROOT/logs/semantic_consolidation"
LOG_FILE="$LOG_DIR/nightly_$(date +%Y%m%d_%H%M%S).log"
LOCK_FILE="/tmp/iris_semantic_consolidation.lock"

# llama.cpp server (OpenAI-compatible API)
LLAMA_PORT=11434
LLAMA_URL="http://localhost:$LLAMA_PORT"

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

insert_system_message() {
    local message="$1"
    log "Notifying Iris: $message"
    local escaped_message="${message//\'/\'\'}"
    PGPASSWORD="$IRIS_DB_PASSWORD" psql -h localhost -U irisuser -d irisdb -c \
        "INSERT INTO chat_history (role, message, c_timestamp) VALUES ('system', E'$escaped_message', NOW());" \
        >> "$LOG_FILE" 2>&1

    if [ $? -eq 0 ]; then
        log "System message inserted into chat history"
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
    PGPASSWORD="$IRIS_DB_PASSWORD" psql -h localhost -U irisuser -d irisdb -c \
        "INSERT INTO service_events (event_type, service_name, source, detail) VALUES ('$event_type', '$service_name', '$source', '$detail');" \
        >> "$LOG_FILE" 2>&1 || true
}

cleanup() {
    log "Cleanup triggered..."
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
        log_error "Semantic consolidation already running (lock file exists)"
        log_error "If stale, remove: rm $LOCK_FILE"
        exit 1
    fi
    touch "$LOCK_FILE"

    # Check database password
    if [ -z "$IRIS_DB_PASSWORD" ]; then
        log_error "IRIS_DB_PASSWORD not set"
        exit 1
    fi

    # Check Python venv
    if [ ! -f "$VENV_PYTHON" ]; then
        log_error "Python venv not found: $VENV_PYTHON"
        exit 1
    fi

    # Check script exists
    if [ ! -f "$SEMANTIC_SCRIPT" ]; then
        log_error "Semantic consolidation script not found: $SEMANTIC_SCRIPT"
        exit 1
    fi

    log "All pre-flight checks passed"
    log ""
}

# ============================================
# LLAMA.CPP HEALTH CHECK
# ============================================
check_llama() {
    log "=========================================="
    log "CHECKING LLAMA.CPP SERVICE"
    log "=========================================="

    # Quick check first
    if curl -sf "$LLAMA_URL/v1/models" >/dev/null 2>&1; then
        log "llama.cpp API responding on port $LLAMA_PORT"
        log ""
        return 0
    fi

    # Retry — memory creation may have just restarted it
    log "llama.cpp not responding, retrying..."
    for i in $(seq 1 10); do
        if curl -sf "$LLAMA_URL/v1/models" >/dev/null 2>&1; then
            log "llama.cpp API ready (attempt $i)"
            log ""
            return 0
        fi
        log "Health check $i/10..."
        sleep 3
    done

    log_error "llama.cpp API not responding after 30s"
    return 1
}

# ============================================
# RUN SEMANTIC CONSOLIDATION
# ============================================
run_semantic_consolidation() {
    log "=========================================="
    log "RUNNING SEMANTIC CONSOLIDATION"
    log "=========================================="

    cd "$PROJECT_ROOT" || return 1
    export PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH"

    log "Executing: $VENV_PYTHON $SEMANTIC_SCRIPT"
    log ""

    "$VENV_PYTHON" "$SEMANTIC_SCRIPT" 2>&1 | tee -a "$LOG_FILE"
    EXIT_CODE=${PIPESTATUS[0]}

    log ""
    if [ $EXIT_CODE -eq 0 ]; then
        log "Semantic consolidation completed successfully"
    else
        log_error "Semantic consolidation failed (exit code: $EXIT_CODE)"
    fi

    log ""
    return $EXIT_CODE
}

# ============================================
# MAIN ORCHESTRATION
# ============================================
main() {
    local start_time=$(date +%s)

    log "=========================================="
    log "NIGHTLY SEMANTIC CONSOLIDATION"
    log "=========================================="
    log "Start time: $(date)"
    log "Log file: $LOG_FILE"
    log ""

    # Pre-flight checks
    preflight_checks || exit 1

    # Check llama.cpp is available
    if ! check_llama; then
        log_error "llama.cpp not available - ABORTING"
        insert_system_message "Semantic consolidation cancelled - llama.cpp service unavailable."
        exit 1
    fi

    log_service_event "semantic_start" "nightly_semantic" "nightly_semantic" "Semantic consolidation started"

    # Run consolidation (capture output for stats)
    CONSOLIDATION_OUTPUT=$(mktemp)
    run_semantic_consolidation > "$CONSOLIDATION_OUTPUT" 2>&1 || true
    CONSOLIDATION_EXIT_CODE=${PIPESTATUS[0]:-$?}
    cat "$CONSOLIDATION_OUTPUT" >> "$LOG_FILE"

    # Extract statistics
    memories_created=$(grep -oP "Memories created:\s+\K\d+" "$CONSOLIDATION_OUTPUT" 2>/dev/null || echo "0")
    memories_reinforced=$(grep -oP "Memories reinforced:\s+\K\d+" "$CONSOLIDATION_OUTPUT" 2>/dev/null || echo "0")
    clusters_processed=$(grep -oP "Clusters processed:\s+\K\d+" "$CONSOLIDATION_OUTPUT" 2>/dev/null || echo "0")
    rm -f "$CONSOLIDATION_OUTPUT"

    # Calculate duration
    local end_time=$(date +%s)
    local duration_seconds=$((end_time - start_time))
    local duration_minutes=$((duration_seconds / 60))

    # Notify completion
    if [ "$memories_created" -gt 0 ] || [ "$memories_reinforced" -gt 0 ]; then
        insert_system_message "Semantic consolidation completed: $memories_created new semantic memories created, $memories_reinforced reinforced from $clusters_processed clusters. Duration: ${duration_minutes}m."
        log_service_event "semantic_end" "nightly_semantic" "nightly_semantic" "$memories_created created, $memories_reinforced reinforced from $clusters_processed clusters in ${duration_minutes}m"
    else
        insert_system_message "Semantic consolidation completed: no new semantic memories generated. Duration: ${duration_minutes}m."
        log_service_event "semantic_end" "nightly_semantic" "nightly_semantic" "No new semantic memories, ${duration_minutes}m"
    fi

    # Final status
    log "=========================================="
    log "NIGHTLY SEMANTIC CONSOLIDATION COMPLETE"
    log "  Clusters processed: $clusters_processed"
    log "  Memories created: $memories_created"
    log "  Memories reinforced: $memories_reinforced"
    log "  Duration: ${duration_minutes} minutes (${duration_seconds} seconds)"
    log "End time: $(date)"
    log "=========================================="

    # Cleanup old logs (keep 30 days)
    find "$LOG_DIR" -name "nightly_*.log" -mtime +30 -delete 2>/dev/null

    exit ${CONSOLIDATION_EXIT_CODE:-0}
}

main "$@"
