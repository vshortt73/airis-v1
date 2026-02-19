#!/bin/bash
# Safe Query Script with Dynamic Thresholds and Safety Margin

# Parameters
table=$1           # Table to query (e.g., chat_history_readable)
limit=$2           # User's requested limit

# Set thresholds based on table type
case "$table" in
    "chat_history_readable") threshold=5000 ;;
    "episodic_memories_readable") threshold=3000 ;;
    "dreams_readable") threshold=2000 ;;
    *) threshold=4000 ;;  # Default for other tables
esac

# Apply 15% safety margin to threshold
threshold=$((threshold * 85 / 100))

# Sample 100 rows to estimate average token size
avg_tokens=$(PGPASSWORD="${AIRIS_DB_PASSWORD:?AIRIS_DB_PASSWORD not set}" psql -t -h localhost -U "${AIRIS_DB_USER:-airisuser}" -d "${AIRIS_DB_NAME:-airisdb}" -c "
  SELECT AVG(
    LENGTH(COALESCE(message,'')) + 
    LENGTH(COALESCE(summary_context,'')) + 
    LENGTH(COALESCE(takeaway,'')) + 
    LENGTH(COALESCE(key_details,''))
n    + LENGTH(COALESCE(conv_title,))
  ) 
  FROM $table LIMIT 100;
")

# Calculate estimated tokens for requested limit
estimated_tokens=$((avg_tokens * limit))

# Determine safe limit
if [ $estimated_tokens -gt $threshold ]; then
    adjusted_limit=$((threshold / avg_tokens))
else
    adjusted_limit=$limit
fi

# Output results and query
echo "Estimated $estimated_tokens tokens for $limit rows"
echo "Safe limit: $adjusted_limit rows"
echo "SELECT * FROM $table LIMIT $adjusted_limit;"

