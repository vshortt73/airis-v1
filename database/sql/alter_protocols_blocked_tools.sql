-- ============================================================================
-- Migrate protocols.tool_usage to blocked_tools (exclusion-based)
-- Changes from "tools you CAN use" to "tools you CAN'T use"
-- New tools are automatically available unless explicitly blocked
-- ============================================================================
-- Run: psql -h localhost -U irisuser -d irisdb -f database/sql/alter_protocols_blocked_tools.sql

-- Step 1: Add the new blocked_tools column
ALTER TABLE protocols ADD COLUMN IF NOT EXISTS blocked_tools JSON DEFAULT '[]'::json;

-- Step 2: Add comment explaining the column
COMMENT ON COLUMN protocols.blocked_tools IS 'JSON array of tool names to exclude from this protocol. New tools are available by default unless listed here.';

-- Step 3: Migrate existing tool_usage data to blocked_tools
-- Logic: tools that were FALSE or missing in tool_usage become blocked_tools
-- This is a complex migration because tool_usage was inclusion-based

-- For each protocol, we need to:
-- 1. Get the list of all enabled tools
-- 2. Compare against tool_usage (which tools were TRUE)
-- 3. Any tool NOT in tool_usage or set to FALSE becomes blocked

-- First, let's see current tool_usage values
SELECT id, name, tool_usage FROM protocols;

-- Migration function to convert inclusion list to exclusion list
DO $$
DECLARE
    protocol_record RECORD;
    all_tools TEXT[];
    allowed_tools TEXT[];
    blocked_tools_array TEXT[];
    tool_name TEXT;
    tool_usage_obj JSONB;
BEGIN
    -- Get all enabled tool names
    SELECT ARRAY_AGG(mt.tool_name)
    INTO all_tools
    FROM mcp_tools mt
    WHERE mt.enabled = true;

    -- Process each protocol
    FOR protocol_record IN SELECT id, name, tool_usage FROM protocols LOOP
        -- If tool_usage is NULL or empty, no tools are blocked (all allowed)
        IF protocol_record.tool_usage IS NULL THEN
            UPDATE protocols SET blocked_tools = '[]'::json WHERE id = protocol_record.id;
            RAISE NOTICE 'Protocol % (id=%): No tool_usage, setting empty blocked_tools', protocol_record.name, protocol_record.id;
            CONTINUE;
        END IF;

        -- Convert to JSONB for easier manipulation
        tool_usage_obj := protocol_record.tool_usage::jsonb;

        -- Find tools that are explicitly FALSE in tool_usage
        -- These become blocked tools
        blocked_tools_array := ARRAY[]::TEXT[];

        -- Check each key in tool_usage
        FOR tool_name IN SELECT jsonb_object_keys(tool_usage_obj) LOOP
            -- If value is explicitly FALSE, add to blocked list
            IF (tool_usage_obj->>tool_name)::boolean = false THEN
                blocked_tools_array := array_append(blocked_tools_array, tool_name);
            END IF;
        END LOOP;

        -- Update the protocol with blocked tools
        UPDATE protocols
        SET blocked_tools = to_json(blocked_tools_array)
        WHERE id = protocol_record.id;

        RAISE NOTICE 'Protocol % (id=%): blocked_tools = %', protocol_record.name, protocol_record.id, blocked_tools_array;
    END LOOP;
END $$;

-- Step 4: Verification - show the migration results
SELECT
    id,
    name,
    tool_usage,
    blocked_tools
FROM protocols
ORDER BY id;

-- Note: We keep tool_usage column for backwards compatibility
-- It can be dropped later after verifying the migration:
-- ALTER TABLE protocols DROP COLUMN tool_usage;
