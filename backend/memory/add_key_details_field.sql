-- Add key_details field and embedding to episodic_memories
-- This field captures specific visual, emotional, and relational details
-- that are often lost in concise summaries

-- Add the text field
ALTER TABLE episodic_memories
ADD COLUMN IF NOT EXISTS key_details TEXT;

-- Add the embedding vector (768 dimensions for all-mpnet-base-v2)
ALTER TABLE episodic_memories
ADD COLUMN IF NOT EXISTS emb_key_details vector(768);

-- Add comment for documentation
COMMENT ON COLUMN episodic_memories.key_details IS
'Specific details (visual, emotional, relational) that enrich memory recall. Generated with category-aware prompts to capture what summaries miss.';

COMMENT ON COLUMN episodic_memories.emb_key_details IS
'Embedding of key_details field for semantic similarity matching. Fifth facet in retrieval system.';

-- Verify changes
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'episodic_memories'
AND column_name IN ('key_details', 'emb_key_details')
ORDER BY column_name;
