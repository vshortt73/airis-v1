"""
Character triat engine for Iris v3
Handles handles all aspects of character trait and their management.
"""

import psycopg2
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

def get_trait_list() -> Optional[str]:
    """
    Get the traits that are active from the fulltraits table

    Note: Protocol activation updates the fulltraits table directly,
    so this function just reads the current values.

    Returns:
        Formatted string with trait name/value pairs
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT name, value
            FROM fulltraits
            ORDER BY name DESC
        """)

        result = cursor.fetchall()

        # Format as string with proper header
        traitlist = "[PERSONALITY TRAITS]\n"
        traitlist += (
            "Each trait below is set on a scale of 1-10 (or a descriptive value). "
            "1 = minimal/suppressed, 5 = moderate, 10 = dominant/maximum. "
            "Before responding, CHECK the actual values below. Do not assume — "
            "your traits are frequently adjusted. A trait at 4 should be noticeably "
            "subdued; a trait at 10 should be unmistakable in your response. "
            "During your thinking, confirm that you have evaluated your current trait values "
            "and explain how they influence your response.\n\n"
        )

        for row in result:
            name, value = row
            traitlist += f"{name}: {value}\n"

        conn.close()
        return traitlist

    except Exception as e:
        print(f"[character_traits.py][get_trait_list] Error: {e}")
        return None

