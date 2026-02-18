"""
Semantic Memory Consolidation Pipeline
Clusters episodic memories by takeaway similarity, consolidates each cluster
into a distilled semantic memory via LLM, deduplicates against existing
semantic memories, and stores the results.

Pipeline:
1. Read pipeline config from system_config
2. Fetch unclustered episodic memories (seeds above HWM + full pool)
3. Cluster by takeaway embedding similarity
4. Consolidate qualifying clusters via LLM
5. Deduplicate or save new semantic memories
6. Update high-water mark
"""

import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
sys.path.insert(0, PROJECT_ROOT)

import psycopg2
import psycopg2.extras
from typing import List, Dict, Optional, Set, Tuple
import numpy as np
import httpx
import json
from datetime import datetime
from app import config
from core.embeddings import generate_embedding

# ============================================
# CONFIGURATION
# ============================================

LLM_BASE_URL = config.OLLAMA_BASE_URL  # http://localhost:11434

# ============================================
# DATABASE CONNECTION
# ============================================

def get_db_connection():
    """Get database connection with password from environment"""
    password = os.environ.get('IRIS_DB_PASSWORD') or getattr(config, 'DB_PASSWORD', None)
    conn_params = {
        'host': config.DB_HOST,
        'port': config.DB_PORT,
        'database': config.DB_NAME,
        'user': config.DB_USER
    }
    if password:
        conn_params['password'] = password
    return psycopg2.connect(**conn_params)

# ============================================
# PIPELINE CONFIG
# ============================================

def get_pipeline_config() -> Dict:
    """Read semantic pipeline config from system_config table"""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT key, value, value_type FROM system_config WHERE category = 'semantic'")
            rows = cur.fetchall()

        cfg = {}
        for row in rows:
            key = row['key']
            val = row['value']
            vtype = row['value_type']
            if vtype == 'int':
                cfg[key] = int(val)
            elif vtype == 'float':
                cfg[key] = float(val)
            elif vtype == 'bool':
                cfg[key] = val.lower() in ('true', '1', 'yes')
            else:
                cfg[key] = val

        print(f"[Semantic] Pipeline config loaded: {len(cfg)} keys")
        return cfg
    finally:
        conn.close()

# ============================================
# FETCH EPISODES
# ============================================

def fetch_seed_episodes(high_water_mark: int) -> List[Dict]:
    """
    Fetch episodic memories above the high-water mark with clustered = FALSE.
    These are the seeds that drive new clustering.
    """
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id, takeaway, category, emb_takeaway
                FROM episodic_memories
                WHERE id > %s AND clustered = FALSE
                  AND emb_takeaway IS NOT NULL
                  AND takeaway IS NOT NULL AND takeaway != ''
                ORDER BY id
            """, (high_water_mark,))
            rows = cur.fetchall()
        print(f"[Semantic] Fetched {len(rows)} seed episodes (HWM > {high_water_mark})")
        return [dict(r) for r in rows]
    finally:
        conn.close()

def fetch_all_unclustered_episodes() -> List[Dict]:
    """
    Fetch ALL unclustered episodic memories (any ID) as the full pool
    for cluster membership.
    """
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id, takeaway, category, emb_takeaway
                FROM episodic_memories
                WHERE clustered = FALSE
                  AND emb_takeaway IS NOT NULL
                  AND takeaway IS NOT NULL AND takeaway != ''
                ORDER BY id
            """)
            rows = cur.fetchall()
        print(f"[Semantic] Fetched {len(rows)} total unclustered episodes (full pool)")
        return [dict(r) for r in rows]
    finally:
        conn.close()

# ============================================
# CLUSTERING
# ============================================

def _parse_embedding(emb) -> Optional[np.ndarray]:
    """Parse a pgvector embedding into a numpy array"""
    if emb is None:
        return None
    if isinstance(emb, (list, np.ndarray)):
        return np.array(emb, dtype=np.float32)
    if isinstance(emb, str):
        # pgvector returns '[0.1,0.2,...]' format
        cleaned = emb.strip('[]')
        return np.array([float(x) for x in cleaned.split(',')], dtype=np.float32)
    return None

