#!/usr/bin/env python3
"""Pull similarity cluster from episodic_memories by ID."""

import os
import sys
import psycopg2

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "database": os.environ.get('AIRIS_DB_NAME', 'airisdb'),
    "user": os.environ.get('AIRIS_DB_USER', 'airisuser'),
    "password": os.environ.get('AIRIS_DB_PASSWORD', ''),
}


def get_similar_ids(memory_id: int, limit: int = 10) -> list[tuple[int, float]]:
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    # Get the embedding and takeaway for the given ID
    cur.execute("SELECT emb_takeaway, takeaway FROM episodic_memories WHERE id = %s", (memory_id,))
    row = cur.fetchone()

    if not row or row[0] is None:
        cur.close()
        conn.close()
        return [], None

    embedding = row[0]
    source_takeaway = row[1]

    # Find closest memories by cosine similarity (excluding self, newest 111 only)
    cur.execute("""
        WITH recent AS (
            SELECT id, emb_takeaway, takeaway
            FROM episodic_memories
            WHERE emb_takeaway IS NOT NULL
            ORDER BY id DESC
            LIMIT 111
        )
        SELECT id, 1 - (emb_takeaway <=> %s) AS similarity, takeaway
        FROM recent
        WHERE id != %s
        ORDER BY emb_takeaway <=> %s
        LIMIT %s
    """, (embedding, memory_id, embedding, limit))

    results = [(r[0], round(r[1], 4), r[2] or '') for r in cur.fetchall()]

    cur.close()
    conn.close()
    return results, source_takeaway


if __name__ == "__main__":
    if not DB_CONFIG["password"]:
        print("Set AIRIS_DB_PASSWORD", file=sys.stderr)
        sys.exit(1)

    memory_id = input("Memory ID: ").strip()

    try:
        memory_id = int(memory_id)
    except ValueError:
        print("Invalid ID", file=sys.stderr)
        sys.exit(1)

    results, source_takeaway = get_similar_ids(memory_id)

    if not results:
        print("No embedding found for that ID", file=sys.stderr)
        sys.exit(1)

    print(f"{memory_id}\t1.0000\t{source_takeaway or ''}")
    for mem_id, score, takeaway in results:
        print(f"{mem_id}\t{score}\t{takeaway}")
