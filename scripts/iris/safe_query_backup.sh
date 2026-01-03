#!/bin/bash
# Safe Query Script
table=$1
limit=$2

# Estimate token count (simplified example)
token_estimate=$(psql -t -c "SELECT SUM(LENGTH(text)) FROM $table" iris)

# Adjust limit based on token threshold (e.g., 5000 tokens)
adjusted_limit=$((limit * 5000 / token_estimate))

# Output adjusted query
echo "SELECT * FROM $table LIMIT $adjusted_limit;"