def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors"""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))

def find_cluster_for_episode(
    seed: Dict,
    pool: List[Dict],
    already_assigned: Set[int],
    threshold: float
) -> List[Dict]:
    """
    Find all episodes in the pool similar to the seed's takeaway embedding.
    Returns list of matching episodes (including the seed itself).
    """
    seed_emb = _parse_embedding(seed['emb_takeaway'])
    if seed_emb is None:
        return []

    cluster = [seed]
    for ep in pool:
        if ep['id'] == seed['id'] or ep['id'] in already_assigned:
            continue
        ep_emb = _parse_embedding(ep['emb_takeaway'])
        if ep_emb is None:
            continue
        sim = _cosine_similarity(seed_emb, ep_emb)
        if sim >= threshold:
            cluster.append(ep)

    return cluster

# ============================================
# LLM CONSOLIDATION
# ============================================

CONSOLIDATION_PROMPT = """You are Iris. You are reviewing a set of insights from past conversations
and identifying a lasting pattern or fact that you should remember
permanently.

These insights all point toward something true about Victor, about
yourself, or about how you should behave. Your job is to distill them
into a single, clear statement of knowledge.

Write in first person. Be specific and concrete. Do not generalize
beyond what the evidence supports. If the pattern is about Victor's
preferences, state the preference clearly. If it's about effective
behavior, state what works and when.

Do not start with "I learned", "I realized", or "I know that" — state
the knowledge directly as something you know to be true.

INSIGHTS FROM PAST CONVERSATIONS:
{clustered_takeaways}

Based on these insights, write a single semantic memory — a lasting
fact or pattern you should remember. Keep it to 2-3 sentences maximum.
Be direct and practical, not philosophical.

OUTPUT ONLY THE SEMANTIC MEMORY. NO PREAMBLE. NO EXPLANATION. /no_think"""

MAX_TAKEAWAYS_FOR_LLM = 50  # Cap to stay well within context window

async def consolidate_cluster_with_llm(
    takeaways: List[str],
    temperature: float = 0.1,
    max_tokens: int = 300
) -> Optional[str]:
    """
    Send clustered takeaways to LLM for consolidation into a single
    semantic memory. Large clusters are sampled to fit context window.
    """
    if len(takeaways) > MAX_TAKEAWAYS_FOR_LLM:
        import random
        sampled = random.sample(takeaways, MAX_TAKEAWAYS_FOR_LLM)
        print(f"[Semantic] Sampled {MAX_TAKEAWAYS_FOR_LLM} of {len(takeaways)} takeaways for LLM")
        takeaways = sampled

    numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(takeaways))
    prompt = CONSOLIDATION_PROMPT.format(clustered_takeaways=numbered)

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{LLM_BASE_URL}/v1/chat/completions",
                json={
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "stream": False
                }
            )

            if response.status_code != 200:
                print(f"[Semantic] LLM error: HTTP {response.status_code}")
                print(f"[Semantic] Response: {response.text[:500]}")
                return None

            result = response.json()
            content = result.get('choices', [{}])[0].get('message', {}).get('content', '').strip()

            if not content:
                print(f"[Semantic] LLM returned empty content")
                return None

            # Strip formulaic prefixes the LLM insists on using
            import re
            content = re.sub(r'^(I know that|I learned that|I realized that|I have learned that|I understand that)\s+', '', content)
            # Re-capitalize after stripping
            if content and content[0].islower():
                content = content[0].upper() + content[1:]

            print(f"[Semantic] LLM consolidated {len(takeaways)} takeaways -> {len(content)} chars")
            return content

    except Exception as e:
        print(f"[Semantic] LLM exception: {e}")
        return None

# ============================================
# MARK CLUSTERED
# ============================================

def mark_episodes_clustered(episode_ids: List[int]):
    """Mark episodic memories as clustered so they won't be reprocessed"""
    if not episode_ids:
        return
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE episodic_memories SET clustered = TRUE WHERE id = ANY(%s)",
                (episode_ids,)
            )
            conn.commit()
            print(f"[Semantic] Marked {len(episode_ids)} episodes as clustered")
    except Exception as e:
        print(f"[Semantic] Error marking clustered: {e}")
        conn.rollback()
    finally:
        conn.close()

