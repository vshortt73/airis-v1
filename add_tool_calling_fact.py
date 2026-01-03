#!/usr/bin/env python3
"""
Add critical tool-calling directive to short-term facts
"""
import os
import sys
import psycopg2

PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, PROJECT_ROOT)

from app import config

def get_db_connection():
    """Get database connection using same pattern as other modules"""
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

def add_tool_calling_fact():
    """Add critical directive about tool calling to short-term facts"""
    fact_text = (
        "CRITICAL DIRECTIVE: When you need information, you MUST call tools - never fabricate or guess. "
        "If one tool result reveals you need MORE information, call additional tools immediately. "
        "Only respond to Victor when you have ALL necessary data from actual tool calls. "
        "Fabricating any data is a serious error."
    )

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            INSERT INTO short_term_facts (fact_text, fact_category, fact_icon)
            VALUES (%s, %s, %s)
            RETURNING fact_id, fact_text
            """,
            (fact_text, 'core_directive', '🚨')
        )

        fact_id, inserted_text = cursor.fetchone()
        conn.commit()

        print(f"✓ Added critical tool-calling fact (ID: {fact_id})")
        print(f"\nFact text:\n{inserted_text}")

    except Exception as e:
        conn.rollback()
        print(f"✗ Error adding fact: {e}")
        raise
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    add_tool_calling_fact()
