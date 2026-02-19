#!/bin/bash
# Test the trigger by inserting messages into chat_history

# Database password — must be set in environment
export PGPASSWORD="${AIRIS_DB_PASSWORD:?AIRIS_DB_PASSWORD not set}"

echo "========================================="
echo "TESTING TRIGGER SYSTEM"
echo "========================================="
echo ""

# Check current count
echo "Current insert counter:"
psql -h localhost -U "${AIRIS_DB_USER:-airisuser}" -d "${AIRIS_DB_NAME:-airisdb}" -c "SELECT * FROM insert_counter WHERE table_name = 'chat_history';"
echo ""

# Get session ID
SESSION_ID=$(psql -h localhost -U "${AIRIS_DB_USER:-airisuser}" -d "${AIRIS_DB_NAME:-airisdb}" -t -c "SELECT session_id FROM chat_sessions ORDER BY start_time DESC LIMIT 1;" | xargs)

if [ -z "$SESSION_ID" ]; then
    echo "Creating a test session..."
    SESSION_ID=$(uuidgen)
    psql -h localhost -U "${AIRIS_DB_USER:-airisuser}" -d "${AIRIS_DB_NAME:-airisdb}" -c "INSERT INTO chat_sessions (session_id, start_time, end_time, message_count) VALUES ('$SESSION_ID', NOW(), NOW(), 0);"
fi

echo "Using session ID: $SESSION_ID"
echo ""

# Insert 6 test messages (to reach 10 total and trigger the script)
echo "Inserting 6 test messages to trigger the batch processor..."
for i in {1..6}; do
    echo "  Inserting message $i..."
    psql -h localhost -U "${AIRIS_DB_USER:-airisuser}" -d "${AIRIS_DB_NAME:-airisdb}" -c "INSERT INTO chat_history (role, message, session_id, system_version) VALUES ('user', 'Test message $i for trigger testing', '$SESSION_ID', '3.0');"
done

echo ""
echo "Messages inserted. Checking trigger log..."
sleep 2

# Show trigger log
psql -h localhost -U "${AIRIS_DB_USER:-airisuser}" -d "${AIRIS_DB_NAME:-airisdb}" -c "SELECT id, trigger_name, count_value, triggered_script, message, event_time FROM trigger_log ORDER BY event_time DESC LIMIT 15;"

echo ""
echo "========================================="
echo "Check the wrapper log for processing details:"
echo "  tail -f /iris-v2/tmp/wrapper_debug.log"
echo ""
echo "Check live_memories table:"
echo "  psql -h localhost -U "${AIRIS_DB_USER:-airisuser}" -d "${AIRIS_DB_NAME:-airisdb}" -c 'SELECT * FROM live_memories ORDER BY injected_at DESC LIMIT 5;'"
echo "========================================="
