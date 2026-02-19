#!/bin/bash
# Nightly Pipeline Orchestrator
# Runs memory-dependent jobs sequentially with per-stage timeouts
#
# Pipeline: memory_creation → semantic_consolidation → drift_metrics
# Each stage has a timeout. Failure in one stage does NOT prevent later stages.
#
# Cron: 0 3 * * * IRIS_DB_PASSWORD='...' /iris-v3/scripts/nightly_pipeline.sh

export IRIS_DB_PASSWORD='yourpassword'
export PGPASSWORD='yourpassword'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/paths.env"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Logging
LOG_DIR="$PROJECT_ROOT/logs/pipeline"
LOG_FILE="$LOG_DIR/pipeline_$(date +%Y%m%d_%H%M%S).log"
LOCK_FILE="/tmp/iris_nightly_pipeline.lock"

# Stage timeouts (seconds)
MEMORY_TIMEOUT=2700      # 45 minutes
SEMANTIC_TIMEOUT=1800    # 30 minutes
DRIFT_TIMEOUT=900        # 15 minutes

mkdir -p "$LOG_DIR"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"; }
log_error() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $1" | tee -a "$LOG_FILE" >&2; }

log_service_event() {
    PGPASSWORD="$IRIS_DB_PASSWORD" psql -h localhost -U irisuser -d irisdb -c \
        "INSERT INTO service_events (event_type, service_name, source, detail)
         VALUES ('$1', '$2', '$3', '$4');" >> "$LOG_FILE" 2>&1 || true
}

insert_system_message() {
    local escaped="${1//\'/\'\'}"
    PGPASSWORD="$IRIS_DB_PASSWORD" psql -h localhost -U irisuser -d irisdb -c \
        "INSERT INTO chat_history (role, message, c_timestamp)
         VALUES ('system', E'$escaped', NOW());" >> "$LOG_FILE" 2>&1 || true
}

cleanup() {
    rm -f "$LOCK_FILE"
}
trap cleanup EXIT INT TERM

# --- Pipeline lock ---
if [ -f "$LOCK_FILE" ]; then
    log_error "Pipeline already running (lock file exists: $LOCK_FILE)"
    exit 1
fi
touch "$LOCK_FILE"

# --- Run a stage ---
run_stage() {
    local name="$1"
    local script="$2"
    local stage_timeout="$3"
    local stage_start=$(date +%s)

    log ""
    log "=========================================="
    log "STAGE: $name (timeout: $((stage_timeout / 60))m)"
    log "=========================================="

    if [ ! -f "$script" ]; then
        log_error "Script not found: $script"
        return 1
    fi

    timeout --signal=TERM --kill-after=60 "$stage_timeout" bash "$script" >> "$LOG_FILE" 2>&1
    local exit_code=$?

    local stage_end=$(date +%s)
    local stage_duration=$(( (stage_end - stage_start) / 60 ))

    if [ $exit_code -eq 124 ]; then
        log_error "$name TIMED OUT after $((stage_timeout / 60))m"
    elif [ $exit_code -ne 0 ]; then
        log_error "$name FAILED (exit code: $exit_code, ${stage_duration}m)"
    else
        log "$name COMPLETED (${stage_duration}m)"
    fi

    return $exit_code
}

# === PIPELINE ===
PIPELINE_START=$(date +%s)
log "=========================================="
log "NIGHTLY PIPELINE - $(date)"
log "=========================================="

log_service_event "pipeline_start" "nightly_pipeline" "nightly_pipeline" "Pipeline started"

# Stage 1: Memory Creation
run_stage "memory_creation" "$SCRIPT_DIR/nightly_memory_creation.sh" $MEMORY_TIMEOUT
MEMORY_EXIT=$?

# Stage 2: Semantic Consolidation
run_stage "semantic_consolidation" "$SCRIPT_DIR/nightly_semantic_consolidation.sh" $SEMANTIC_TIMEOUT
SEMANTIC_EXIT=$?

# Stage 3: Drift Metrics
run_stage "drift_metrics" "$SCRIPT_DIR/nightly_drift_metrics.sh" $DRIFT_TIMEOUT
DRIFT_EXIT=$?

# === SUMMARY ===
PIPELINE_END=$(date +%s)
PIPELINE_DURATION=$(( (PIPELINE_END - PIPELINE_START) / 60 ))

status_emoji() { [ "$1" -eq 0 ] && echo "ok" || echo "FAILED"; }

SUMMARY="memory=$(status_emoji $MEMORY_EXIT), semantic=$(status_emoji $SEMANTIC_EXIT), drift=$(status_emoji $DRIFT_EXIT), ${PIPELINE_DURATION}m total"

log ""
log "=========================================="
log "PIPELINE COMPLETE: $SUMMARY"
log "=========================================="

log_service_event "pipeline_end" "nightly_pipeline" "nightly_pipeline" "$SUMMARY"

# Only notify Iris if something failed
if [ $MEMORY_EXIT -ne 0 ] || [ $SEMANTIC_EXIT -ne 0 ] || [ $DRIFT_EXIT -ne 0 ]; then
    insert_system_message "Nightly pipeline completed with issues: $SUMMARY"
fi

# Cleanup old logs (keep 30 days)
find "$LOG_DIR" -name "pipeline_*.log" -mtime +30 -delete 2>/dev/null

# Exit with failure if any stage failed
[ $MEMORY_EXIT -eq 0 ] && [ $SEMANTIC_EXIT -eq 0 ] && [ $DRIFT_EXIT -eq 0 ]