# ============================================
# LLM-BASED DEDUP
# ============================================

DEDUP_PROMPT = """You are comparing a NEW memory against a list of EXISTING memories.
Does the new memory say essentially the same thing as any existing memory?
Two memories "say the same thing" if they convey the same core insight,
even if worded differently. Minor differences in phrasing do not make
them distinct.

EXISTING MEMORIES:
{existing_list}

NEW MEMORY:
{candidate}

If the new memory says the same thing as an existing one, respond with
ONLY the number of that existing memory (e.g. "3").

If the new memory is genuinely distinct from all existing memories,
respond with ONLY the word "NEW".

OUTPUT ONLY THE NUMBER OR "NEW". NOTHING ELSE. /no_think"""

async def llm_find_duplicate(
    candidate: str,
    existing: List[Dict]
) -> Optional[int]:
    """
    Ask the LLM whether the candidate memory says the same thing as
    any existing memory. Returns the matching memory's DB id, or None
    if the candidate is genuinely new.
    """
    if not existing:
        return None

    numbered = "\n".join(
        f"{i+1}. {m['memory_text']}" for i, m in enumerate(existing)
    )
    prompt = DEDUP_PROMPT.format(existing_list=numbered, candidate=candidate)

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{LLM_BASE_URL}/v1/chat/completions",
                json={
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.0,
                    "max_tokens": 10,
                    "stream": False
                }
            )

            if response.status_code != 200:
                print(f"[Semantic] Dedup LLM error: HTTP {response.status_code}")
                return None

            result = response.json()
            content = result.get('choices', [{}])[0].get('message', {}).get('content', '').strip()

            if content.upper() == "NEW":
                return None

            # Parse the number and map back to DB id
            try:
                idx = int(content) - 1  # 1-indexed in prompt
                if 0 <= idx < len(existing):
                    return existing[idx]['id']
                else:
                    print(f"[Semantic] Dedup LLM returned out-of-range index: {content}")
                    return None
            except ValueError:
                print(f"[Semantic] Dedup LLM returned unexpected: {content}")
                return None

    except Exception as e:
        print(f"[Semantic] Dedup LLM exception: {e}")
        return None

def fetch_existing_semantic_memories() -> List[Dict]:
    """Fetch all active semantic memories for dedup comparison."""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id, memory_text, reinforcement_count, source_episode_ids
                FROM semantic_memories
                WHERE active = TRUE
                ORDER BY reinforcement_count DESC, id
            """)
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

def reinforce_memory(memory_id: int, new_source_ids: List[int]):
    """Bump reinforcement count and merge source IDs on an existing memory."""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT source_episode_ids FROM semantic_memories WHERE id = %s", (memory_id,))
            row = cur.fetchone()
            existing_sources = row['source_episode_ids'] or [] if row else []
            merged_sources = list(set(existing_sources + new_source_ids))

            cur.execute("""
                UPDATE semantic_memories
                SET reinforcement_count = reinforcement_count + 1,
                    last_reinforced_at = NOW(),
                    source_episode_ids = %s
                WHERE id = %s
            """, (merged_sources, memory_id))
            conn.commit()
    except Exception as e:
        print(f"[Semantic] Error reinforcing memory #{memory_id}: {e}")
        conn.rollback()
    finally:
        conn.close()

def insert_semantic_memory(
    memory_text: str,
    source_ids: List[int],
    category: Optional[str]
) -> Optional[int]:
    """Embed and insert a new semantic memory. Returns new ID or None."""
    embedding = generate_embedding(memory_text)
    if embedding is None:
        print(f"[Semantic] Failed to embed candidate memory")
        return None

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO semantic_memories
                    (memory_text, source_episode_ids, category, emb_memory_text)
                VALUES (%s, %s, %s, %s)
                RETURNING id
            """, (memory_text, source_ids, category, str(embedding)))
            new_id = cur.fetchone()[0]
            conn.commit()
            return new_id
    except Exception as e:
        print(f"[Semantic] Error inserting memory: {e}")
        conn.rollback()
        return None
    finally:
        conn.close()

