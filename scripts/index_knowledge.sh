#!/bin/bash
# Knowledge Base Indexing Script
# Scans configured directories and indexes documents for RAG search
# Called by cron for scheduled indexing (nightly at 3 AM)
# Pattern: Follows nightly_memory_creation.sh

export IRIS_DB_PASSWORD='yourpassword'
export PGPASSWORD='yourpassword'

# Database password — must be set in environment before running
if [ -z "$IRIS_DB_PASSWORD" ]; then
    echo "ERROR: IRIS_DB_PASSWORD not set. Export it before running this script."
    exit 1
fi
set -o pipefail

# ============================================
# CONFIGURATION
# ============================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/paths.env"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_PYTHON="$IRIS_VENV/bin/python"

# Paths
INDEX_SCRIPT="$PROJECT_ROOT/backend/knowledge/indexer.py"

# Logging
LOG_DIR="$PROJECT_ROOT/logs/knowledge_indexing"
LOG_FILE="$LOG_DIR/index_$(date +%Y%m%d_%H%M%S).log"
LOCK_FILE="/tmp/iris_knowledge_indexing.lock"

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
        log_error "Indexing already running (lock file exists)"
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

    # Check indexing script
    if [ ! -f "$INDEX_SCRIPT" ]; then
        log_error "Indexing script not found: $INDEX_SCRIPT"
        exit 1
    fi

    log "✓ All pre-flight checks passed"
    log ""
}

# ============================================
# RUN INDEXING
# ============================================
run_indexing() {
    log "=========================================="
    log "RUNNING KNOWLEDGE BASE INDEXING"
    log "=========================================="

    cd "$PROJECT_ROOT" || return 1
    export PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH"

    log "Executing: $VENV_PYTHON $INDEX_SCRIPT"
    log ""

    "$VENV_PYTHON" "$INDEX_SCRIPT" 2>&1 | tee -a "$LOG_FILE"
    EXIT_CODE=${PIPESTATUS[0]}

    log ""
    if [ $EXIT_CODE -eq 0 ]; then
        log "✓ Indexing completed successfully"
    else
        log_error "Indexing failed (exit code: $EXIT_CODE)"
    fi

    log ""
    return $EXIT_CODE
}

# ============================================
# MAIN
# ============================================
main() {
    local start_time=$(date +%s)

    log "=========================================="
    log "KNOWLEDGE BASE INDEXING"
    log "=========================================="
    log "Start time: $(date)"
    log "Log file: $LOG_FILE"
    log ""

    preflight_checks || exit 1

    INDEXING_EXIT_CODE=0
    run_indexing || INDEXING_EXIT_CODE=$?

    local end_time=$(date +%s)
    local duration_seconds=$((end_time - start_time))
    local duration_minutes=$((duration_seconds / 60))

    log "=========================================="
    if [ $INDEXING_EXIT_CODE -eq 0 ]; then
        log "✓ INDEXING COMPLETED SUCCESSFULLY"
        log "  Duration: ${duration_minutes} minutes (${duration_seconds} seconds)"
    else
        log "✗ INDEXING FAILED"
        log "  Duration: ${duration_minutes} minutes (${duration_seconds} seconds)"
    fi
    log "End time: $(date)"
    log "=========================================="

    # Cleanup old logs (keep 30 days)
    find "$LOG_DIR" -name "index_*.log" -mtime +30 -delete 2>/dev/null

    exit $INDEXING_EXIT_CODE
}

main "$@"
