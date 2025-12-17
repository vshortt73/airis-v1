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

def get_trait_list() -> Optional[Dict]:
    """
    Get the traits that are active
    
    Returns:
        Dict with 'trait_name' and 'value'
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
        traitlist = "[PERSONALITY TRAITS]\n";
        traitlist = "these trait settings control the way in which you respond and communicate. evaluate each trait to ensure response aligns with the settings."

        for row in result:
                    name, value = row
                    
                    traitlist = traitlist + f"{name}: {value}\n"
        conn.close()
        return traitlist

    except Exception as e:
        print(f"[persistence.py][get_trail_list] Error: {e}")
        return None