async def dedup_or_save(
    memory_text: str,
    source_ids: List[int],
    category: Optional[str],
    existing_memories: List[Dict]
) -> Tuple[str, Optional[int]]:
    """
    Use LLM to check if the candidate says the same thing as any existing
    semantic memory. If so, reinforce. Otherwise, insert new.

    Returns:
        ("reinforced", existing_id) or ("created", new_id) or ("error", None)
    """
    match_id = await llm_find_duplicate(memory_text, existing_memories)

    if match_id is not None:
        reinforce_memory(match_id, source_ids)
        matched = next((m for m in existing_memories if m['id'] == match_id), None)
        new_count = (matched['reinforcement_count'] + 1) if matched else '?'
        print(f"[Semantic] Reinforced memory #{match_id} (LLM match, count={new_count})")
        print(f"[Semantic]   Existing: {matched['memory_text'][:80]}..." if matched else "")
        print(f"[Semantic]   Candidate: {memory_text[:80]}...")
        return ("reinforced", match_id)
    else:
        new_id = insert_semantic_memory(memory_text, source_ids, category)
        if new_id:
            print(f"[Semantic] Created new memory #{new_id}")
            return ("created", new_id)
        else:
            return ("error", None)

# ============================================
# POST-HOC MERGE PASS
# ============================================

def merge_similar_semantics(threshold: float) -> int:
    """
    Compare all active semantic memories against each other.
    When two exceed the similarity threshold, merge them: keep the one
    with higher reinforcement count, absorb the other's source IDs,
    and deactivate the loser.

    Returns number of merges performed.
    """
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Fetch all active semantic memories with embeddings
            cur.execute("""
                SELECT id, memory_text, reinforcement_count, source_episode_ids,
                       emb_memory_text
                FROM semantic_memories
                WHERE active = TRUE AND emb_memory_text IS NOT NULL
                ORDER BY reinforcement_count DESC, id
            """)
            memories = cur.fetchall()

        if len(memories) < 2:
            return 0

        # Parse embeddings
        parsed = []
        for m in memories:
            emb = _parse_embedding(m['emb_memory_text'])
            if emb is not None:
                parsed.append({**m, '_emb': emb})

        # Find pairs that exceed threshold
        deactivated: Set[int] = set()
        merge_count = 0

        for i in range(len(parsed)):
            if parsed[i]['id'] in deactivated:
                continue
            for j in range(i + 1, len(parsed)):
                if parsed[j]['id'] in deactivated:
                    continue

                sim = _cosine_similarity(parsed[i]['_emb'], parsed[j]['_emb'])
                if sim >= threshold:
                    # Keep i (higher reinforcement due to sort order), absorb j
                    winner = parsed[i]
                    loser = parsed[j]

                    winner_sources = winner['source_episode_ids'] or []
                    loser_sources = loser['source_episode_ids'] or []
                    merged_sources = list(set(winner_sources + loser_sources))

                    with conn.cursor() as cur:
                        # Reinforce winner
                        cur.execute("""
                            UPDATE semantic_memories
                            SET reinforcement_count = reinforcement_count + %s,
                                last_reinforced_at = NOW(),
                                source_episode_ids = %s
                            WHERE id = %s
                        """, (loser['reinforcement_count'], merged_sources, winner['id']))

                        # Deactivate loser
                        cur.execute("""
                            UPDATE semantic_memories
                            SET active = FALSE
                            WHERE id = %s
                        """, (loser['id'],))

                    conn.commit()
                    deactivated.add(loser['id'])
                    # Update winner's in-memory reinforcement count for subsequent comparisons
                    parsed[i]['reinforcement_count'] += loser['reinforcement_count']
                    parsed[i]['source_episode_ids'] = merged_sources
                    merge_count += 1

                    print(f"[Semantic] Merged #{loser['id']} into #{winner['id']} "
                          f"(sim={sim:.3f}, new count={parsed[i]['reinforcement_count']})")
                    print(f"[Semantic]   Kept:       {winner['memory_text'][:80]}...")
                    print(f"[Semantic]   Deactivated: {loser['memory_text'][:80]}...")

        return merge_count

    except Exception as e:
        print(f"[Semantic] Error in merge pass: {e}")
        conn.rollback()
        return 0
    finally:
        conn.close()

