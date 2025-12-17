#!/bin/bash
# Fix permissions for trigger logging system
# Run this with: sudo ./scripts/fix_trigger_permissions.sh

echo "========================================="
echo "FIXING TRIGGER PERMISSIONS"
echo "========================================="
echo ""

# Option 1: Fix existing log file
echo "Option 1: Fixing existing log file permissions..."
if [ -f "/iris-v2/tmp/wrapper_debug.log" ]; then
    chmod 666 /iris-v2/tmp/wrapper_debug.log
    echo "✓ Fixed permissions on /iris-v2/tmp/wrapper_debug.log"
    ls -la /iris-v2/tmp/wrapper_debug.log
else
    echo "⚠ Log file not found: /iris-v2/tmp/wrapper_debug.log"
fi

echo ""
echo "Option 2: Creating new log file with proper permissions..."
# Option 2: Create new log file in /var/log
touch /var/log/iris_memory_trigger.log
chmod 666 /var/log/iris_memory_trigger.log
chown postgres:postgres /var/log/iris_memory_trigger.log
echo "✓ Created /var/log/iris_memory_trigger.log with postgres ownership"
ls -la /var/log/iris_memory_trigger.log

echo ""
echo "Updating wrapper script to use new log location..."
sed -i.bak 's|LOG_FILE="/iris-v2/tmp/wrapper_debug.log"|LOG_FILE="/var/log/iris_memory_trigger.log"|g' /var/lib/postgresql/scripts/run_processing.sh

echo "✓ Updated wrapper script"
echo "  Backup saved: /var/lib/postgresql/scripts/run_processing.sh.bak"
echo ""

echo "========================================="
echo "PERMISSIONS FIXED!"
echo ""
echo "Next steps:"
echo "1. Reset the counter:"
echo "   psql -h localhost -U irisuser -d irisdb -c \"UPDATE insert_counter SET count_value = 0 WHERE table_name = 'chat_history';\""
echo ""
echo "2. Test the trigger:"
echo "   /iris-v3/scripts/test_trigger.sh"
echo ""
echo "3. Monitor the new log:"
echo "   tail -f /var/log/iris_memory_trigger.log"
echo "========================================="
