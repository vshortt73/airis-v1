#!/bin/bash
table=$1           # episodic_memories_readable
limit=$2           # How many rows you want (e.g., 10)
threshold=3000      # Max tokens to stay within context window

# Step 1: Calculate average tokens per row
# We sample 100 rows to get a realistic average
avg_tokens=$(PGPASSWORD="${AIRIS_DB_PASSWORD:?AIRIS_DB_PASSWORD not set}" psql -t -h localhost -U "${AIRIS_DB_USER:-airisuser}" -d "${AIRIS_DB_NAME:-airisdb}" -c "
  SELECT AVG(
    LENGTH(COALESCE(transcript,'')) + 
    LENGTH(COALESCE(summary_context,'')) + 
    LENGTH(COALESCE(takeaway,'')) + 
    LENGTH(COALESCE(key_details,''))
  ) / 4
  FROM $table LIMIT 100;
")

# Step 2: Estimate tokens for YOUR requested limit
estimated_tokens=$((avg_tokens * limit))

# Step 3: If too big, calculate safe limit
if [ $estimated_tokens > $threshold ]; then
    # Math: if avg is 2800 tokens/row and threshold is 3000
    # Safe limit = 3000 / 2800 = 1 row
    adjusted_limit=$((threshold / avg_tokens))
else
    adjusted_limit=$limit
fi

echo "Estimated $estimated_tokens tokens for $limit rows"
echo "Safe limit: $adjusted_limit rows"
echo "SELECT * FROM $table LIMIT $adjusted_limit;"