#!/bin/bash
# Migrate configuration from config.py to PostgreSQL database
# Run this ONCE to set up database-backed configuration

set -e  # Exit on error

echo "============================================"
echo "  Iris Configuration Migration"
echo "  File-based → Database-backed"
echo "============================================"
echo ""

# Check if running from project root
if [ ! -f "app/config.py" ]; then
    echo "✗ Error: Must run from project root (/iris-v3)"
    exit 1
fi

# Check database password
if [ -z "$IRIS_DB_PASSWORD" ]; then
    echo "✗ Error: IRIS_DB_PASSWORD environment variable not set"
    echo "  Export it first: export IRIS_DB_PASSWORD='your_password'"
    exit 1
fi

echo "Step 1: Creating system_config table..."
export PGPASSWORD="$IRIS_DB_PASSWORD"
psql -h iris-desktop -U irisuser -d irisdb -f database/sql/create_system_config_table.sql

if [ $? -ne 0 ]; then
    echo "✗ Failed to create table"
    exit 1
fi

echo "✓ Table created"
echo ""

echo "Step 2: Populating with default values..."
psql -h iris-desktop -U irisuser -d irisdb -f database/sql/populate_system_config.sql

if [ $? -ne 0 ]; then
    echo "✗ Failed to populate config"
    exit 1
fi

echo "✓ Configuration populated"
echo ""

echo "Step 3: Verifying migration..."
COUNT=$(psql -h iris-desktop  -U irisuser -d irisdb -t -c "SELECT COUNT(*) FROM system_config;")
echo "  Found $COUNT configuration entries"

if [ "$COUNT" -lt "20" ]; then
    echo "⚠ Warning: Expected more config entries"
fi

echo ""
echo "============================================"
echo "  Migration Complete!"
echo "============================================"
echo ""
echo "Next steps:"
echo "  1. Review config values: SELECT * FROM system_config;"
echo "  2. Restart Iris server to load database config"
echo "  3. Use admin console to manage configuration"
echo ""
echo "Note: config.py will still be used for bootstrap"
echo "(database connection, critical paths, etc.)"
