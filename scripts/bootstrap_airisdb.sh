#!/bin/bash
set -e

# ============================================================================
# Airis v1 — Database Bootstrap Script
# Creates airisdb from scratch with empty tables and neutral traits.
# ============================================================================
#
# PREREQUISITES (run as postgres superuser FIRST):
#
#   sudo -u postgres psql -c "CREATE USER airisuser WITH PASSWORD 'yourpassword';"
#   sudo -u postgres psql -c "CREATE DATABASE airisdb OWNER airisuser;"
#   sudo -u postgres psql -d airisdb -c "CREATE EXTENSION IF NOT EXISTS vector;"
#   sudo -u postgres psql -d airisdb -c "CREATE EXTENSION IF NOT EXISTS pgcrypto;"
#
# THEN run this script:
#   export AIRIS_DB_PASSWORD='yourpassword'
#   ./scripts/bootstrap_airisdb.sh
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SQL_DIR="$REPO_ROOT/database/sql"

# Database connection
DB_HOST="${AIRIS_DB_HOST:-localhost}"
DB_USER="${AIRIS_DB_USER:-airisuser}"
DB_NAME="${AIRIS_DB_NAME:-airisdb}"

if [ -z "$AIRIS_DB_PASSWORD" ]; then
    echo "ERROR: AIRIS_DB_PASSWORD not set."
    echo "  export AIRIS_DB_PASSWORD='yourpassword'"
    exit 1
fi
export PGPASSWORD="$AIRIS_DB_PASSWORD"

run_sql() {
    local file="$1"
    local label="$2"
    if [ ! -f "$file" ]; then
        echo "  SKIP (not found): $file"
        return 0
    fi
    echo "  $label"
    psql -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" -f "$file" -q 2>&1 | grep -v "^$" | head -5
}

echo "============================================"
echo "  Airis v1 Database Bootstrap"
echo "  DB: $DB_NAME @ $DB_HOST (user: $DB_USER)"
echo "============================================"
echo ""

# Verify connection
if ! psql -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" -c "SELECT 1" -q 2>/dev/null; then
    echo "ERROR: Cannot connect to $DB_NAME. Did you run the prerequisites?"
    exit 1
fi
echo "✓ Connected to $DB_NAME"
echo ""

# ── PHASE 1: Base Tables ──
echo "── Phase 1: Base Tables ──"
run_sql "$SQL_DIR/create_base_tables.sql"          "Base tables + triggers"
run_sql "$SQL_DIR/create_system_config_table.sql"   "system_config"
run_sql "$SQL_DIR/create_emotional_state_table.sql" "emotional_state"
run_sql "$SQL_DIR/create_short_term_facts.sql"      "short_term_facts"

# ── PHASE 2: Subsystem Tables ──
echo ""
echo "── Phase 2: Subsystem Tables ──"
run_sql "$REPO_ROOT/backend/memory/create_episodic_dreams_table.sql"       "episodic_dreams"
run_sql "$REPO_ROOT/backend/memory/dreams/create_dream_truths_table.sql"   "dream_truths"
run_sql "$REPO_ROOT/create_protocol_tracking_tables.sql"                    "protocol tracking"
run_sql "$SQL_DIR/create_seeds_table.sql"           "seeds"
run_sql "$SQL_DIR/create_knowledge_tables.sql"      "knowledge"
run_sql "$SQL_DIR/create_semantic_memories_table.sql" "semantic_memories"
run_sql "$SQL_DIR/create_face_tables.sql"           "face recognition"
run_sql "$SQL_DIR/create_calendar_events_table.sql" "calendar_events"
run_sql "$SQL_DIR/create_meeting_tables.sql"        "meetings"

# ── PHASE 3: Observability ──
echo ""
echo "── Phase 3: Observability Tables ──"
run_sql "$SQL_DIR/create_service_events_table.sql"  "service_events"
run_sql "$SQL_DIR/create_turn_metrics_table.sql"    "turn_metrics"
run_sql "$SQL_DIR/create_drift_metrics_table.sql"   "drift_metrics"
run_sql "$SQL_DIR/create_drive_wake_log.sql"        "drive_wake_log"
run_sql "$SQL_DIR/create_last_prompt_table.sql"     "last_prompt"
run_sql "$SQL_DIR/create_bloom_tracking.sql"        "bloom_tracking"
run_sql "$SQL_DIR/create_mcp_servers_table.sql"     "mcp_servers"
run_sql "$SQL_DIR/create_drive_state_tables.sql"    "drive_state"

# ── PHASE 4: Configuration ──
echo ""
echo "── Phase 4: Configuration ──"
run_sql "$SQL_DIR/populate_system_config_complete.sql" "system_config (base)"
run_sql "$SQL_DIR/add_sglang_config.sql"              "sglang + CPU-only config"
run_sql "$SQL_DIR/add_activation_config.sql"           "progressive activation thresholds"
run_sql "$SQL_DIR/add_retrieval_v2_config.sql"         "retrieval v2"
run_sql "$SQL_DIR/add_semantic_memory_config.sql"      "semantic memory"
run_sql "$SQL_DIR/add_gap_report_config.sql"           "gap report"
run_sql "$SQL_DIR/add_smart_tool_config.sql"           "smart tool selection"
run_sql "$SQL_DIR/add_repetition_penalty_config.sql"   "repetition penalty"
run_sql "$SQL_DIR/add_node2_optional_flags.sql"        "node2 optional flags"