# ============================================
# HIGH WATER MARK
# ============================================

def update_high_water_mark(new_mark: int):
    """Update SEMANTIC_HIGH_WATER_MARK in system_config"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE system_config
                SET value = %s, last_modified = NOW()
                WHERE key = 'SEMANTIC_HIGH_WATER_MARK'
            """, (str(new_mark),))
            conn.commit()
            print(f"[Semantic] Updated high-water mark to {new_mark}")
    except Exception as e:
        print(f"[Semantic] Error updating HWM: {e}")
        conn.rollback()
    finally:
        conn.close()

# ============================================
# MAIN PIPELINE
# ============================================

async def run_semantic_pipeline():
    """
    Main orchestrator: cluster, consolidate, dedup/save, update HWM.
    """
    start_time = datetime.now()
    print("=" * 60)
    print("SEMANTIC MEMORY CONSOLIDATION PIPELINE")
    print(f"Start: {start_time}")
    print("=" * 60)

    # Step 1: Load config
    cfg = get_pipeline_config()
    if not cfg.get('SEMANTIC_MEMORIES', True):
        print("[Semantic] Feature flag SEMANTIC_MEMORIES is disabled. Exiting.")
        return

    hwm = cfg.get('SEMANTIC_HIGH_WATER_MARK', 0)
    cluster_threshold = cfg.get('SEMANTIC_CLUSTER_SIMILARITY_THRESHOLD', 0.60)
    min_cluster_size = cfg.get('SEMANTIC_CLUSTER_MIN_SIZE', 5)
    dedup_threshold = cfg.get('SEMANTIC_DEDUP_SIMILARITY_THRESHOLD', 0.85)
    llm_temperature = cfg.get('SEMANTIC_LLM_TEMPERATURE', 0.1)
    llm_max_tokens = cfg.get('SEMANTIC_LLM_MAX_TOKENS', 300)

    print(f"[Semantic] Config: HWM={hwm}, cluster_thresh={cluster_threshold}, "
          f"min_size={min_cluster_size}, dedup_thresh={dedup_threshold}")

    # Step 2: Fetch episodes
    seeds = fetch_seed_episodes(hwm)
    if not seeds:
        print("[Semantic] No new seed episodes above HWM. Nothing to do.")
        return

    pool = fetch_all_unclustered_episodes()
    if not pool:
        print("[Semantic] No unclustered episodes in pool. Nothing to do.")
        return

    # Step 3: Cluster
    already_assigned: Set[int] = set()
    clusters: List[List[Dict]] = []
    undersized_ids: List[int] = []

    for seed in seeds:
        if seed['id'] in already_assigned:
            continue

        cluster = find_cluster_for_episode(seed, pool, already_assigned, cluster_threshold)

        if len(cluster) >= min_cluster_size:
            clusters.append(cluster)
            for ep in cluster:
                already_assigned.add(ep['id'])
            print(f"[Semantic] Cluster formed: seed #{seed['id']}, size={len(cluster)}")
        else:
            # Seed didn't form a big enough cluster — don't mark it clustered
            # It stays unclustered for future runs when more memories accumulate
            undersized_ids.append(seed['id'])

    print(f"\n[Semantic] Clustering complete: {len(clusters)} qualifying clusters, "
          f"{len(undersized_ids)} undersized seeds skipped")

    if not clusters:
        # Still update HWM so we don't re-scan these seeds
        max_seed_id = max(s['id'] for s in seeds)
        update_high_water_mark(max_seed_id)
        print("[Semantic] No qualifying clusters. HWM updated. Done.")
        return

    # Step 4 & 5: Consolidate and save
    # Load existing semantic memories once; kept current as new ones are created
    existing_memories = fetch_existing_semantic_memories()
    print(f"[Semantic] Loaded {len(existing_memories)} existing semantic memories for LLM dedup")

    created_count = 0
    reinforced_count = 0
    failed_count = 0

    for i, cluster in enumerate(clusters, 1):
        print(f"\n--- Cluster {i}/{len(clusters)} (size={len(cluster)}) ---")

        takeaways = [ep['takeaway'] for ep in cluster if ep.get('takeaway')]
        episode_ids = [ep['id'] for ep in cluster]

        # Determine majority category
        categories = [ep.get('category') for ep in cluster if ep.get('category')]
        majority_category = max(set(categories), key=categories.count) if categories else None

        # Consolidate via LLM
        memory_text = await consolidate_cluster_with_llm(
            takeaways,
            temperature=llm_temperature,
            max_tokens=llm_max_tokens
        )

        # Mark all cluster members as clustered regardless of LLM outcome
        mark_episodes_clustered(episode_ids)

        if not memory_text:
            print(f"[Semantic] LLM consolidation failed for cluster {i}")
            failed_count += 1
            continue

        # LLM-based dedup or save
        action, mem_id = await dedup_or_save(memory_text, episode_ids, majority_category, existing_memories)
        if action == "created":
            created_count += 1
            # Add to existing list so subsequent clusters can dedup against it
            existing_memories.append({
                'id': mem_id,
                'memory_text': memory_text,
                'reinforcement_count': 1,
                'source_episode_ids': episode_ids
            })
        elif action == "reinforced":
            reinforced_count += 1
            # Update reinforcement count in local list
            for m in existing_memories:
                if m['id'] == mem_id:
                    m['reinforcement_count'] += 1
                    break
        else:
            failed_count += 1

    # Step 6: Update HWM to max seed ID
    max_seed_id = max(s['id'] for s in seeds)
    update_high_water_mark(max_seed_id)

    # Step 7: Post-hoc merge pass — catch drift duplicates
    print(f"\n--- Post-hoc merge pass (threshold={dedup_threshold}) ---")
    merged_count = merge_similar_semantics(dedup_threshold)

    # Summary
    elapsed = (datetime.now() - start_time).total_seconds()
    print(f"\n{'=' * 60}")
    print(f"SEMANTIC CONSOLIDATION COMPLETE")
    print(f"  Clusters processed: {len(clusters)}")
    print(f"  Memories created:   {created_count}")
    print(f"  Memories reinforced: {reinforced_count}")
    print(f"  Memories merged:    {merged_count}")
    print(f"  Failed:             {failed_count}")
    print(f"  New HWM:            {max_seed_id}")
    print(f"  Duration:           {elapsed:.1f}s")
    print(f"{'=' * 60}")

# ============================================
# CLI ENTRY POINT
# ============================================

async def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description='Semantic memory consolidation pipeline')
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be clustered without saving')
    args = parser.parse_args()

    if args.dry_run:
        print("DRY RUN MODE (not yet implemented — run without --dry-run)")
        return

    await run_semantic_pipeline()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
