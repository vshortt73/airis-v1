#!/bin/bash
# Nightly Drift Metrics Computation
# Reads turn_metrics from the last 7 days, computes longitudinal drift metrics.
# Runs after semantic consolidation.
#
# Cron: 0 4 * * * /iris-v3/scripts/nightly_drift_metrics.sh
# (runs at 4:00 AM, 30 min after semantic consolidation)

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

DRIFT_SCRIPT="$PROJECT_ROOT/backend/observability/drift_metrics.py"

# Logging
LOG_DIR="$PROJECT_ROOT/logs/drift_metrics"
LOG_FILE="$LOG_DIR/nightly_$(date +%Y%m%d_%H%M%S).log"
LOCK_FILE="/tmp/iris_drift_metrics.lock"

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
    if [ -f "$LOCK_FILE" ]; then
        rm -f "$LOCK_FILE"
    fi
}
trap cleanup EXIT INT TERM

# ============================================
# MAIN
# ============================================
main() {
    local start_time=$(date +%s)

    log "=========================================="
    log "NIGHTLY DRIFT METRICS COMPUTATION"
    log "=========================================="
    log "Start time: $(date)"
    log ""

    # Check lock file
    if [ -f "$LOCK_FILE" ]; then
        log_error "Drift metrics already running (lock file exists)"
        exit 1
    fi
    touch "$LOCK_FILE"

    # Check prerequisites
    if [ -z "$IRIS_DB_PASSWORD" ]; then
        log_error "IRIS_DB_PASSWORD not set"
        exit 1
    fi

    if [ ! -f "$VENV_PYTHON" ]; then
        log_error "Python venv not found: $VENV_PYTHON"
        exit 1
    fi

    if [ ! -f "$DRIFT_SCRIPT" ]; then
        log_error "Drift metrics script not found: $DRIFT_SCRIPT"
        exit 1
    fi

    log_service_event "drift_start" "nightly_drift" "nightly_drift" "Drift metrics computation started"

    # Run computation
    cd "$PROJECT_ROOT" || exit 1
    export PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH"

    log "Executing: $VENV_PYTHON $DRIFT_SCRIPT --window-days 7"
    "$VENV_PYTHON" "$DRIFT_SCRIPT" --window-days 7 2>&1 | tee -a "$LOG_FILE"
    EXIT_CODE=${PIPESTATUS[0]}

    local end_time=$(date +%s)
    local duration=$((end_time - start_time))

    if [ $EXIT_CODE -eq 0 ]; then
        log "Drift metrics completed successfully (${duration}s)"
        log_service_event "drift_end" "nightly_drift" "nightly_drift" "Completed in ${duration}s"
    else
        log_error "Drift metrics failed (exit code: $EXIT_CODE)"
        log_service_event "drift_end" "nightly_drift" "nightly_drift" "Failed (exit code: $EXIT_CODE)"
    fi

    # Cleanup old logs (keep 30 days)
    find "$LOG_DIR" -name "nightly_*.log" -mtime +30 -delete 2>/dev/null

    exit ${EXIT_CODE:-0}
}

main "$@"
