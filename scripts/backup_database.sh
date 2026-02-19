#!/bin/bash
# Nightly database backup for Iris
# Keeps last 30 days of backups

BACKUP_DIR="/mnt/18tb/backup/iris_db"
DB_NAME="${AIRIS_DB_NAME:-airisdb}"
DB_USER="${AIRIS_DB_USER:-airisuser}"
DB_HOST="localhost"
RETENTION_DAYS=30

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"

# Generate filename with timestamp
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/airisdb_$TIMESTAMP.dump"

# Export password (read from environment or use default location)
export PGPASSWORD="${AIRIS_DB_PASSWORD}"

if [ -z "$PGPASSWORD" ]; then
    echo "Error: AIRIS_DB_PASSWORD not set"
    exit 1
fi

# Create backup
echo "[$TIMESTAMP] Starting backup of $DB_NAME..."
pg_dump -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" -F c -f "$BACKUP_FILE"

if [ $? -eq 0 ]; then
    FILESIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    echo "[$TIMESTAMP] Backup complete: $BACKUP_FILE ($FILESIZE)"

    # Remove backups older than retention period
    DELETED=$(find "$BACKUP_DIR" -name "airisdb_*.dump" -mtime +$RETENTION_DAYS -delete -print | wc -l)
    if [ "$DELETED" -gt 0 ]; then
        echo "[$TIMESTAMP] Removed $DELETED old backup(s)"
    fi
else
    echo "[$TIMESTAMP] Backup FAILED"
    exit 1
fi
