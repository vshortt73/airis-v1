#!/bin/bash
# Fix model cache permissions for postgres user
# Run with: sudo ./scripts/fix_model_permissions.sh

echo "========================================="
echo "FIXING MODEL CACHE PERMISSIONS"
echo "========================================="
echo ""

MODEL_CACHE="/home/captain/.cache/huggingface/hub/models--sentence-transformers--all-mpnet-base-v2"

if [ ! -d "$MODEL_CACHE" ]; then
    echo "❌ Model cache not found at: $MODEL_CACHE"
    exit 1
fi

echo "Found model cache at: $MODEL_CACHE"
echo ""

# Option 1: Make cache readable by postgres user
echo "Option 1: Making cache readable to postgres user..."
chmod -R o+rX /home/captain/.cache/huggingface/
echo "✓ Set read permissions on huggingface cache"

# Check and fix .locks directory if it exists
if [ -d "/home/captain/.cache/huggingface/hub/.locks" ]; then
    chmod -R 777 /home/captain/.cache/huggingface/hub/.locks/
    echo "✓ Fixed .locks directory permissions"
fi

# Fix refs directory specifically
if [ -d "$MODEL_CACHE/refs" ]; then
    chmod -R o+rX "$MODEL_CACHE/refs"
    echo "✓ Fixed refs directory permissions"
fi

# Fix snapshots directory
if [ -d "$MODEL_CACHE/snapshots" ]; then
    chmod -R o+rX "$MODEL_CACHE/snapshots"
    echo "✓ Fixed snapshots directory permissions"
fi

echo ""
echo "Testing permissions..."
ls -la "$MODEL_CACHE" | head -10
echo ""
ls -la "$MODEL_CACHE/refs" 2>/dev/null || echo "No refs directory"
echo ""

echo "========================================="
echo "PERMISSIONS FIXED!"
echo ""
echo "Next steps:"
echo "1. Reset the counter:"
echo "   export PGPASSWORD='yourpassword'"
echo "   psql -h localhost -U irisuser -d irisdb -c \"UPDATE insert_counter SET count_value = 0 WHERE table_name = 'chat_history';\""
echo ""
echo "2. Test the trigger:"
echo "   /iris-v3/scripts/test_trigger.sh"
echo ""
echo "3. Wait 60 seconds, then check live_memories:"
echo "   psql -h localhost -U irisuser -d irisdb -c \"SELECT COUNT(*), MAX(injected_at) FROM live_memories;\""
echo ""
echo "4. Check wrapper log:"
echo "   tail -30 /iris-v2/tmp/wrapper_debug.log"
echo "========================================="
