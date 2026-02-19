-- Bloom tracking table for progressive activation
-- Single row, no resident_id — one box, one person
CREATE TABLE IF NOT EXISTS bloom_tracking (
    bloom_level INT DEFAULT 0,
    level_reached_at TIMESTAMP DEFAULT NOW(),
    total_conversations INT DEFAULT 0,
    total_memories INT DEFAULT 0,
    total_facts INT DEFAULT 0
);

-- Seed the single row if table is empty
INSERT INTO bloom_tracking (bloom_level)
SELECT 0
WHERE NOT EXISTS (SELECT 1 FROM bloom_tracking);
