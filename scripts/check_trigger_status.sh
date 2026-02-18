#!/bin/bash
# Check trigger status and logs

echo "========================================="
echo "TRIGGER STATUS CHECK"
echo "========================================="
echo ""

# Database password
# Database password — must be set in environment
export PGPASSWORD="${IRIS_DB_PASSWORD:?IRIS_DB_PASSWORD not set}"

# Check insert counter
echo "1. INSERT COUNTER STATUS:"
psql -h localhost -U irisuser -d irisdb -c "SELECT * FROM insert_counter WHERE table_name = 'chat_history';"
echo ""

# Check recent trigger logs
echo "2. RECENT TRIGGER LOGS (last 10):"
psql -h localhost -U irisuser -d irisdb -c "SELECT id, trigger_name, count_value, triggered_script, message, error, event_time FROM trigger_log ORDER BY event_time DESC LIMIT 10;"
echo ""

# Check wrapper script log
echo "3. WRAPPER SCRIPT LOG (last 20 lines):"
tail -20 /iris-v2/tmp/wrapper_debug.log
echo ""

# Check live_memories table
echo "4. LIVE_MEMORIES TABLE (last 5 entries):"
psql -h localhost -U irisuser -d irisdb -c "SELECT * FROM live_memories ORDER BY injected_at DESC LIMIT 5;"
echo ""

# Check active triggers
echo "5. ACTIVE TRIGGERS ON chat_history:"
psql -h localhost -U irisuser -d irisdb -c "SELECT trigger_name, event_manipulation, action_statement FROM information_schema.triggers WHERE event_object_table = 'chat_history';"
echo ""

echo "========================================="
echo "To test the trigger, run 6 more chat messages (currently at 4/10)"
echo "Or manually insert test messages with:"
echo "  ./scripts/test_trigger.sh"
echo "========================================="