# ── PHASE 5: Instructions, Protocols, Tools ──
echo ""
echo "── Phase 5: Instructions & Tools ──"
run_sql "$SQL_DIR/insert_optimized_instructions.sql"   "system instructions + protocol"
run_sql "$SQL_DIR/populate_mcp_servers.sql"             "MCP servers"
for tool_file in insert_memory_tools.sql insert_calendar_tools.sql \
                 insert_meeting_tools.sql insert_knowledge_tools.sql \
                 insert_directions_tools.sql insert_creative_tools.sql \
                 insert_face_tools.sql \
                 insert_news_tools.sql insert_webcam_recognize_tool.sql \
                 insert_distributed_health_tool.sql; do
    run_sql "$SQL_DIR/$tool_file" "$tool_file"
done

# ── PHASE 6: Post-Processing ──
echo ""
echo "── Phase 6: Post-Processing ──"
run_sql "$SQL_DIR/update_seed_tool_batch_dismiss.sql"  "seed tool update"
run_sql "$SQL_DIR/update_trait_evaluation_rule.sql"     "trait eval rule"
run_sql "$SQL_DIR/update_knowledge_tool_save.sql"       "knowledge save update"
run_sql "$SQL_DIR/alter_mcp_tools_smart_selection.sql"  "smart selection columns"
run_sql "$SQL_DIR/populate_tool_metadata.sql"           "tool metadata"
run_sql "$SQL_DIR/alter_protocols_blocked_tools.sql"    "protocol blocked tools"
run_sql "$SQL_DIR/convert_all_instructions_to_xml.sql"  "XML instruction format"
run_sql "$SQL_DIR/fix_instruction_103_add_read_directives.sql" "instruction 103 fix"
run_sql "$SQL_DIR/fix_instruction_103_xml_tags.sql"     "instruction 103 XML tags"
run_sql "$SQL_DIR/fix_tool_schemas_anyof.sql"           "tool schema anyOf fix"
run_sql "$SQL_DIR/create_readable_views.sql"            "readable views"
run_sql "$SQL_DIR/create_temporal_views.sql"            "temporal tags + views"

# ── PHASE 7: Neutral Traits ──
echo ""
echo "── Phase 7: Neutral Traits (Bloom Level 0) ──"
psql -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" -q <<'TRAITS_SQL'
-- 5 neutral traits for cold start
-- These are generic relational qualities, not Iris-specific personality
DELETE FROM fulltraits;
INSERT INTO fulltraits (id, name, description, value) VALUES
    (1, 'warmth',     'How warm and approachable the companion feels',   'neutral'),
    (2, 'curiosity',  'How curious and interested in the person',        'neutral'),
    (3, 'patience',   'How patient and unhurried in conversation',       'neutral'),
    (4, 'empathy',    'How empathetic and emotionally attuned',          'neutral'),
    (5, 'humor',      'How playful and willing to use humor',            'neutral');
TRAITS_SQL
echo "  ✓ 5 neutral traits inserted"

# ── PHASE 8: Bloom Tracking Init ──
echo ""
echo "── Phase 8: Bloom Tracking ──"
psql -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" -q <<'BLOOM_SQL'
DELETE FROM bloom_tracking;
INSERT INTO bloom_tracking (bloom_level, total_conversations, total_memories, total_facts)
VALUES (0, 0, 0, 0);
BLOOM_SQL
echo "  ✓ Bloom level 0 (seed)"

# ── Verify ──
echo ""
echo "============================================"
echo "  Verification"
echo "============================================"
psql -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" -c "
SELECT 'tables' AS check, COUNT(*)::TEXT AS result FROM information_schema.tables WHERE table_schema = 'public'
UNION ALL SELECT 'system_config', COUNT(*)::TEXT FROM system_config
UNION ALL SELECT 'instructions', COUNT(*)::TEXT FROM system_instructions WHERE active = true
UNION ALL SELECT 'tools', COUNT(*)::TEXT FROM mcp_tools WHERE enabled = true
UNION ALL SELECT 'traits', COUNT(*)::TEXT FROM fulltraits
UNION ALL SELECT 'bloom_level', bloom_level::TEXT FROM (SELECT bloom_level FROM bloom_tracking LIMIT 1) b
UNION ALL SELECT 'backend', value FROM system_config WHERE key = 'INFERENCE_BACKEND'
UNION ALL SELECT 'embeddings_cpu', value FROM system_config WHERE key = 'EMBEDDINGS_CPU_ONLY';
"

echo ""
echo "✓ Airis database bootstrap complete!"
echo "  Start Airis with: export AIRIS_DB_PASSWORD='yourpassword' && ./scripts/start.sh"
