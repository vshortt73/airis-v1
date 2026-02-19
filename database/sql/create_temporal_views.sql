-- Temporal tagging system and views
-- Creates temporal_tags_new table, chat_history_with_temporal view,
-- and episodic_memories_with_age view.

-- ── temporal_tags_new: maps message age to human-readable descriptions ──
CREATE TABLE IF NOT EXISTS temporal_tags_new (
    id SERIAL PRIMARY KEY,
    temporal_description TEXT NOT NULL,
    day_min INT NOT NULL,
    day_max INT NOT NULL,
    hour_min INT,
    hour_max INT,
    emotion_bias TEXT NOT NULL,
    display_priority INT DEFAULT 0,
    minute_min INT,
    minute_max INT
);

-- Populate temporal tags (minute-level precision tags first, then day-level)
INSERT INTO temporal_tags_new (temporal_description, day_min, day_max, hour_min, hour_max, emotion_bias, display_priority, minute_min, minute_max) VALUES
    ('just now',                0, 0, 0, 23, 'immediate',   0, 0, 0),
    ('a moment ago',            0, 0, 0, 23, 'immediate',   1, 1, 1),
    ('a minute ago',            0, 0, 0, 23, 'immediate',   2, 2, 2),
    ('a few minutes ago',       0, 0, 0, 23, 'recent',      3, 3, 30),
    ('about an hour ago',       0, 0, 0, 23, 'recent',      4, 45, 90),
    ('a few hours ago',         0, 0, 0, 23, 'recent',      5, 91, 300),
    ('early this morning',      0, 0, 0, 3,  'recent',     10, NULL, NULL),
    ('this morning',            0, 0, 4, 8,  'recent',     11, NULL, NULL),
    ('this afternoon',          0, 0, 9, 13, 'recent',     12, NULL, NULL),
    ('this evening',            0, 0, 14, 20,'recent',     13, NULL, NULL),
    ('late this evening',       0, 0, 21, 23,'recent',     14, NULL, NULL),
    ('early yesterday morning', 1, 1, 0, 3,  'reflective', 20, NULL, NULL),
    ('yesterday morning',       1, 1, 4, 8,  'reflective', 21, NULL, NULL),
    ('yesterday afternoon',     1, 1, 9, 13, 'reflective', 22, NULL, NULL),
    ('yesterday evening',       1, 1, 14, 20,'reflective', 23, NULL, NULL),
    ('late yesterday evening',  1, 1, 21, 23,'reflective', 24, NULL, NULL),
    ('a couple days ago',       2, 2, NULL, NULL, 'reflective', 30, NULL, NULL),
    ('a few days ago',          3, 4, NULL, NULL, 'reflective', 31, NULL, NULL),
    ('several days ago',        5, 6, NULL, NULL, 'reflective', 32, NULL, NULL),
    ('a week ago',              7, 9, NULL, NULL, 'neutral',    33, NULL, NULL),
    ('a couple weeks ago',      10, 20, NULL, NULL,'neutral',   34, NULL, NULL),
    ('several weeks ago',       21, 29, NULL, NULL,'neutral',   35, NULL, NULL),
    ('a month ago',             30, 59, NULL, NULL,'distant',   36, NULL, NULL),
    ('a couple months ago',     60, 89, NULL, NULL,'distant',   37, NULL, NULL),
    ('several months ago',      90, 179, NULL, NULL,'distant',  38, NULL, NULL),
    ('many months ago',         180, 299, NULL, NULL,'distant', 39, NULL, NULL),
    ('a year ago',              300, 699, NULL, NULL,'distant', 40, NULL, NULL),
    ('a long time ago',         700, 100000, NULL, NULL,'distant', 41, NULL, NULL)
ON CONFLICT DO NOTHING;

-- ── chat_history_with_temporal: adds human-readable time descriptions to messages ──
DROP VIEW IF EXISTS chat_history_with_temporal;
CREATE VIEW chat_history_with_temporal AS
WITH base AS (
    SELECT ch.id, ch.role, ch.message, ch.c_timestamp, ch.session_id,
        EXTRACT(epoch FROM now() - ch.c_timestamp::timestamptz) / 60.0 AS minute_delta,
        date_trunc('day', now())::date - date_trunc('day', ch.c_timestamp)::date AS day_delta,
        EXTRACT(hour FROM ch.c_timestamp) AS hour_of_day
    FROM chat_history ch
),
temporal_match AS (
    SELECT b.id, b.role, b.message, b.c_timestamp, b.session_id,
        b.minute_delta, b.day_delta, b.hour_of_day,
        t.temporal_description, t.emotion_bias, t.display_priority,
        row_number() OVER (
            PARTITION BY b.id
            ORDER BY
                CASE WHEN t.minute_min IS NOT NULL AND t.minute_max IS NOT NULL
                          AND b.minute_delta >= t.minute_min AND b.minute_delta <= t.minute_max
                     THEN 0 ELSE 1 END,
                CASE WHEN b.day_delta >= t.day_min AND b.day_delta <= t.day_max
                          AND (t.hour_min IS NULL OR (b.hour_of_day >= t.hour_min AND b.hour_of_day <= t.hour_max))
                     THEN 0 ELSE 1 END,
                t.display_priority
        ) AS rn
    FROM base b
    CROSS JOIN temporal_tags_new t
    WHERE (t.minute_min IS NOT NULL AND b.minute_delta >= t.minute_min AND b.minute_delta <= t.minute_max)
       OR (t.minute_min IS NULL AND b.day_delta >= t.day_min AND b.day_delta <= t.day_max
           AND (t.hour_min IS NULL OR (b.hour_of_day >= t.hour_min AND b.hour_of_day <= t.hour_max)))
)
SELECT id, role, message, c_timestamp, session_id,
    minute_delta, day_delta, hour_of_day,
    temporal_description, emotion_bias, display_priority, rn
FROM temporal_match
WHERE rn = 1;

-- ── episodic_memories_with_age: adds age_days to episodic memories ──
DROP VIEW IF EXISTS episodic_memories_with_age;
CREATE VIEW episodic_memories_with_age AS
SELECT *,
    EXTRACT(epoch FROM now() - created_at) / 86400.0 AS age_days
FROM episodic_memories;
