-- Last prompt forensics table
-- Stores the exact messages array sent to the LLM on every turn.
-- Single row, overwritten each call. Survives restarts for post-mortem debugging.

CREATE TABLE IF NOT EXISTS last_prompt (
    id integer PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    messages jsonb NOT NULL,
    token_count integer,
    captured_at timestamp with time zone DEFAULT now()
);

-- Seed the single row so upserts always work
INSERT INTO last_prompt (id, messages, token_count)
VALUES (1, '[]'::jsonb, 0)
ON CONFLICT (id) DO NOTHING;
