"""
Character triat engine for Iris v3
Handles handles all aspects of character trait and their management.
"""

import psycopg2
from psycopg2.extras import DictCursor
from typing import List, Dict, Optional
from datetime import datetime
import uuid
import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)
from app import config
from core.token_counter import TokenCounter

def get_db_connection():
    """Create database connection"""
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

def get_memories() -> Optional[Dict]:

    block = "";
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""SELECT lm.*,
                                   em.takeaway,
                                   em.summary_context,
                                   em.summary_significance,
                                   em.summary_tone,
                                   em.summary_event,
                                   em.emotion_label,
                                   em.voice,
                                   em.category,
                                   ' ' as temporal_description,
                                   'neutral' as emotion_bias
                                   from live_memories lm
                                    join public.episodic_memories_with_age em on lm.memory_id = em.id
                            """)
                mems = cur.fetchall()
                print(f"[memory_loader.py][get_memories] loaded {len(mems)} memories for system prompt")
                block_lines = []
                for row in mems:
                    # Clean and normalize fields
                    takeaway = row.get("takeaway", "").strip()
                    if takeaway.lower().startswith("[relational]"):
                        takeaway = takeaway.split("]", 1)[-1].strip()
                    if takeaway.lower().startswith("adaptive"):
                        takeaway = takeaway[len("adaptive"):].strip()

                    summary = row.get("summary_context", "")
                    if summary and (summary.lower().startswith("20") or len(summary.split()) < 2):
                        summary = ""  # suppress garbage (timestamps, single words)

                    significance = row.get("summary_significance", "").strip()
                    tone = row.get("summary_tone", "").strip()
                    event = row.get("summary_event", "").strip()
                    voice = row.get("voice", "").strip()
                    category = row.get("category", "").strip()
                    emotion = row.get("emotion_label", "").strip()
                    temporal = row.get("temporal_description", "").strip()
                    bias = row.get("emotion_bias", "").strip() 

                    # Build formatted block
                    block += "-------------------------------------------------------\n"
                    if voice or category:
                        block = block + (f"          Voice: {voice} | Category: {category}\n")
                    if temporal:
                        block = block + (f"Temporal Anchor: {temporal} | bias: {bias}\n")               
                    if emotion:
                        block = block +(f"         Emotion: {emotion}\n")
                    if takeaway:
                        block = block +(f"        Takeaway: {takeaway}\n")
                    if summary:
                        block = block +(f"         Summary: {summary}\n")
                    if significance:
                        block = block +(f"    Significance: {significance}\n")
                    if tone:
                        block = block +(f"            Tone: {tone}\n")
                    if event:
                        block = block +(f"           Event: {event}\n")

                return(f"[LONG TERM MEMORIES] when appropriate, reference these memories in the current conversation.\n {block}")

    except Exception as e:
        print(f"[memory_loader.py][get_memories] Error: {e}")
        return None

if __name__ == "__main__":
    print(get_memories())
    
