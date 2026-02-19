"""
Progressive Activation — Airis companion bloom system

The companion starts empty and grows as the relationship develops.
Each activation layer unlocks when the relationship naturally generates enough data.

Layer 0: Seed        — just system_instructions (cold-start prompt)
Layer 1: Facts       — short-term facts exist → include facts section
Layer 2: Memory      — episodic memories reach threshold → enable retrieval
Layer 3: Personality — traits populated → include traits in prompt
Layer 4: Knowledge   — semantic memories exist → include semantic section
Layer 5: Full Bloom  — dreams generated → include dreams, dream truths, drive

Thresholds are configurable via system_config (category 'activation').
"""

import os
import sys
import psycopg2
from datetime import datetime

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)
from app import config


def _get_db_connection():
    password = os.environ.get('AIRIS_DB_PASSWORD') or getattr(config, 'DB_PASSWORD', None)
    conn_params = {
        'host': config.DB_HOST,
        'port': config.DB_PORT,
        'database': config.DB_NAME,
        'user': config.DB_USER,
    }
    if password:
        conn_params['password'] = password
    return psycopg2.connect(**conn_params)


def _get_thresholds() -> dict:
    """Load activation thresholds from system_config, with sensible defaults."""
    defaults = {
        'FACT_THRESHOLD': 1,
        'MEMORY_THRESHOLD': 5,
        'TRAIT_THRESHOLD': 1,
        'SEMANTIC_THRESHOLD': 1,
        'DREAM_THRESHOLD': 1,
        'PROGRESSIVE_ACTIVATION_ENABLED': True,
    }
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT key, value, value_type FROM system_config WHERE category = 'activation'"
        )
        for key, value, value_type in cur.fetchall():
            if value_type == 'int':
                defaults[key] = int(value)
            elif value_type == 'bool':
                defaults[key] = value.lower() in ('true', '1', 'yes')
            else:
                defaults[key] = value
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[progressive_activation] Could not load thresholds from DB, using defaults: {e}")
    return defaults


def _get_data_counts() -> dict:
    """Single query to count rows in each activation-relevant table."""
    counts = {
        'facts': 0,
        'memories': 0,
        'traits': 0,
        'semantic': 0,
        'dreams': 0,
    }
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT
                (SELECT COUNT(*) FROM short_term_facts WHERE status = 'active') AS facts,
                (SELECT COUNT(*) FROM episodic_memories) AS memories,
                (SELECT COUNT(*) FROM fulltraits) AS traits,
                (SELECT COUNT(*) FROM semantic_memories WHERE active = TRUE) AS semantic,
                (SELECT COUNT(*) FROM episodic_dreams) AS dreams
        """)
        row = cur.fetchone()
        if row:
            counts['facts'] = row[0] or 0
            counts['memories'] = row[1] or 0
            counts['traits'] = row[2] or 0
            counts['semantic'] = row[3] or 0
            counts['dreams'] = row[4] or 0
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[progressive_activation] Could not query data counts: {e}")
    return counts


def _compute_bloom_level(counts: dict, thresholds: dict) -> int:
    """Compute the current bloom level (0-5) based on data counts and thresholds."""
    level = 0
    if counts['facts'] >= thresholds.get('FACT_THRESHOLD', 1):
        level = 1
    if level >= 1 and counts['memories'] >= thresholds.get('MEMORY_THRESHOLD', 5):
        level = 2
    if level >= 2 and counts['traits'] >= thresholds.get('TRAIT_THRESHOLD', 1):
        level = 3
    if level >= 3 and counts['semantic'] >= thresholds.get('SEMANTIC_THRESHOLD', 1):
        level = 4
    if level >= 4 and counts['dreams'] >= thresholds.get('DREAM_THRESHOLD', 1):
        level = 5
    return level


def _update_bloom_tracking(bloom_level: int, counts: dict):
    """Update the single-row bloom_tracking table if level has advanced."""
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT bloom_level FROM bloom_tracking LIMIT 1")
        row = cur.fetchone()
        if row is None:
            cur.execute(
                """INSERT INTO bloom_tracking (bloom_level, level_reached_at, total_memories, total_facts)
                   VALUES (%s, NOW(), %s, %s)""",
                (bloom_level, counts['memories'], counts['facts'])
            )
        elif bloom_level > row[0]:
            cur.execute(
                """UPDATE bloom_tracking
                   SET bloom_level = %s, level_reached_at = NOW(),
                       total_memories = %s, total_facts = %s""",
                (bloom_level, counts['memories'], counts['facts'])
            )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        # Non-fatal — bloom tracking is informational
        print(f"[progressive_activation] Could not update bloom_tracking: {e}")


def get_activation_state() -> dict:
    """
    Check what data exists and determine which subsystems activate.

    Returns a dict of boolean flags for each prompt section, plus the bloom level.
    If PROGRESSIVE_ACTIVATION_ENABLED is false, all flags are True (bypass mode).
    """
    thresholds = _get_thresholds()

    # Bypass mode — all sections included (development/debugging)
    if not thresholds.get('PROGRESSIVE_ACTIVATION_ENABLED', True):
        return {
            'include_facts': True,
            'include_memories': True,
            'include_traits': True,
            'include_semantic': True,
            'include_dreams': True,
            'include_drive': True,
            'bloom_level': 5,
            'bypassed': True,
        }

    counts = _get_data_counts()
    bloom_level = _compute_bloom_level(counts, thresholds)

    state = {
        'include_facts': counts['facts'] >= thresholds.get('FACT_THRESHOLD', 1),
        'include_memories': counts['memories'] >= thresholds.get('MEMORY_THRESHOLD', 5),
        'include_traits': counts['traits'] >= thresholds.get('TRAIT_THRESHOLD', 1),
        'include_semantic': counts['semantic'] >= thresholds.get('SEMANTIC_THRESHOLD', 1),
        'include_dreams': counts['dreams'] >= thresholds.get('DREAM_THRESHOLD', 1),
        'include_drive': counts['dreams'] >= thresholds.get('DREAM_THRESHOLD', 1),
        'bloom_level': bloom_level,
        'bypassed': False,
    }

    _update_bloom_tracking(bloom_level, counts)

    return state


BLOOM_LABELS = {
    0: "Seed",
    1: "Facts Emerging",
    2: "Memory Active",
    3: "Personality Emerging",
    4: "Knowledge Deepening",
    5: "Full Bloom",
}


def get_bloom_label(level: int) -> str:
    """Human-readable label for a bloom level."""
    return BLOOM_LABELS.get(level, f"Level {level}")
